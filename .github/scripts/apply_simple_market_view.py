from pathlib import Path
import ast

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# 1) Longer, bounded caches: keep the analysis rigorous, avoid repeating it on every Streamlit rerun.
s = s.replace(
    "@st.cache_data(ttl=30, show_spinner=False)\ndef fetch_binance_history",
    "@st.cache_data(ttl=90, max_entries=64, show_spinner=False)\ndef fetch_binance_history",
    1,
)
s = s.replace(
    "@st.cache_data(ttl=30, show_spinner=False)\ndef fetch_timeframe_history",
    "@st.cache_data(ttl=90, max_entries=64, show_spinner=False)\ndef fetch_timeframe_history",
    1,
)
s = s.replace(
    "@st.cache_data(ttl=300, show_spinner=False)\ndef model_signal",
    "@st.cache_data(ttl=900, max_entries=48, show_spinner=False)\ndef model_signal",
    1,
)
if "@st.cache_data(ttl=900, max_entries=12, show_spinner=False)\ndef build_timing_rows" not in s:
    s = s.replace(
        "def build_timing_rows(symbol_code: str):",
        "@st.cache_data(ttl=900, max_entries=12, show_spinner=False)\ndef build_timing_rows(symbol_code: str):",
        1,
    )
if "@st.cache_data(ttl=900, max_entries=24, show_spinner=False)\ndef build_candle_radar" not in s:
    s = s.replace(
        "def build_candle_radar(symbol_code: str, timeframe: str, history_bars: int):",
        "@st.cache_data(ttl=900, max_entries=24, show_spinner=False)\ndef build_candle_radar(symbol_code: str, timeframe: str, history_bars: int):",
        1,
    )

# 2) All TradingView-style timeframes from 1 minute through monthly.
old_tf = '''    TIMEFRAME_UI = {
        "1 minuto": "1m",
        "5 minutos": "5m",
        "15 minutos": "15m",
        "1 hora": "1h",
        "4 horas": "4h",
        "1 día": "1D",
        "1 semana": "1W",
        "1 mes": "1M",
    }'''
new_tf = '''    TIMEFRAME_UI = {
        "1 minuto": "1m",
        "2 minutos": "2m",
        "3 minutos": "3m",
        "5 minutos": "5m",
        "10 minutos": "10m",
        "15 minutos": "15m",
        "30 minutos": "30m",
        "45 minutos": "45m",
        "1 hora": "1h",
        "2 horas": "2h",
        "3 horas": "3h",
        "4 horas": "4h",
        "1 día": "1D",
        "1 semana": "1W",
        "1 mes": "1M",
    }'''
if old_tf in s:
    s = s.replace(old_tf, new_tf, 1)
elif new_tf not in s:
    raise RuntimeError("No se encontró TIMEFRAME_UI para actualizar")

helpers = '''\n\ndef _strict_simple_state(signal):
    """Only color the chart when several independent reliability checks pass."""
    if not signal.get("ok") or not signal.get("model_validated"):
        return None
    rel = reliability_level(signal)
    if rel not in ("MEDIA", "ALTA"):
        return None
    dom, prob, margin = scenario_from_probs(signal["pup"], signal["pflat"], signal["pdown"])
    if prob < 0.45 or margin < 0.06:
        return None
    if float(signal.get("model_agreement", 0.0)) < (2 / 3):
        return None
    if signal.get("analog_agreement") is False:
        return None
    return {
        "scenario": dom,
        "probability": float(prob),
        "reliability": rel,
        "source": "modelos + validación histórica + patrones",
    }


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def monthly_consensus_state(symbol_code: str):
    """Monthly state requires daily + weekly validated agreement and monthly cycle alignment."""
    votes = []
    for tf, history, horizon_bars in (("1D", 1000, 30), ("1W", 520, 4)):
        raw = fetch_timeframe_history(symbol_code, tf, history + 2)
        closed = raw[raw.is_closed].drop(columns=["is_closed"]).tail(history).reset_index(drop=True)
        res = model_signal(closed, horizon=horizon_bars, deep=False)
        state = _strict_simple_state(res)
        if state:
            votes.append(state)

    raw_m = fetch_timeframe_history(symbol_code, "1M", DEFAULT_HISTORY["1M"] + 2)
    monthly = raw_m[raw_m.is_closed].drop(columns=["is_closed"]).reset_index(drop=True)
    if len(monthly) < 30 or len(votes) < 2:
        return None

    close = monthly["close"].astype(float)
    ema6 = float(close.ewm(span=6, adjust=False).mean().iloc[-1])
    ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
    ema24 = float(close.ewm(span=24, adjust=False).mean().iloc[-1])
    last = float(close.iloc[-1])
    mom3 = last / float(close.iloc[-4]) - 1.0
    mom6 = last / float(close.iloc[-7]) - 1.0

    monthly_direction = None
    if last > ema6 > ema12 > ema24 and mom3 > 0 and mom6 > 0:
        monthly_direction = "SUBIDA"
    elif last < ema6 < ema12 < ema24 and mom3 < 0 and mom6 < 0:
        monthly_direction = "BAJADA"
    elif abs(mom3) < 0.06 and abs(last / ema12 - 1.0) < 0.06:
        monthly_direction = "LATERAL"

    if votes[0]["scenario"] != votes[1]["scenario"]:
        return None
    dominant = votes[0]["scenario"]
    if monthly_direction != dominant:
        return None

    probability = (votes[0]["probability"] + votes[1]["probability"]) / 2.0
    reliability = "ALTA" if all(v["reliability"] == "ALTA" for v in votes) else "MEDIA"
    return {
        "scenario": dominant,
        "probability": float(probability),
        "reliability": reliability,
        "source": "1D + 1W + ciclo mensual",
    }


def simple_signal_chart(df, symbol, timeframe, horizon, state, simple_forecast=None):
    """One clean chart: price plus green/red/yellow evidence area, or gray when evidence is insufficient."""
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.timestamp,
        open=df.open,
        high=df.high,
        low=df.low,
        close=df.close,
        name="Precio",
        increasing_line_color="#2ecc71",
        decreasing_line_color="#ff5c5c",
    ))
    palette = {
        "SUBIDA": ("#2ecc71", "rgba(46,204,113,.15)", "ALCISTA"),
        "BAJADA": ("#ff5c5c", "rgba(255,92,92,.15)", "BAJISTA"),
        "LATERAL": ("#f2c94c", "rgba(242,201,76,.15)", "LATERAL"),
    }
    last_x = pd.Timestamp(df.timestamp.iloc[-1])
    last_y = float(df.close.iloc[-1])

    if state:
        scenario = state["scenario"]
        line_color, fill_color, label = palette[scenario]
        end_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, int(horizon)))
        zone = None
        plan = None
        if simple_forecast is not None:
            if scenario == "SUBIDA":
                zone, plan = simple_forecast.up, simple_forecast.long_plan
            elif scenario == "BAJADA":
                zone, plan = simple_forecast.down, simple_forecast.short_plan
            else:
                zone = simple_forecast.flat

        if end_x > last_x:
            if zone is not None:
                fig.add_shape(
                    type="rect", x0=last_x, x1=end_x,
                    y0=float(zone.low), y1=float(zone.high),
                    fillcolor=fill_color,
                    line={"color": line_color, "width": 1},
                    layer="below",
                )
                label_y = (float(zone.low) + float(zone.high)) / 2.0
            else:
                fig.add_vrect(x0=last_x, x1=end_x, fillcolor=fill_color, line_width=0, layer="below")
                label_y = last_y
            fig.add_annotation(
                x=end_x, y=label_y,
                text=f"{label}<br>{state['probability']*100:.0f}%",
                showarrow=False,
                font={"color": line_color, "size": 15},
                bgcolor="rgba(8,11,15,.80)",
            )
        if plan is not None and scenario in ("SUBIDA", "BAJADA"):
            fig.add_hline(
                y=float(plan.stop), line_dash="dot", line_color=line_color,
                annotation_text="Invalidación",
            )
    else:
        fig.add_annotation(
            x=last_x, y=last_y,
            text="SIN SEÑAL SUFICIENTEMENTE FIABLE",
            showarrow=True,
            font={"color": "#b7bec7", "size": 14},
            bgcolor="rgba(8,11,15,.84)",
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#080b0f",
        plot_bgcolor="#080b0f",
        height=650,
        margin=dict(l=8, r=8, t=38, b=8),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        dragmode="pan",
        showlegend=False,
        uirevision=f"simple-{symbol}-{timeframe}",
    )
    fig.update_xaxes(gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across")
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig
'''

if "def _strict_simple_state(signal):" not in s:
    marker = "\ndef store_df(key, value):\n"
    if marker not in s:
        raise RuntimeError("No se encontró punto para insertar helpers")
    s = s.replace(marker, helpers + marker, 1)

simple_branch = '''\n\n# ------------------------- Ultra-simple main view -------------------------
if ui_mode == "Sencillo":
    if timeframe == "1M":
        with st.spinner("Analizando diario, semanal y ciclo mensual..."):
            simple_state = monthly_consensus_state(SYMBOLS[selected])
    else:
        simple_state = _strict_simple_state(signal)

    if simple_state:
        scenario = simple_state["scenario"]
        icon = "🟢" if scenario == "SUBIDA" else "🔴" if scenario == "BAJADA" else "🟡"
        label = "ALCISTA" if scenario == "SUBIDA" else "BAJISTA" if scenario == "BAJADA" else "LATERAL"
        st.markdown(f"## {icon} {selected} · {label}")
        st.caption(
            f"{timeframe_label} · evidencia {simple_state['reliability'].lower()} · "
            f"probabilidad estimada {simple_state['probability']*100:.1f}%"
        )
    else:
        st.markdown(f"## ⚪ {selected} · SIN SEÑAL CLARA")
        st.caption(
            f"{timeframe_label} · no se colorea la gráfica hasta que el análisis supere los filtros de fiabilidad."
        )

    simple_fig = simple_signal_chart(
        display_df, selected, timeframe, horizon, simple_state, simple_forecast
    )
    st.plotly_chart(
        simple_fig,
        width="stretch",
        theme=None,
        key=f"simple_main_{selected}_{timeframe}_{horizon}",
        config=plot_config(),
    )

    if simple_state:
        alert_key = f"last_simple_state::{selected}::{timeframe}"
        previous = st.session_state.get(alert_key)
        current = simple_state["scenario"]
        if previous is not None and previous != current:
            text = "SUBIDA" if current == "SUBIDA" else "BAJADA" if current == "BAJADA" else "LATERAL"
            st.toast(f"Cambio detectado en {selected} · {timeframe_label}: {text}", icon="🔔")
        st.session_state[alert_key] = current

    with st.expander("Qué está analizando por detrás", expanded=False):
        st.caption(
            "Modelos estadísticos, validación fuera de muestra, patrones históricos, tendencia, volumen y contexto de ciclo. "
            "La pantalla principal solo muestra el resultado cuando la evidencia es suficiente."
        )
    st.stop()
'''

if "Ultra-simple main view" not in s:
    marker2 = "\nrender_live_strip(SYMBOLS[selected])\n"
    if marker2 not in s:
        raise RuntimeError("No se encontró punto para insertar vista simple")
    s = s.replace(marker2, simple_branch + marker2, 1)

# Ensure it remains valid Python before writing.
ast.parse(s)
p.write_text(s, encoding="utf-8")
print("app.py actualizado correctamente")
