from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Make the user-facing label about direction, not a specific candle body.
s = s.replace(
'''        label = f"VELA {target_label}: {short_label} · {probability*100:.1f}%"\n        hover = (f"Predicción: {short_label}<br>Vela objetivo: {target_label}"\n                 f"<br>Confianza: {probability*100:.1f}%<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}")\n''',
'''        if short_label == "LATERAL":\n            short_label = "SIN DIRECCIÓN"\n        label = f"{short_label} · {probability*100:.1f}% · {timeframe}"\n        hover = (f"Rumbo más probable: {short_label}"\n                 f"<br>Confianza: {probability*100:.1f}%<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}")\n''',
1,
)

# 2) Put the main point OUTSIDE the candle plotting area, in the right margin.
old_point = '''    # MAIN INDICATOR: restore a clearly visible large point at the exact FUTURE\n    # candle start. Because dot_x is to the right of the forming candle, it never\n    # covers a real candle. A dotted guide identifies the target time.\n    fig.add_trace(go.Scatter(\n        x=[dot_x], y=[last_y], mode="markers",\n        marker={"size": 27, "color": dot_color, "line": {"color": "#ffffff", "width": 2}},\n        hovertemplate=hover + "<extra></extra>", showlegend=False, name="Predicción",\n    ))\n    fig.add_vline(x=dot_x, line_width=1, line_dash="dot", line_color=dot_color, opacity=0.60)\n    fig.add_annotation(\n        x=dot_x, y=last_y, xref="x", yref="y", text=f"<b>{label}</b>", showarrow=False,\n        xshift=14, yshift=32, xanchor="left",\n        font={"color": dot_color, "size": 13},\n        bgcolor="rgba(8,11,15,.92)", bordercolor=dot_color, borderwidth=1, borderpad=4,\n        hovertext=hover,\n    )\n'''
new_point = '''    # MAIN INDICATOR: fixed signal rail OUTSIDE the price plot.\n    # It stays visually dominant but can never cover a candle.\n    fig.add_shape(\n        type="circle", xref="paper", yref="paper",\n        x0=1.018, x1=1.060, y0=0.47, y1=0.53,\n        fillcolor=dot_color, line={"color": "#ffffff", "width": 2},\n        layer="above",\n    )\n    fig.add_annotation(\n        x=1.078, y=0.50, xref="paper", yref="paper", text=f"<b>{label}</b>", showarrow=False,\n        xanchor="left", yanchor="middle", align="left",\n        font={"color": dot_color, "size": 13},\n        bgcolor="rgba(8,11,15,.94)", bordercolor=dot_color, borderwidth=1, borderpad=5,\n        hovertext=hover,\n    )\n'''
if old_point not in s:
    raise RuntimeError('No se encontró bloque del punto principal')
s = s.replace(old_point, new_point, 1)

# 3) Remove the huge empty future area now that the signal lives in the margin.
old_range = '''    # Keep a true empty projection area to the right. Historical candles end at\n    # last_x; the signal dot lives in its own future column.\n    try:\n        span = last_x - first_x\n        if span <= pd.Timedelta(0):\n            span = pd.Timedelta(minutes=1)\n        right_edge = max(signal_right_x, last_x + span * 0.16)\n        fig.update_xaxes(range=[first_x, right_edge])\n    except Exception:\n        pass\n'''
new_range = '''    # Keep only a small amount of price-chart breathing room; the signal itself\n    # is outside the plot, so there is no need for a large blank future area.\n    try:\n        span = last_x - first_x\n        if span <= pd.Timedelta(0):\n            span = pd.Timedelta(minutes=1)\n        min_future = pd.Timedelta(minutes=max(1.0, float(INTERVAL_MINUTES.get(timeframe, 1))) * max(1, int(horizon)))\n        right_edge = max(last_x + span * 0.035, last_x + min_future)\n        fig.update_xaxes(range=[first_x, right_edge])\n    except Exception:\n        pass\n'''
if old_range not in s:
    raise RuntimeError('No se encontró rango de proyección')
s = s.replace(old_range, new_range, 1)

s = s.replace(
'        height=650, margin=dict(l=8, r=18, t=58, b=48),',
'        height=650, margin=dict(l=8, r=220, t=58, b=48),',
1,
)

# 4) Header: simply say SUBE / BAJA / SIN DIRECCIÓN, not “VELA 15:xx”.
old_header = '''        if simple_state:\n            sc = simple_state["scenario"]\n            icon = "🟢" if sc == "SUBIDA" else "🔴" if sc == "BAJADA" else "🟡"\n            label = "SUBE" if sc == "SUBIDA" else "BAJA" if sc == "BAJADA" else "LATERAL"\n            strength = simple_state.get("reliability", "BAJA").lower()\n            st.markdown(f"### {icon} {selected} · VELA {target_text}: {label} · {simple_state['probability']*100:.1f}%")\n            st.caption(f"Predicción emitida antes de que empiece la vela {target_text} · usa solo velas cerradas · evidencia {strength}.")\n        else:\n            st.markdown(f"### ⚪ {selected} · DATOS INSUFICIENTES · {timeframe}")\n'''
new_header = '''        if simple_state:\n            sc = simple_state["scenario"]\n            icon = "🟢" if sc == "SUBIDA" else "🔴" if sc == "BAJADA" else "🟡"\n            label = "SUBE" if sc == "SUBIDA" else "BAJA" if sc == "BAJADA" else "SIN DIRECCIÓN"\n            strength = simple_state.get("reliability", "BAJA").lower()\n            st.markdown(f"### {icon} {selected} · {label} · {simple_state['probability']*100:.1f}%")\n            st.caption(f"Rumbo más probable desde aquí · {timeframe} · evidencia {strength}. La señal usa solo información ya disponible.")\n        else:\n            st.markdown(f"### ⚪ {selected} · DATOS INSUFICIENTES · {timeframe}")\n'''
if old_header not in s:
    raise RuntimeError('No se encontró encabezado simple')
s = s.replace(old_header, new_header, 1)

# 5) Forward audit must score “did price go up/down from the reference point?”,
# not whether a particular candle body was green/red.
s = s.replace(
'''            audit[target_iso] = {\n                "scenario": simple_state["scenario"],\n                "confidence": float(simple_state["probability"]),\n                "resolved": False,\n            }\n''',
'''            audit[target_iso] = {\n                "scenario": simple_state["scenario"],\n                "confidence": float(simple_state["probability"]),\n                "reference_price": float(closed_simple["close"].iloc[-1]),\n                "resolved": False,\n            }\n''',
1,
)

s = s.replace(
'            move = float(candle["close"] / candle["open"] - 1.0)\n',
'            reference_price = float(rec.get("reference_price", candle["open"]))\n            move = float(candle["close"] / max(reference_price, 1e-12) - 1.0)\n',
1,
)

s = s.replace(
'            predicted_txt = "SUBE" if last_eval.get("scenario") == "SUBIDA" else "BAJA" if last_eval.get("scenario") == "BAJADA" else "LATERAL"\n',
'            predicted_txt = "SUBE" if last_eval.get("scenario") == "SUBIDA" else "BAJA" if last_eval.get("scenario") == "BAJADA" else "SIN DIRECCIÓN"\n',
1,
)

s = s.replace(
'        st.caption(f"Objetivo: vela futura {target_text}. 🟢 sube · 🔴 baja · 🟡 lateral. El punto avanza a la siguiente vela antes de que empiece.")\n',
'        st.caption("🟢 sube · 🔴 baja · 🟡 sin dirección clara. El punto indica el rumbo más probable y no tapa las velas.")\n',
1,
)

p.write_text(s, encoding='utf-8')
print('simple direction patch applied')
