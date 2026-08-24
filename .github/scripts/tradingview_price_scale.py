from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

start = s.find('def trend_chart(df: pd.DataFrame, symbol: str, timeframe: str, trend_info: dict):')
end = s.find('@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)\ndef monthly_consensus_state', start)
if start < 0 or end < 0:
    raise RuntimeError('No se encontró el bloque trend_chart')

block = s[start:end]

old_head = '''    plot_df = df.copy()\n    plot_ts = pd.to_datetime(plot_df["timestamp"], utc=True)\n    plot_df["timestamp"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)\n    fig.add_trace(go.Candlestick(\n        x=plot_df.timestamp,\n        open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,\n        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",\n    ))\n'''

new_head = '''    plot_df = df.copy()\n    plot_ts = pd.to_datetime(plot_df["timestamp"], utc=True)\n    plot_df["timestamp"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)\n\n    # TradingView-like price precision: large assets use 2 decimals while\n    # lower-priced coins keep enough decimals to avoid misleading rounding.\n    last_price = float(plot_df["close"].iloc[-1])\n    last_open = float(plot_df["open"].iloc[-1])\n    abs_price = abs(last_price)\n    if abs_price >= 100:\n        price_decimals = 2\n    elif abs_price >= 1:\n        price_decimals = 4\n    elif abs_price >= 0.01:\n        price_decimals = 5\n    else:\n        price_decimals = 8\n    price_tickformat = f",.{price_decimals}f"\n    price_text = f"{last_price:,.{price_decimals}f}"\n    current_price_color = "#2ecc71" if last_price >= last_open else "#ff5c5c"\n\n    ohlc_hover = [\n        (f"{pd.Timestamp(t).strftime('%d %b %Y · %H:%M')}"\n         f"<br>O {float(o):,.{price_decimals}f}"\n         f" · H {float(h):,.{price_decimals}f}"\n         f" · L {float(l):,.{price_decimals}f}"\n         f" · C {float(c):,.{price_decimals}f}")\n        for t, o, h, l, c in zip(\n            plot_df["timestamp"], plot_df["open"], plot_df["high"], plot_df["low"], plot_df["close"]\n        )\n    ]\n\n    fig.add_trace(go.Candlestick(\n        x=plot_df.timestamp,\n        open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,\n        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",\n        hovertext=ohlc_hover, hoverinfo="text",\n    ))\n'''

if old_head not in block:
    raise RuntimeError('No se encontró el encabezado actual de trend_chart')
block = block.replace(old_head, new_head, 1)

rail_marker = '''    fig.add_shape(type="circle", xref="paper", yref="paper",\n                  x0=1.018, x1=1.058, y0=0.61, y1=0.67,\n                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})\n'''

price_label = '''    # Current-price line and right-axis label, similar to TradingView.\n    # This is descriptive live-chart context, not a forecast marker.\n    fig.add_shape(\n        type="line", xref="paper", yref="y",\n        x0=0.0, x1=1.0, y0=last_price, y1=last_price,\n        line={"color": current_price_color, "width": 1, "dash": "dot"},\n        layer="above",\n    )\n    fig.add_annotation(\n        x=1.004, y=last_price, xref="paper", yref="y",\n        text=f"<b>{price_text}</b>", showarrow=False,\n        xanchor="left", yanchor="middle",\n        font={"color": "#ffffff", "size": 11},\n        bgcolor=current_price_color, bordercolor=current_price_color,\n        borderwidth=1, borderpad=4,\n    )\n\n'''

if rail_marker not in block:
    raise RuntimeError('No se encontró el rail de tendencia para insertar precio actual')
block = block.replace(rail_marker, price_label + rail_marker, 1)

old_y = '    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")\n'
new_y = '''    fig.update_yaxes(\n        gridcolor="#171d24", fixedrange=False, side="right",\n        tickformat=price_tickformat, hoverformat=price_tickformat,\n        separatethousands=True, showexponent="none", exponentformat="none",\n        ticks="outside", ticklen=5, tickcolor="#65707c",\n        tickfont={"size": 11, "color": "#c7d0d9"},\n        automargin=True,\n    )\n'''
if old_y not in block:
    raise RuntimeError('No se encontró el eje Y actual de trend_chart')
block = block.replace(old_y, new_y, 1)

s = s[:start] + block + s[end:]
p.write_text(s, encoding='utf-8')
print('Escala de precios TradingView aplicada al gráfico sencillo.')
