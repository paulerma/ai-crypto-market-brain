from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# Update simple-mode wording.
s = s.replace(
    'st.caption("Elige activo y temporalidad. El punto de color en la gráfica es la señal principal.")',
    'st.caption("Elige activo y temporalidad. La vista sencilla detecta la tendencia actual y el próximo cambio probable.")',
    1,
)
s = s.replace(
    'help="El punto de la gráfica indica el rumbo más probable para esta temporalidad.",',
    'help="Muestra la tendencia actual y una ventana probable para el próximo cambio de tendencia.",',
    1,
)

insert_marker = '@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)\ndef monthly_consensus_state'
if insert_marker not in s:
    raise RuntimeError('No se encontró el punto de inserción para el detector de tendencia')

helpers = r'''

def _duration_text(timeframe: str, bars: int) -> str:
    """Human readable duration for a number of bars in the selected timeframe."""
    bars = max(1, int(bars))
    if timeframe == "1M":
        return f"{bars} mes" if bars == 1 else f"{bars} meses"
    if timeframe == "1W":
        return f"{bars} semana" if bars == 1 else f"{bars} semanas"
    if timeframe == "1D":
        return f"{bars} día" if bars == 1 else f"{bars} días"
    minutes = float(INTERVAL_MINUTES.get(timeframe, 1)) * bars
    if minutes < 60:
        return f"{int(round(minutes))} min"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.0f} h" if abs(hours - round(hours)) < 1e-9 else f"{hours:.1f} h"
    days = hours / 24.0
    return f"{days:.0f} días" if abs(days - round(days)) < 1e-9 else f"{days:.1f} días"


def current_trend_state(closed: pd.DataFrame, timeframe: str) -> dict:
    """Describe the trend that is already present, without making a future claim."""
    if closed is None or closed.empty or len(closed) < 35:
        return {"scenario": "LATERAL", "strength": 0.0, "score": 0}
    features = build_features(closed)
    row = features.iloc[-1]
    c = closed["close"].astype(float)
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    last = float(c.iloc[-1])
    ret1 = float(c.iloc[-1] / c.iloc[-2] - 1.0) if len(c) >= 2 else 0.0
    ret3 = float(c.iloc[-1] / c.iloc[-4] - 1.0) if len(c) >= 4 else ret1
    slope20 = float(ema20.iloc[-1] / ema20.iloc[-5] - 1.0) if len(ema20) >= 5 else 0.0

    score = 0
    score += 1 if last >= float(ema20.iloc[-1]) else -1
    score += 1 if float(ema20.iloc[-1]) >= float(ema50.iloc[-1]) else -1
    score += 1 if slope20 >= 0 else -1
    score += 1 if float(row.get("macd_hist_pct", 0.0)) >= 0 else -1
    score += 1 if float(row.get("di_spread", 0.0)) >= 0 else -1
    score += 1 if ret3 >= 0 else -1

    # Very fast charts need the recent turn to matter more than slow averages.
    if timeframe in ("1m", "2m", "3m", "5m"):
        score += 1 if ret1 >= 0 else -1
        score += 1 if ret3 >= 0 else -1
        max_score = 8
    else:
        max_score = 6

    adx = float(row.get("adx_14", 0.0))
    try:
        recent = closed.tail(8)
        recent_range = float((recent["high"].max() - recent["low"].min()) / max(last, 1e-12))
        atr_pct = float(row.get("atr_pct", 0.0))
        compressed = recent_range <= max(atr_pct * 1.6, 0.0008)
    except Exception:
        compressed = False

    if abs(score) <= 1 and (adx < 18 or compressed):
        scenario = "LATERAL"
    elif score > 0:
        scenario = "SUBIDA"
    else:
        scenario = "BAJADA"
    return {
        "scenario": scenario,
        "strength": float(min(1.0, abs(score) / max(max_score, 1))),
        "score": int(score),
    }


@st.cache_data(ttl=300, max_entries=96, show_spinner=False)
def trend_transition_forecast(closed: pd.DataFrame, timeframe: str, cycle_context: str | None) -> dict:
    """Infer a transition window from several horizons of the SAME timeframe.

    We do not claim an exact turning timestamp. A transition is surfaced only
    when the opposite direction is supported by two consecutive horizons.
    """
    current = current_trend_state(closed, timeframe)
    horizons = [1, 2, 4, 8]
    future = []
    for h in horizons:
        try:
            res = fast_statistical_signal(closed, timeframe, int(h), cycle_context)
            state = res.get("state") if res.get("ok") else None
            if state:
                future.append({
                    "horizon": int(h),
                    "scenario": state.get("scenario", "LATERAL"),
                    "probability": float(state.get("probability", 0.5)),
                    "reliability": state.get("reliability", "BAJA"),
                })
            else:
                future.append({"horizon": int(h), "scenario": "LATERAL", "probability": 0.5, "reliability": "BAJA"})
        except Exception:
            future.append({"horizon": int(h), "scenario": "LATERAL", "probability": 0.5, "reliability": "BAJA"})

    current_dir = current["scenario"]
    transition = None
    for i in range(len(future) - 1):
        a, b = future[i], future[i + 1]
        candidate = a["scenario"]
        if candidate not in ("SUBIDA", "BAJADA"):
            continue
        if candidate == current_dir:
            continue
        if b["scenario"] != candidate:
            continue
        # Require a real directional edge, not a 50/50 flip.
        if min(a["probability"], b["probability"]) < 0.54:
            continue
        previous_h = future[i - 1]["horizon"] if i > 0 else 0
        start_h = max(1, previous_h)
        end_h = int(a["horizon"])
        if end_h < start_h:
            end_h = start_h
        transition = {
            "to": candidate,
            "start_bars": int(start_h),
            "end_bars": int(end_h),
            "probability": float((a["probability"] + b["probability"]) / 2.0),
            "reliability": "ALTA" if a["reliability"] == "ALTA" and b["reliability"] == "ALTA" else "MEDIA",
        }
        break

    return {
        "current": current,
        "transition": transition,
        "future": future,
        "max_horizon": horizons[-1],
    }


def transition_window_text(timeframe: str, transition: dict | None, max_horizon: int) -> str:
    if not transition:
        return f"sin cambio claro en próximas {_duration_text(timeframe, max_horizon)}"
    a = _duration_text(timeframe, int(transition["start_bars"]))
    b = _duration_text(timeframe, int(transition["end_bars"]))
    if a == b:
        return f"aprox. en {a}"
    return f"entre {a} y {b}"


def trend_chart(df: pd.DataFrame, symbol: str, timeframe: str, trend_info: dict):
    """Clean TradingView-like chart with trend status outside the candles."""
    fig = go.Figure()
    plot_df = df.copy()
    plot_ts = pd.to_datetime(plot_df["timestamp"], utc=True)
    plot_df["timestamp"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)
    fig.add_trace(go.Candlestick(
        x=plot_df.timestamp,
        open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,
        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",
    ))

    current = trend_info.get("current", {})
    cur = current.get("scenario", "LATERAL")
    cur_color = "#2ecc71" if cur == "SUBIDA" else "#ff5c5c" if cur == "BAJADA" else "#f2c94c"
    cur_label = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"

    tr = trend_info.get("transition")
    if tr:
        to = tr["to"]
        next_color = "#2ecc71" if to == "SUBIDA" else "#ff5c5c"
        next_label = "ALCISTA" if to == "SUBIDA" else "BAJISTA"
        window = transition_window_text(timeframe, tr, int(trend_info.get("max_horizon", 8)))
        second = f"POSIBLE CAMBIO A {next_label} · {window}"
        second_color = next_color
    else:
        second = transition_window_text(timeframe, None, int(trend_info.get("max_horizon", 8))).upper()
        second_color = "#9aa4ae"

    # Signal rail is outside the price area, so no candle is ever covered.
    fig.add_shape(type="circle", xref="paper", yref="paper",
                  x0=1.018, x1=1.058, y0=0.59, y1=0.65,
                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})
    fig.add_annotation(x=1.074, y=0.62, xref="paper", yref="paper",
                       text=f"<b>TENDENCIA AHORA: {cur_label}</b>", showarrow=False,
                       xanchor="left", font={"color": cur_color, "size": 14})
    fig.add_annotation(x=1.074, y=0.52, xref="paper", yref="paper",
                       text=f"<b>{second}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": second_color, "size": 12})
    if tr:
        fig.add_annotation(x=1.074, y=0.45, xref="paper", yref="paper",
                           text=f"evidencia {str(tr.get('reliability','MEDIA')).lower()} · {tr.get('probability',0.5)*100:.0f}%",
                           showarrow=False, xanchor="left",
                           font={"color": "#8b949e", "size": 11})

    if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m"):
        tick_fmt, hover_fmt = "%H:%M", "%d %b %Y · %H:%M"
    elif timeframe in ("30m", "45m", "1h", "2h", "3h", "4h"):
        tick_fmt, hover_fmt = "%d %b\n%H:%M", "%d %b %Y · %H:%M"
    elif timeframe == "1D":
        tick_fmt, hover_fmt = "%d %b", "%d %b %Y"
    elif timeframe == "1W":
        tick_fmt, hover_fmt = "%d %b", "Semana · %d %b %Y"
    else:
        tick_fmt, hover_fmt = "%b %Y", "%B %Y"

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=650, margin=dict(l=8, r=300, t=36, b=48),
        xaxis_rangeslider_visible=False, hovermode="x unified", dragmode="pan",
        showlegend=False, uirevision=f"trend-{symbol}-{timeframe}",
    )
    fig.update_xaxes(
        gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across",
        spikesnap="cursor", tickformat=tick_fmt, hoverformat=hover_fmt,
        showgrid=True, showticklabels=True, ticks="outside", ticklen=5,
        tickcolor="#65707c", tickfont={"size": 11, "color": "#aab4bf"},
        nticks=13, automargin=True,
    )
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig

'''

s = s.replace(insert_marker, helpers + insert_marker, 1)

start_marker = '# ------------------------- Fast simple mode -------------------------\n'
end_marker = '# ------------------------- Data -------------------------\n'
start = s.find(start_marker)
end = s.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError('No se encontró el bloque de modo sencillo')

new_simple = r'''# ------------------------- Fast simple mode -------------------------
if ui_mode == "Sencillo":
    # Trend detection does not need candle-by-candle model reruns. Refresh the
    # recent tail often enough to notice a new closed bar, while cached trend
    # calculations are reused until the data actually changes.
    _simple_refresh = "10s" if timeframe == "1m" else "15s" if timeframe in ("2m", "3m", "5m") else "30s" if timeframe in ("10m", "15m", "30m", "45m") else "60s"

    @st.fragment(run_every=_simple_refresh)
    def _render_fast_simple_mode():
        fast_history = min(int(training_bars), 1200)
        need_simple = max(fast_history + 2, int(chart_bars) + 2)
        try:
            base_simple = fetch_timeframe_history(SYMBOLS[selected], timeframe, need_simple)
            recent_simple = fetch_recent_timeframe_history(SYMBOLS[selected], timeframe, 36)
            full_simple = (pd.concat([base_simple, recent_simple], ignore_index=True)
                           .sort_values("timestamp")
                           .drop_duplicates("timestamp", keep="last")
                           .tail(need_simple)
                           .reset_index(drop=True))
            closed_simple = (full_simple[full_simple.is_closed]
                             .drop(columns=["is_closed"])
                             .tail(fast_history)
                             .reset_index(drop=True))
            chart_simple = full_simple.drop(columns=["is_closed"]).tail(int(chart_bars)).reset_index(drop=True)
        except Exception as e:
            st.error(f"No se pudieron cargar datos de mercado: {e}")
            return

        if closed_simple.empty:
            st.warning("Todavía no hay suficiente histórico cerrado para detectar tendencia.")
            return

        cycle = fast_cycle_context(SYMBOLS[selected])
        trend_info = trend_transition_forecast(closed_simple, timeframe, cycle)
        current = trend_info.get("current", {})
        cur = current.get("scenario", "LATERAL")
        cur_icon = "🟢" if cur == "SUBIDA" else "🔴" if cur == "BAJADA" else "🟡"
        cur_label = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"

        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label}")
        tr = trend_info.get("transition")
        if tr:
            to_icon = "🟢" if tr["to"] == "SUBIDA" else "🔴"
            to_label = "ALCISTA" if tr["to"] == "SUBIDA" else "BAJISTA"
            window = transition_window_text(timeframe, tr, int(trend_info.get("max_horizon", 8)))
            st.markdown(f"**{to_icon} Posible cambio a {to_label}: {window}**")
            st.caption(f"Evidencia {str(tr.get('reliability','MEDIA')).lower()} · confianza estimada {tr.get('probability',0.5)*100:.0f}%. Es una ventana probabilística, no una hora exacta.")
        else:
            window = transition_window_text(timeframe, None, int(trend_info.get("max_horizon", 8)))
            st.caption(f"No se detecta un cambio de tendencia suficientemente consistente: {window}.")

        fig_fast = trend_chart(chart_simple, selected, timeframe, trend_info)
        st.plotly_chart(fig_fast, width="stretch", theme=None,
                        key=f"trend_simple_{selected}_{timeframe}", config=plot_config())

        # Notify only when the ACTUAL detected trend changes, not on every candle.
        alert_key = f"trend_state::{selected}::{timeframe}"
        previous = st.session_state.get(alert_key)
        if previous is not None and previous != cur:
            text = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"
            st.toast(f"{selected} · {timeframe}: cambio de tendencia detectado → {text}", icon="🔔")
        st.session_state[alert_key] = cur

        # Notify when a NEW transition window appears or changes direction.
        watch_key = f"trend_watch::{selected}::{timeframe}"
        watch_now = None if not tr else (tr.get("to"), tr.get("start_bars"), tr.get("end_bars"))
        watch_prev = st.session_state.get(watch_key)
        if watch_now is not None and watch_prev is not None and watch_now != watch_prev:
            to_text = "ALCISTA" if tr["to"] == "SUBIDA" else "BAJISTA"
            st.toast(f"Posible próximo cambio → {to_text} · {transition_window_text(timeframe, tr, trend_info.get('max_horizon',8))}", icon="🔔")
        st.session_state[watch_key] = watch_now

        st.caption("🟢 tendencia alcista · 🔴 tendencia bajista · 🟡 sin tendencia clara. La app busca cambios de tendencia por temporalidad, no vela por vela.")

    _render_fast_simple_mode()
    st.stop()

'''

s = s[:start] + new_simple + s[end:]

p.write_text(s, encoding='utf-8')
print('Trend transition detector patch applied')
