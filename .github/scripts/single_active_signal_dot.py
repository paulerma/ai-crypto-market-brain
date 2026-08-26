from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '''    marker_end_times = []
    for direction, color, text_pos in (
        ("SUBIDA", "#2ecc71", "top center"),
        ("BAJADA", "#ff5c5c", "bottom center"),
    ):
        fc = dirs.get(direction)
        if not fc or not fc.get("has_window"):
            continue
        start_bars = max(1, int(fc.get("start_bars", 1)))
        end_bars = max(start_bars, int(fc.get("end_bars", start_bars)))
        marker_x = _marker_time(start_bars)
        marker_end_times.append(_marker_time(end_bars))
        window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        y_pos = float(fc.get("target_price", last_price))
        target_txt = _market_price_text(y_pos, last_price)
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[y_pos], mode="markers+text",
            marker={"size": 18, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[f"{label} · {window} · {target_txt}"], textposition=text_pos,
            textfont={"color": color, "size": 11},
            hovertemplate=(f"{label}<br>Tiempo estimado: {window}"
                           f"<br>Objetivo aproximado: {target_txt}"
                           f"<br>Confianza IA: {float(fc.get('probability',0.5))*100:.0f}%<extra></extra>"),
            name=f"{label} probable",
            showlegend=False,
            cliponaxis=False,
        ))

    # Reserve future space so the timing dots are visible to the right of the
    # latest candle instead of overlapping price action.
    try:
        default_future = _marker_time(2)
        right_edge = max(marker_end_times + [default_future])
        historical_span = last_x - first_x
        if historical_span <= pd.Timedelta(0):
            historical_span = pd.Timedelta(minutes=1)
        right_edge = max(right_edge, last_x + historical_span * 0.08)
        fig.update_xaxes(range=[first_x, right_edge])
    except Exception:
        pass
'''

new = '''    # ONE signal dot only. The dot is a live directional SIGNAL, not a pair of
    # future projection markers. A forming reversal has priority over the trend
    # already in force; otherwise the current directional phase can stay active.
    onsets = trend_info.get("direction_onsets") or {}
    signal_candidates = []
    for direction in ("SUBIDA", "BAJADA"):
        onset = onsets.get(direction) or {}
        status = onset.get("status")
        if status not in ("EN_FORMACION", "YA_EN_CURSO"):
            continue
        priority = 2 if status == "EN_FORMACION" else 1
        evidence = float(onset.get("evidence", 0.5))
        signal_candidates.append((priority, evidence, direction, status))

    active_signal = max(signal_candidates, key=lambda x: (x[0], x[1])) if signal_candidates else None
    marker_end_times = []
    if active_signal is not None:
        _, evidence, direction, status = active_signal
        color = "#2ecc71" if direction == "SUBIDA" else "#ff5c5c"
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        marker_x = _marker_time(1)
        marker_end_times.append(marker_x)
        status_txt = "GIRO EN FORMACIÓN" if status == "EN_FORMACION" else "SEÑAL ACTIVA"
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[last_price], mode="markers+text",
            marker={"size": 19, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[label], textposition="top center",
            textfont={"color": color, "size": 12},
            hovertemplate=(f"{status_txt}<br>{label}"
                           f"<br>Evidencia IA: {evidence*100:.0f}%<extra></extra>"),
            name=f"Señal {label.lower()}",
            showlegend=False,
            cliponaxis=False,
        ))

    # Keep a little space to the right for the single active signal dot.
    try:
        default_future = _marker_time(1)
        right_edge = max(marker_end_times + [default_future])
        historical_span = last_x - first_x
        if historical_span <= pd.Timedelta(0):
            historical_span = pd.Timedelta(minutes=1)
        right_edge = max(right_edge, last_x + historical_span * 0.05)
        fig.update_xaxes(range=[first_x, right_edge])
    except Exception:
        pass
'''

if new in s:
    print("Signal-dot patch already applied")
elif old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print("Applied single active signal dot")
else:
    raise RuntimeError("Expected two-marker block not found")
