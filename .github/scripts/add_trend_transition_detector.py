from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# Replace the current trend/reversal helper block in-place. This script is
# intentionally idempotent so rerunning the workflow does not duplicate code.
helper_start = s.find('def _duration_text(timeframe: str, bars: int) -> str:')
helper_end_marker = '@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)\ndef monthly_consensus_state'
helper_end = s.find(helper_end_marker, helper_start)
if helper_start < 0 or helper_end < 0:
    raise RuntimeError('No se encontró el bloque actual del detector de tendencia')

helpers = r'''def _duration_text(timeframe: str, bars: int) -> str:
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


LEADING_TIMEFRAMES = {
    "1m": [],
    "2m": ["1m"],
    "3m": ["1m", "2m"],
    "5m": ["1m", "3m"],
    "10m": ["2m", "5m"],
    "15m": ["3m", "5m"],
    "30m": ["5m", "15m"],
    "45m": ["15m", "30m"],
    "1h": ["15m", "30m"],
    "2h": ["30m", "1h"],
    "3h": ["30m", "1h"],
    "4h": ["1h", "2h"],
    "1D": ["1h", "4h"],
    "1W": ["4h", "1D"],
    "1M": ["1D", "1W"],
}


@st.cache_data(ttl=45, max_entries=128, show_spinner=False)
def leading_sensor_state(symbol_code: str, sensor_tf: str, cycle_context: str | None) -> dict | None:
    """Use a lower timeframe as an early sensor without rerunning the heavy ML stack."""
    try:
        hist = min(int(DEFAULT_HISTORY.get(sensor_tf, 600)), 700)
        base = fetch_timeframe_history(symbol_code, sensor_tf, hist + 2)
        recent = fetch_recent_timeframe_history(symbol_code, sensor_tf, 36)
        full = (pd.concat([base, recent], ignore_index=True)
                .sort_values("timestamp")
                .drop_duplicates("timestamp", keep="last")
                .tail(hist + 2)
                .reset_index(drop=True))
        closed = full[full.is_closed].drop(columns=["is_closed"]).tail(hist).reset_index(drop=True)
        if len(closed) < 60:
            return None
        trend = current_trend_state(closed, sensor_tf)
        fast = fast_statistical_signal(closed, sensor_tf, 1, cycle_context)
        state = fast.get("state") if fast.get("ok") else None
        return {
            "timeframe": sensor_tf,
            "trend": trend,
            "forecast": state,
            "impulse": fast.get("impulse") if fast.get("ok") else None,
            "volume": fast.get("volume_direction") if fast.get("ok") else None,
        }
    except Exception:
        return None


def _precursor_strength(closed: pd.DataFrame, target: str) -> float:
    """Score changes that tend to occur before a full trend flip becomes visible."""
    try:
        f = build_features(closed)
        if len(f) < 6:
            return 0.5
        now = f.iloc[-1]
        prev = f.iloc[-4]
        c = closed["close"].astype(float)
        ret_now = float(c.iloc[-1] / c.iloc[-3] - 1.0) if len(c) >= 3 else 0.0
        ret_prev = float(c.iloc[-3] / c.iloc[-6] - 1.0) if len(c) >= 6 else 0.0

        macd_delta = float(now.get("macd_hist_pct", 0.0)) - float(prev.get("macd_hist_pct", 0.0))
        di_delta = float(now.get("di_spread", 0.0)) - float(prev.get("di_spread", 0.0))
        rsi_delta = float(now.get("rsi_14", 50.0)) - float(prev.get("rsi_14", 50.0))
        ret_delta = ret_now - ret_prev

        checks = []
        if target == "SUBIDA":
            checks.extend([macd_delta > 0, di_delta > 0, rsi_delta > 0, ret_delta > 0])
        else:
            checks.extend([macd_delta < 0, di_delta < 0, rsi_delta < 0, ret_delta < 0])

        if "taker_base" in closed.columns and "volume" in closed.columns:
            tail = closed.tail(5)
            volume = tail["volume"].astype(float).replace(0, np.nan)
            ratio = float((tail["taker_base"].astype(float) / volume).replace([np.inf, -np.inf], np.nan).dropna().mean())
            if np.isfinite(ratio):
                checks.append(ratio >= 0.51 if target == "SUBIDA" else ratio <= 0.49)

        if not checks:
            return 0.5
        return float(sum(bool(x) for x in checks) / len(checks))
    except Exception:
        return 0.5


def _direction_support(scenario: str, probability: float, candidate: str) -> float:
    probability = float(np.clip(probability, 0.0, 1.0))
    if scenario == candidate:
        return probability
    if scenario in ("SUBIDA", "BAJADA") and scenario != candidate:
        return 1.0 - probability
    return 0.5


@st.cache_data(ttl=45, max_entries=96, show_spinner=False)
def trend_transition_forecast(symbol_code: str, closed: pd.DataFrame, timeframe: str, cycle_context: str | None) -> dict:
    """Early reversal detector using multi-horizon + lower-timeframe precursor evidence.

    The current trend is descriptive. The reversal layer tries to detect the
    opposite move BEFORE the selected timeframe has fully flipped. It combines:
    historical analogues, trend/momentum, volume, immediate impulse, several
    horizons of the selected timeframe, and lower-timeframe leading sensors.
    """
    current = current_trend_state(closed, timeframe)
    horizons = [1, 2, 4, 8]
    future = []
    raw_results = []
    for h in horizons:
        try:
            res = fast_statistical_signal(closed, timeframe, int(h), cycle_context)
            raw_results.append(res)
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
            raw_results.append({"ok": False})
            future.append({"horizon": int(h), "scenario": "LATERAL", "probability": 0.5, "reliability": "BAJA"})

    sensors = []
    for tf in LEADING_TIMEFRAMES.get(timeframe, []):
        snap = leading_sensor_state(symbol_code, tf, cycle_context)
        if snap:
            sensors.append(snap)

    current_dir = current.get("scenario", "LATERAL")
    candidates = ["SUBIDA", "BAJADA"]
    if current_dir == "SUBIDA":
        candidates = ["BAJADA"]
    elif current_dir == "BAJADA":
        candidates = ["SUBIDA"]

    candidate_rows = []
    horizon_weights = [0.38, 0.30, 0.20, 0.12]
    for candidate in candidates:
        future_support = sum(
            w * _direction_support(r["scenario"], r["probability"], candidate)
            for w, r in zip(horizon_weights, future)
        )

        sensor_values = []
        sensor_agree = 0
        for snap in sensors:
            tr = snap.get("trend", {})
            fc = snap.get("forecast") or {}
            tr_support = 0.5
            if tr.get("scenario") == candidate:
                tr_support = 0.5 + 0.5 * float(tr.get("strength", 0.0))
                sensor_agree += 1
            elif tr.get("scenario") in ("SUBIDA", "BAJADA"):
                tr_support = 0.5 - 0.35 * float(tr.get("strength", 0.0))
            fc_support = _direction_support(fc.get("scenario", "LATERAL"), fc.get("probability", 0.5), candidate)
            sensor_values.append(0.45 * tr_support + 0.55 * fc_support)
            if fc.get("scenario") == candidate:
                sensor_agree += 1
        sensor_support = float(np.mean(sensor_values)) if sensor_values else 0.5

        precursor = _precursor_strength(closed, candidate)
        weakening = 0.5 if current_dir == "LATERAL" else 1.0 - float(current.get("strength", 0.5))

        immediate = raw_results[0] if raw_results and raw_results[0].get("ok") else {}
        component_dirs = [
            immediate.get("technical"),
            immediate.get("volume_direction"),
            immediate.get("impulse"),
            immediate.get("cycle"),
        ]
        component_support = float(np.mean([
            1.0 if x == candidate else 0.0 if x in ("SUBIDA", "BAJADA") else 0.5
            for x in component_dirs
        ])) if component_dirs else 0.5

        # Lower timeframes and precursor acceleration intentionally have more
        # weight than slow confirmation, because this layer is for EARLY warning.
        evidence = float(
            0.32 * future_support
            + 0.28 * sensor_support
            + 0.24 * precursor
            + 0.10 * component_support
            + 0.06 * weakening
        )

        earliest = None
        for r in future:
            if r["scenario"] == candidate and r["probability"] >= 0.52:
                earliest = int(r["horizon"])
                break
        if earliest is None and sensor_support >= 0.60 and precursor >= 0.60:
            earliest = 1
        if earliest is None:
            earliest = 4 if evidence >= 0.54 else 8

        if earliest <= 1:
            start_bars, end_bars = 1, 2
        elif earliest <= 2:
            start_bars, end_bars = 1, 2
        elif earliest <= 4:
            start_bars, end_bars = 2, 4
        else:
            start_bars, end_bars = 4, 8

        if evidence >= 0.68 and sensor_support >= 0.60 and precursor >= 0.60:
            start_bars, end_bars = 1, min(2, end_bars)

        candidate_rows.append({
            "to": candidate,
            "evidence": evidence,
            "future_support": future_support,
            "sensor_support": sensor_support,
            "precursor": precursor,
            "component_support": component_support,
            "sensor_agree": sensor_agree,
            "start_bars": int(start_bars),
            "end_bars": int(end_bars),
        })

    best = max(candidate_rows, key=lambda x: x["evidence"]) if candidate_rows else None
    transition = None
    early_warning = None
    if best:
        # Two-stage output: very early warning first, then stronger "probable" move.
        if best["evidence"] >= 0.58:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.68 else "MEDIA"
        elif best["evidence"] >= 0.52:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.70))
            early_warning["reliability"] = "TEMPRANA"

    return {
        "current": current,
        "transition": transition,
        "early_warning": early_warning,
        "future": future,
        "sensors": sensors,
        "candidate_rows": candidate_rows,
        "max_horizon": horizons[-1],
    }


def transition_window_text(timeframe: str, transition: dict | None, max_horizon: int = 8) -> str:
    if not transition:
        return "sin giro temprano detectado todavía"
    a = _duration_text(timeframe, int(transition["start_bars"]))
    b = _duration_text(timeframe, int(transition["end_bars"]))
    if a == b:
        return f"en {a}"
    return f"entre {a} y {b}"


def trend_chart(df: pd.DataFrame, symbol: str, timeframe: str, trend_info: dict):
    """Clean chart: current trend + early probable next move outside candles."""
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
    early = trend_info.get("early_warning")
    active = tr or early
    if active:
        to = active["to"]
        next_color = "#2ecc71" if to == "SUBIDA" else "#ff5c5c"
        move_label = "PROBABLE SUBIDA" if to == "SUBIDA" else "PROBABLE BAJADA"
        if early and not tr:
            move_label = "SUBIDA EN FORMACIÓN" if to == "SUBIDA" else "BAJADA EN FORMACIÓN"
            next_color = "#f0a43c"
        window = transition_window_text(timeframe, active, int(trend_info.get("max_horizon", 8)))
        second = f"{move_label} · {window}"
        second_color = next_color
    else:
        second = "SIN GIRO TEMPRANO DETECTADO TODAVÍA"
        second_color = "#9aa4ae"

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
    if active:
        evidence_word = "temprana" if early and not tr else str(active.get("reliability", "MEDIA")).lower()
        fig.add_annotation(x=1.074, y=0.45, xref="paper", yref="paper",
                           text=f"confianza IA {active.get('probability',0.5)*100:.0f}% · evidencia {evidence_word}",
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

s = s[:helper_start] + helpers + '\n\n' + s[helper_end:]

start_marker = '# ------------------------- Fast simple mode -------------------------\n'
end_marker = '# ------------------------- Data -------------------------\n'
start = s.find(start_marker)
end = s.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError('No se encontró el bloque de modo sencillo')

new_simple = r'''# ------------------------- Fast simple mode -------------------------
if ui_mode == "Sencillo":
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
        trend_info = trend_transition_forecast(SYMBOLS[selected], closed_simple, timeframe, cycle)
        current = trend_info.get("current", {})
        cur = current.get("scenario", "LATERAL")
        cur_icon = "🟢" if cur == "SUBIDA" else "🔴" if cur == "BAJADA" else "🟡"
        cur_label = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"

        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label} AHORA")
        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early
        if tr:
            to_icon = "🟢" if tr["to"] == "SUBIDA" else "🔴"
            move = "PROBABLE SUBIDA" if tr["to"] == "SUBIDA" else "PROBABLE BAJADA"
            window = transition_window_text(timeframe, tr, int(trend_info.get("max_horizon", 8)))
            st.markdown(f"## {to_icon} {move} · {window}")
            st.caption(f"Confianza IA {tr.get('probability',0.5)*100:.0f}% · evidencia {str(tr.get('reliability','MEDIA')).lower()}. La IA fusiona patrones históricos, momentum, volumen, impulso, varios horizontes y temporalidades adelantadas.")
        elif early:
            direction = "SUBIDA" if early["to"] == "SUBIDA" else "BAJADA"
            window = transition_window_text(timeframe, early, int(trend_info.get("max_horizon", 8)))
            st.markdown(f"## 🟠 {direction} POSIBLE EN FORMACIÓN · {window}")
            st.caption(f"Señales precursoras detectadas · confianza IA {early.get('probability',0.5)*100:.0f}%. Todavía no alcanza el nivel de 'probable'.")
        else:
            st.caption("Sin giro temprano detectado todavía. Esto NO significa que la tendencia no pueda cambiar; solo que la evidencia precursora aún no es suficiente.")

        fig_fast = trend_chart(chart_simple, selected, timeframe, trend_info)
        st.plotly_chart(fig_fast, width="stretch", theme=None,
                        key=f"trend_simple_{selected}_{timeframe}", config=plot_config())

        alert_key = f"trend_state::{selected}::{timeframe}"
        previous = st.session_state.get(alert_key)
        if previous is not None and previous != cur:
            text = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"
            st.toast(f"{selected} · {timeframe}: tendencia cambió → {text}", icon="🔔")
        st.session_state[alert_key] = cur

        watch_key = f"trend_watch::{selected}::{timeframe}"
        watch_now = None if not active else (active.get("to"), active.get("start_bars"), active.get("end_bars"), bool(tr))
        watch_prev = st.session_state.get(watch_key)
        if watch_now is not None and watch_prev != watch_now:
            direction = "SUBIDA" if active["to"] == "SUBIDA" else "BAJADA"
            prefix = "Probable" if tr else "Posible en formación"
            st.toast(f"{prefix} {direction.lower()} · {transition_window_text(timeframe, active, trend_info.get('max_horizon',8))}", icon="🔔")
        st.session_state[watch_key] = watch_now

        sensor_tfs = [x.get("timeframe") for x in trend_info.get("sensors", []) if x.get("timeframe")]
        if sensor_tfs:
            st.caption(f"Sensores adelantados usados: {', '.join(sensor_tfs)} · temporalidad principal: {timeframe}.")
        st.caption("La meta es detectar debilitamiento y giro antes de que la tendencia principal ya haya cambiado. No garantiza anticipar todos los giros.")

    _render_fast_simple_mode()
    st.stop()

'''

s = s[:start] + new_simple + s[end:]

# Update wording if an older caption/help string is still present.
s = s.replace(
    'st.caption("Elige activo y temporalidad. La vista sencilla detecta la tendencia actual y el próximo cambio probable.")',
    'st.caption("Elige activo y temporalidad. La IA busca la tendencia actual y señales tempranas del próximo giro.")',
    1,
)
s = s.replace(
    'help="Muestra la tendencia actual y una ventana probable para el próximo cambio de tendencia.",',
    'help="Muestra la tendencia actual y señales tempranas de probable subida o bajada antes del giro completo.",',
    1,
)

p.write_text(s, encoding='utf-8')
print('Early reversal detector patched successfully')
