from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '''    active_signal = max(signal_candidates, key=lambda x: (x[0], x[1])) if signal_candidates else None
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
'''

new = '''    active_signal = max(signal_candidates, key=lambda x: (x[0], x[1])) if signal_candidates else None
    marker_end_times = []
    if active_signal is not None:
        _, evidence, direction, status = active_signal
        color = "#2ecc71" if direction == "SUBIDA" else "#ff5c5c"
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        marker_x = _marker_time(1)
        marker_end_times.append(marker_x)
        status_txt = "GIRO EN FORMACIÓN" if status == "EN_FORMACION" else "SEÑAL ACTIVA"

        # Attach the target of the SAME ordered directional path to the active
        # signal. Prefer the first still-unreached target; do not display a stale
        # target that price has already crossed.
        path_rows = list((trend_info.get("market_path") or {}).get("rows") or [])
        direction_rows = [r for r in path_rows if r.get("direction") == direction and r.get("target_price") is not None]
        target_row = None
        for r in direction_rows:
            tp = float(r.get("target_price"))
            if (direction == "SUBIDA" and tp > last_price) or (direction == "BAJADA" and tp < last_price):
                target_row = r
                break

        # If every closed-candle target was already crossed by the live price,
        # re-anchor the nearest expected move to the current price rather than
        # keeping an obsolete level on screen.
        if target_row is None and direction_rows:
            base_ref = float((trend_info.get("market_path") or {}).get("reference_price") or last_price)
            source_row = direction_rows[0]
            old_target = float(source_row.get("target_price"))
            expected_return = (old_target / base_ref - 1.0) if base_ref > 0 else 0.0
            if direction == "SUBIDA":
                expected_return = max(abs(expected_return), 0.001)
            else:
                expected_return = -max(abs(expected_return), 0.001)
            target_value = last_price * (1.0 + expected_return)
            target_horizon = int(source_row.get("horizon", 1))
        elif target_row is not None:
            target_value = float(target_row.get("target_price"))
            target_horizon = int(target_row.get("horizon", 1))
        else:
            fc = dirs.get(direction) or {}
            target_value = float(fc.get("target_price", last_price))
            target_horizon = int(fc.get("timing_bars", 1))

        target_txt = _market_price_text(target_value, last_price)
        target_time = _duration_text(timeframe, max(1, target_horizon))
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[last_price], mode="markers+text",
            marker={"size": 19, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[f"{label} · hasta aprox. {target_txt}"], textposition="top center",
            textfont={"color": color, "size": 12},
            hovertemplate=(f"{status_txt}<br>{label}"
                           f"<br>Objetivo aprox.: {target_txt}"
                           f"<br>Horizonte objetivo: {target_time}"
                           f"<br>Evidencia IA: {evidence*100:.0f}%<extra></extra>"),
            name=f"Señal {label.lower()}",
            showlegend=False,
            cliponaxis=False,
        ))
'''

if new in s:
    print("Target label already present")
elif old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print("Added target to active signal")
else:
    raise RuntimeError("Active signal block not found")
