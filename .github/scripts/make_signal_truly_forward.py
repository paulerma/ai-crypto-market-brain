from pathlib import Path
import ast

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# 1) Local chart timezone for a TradingView-like clock.
old = "from datetime import datetime, timezone\n\nimport requests"
new = "from datetime import datetime, timezone\nfrom zoneinfo import ZoneInfo\n\nimport requests"
if old in s:
    s = s.replace(old, new, 1)
elif "from zoneinfo import ZoneInfo" not in s:
    raise RuntimeError("No se encontró import datetime")

old = "VISIBLE_OPTIONS = [100, 200, 350, 500, 800]\n"
new = "VISIBLE_OPTIONS = [100, 200, 350, 500, 800]\nCHART_TZ = ZoneInfo(\"America/Hermosillo\")\n"
if old in s:
    s = s.replace(old, new, 1)
elif "CHART_TZ = ZoneInfo" not in s:
    raise RuntimeError("No se encontró VISIBLE_OPTIONS")

# 2) Very small fresh tail so 1m is not delayed by the 90-second historical cache.
anchor = '''    return out.tail(int(total)).reset_index(drop=True)\n\n\ndef fetch_live_quote(symbol: str) -> dict:\n'''
insert = '''    return out.tail(int(total)).reset_index(drop=True)\n\n\n@st.cache_data(ttl=3, max_entries=64, show_spinner=False)\ndef fetch_recent_binance_history(symbol: str, interval: str, total: int = 48) -> pd.DataFrame:\n    \"\"\"Fetch only the newest candles with a very short cache.\n\n    The long historical request stays cached for performance; this tiny tail is\n    merged on top so a newly closed 1m candle is detected within a few seconds.\n    \"\"\"\n    url = \"https://data-api.binance.vision/api/v3/klines\"\n    take = max(3, min(1000, int(total)))\n    r = requests.get(url, params={\"symbol\": symbol, \"interval\": interval, \"limit\": take}, timeout=10)\n    r.raise_for_status()\n    raw = r.json()\n    if not raw:\n        raise RuntimeError(\"Binance no devolvió velas recientes.\")\n    cols = [\"open_time\",\"open\",\"high\",\"low\",\"close\",\"volume\",\"close_time\",\"quote_volume\",\"trades\",\"taker_base\",\"taker_quote\",\"ignore\"]\n    df = pd.DataFrame(raw, columns=cols)\n    df[\"timestamp\"] = pd.to_datetime(df[\"open_time\"], unit=\"ms\", utc=True)\n    for c in [\"open\",\"high\",\"low\",\"close\",\"volume\",\"quote_volume\",\"trades\",\"taker_base\",\"taker_quote\"]:\n        df[c] = pd.to_numeric(df[c], errors=\"coerce\")\n    now_ms = pd.Timestamp.now(tz=\"UTC\").value // 1_000_000\n    df[\"is_closed\"] = pd.to_numeric(df[\"close_time\"], errors=\"coerce\") <= now_ms\n    keep = [\"timestamp\",\"open\",\"high\",\"low\",\"close\",\"volume\",\"quote_volume\",\"trades\",\"taker_base\",\"taker_quote\",\"is_closed\"]\n    return (df[keep]\n            .dropna(subset=[\"timestamp\",\"open\",\"high\",\"low\",\"close\",\"volume\"])\n            .sort_values(\"timestamp\").reset_index(drop=True))\n\n\n@st.cache_data(ttl=3, max_entries=64, show_spinner=False)\ndef fetch_recent_timeframe_history(symbol: str, timeframe: str, total: int = 32) -> pd.DataFrame:\n    spec = STANDARD_TIMEFRAMES[timeframe]\n    if not spec.is_synthetic:\n        return fetch_recent_binance_history(symbol, spec.fetch_interval, total)\n    raw_needed = int(total) * int(spec.aggregate_factor) + int(spec.aggregate_factor) * 2\n    raw = fetch_recent_binance_history(symbol, spec.fetch_interval, raw_needed)\n    out = aggregate_market_bars(raw, int(spec.aggregate_factor), spec.aggregate_unit)\n    if out.empty:\n        raise RuntimeError(f\"No se pudieron construir velas recientes {timeframe}.\")\n    return out.tail(int(total)).reset_index(drop=True)\n\n\ndef fetch_live_quote(symbol: str) -> dict:\n'''
if anchor in s:
    s = s.replace(anchor, insert, 1)
elif "def fetch_recent_timeframe_history" not in s:
    raise RuntimeError("No se encontró el final de fetch_timeframe_history")

# 3) Chart accepts the exact future candle start time.
s = s.replace(
    "def simple_signal_chart(df, symbol, timeframe, horizon, state, simple_forecast=None):",
    "def simple_signal_chart(df, symbol, timeframe, horizon, state, simple_forecast=None, target_time=None):",
    1,
)

old_chart_start = '''    fig = go.Figure()\n    fig.add_trace(go.Candlestick(\n        x=df.timestamp, open=df.open, high=df.high, low=df.low, close=df.close,\n        name=\"Precio\", increasing_line_color=\"#2ecc71\", decreasing_line_color=\"#ff5c5c\",\n    ))\n\n    last_x = pd.Timestamp(df.timestamp.iloc[-1])\n    first_x = pd.Timestamp(df.timestamp.iloc[0])\n    last_y = float(df.close.iloc[-1])\n    try:\n        # Reserve a separate visual signal column to the RIGHT of price.\n        # This is deliberately farther than one/two candles so the dot can never\n        # be mistaken for, or cover, a real candle. Forecast horizon is unchanged.\n        visual_slots = 6 if timeframe in (\"1m\", \"2m\", \"3m\", \"5m\", \"10m\", \"15m\") else 4\n        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, visual_slots))\n        signal_right_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, visual_slots + 5))\n    except Exception:\n        dot_x = last_x\n        signal_right_x = last_x\n'''
new_chart_start = '''    fig = go.Figure()\n    plot_df = df.copy()\n    plot_ts = pd.to_datetime(plot_df[\"timestamp\"], utc=True)\n    plot_df[\"timestamp\"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)\n    fig.add_trace(go.Candlestick(\n        x=plot_df.timestamp, open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,\n        name=\"Precio\", increasing_line_color=\"#2ecc71\", decreasing_line_color=\"#ff5c5c\",\n    ))\n\n    last_x = pd.Timestamp(plot_df.timestamp.iloc[-1])\n    first_x = pd.Timestamp(plot_df.timestamp.iloc[0])\n    last_y = float(plot_df.close.iloc[-1])\n    try:\n        if target_time is not None:\n            _target = pd.Timestamp(target_time)\n            if _target.tzinfo is None:\n                _target = _target.tz_localize(\"UTC\")\n            dot_x = _target.tz_convert(CHART_TZ).tz_localize(None)\n        else:\n            dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))\n        signal_right_x = pd.Timestamp(future_time(dot_x.to_pydatetime(), timeframe, 3))\n    except Exception:\n        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))\n        signal_right_x = dot_x\n'''
if old_chart_start in s:
    s = s.replace(old_chart_start, new_chart_start, 1)
elif "plot_df = df.copy()" not in s:
    raise RuntimeError("No se encontró inicio de simple_signal_chart")

# Label explicitly names the future candle time.
old_label = '''        probability = float(state.get(\"probability\", 0.0))\n        reliability = str(state.get(\"reliability\", \"\")).capitalize()\n        label = f\"PRÓXIMO: {short_label} · {probability*100:.1f}% · {timeframe}\"\n        hover = (f\"{short_label}<br>Confianza: {probability*100:.1f}%\"\n                 f\"<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}\")\n'''
new_label = '''        probability = float(state.get(\"probability\", 0.0))\n        reliability = str(state.get(\"reliability\", \"\")).capitalize()\n        if timeframe in (\"1m\", \"2m\", \"3m\", \"5m\", \"10m\", \"15m\", \"30m\", \"45m\", \"1h\", \"2h\", \"3h\", \"4h\"):\n            target_label = dot_x.strftime(\"%H:%M\")\n        elif timeframe in (\"1D\", \"1W\"):\n            target_label = dot_x.strftime(\"%d %b\")\n        else:\n            target_label = dot_x.strftime(\"%b %Y\")\n        label = f\"VELA {target_label}: {short_label} · {probability*100:.1f}%\"\n        hover = (f\"Predicción: {short_label}<br>Vela objetivo: {target_label}\"\n                 f\"<br>Confianza: {probability*100:.1f}%<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}\")\n'''
if old_label in s:
    s = s.replace(old_label, new_label, 1)
elif "VELA {target_label}" not in s:
    raise RuntimeError("No se encontró label de señal")

# 4) Put the dot in a dedicated top prediction lane; never over price candles.
old_marker = '''    # MAIN INDICATOR: one large dot at the right of the chart.\n    fig.add_trace(go.Scatter(\n        x=[dot_x], y=[last_y], mode=\"markers\",\n        marker={\"size\": 24, \"color\": dot_color,\n                \"line\": {\"color\": \"#ffffff\", \"width\": 2}},\n        hovertemplate=hover + \"<extra></extra>\",\n        name=\"Señal principal\", showlegend=False,\n    ))\n    fig.add_annotation(\n        x=dot_x, y=last_y, text=f\"<b>{label}</b>\", showarrow=False,\n        xshift=10, yshift=32, xanchor=\"left\",\n        font={\"color\": dot_color, \"size\": 13},\n        bgcolor=\"rgba(8,11,15,.88)\", bordercolor=dot_color,\n        borderwidth=1, borderpad=4,\n    )\n'''
new_marker = '''    # MAIN INDICATOR: a prediction lane at the TOP of the chart. The x-position\n    # is the future candle start; y uses paper coordinates, so it can never cover price.\n    slot_minutes = max(float(INTERVAL_MINUTES.get(timeframe, 1)), 1.0)\n    half = pd.Timedelta(minutes=slot_minutes * 0.20)\n    fig.add_shape(\n        type=\"circle\", xref=\"x\", yref=\"paper\",\n        x0=dot_x - half, x1=dot_x + half, y0=0.925, y1=0.975,\n        fillcolor=dot_color, line={\"color\": \"#ffffff\", \"width\": 2}, layer=\"above\",\n    )\n    fig.add_vline(x=dot_x, line_width=1, line_dash=\"dot\", line_color=dot_color, opacity=0.55)\n    fig.add_annotation(\n        x=dot_x, y=0.985, xref=\"x\", yref=\"paper\", text=f\"<b>{label}</b>\", showarrow=False,\n        xanchor=\"center\", yanchor=\"bottom\",\n        font={\"color\": dot_color, \"size\": 13},\n        bgcolor=\"rgba(8,11,15,.92)\", bordercolor=dot_color, borderwidth=1, borderpad=4,\n        hovertext=hover,\n    )\n'''
if old_marker in s:
    s = s.replace(old_marker, new_marker, 1)
elif "prediction lane at the TOP" not in s:
    raise RuntimeError("No se encontró bloque del punto")

# 5) More bottom room + unmistakable clock labels.
s = s.replace(
    'height=650, margin=dict(l=8, r=18, t=28, b=8),',
    'height=650, margin=dict(l=8, r=18, t=58, b=48),',
    1,
)
old_axis = '''    if timeframe in (\"1m\", \"2m\", \"3m\", \"5m\", \"10m\", \"15m\", \"30m\", \"45m\", \"1h\", \"2h\", \"3h\", \"4h\"):\n        tick_fmt = \"%H:%M\"\n        hover_fmt = \"%d %b %Y · %H:%M\"\n    elif timeframe == \"1D\":\n        tick_fmt = \"%d %b\"\n        hover_fmt = \"%d %b %Y\"\n    elif timeframe == \"1W\":\n        tick_fmt = \"%d %b\"\n        hover_fmt = \"Semana · %d %b %Y\"\n    else:\n        tick_fmt = \"%b %Y\"\n        hover_fmt = \"%B %Y\"\n\n    fig.update_xaxes(\n        gridcolor=\"#171d24\", fixedrange=False, showspikes=True, spikemode=\"across\",\n        spikesnap=\"cursor\", tickformat=tick_fmt, hoverformat=hover_fmt,\n        showgrid=True, ticks=\"outside\", ticklabelmode=\"instant\",\n    )\n'''
new_axis = '''    if timeframe in (\"1m\", \"2m\", \"3m\", \"5m\", \"10m\", \"15m\"):\n        tick_fmt = \"%H:%M\"\n        hover_fmt = \"%d %b %Y · %H:%M\"\n    elif timeframe in (\"30m\", \"45m\", \"1h\", \"2h\", \"3h\", \"4h\"):\n        tick_fmt = \"%d %b\\n%H:%M\"\n        hover_fmt = \"%d %b %Y · %H:%M\"\n    elif timeframe == \"1D\":\n        tick_fmt = \"%d %b\"\n        hover_fmt = \"%d %b %Y\"\n    elif timeframe == \"1W\":\n        tick_fmt = \"%d %b\"\n        hover_fmt = \"Semana · %d %b %Y\"\n    else:\n        tick_fmt = \"%b %Y\"\n        hover_fmt = \"%B %Y\"\n\n    fig.update_xaxes(\n        gridcolor=\"#171d24\", fixedrange=False, showspikes=True, spikemode=\"across\",\n        spikesnap=\"cursor\", tickformat=tick_fmt, hoverformat=hover_fmt,\n        showgrid=True, showticklabels=True, ticks=\"outside\", ticklen=5,\n        tickcolor=\"#65707c\", tickfont={\"size\": 11, \"color\": \"#aab4bf\"},\n        nticks=13, automargin=True, ticklabelmode=\"instant\",\n    )\n'''
if old_axis in s:
    s = s.replace(old_axis, new_axis, 1)
elif "showticklabels=True" not in s:
    raise RuntimeError("No se encontró eje temporal")

# 6) Update button also clears the fresh 3-second tail.
old_clear = '''        fetch_binance_history.clear()\n        cached_breadth.clear()\n'''
new_clear = '''        fetch_binance_history.clear()\n        fetch_recent_binance_history.clear()\n        fetch_recent_timeframe_history.clear()\n        cached_breadth.clear()\n'''
if old_clear in s:
    s = s.replace(old_clear, new_clear, 1)

# 7) Refresh fast enough to move the prediction forward BEFORE the target candle starts.
s = s.replace(
    '    @st.fragment(run_every="60s")\n    def _render_fast_simple_mode():',
    '    _simple_refresh = "5s" if timeframe == "1m" else "10s" if timeframe in ("2m", "3m", "5m") else "20s" if timeframe in ("10m", "15m") else "30s"\n    @st.fragment(run_every=_simple_refresh)\n    def _render_fast_simple_mode():',
    1,
)

old_fetch = '''            full_simple = fetch_timeframe_history(SYMBOLS[selected], timeframe, need_simple)\n            closed_simple = (full_simple[full_simple.is_closed]\n                             .drop(columns=[\"is_closed\"])\n                             .tail(fast_history)\n                             .reset_index(drop=True))\n            chart_simple = full_simple.drop(columns=[\"is_closed\"]).tail(int(chart_bars)).reset_index(drop=True)\n'''
new_fetch = '''            base_simple = fetch_timeframe_history(SYMBOLS[selected], timeframe, need_simple)\n            recent_simple = fetch_recent_timeframe_history(SYMBOLS[selected], timeframe, 36)\n            full_simple = (pd.concat([base_simple, recent_simple], ignore_index=True)\n                           .sort_values(\"timestamp\")\n                           .drop_duplicates(\"timestamp\", keep=\"last\")\n                           .tail(need_simple)\n                           .reset_index(drop=True))\n            closed_simple = (full_simple[full_simple.is_closed]\n                             .drop(columns=[\"is_closed\"])\n                             .tail(fast_history)\n                             .reset_index(drop=True))\n            chart_simple = full_simple.drop(columns=[\"is_closed\"]).tail(int(chart_bars)).reset_index(drop=True)\n'''
if old_fetch in s:
    s = s.replace(old_fetch, new_fetch, 1)
elif "recent_simple = fetch_recent_timeframe_history" not in s:
    raise RuntimeError("No se encontró carga del modo simple")

# 8) Target the next candle that has NOT STARTED yet. If a candle is forming,\n# predict the following candle with horizon=2 from the last closed bar.\nold_engine = '''        # Statistical/cycle engine: no walk-forward retraining on timeframe changes.\n        cycle = fast_cycle_context(SYMBOLS[selected])\n        fast_result = fast_statistical_signal(closed_simple, timeframe, int(horizon), cycle)\n        simple_state = fast_result.get(\"state\") if fast_result.get(\"ok\") else None\n'''
new_engine = '''        # Strict forward prediction: the target candle must not have started yet.\n        # The engine uses ONLY closed candles. If one candle is currently forming,\n        # horizon=2 predicts the close of the following, still-unopened candle.\n        forming_simple = full_simple[~full_simple.is_closed]\n        last_closed_open = pd.Timestamp(closed_simple.timestamp.iloc[-1])\n        if not forming_simple.empty:\n            current_open = pd.Timestamp(forming_simple.timestamp.iloc[-1])\n            target_time = future_time(current_open.to_pydatetime(), timeframe, 1)\n            prediction_horizon = 2\n        else:\n            target_time = future_time(last_closed_open.to_pydatetime(), timeframe, 1)\n            prediction_horizon = 1\n\n        cycle = fast_cycle_context(SYMBOLS[selected])\n        fast_result = fast_statistical_signal(closed_simple, timeframe, int(prediction_horizon), cycle)\n        simple_state = fast_result.get(\"state\") if fast_result.get(\"ok\") else None\n'''
if old_engine in s:
    s = s.replace(old_engine, new_engine, 1)
elif "prediction_horizon = 2" not in s:
    raise RuntimeError("No se encontró motor simple")

# Forecast uses the true forward horizon.
s = s.replace(
    'float(fast_result["atr"]), int(horizon), barrier_k=1.5,',
    'float(fast_result["atr"]), int(prediction_horizon), barrier_k=1.5,',
    1,
)
s = s.replace(
    'band.low68, band.high68, float(fast_result["atr"]), int(horizon),',
    'band.low68, band.high68, float(fast_result["atr"]), int(prediction_horizon),',
    1,
)

# 9) Header names the exact future candle, proving the signal is forward-looking.
old_header = '''        if simple_state:\n            sc = simple_state[\"scenario\"]\n            icon = \"🟢\" if sc == \"SUBIDA\" else \"🔴\" if sc == \"BAJADA\" else \"🟡\"\n            label = \"SUBE\" if sc == \"SUBIDA\" else \"BAJA\" if sc == \"BAJADA\" else \"LATERAL\"\n            strength = simple_state.get(\"reliability\", \"BAJA\").lower()\n            st.markdown(f\"### {icon} {selected} · PRÓXIMO: {label} · {simple_state['probability']*100:.1f}% · {timeframe}\")\n            st.caption(f\"Evidencia {strength} · el color muestra el rumbo más probable, no una certeza.\")\n        else:\n            st.markdown(f\"### ⚪ {selected} · DATOS INSUFICIENTES · {timeframe}\")\n\n        fig_fast = simple_signal_chart(\n            chart_simple, selected, timeframe, int(horizon), simple_state, simple_forecast_fast\n        )\n        st.plotly_chart(fig_fast, width=\"stretch\", theme=None,\n                        key=f\"fast_simple_{selected}_{timeframe}_{horizon}\", config=plot_config())\n'''
new_header = '''        _target = pd.Timestamp(target_time)\n        if _target.tzinfo is None:\n            _target = _target.tz_localize(\"UTC\")\n        target_local = _target.tz_convert(CHART_TZ)\n        if timeframe in (\"1m\", \"2m\", \"3m\", \"5m\", \"10m\", \"15m\", \"30m\", \"45m\", \"1h\", \"2h\", \"3h\", \"4h\"):\n            target_text = target_local.strftime(\"%H:%M\")\n        elif timeframe in (\"1D\", \"1W\"):\n            target_text = target_local.strftime(\"%d %b\")\n        else:\n            target_text = target_local.strftime(\"%b %Y\")\n\n        if simple_state:\n            sc = simple_state[\"scenario\"]\n            icon = \"🟢\" if sc == \"SUBIDA\" else \"🔴\" if sc == \"BAJADA\" else \"🟡\"\n            label = \"SUBE\" if sc == \"SUBIDA\" else \"BAJA\" if sc == \"BAJADA\" else \"LATERAL\"\n            strength = simple_state.get(\"reliability\", \"BAJA\").lower()\n            st.markdown(f\"### {icon} {selected} · VELA {target_text}: {label} · {simple_state['probability']*100:.1f}%\")\n            st.caption(f\"Predicción emitida antes de que empiece la vela {target_text} · usa solo velas cerradas · evidencia {strength}.\")\n        else:\n            st.markdown(f\"### ⚪ {selected} · DATOS INSUFICIENTES · {timeframe}\")\n\n        fig_fast = simple_signal_chart(\n            chart_simple, selected, timeframe, int(prediction_horizon), simple_state, simple_forecast_fast, target_time=target_time\n        )\n        st.plotly_chart(fig_fast, width=\"stretch\", theme=None,\n                        key=f\"fast_simple_{selected}_{timeframe}_{prediction_horizon}_{target_text}\", config=plot_config())\n'''
if old_header in s:
    s = s.replace(old_header, new_header, 1)
elif "Predicción emitida antes de que empiece" not in s:
    raise RuntimeError("No se encontró encabezado predictivo")

# Final caption: do not imply reaction to a candle already moving.
s = s.replace(
    '        st.caption(f"Señal para las próximas {horizon} vela(s) de {timeframe}. 🟢 sube · 🔴 baja · 🟡 lateral.")',
    '        st.caption(f"Objetivo: vela futura {target_text}. 🟢 sube · 🔴 baja · 🟡 lateral. El punto avanza a la siguiente vela antes de que empiece.")',
    1,
)

ast.parse(s)
p.write_text(s, encoding="utf-8")
print("forward-only signal and TradingView clock applied")
