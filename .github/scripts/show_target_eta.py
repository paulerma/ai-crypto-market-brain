from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '''        target_value, target_horizon = pair
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

new = '''        target_value, target_horizon = pair
        target_txt = _market_price_text(target_value, last_price)
        target_time = _duration_text(timeframe, max(1, int(target_horizon)))
        objective_name = "OBJETIVO SUBIDA" if direction == "SUBIDA" else "OBJETIVO BAJADA"
        fig.add_shape(
            type="line", xref="paper", yref="y",
            x0=0.0, x1=1.0, y0=target_value, y1=target_value,
            line={"color": color, "width": 1, "dash": "dash"},
            layer="above",
        )
        fig.add_annotation(
            x=0.985, y=target_value, xref="paper", yref="y",
            text=f"<b>{objective_name} · {target_txt} · aprox. {target_time}</b>",
            showarrow=False, xanchor="right", yanchor=yanchor,
            font={"color": color, "size": 11},
            bgcolor="rgba(8,11,15,0.88)", bordercolor=color,
            borderwidth=1, borderpad=3,
        )
'''

if new in s:
    print("Target ETA already visible")
elif old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print("Added ETA to both target labels")
else:
    raise RuntimeError("Both-target annotation block not found")
