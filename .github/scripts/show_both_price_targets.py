from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

start_marker = '''    active_signal = max(signal_candidates, key=lambda x: (x[0], x[1])) if signal_candidates else None
'''
end_marker = '''    # Keep a little space to the right for the single active signal dot.
'''

start = s.find(start_marker)
end = s.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("Active signal target block not found")

new_block = '''    def _target_for_direction(direction: str):
        """Return a current, directionally valid target for UP or DOWN."""
        path = trend_info.get("market_path") or {}
        path_rows = list(path.get("rows") or [])
        direction_rows = [
            r for r in path_rows
            if r.get("direction") == direction and r.get("target_price") is not None
        ]

        # Prefer the first target that has not already been crossed by live price.
        for r in direction_rows:
            try:
                tp = float(r.get("target_price"))
            except Exception:
                continue
            if (direction == "SUBIDA" and tp > last_price) or (direction == "BAJADA" and tp < last_price):
                return tp, int(r.get("horizon", 1))

        # Then use the dedicated directional forecast (both directions are
        # calculated even if only one signal dot is active).
        fc = dirs.get(direction) or {}
        candidate_target = fc.get("target_price")
        candidate_horizon = int(fc.get("timing_bars", fc.get("start_bars", 1)))
        try:
            if candidate_target is not None and np.isfinite(float(candidate_target)):
                tp = float(candidate_target)
                if (direction == "SUBIDA" and tp > last_price) or (direction == "BAJADA" and tp < last_price):
                    return tp, max(1, candidate_horizon)
        except Exception:
            pass

        # If the model target was already crossed, preserve its expected
        # percentage move but re-anchor it to the live price.
        base_ref = float(path.get("reference_price") or last_price)
        source_target = None
        source_horizon = max(1, candidate_horizon)
        if direction_rows:
            source_target = float(direction_rows[0].get("target_price"))
            source_horizon = int(direction_rows[0].get("horizon", source_horizon))
        elif candidate_target is not None:
            try:
                source_target = float(candidate_target)
            except Exception:
                source_target = None

        if source_target is not None and base_ref > 0:
            expected_return = abs(source_target / base_ref - 1.0)
        else:
            expected_return = 0.0

        # Final market-derived fallback from recent realized true range. This is
        # only used when no usable directional target survives.
        if not np.isfinite(expected_return) or expected_return < 0.001:
            try:
                recent = plot_df.tail(20)
                prev_close = recent["close"].shift(1)
                tr_parts = pd.concat([
                    (recent["high"] - recent["low"]).abs(),
                    (recent["high"] - prev_close).abs(),
                    (recent["low"] - prev_close).abs(),
                ], axis=1)
                atr_live = float(tr_parts.max(axis=1).tail(14).mean())
            except Exception:
                atr_live = last_price * 0.005
            if not np.isfinite(atr_live) or atr_live <= 0:
                atr_live = last_price * 0.005
            expected_return = max(atr_live / max(last_price, 1e-12), 0.001) * np.sqrt(max(1, source_horizon))

        tp = last_price * (1.0 + expected_return) if direction == "SUBIDA" else last_price * (1.0 - expected_return)
        return float(max(tp, 1e-12)), max(1, source_horizon)

    # Calculate BOTH price objectives on every rerun, independently of which
    # directional signal dot is active.
    target_levels = {}
    for _direction in ("SUBIDA", "BAJADA"):
        try:
            target_levels[_direction] = _target_for_direction(_direction)
        except Exception:
            target_levels[_direction] = None

    active_signal = max(signal_candidates, key=lambda x: (x[0], x[1])) if signal_candidates else None
    marker_end_times = []
    if active_signal is not None:
        _, evidence, direction, status = active_signal
        color = "#2ecc71" if direction == "SUBIDA" else "#ff5c5c"
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        marker_x = _marker_time(1)
        marker_end_times.append(marker_x)
        status_txt = "GIRO EN FORMACIÓN" if status == "EN_FORMACION" else "SEÑAL ACTIVA"

        target_pair = target_levels.get(direction)
        if target_pair is not None:
            target_value, target_horizon = target_pair
            target_txt = _market_price_text(target_value, last_price)
            target_time = _duration_text(timeframe, max(1, target_horizon))
        else:
            target_txt = "N/D"
            target_time = "N/D"

        # ONE dot = active signal. Price objectives are drawn separately below.
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[last_price], mode="markers+text",
            marker={"size": 19, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[label], textposition="top center",
            textfont={"color": color, "size": 12},
            hovertemplate=(f"{status_txt}<br>{label}"
                           f"<br>Objetivo aprox.: {target_txt}"
                           f"<br>Horizonte objetivo: {target_time}"
                           f"<br>Evidencia IA: {evidence*100:.0f}%<extra></extra>"),
            name=f"Señal {label.lower()}",
            showlegend=False,
            cliponaxis=False,
        ))

    # ALWAYS show both directional price objectives, including while the market
    # is lateral. They are reference targets, not two simultaneous active signals.
    for direction, color, yanchor in (
        ("SUBIDA", "#2ecc71", "bottom"),
        ("BAJADA", "#ff5c5c", "top"),
    ):
        pair = target_levels.get(direction)
        if pair is None:
            continue
        target_value, target_horizon = pair
        target_txt = _market_price_text(target_value, last_price)
        objective_name = "OBJETIVO SUBIDA" if direction == "SUBIDA" else "OBJETIVO BAJADA"
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0.0, x1=1.0, y0=target_value, y1=target_value,
            line={"color": color, "width": 1, "dash": "dash"},
            layer="above",
        )
        fig.add_annotation(
            x=0.985, y=target_value, xref="paper", yref="y",
            text=f"<b>{objective_name} · {target_txt}</b>",
            showarrow=False, xanchor="right", yanchor=yanchor,
            font={"color": color, "size": 11},
            bgcolor="rgba(8,11,15,0.88)", bordercolor=color,
            borderwidth=1, borderpad=3,
        )

'''

s = s[:start] + new_block + s[end:]
p.write_text(s, encoding="utf-8")
print("Show both UP and DOWN targets on every timeframe")
