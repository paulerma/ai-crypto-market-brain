from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '''        else:
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

new = '''        else:
            fc = dirs.get(direction) or {}
            candidate_target = fc.get("target_price")
            target_horizon = int(fc.get("timing_bars", 1))
            if candidate_target is not None and np.isfinite(float(candidate_target)):
                target_value = float(candidate_target)
            else:
                # Last-resort market-derived target so an active signal never
                # loses its price objective. Use recent true-range volatility,
                # not an arbitrary fixed dollar amount.
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
                move = max(atr_live, last_price * 0.001) * np.sqrt(max(1, target_horizon))
                target_value = last_price + move if direction == "SUBIDA" else last_price - move

        # Guard directional consistency after every fallback/re-anchor.
        if direction == "SUBIDA" and target_value <= last_price:
            distance = max(abs(last_price - target_value), last_price * 0.001)
            target_value = last_price + distance
        elif direction == "BAJADA" and target_value >= last_price:
            distance = max(abs(target_value - last_price), last_price * 0.001)
            target_value = last_price - distance

        target_txt = _market_price_text(target_value, last_price)
        target_time = _duration_text(timeframe, max(1, target_horizon))

        # Keep the dot text short on mobile; the price target gets its own line
        # and in-chart label so it cannot be clipped at the right edge.
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
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0.0, x1=1.0, y0=target_value, y1=target_value,
            line={"color": color, "width": 1, "dash": "dash"},
            layer="above",
        )
        objective_name = "OBJETIVO SUBIDA" if direction == "SUBIDA" else "OBJETIVO BAJADA"
        fig.add_annotation(
            x=0.985, y=target_value, xref="paper", yref="y",
            text=f"<b>{objective_name} · {target_txt}</b>",
            showarrow=False, xanchor="right", yanchor="bottom",
            font={"color": color, "size": 11},
            bgcolor="rgba(8,11,15,0.88)", bordercolor=color,
            borderwidth=1, borderpad=3,
        )
'''

if new in s:
    print("Active target line already present")
elif old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print("Added always-visible active signal target line")
else:
    raise RuntimeError("Expected active target block not found")
