from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

rail = '''    fig.add_shape(type="circle", xref="paper", yref="paper",
                  x0=1.018, x1=1.058, y0=0.61, y1=0.67,
                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})
    fig.add_annotation(x=1.074, y=0.64, xref="paper", yref="paper",
                       text=f"<b>TENDENCIA AHORA: {cur_label}</b>", showarrow=False,
                       xanchor="left", font={"color": cur_color, "size": 14})
    fig.add_annotation(x=1.074, y=0.53, xref="paper", yref="paper",
                       text=f"<b>🟢 {up_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#2ecc71", "size": 12})
    fig.add_annotation(x=1.074, y=0.45, xref="paper", yref="paper",
                       text=f"<b>🔴 {down_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#ff5c5c", "size": 12})
'''
if rail in s:
    s = s.replace(rail, '', 1)

s = s.replace('        height=650, margin=dict(l=8, r=300, t=36, b=48),',
              '        height=650, margin=dict(l=8, r=80, t=36, b=48),', 1)

extra = '''        sensor_tfs = [x.get("timeframe") for x in trend_info.get("sensors", []) if x.get("timeframe")]
        if sensor_tfs:
            st.caption(f"Sensores adelantados usados: {', '.join(sensor_tfs)} · temporalidad principal: {timeframe}.")
        st.caption("La meta es detectar debilitamiento y giro antes de que la tendencia principal ya haya cambiado. No garantiza anticipar todos los giros.")
'''
if extra in s:
    s = s.replace(extra, '', 1)

p.write_text(s, encoding='utf-8')
print('Gráfica sencilla limpiada: solo tiempos de subida/bajada, puntos y precio.')
