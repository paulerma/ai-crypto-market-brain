from pathlib import Path
import ast

p = Path('app.py')
s = p.read_text(encoding='utf-8')

old_dot = '''    try:\n        # Visual anchor only: place the signal two slots to the right so it never\n        # covers the live/last candle. The forecast horizon itself is unchanged.\n        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 2))\n    except Exception:\n        dot_x = last_x\n'''
new_dot = '''    try:\n        # Reserve a separate visual signal column to the RIGHT of price.\n        # This is deliberately farther than one/two candles so the dot can never\n        # be mistaken for, or cover, a real candle. Forecast horizon is unchanged.\n        visual_slots = 6 if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m") else 4\n        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, visual_slots))\n        signal_right_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, visual_slots + 5))\n    except Exception:\n        dot_x = last_x\n        signal_right_x = last_x\n'''
if old_dot in s:
    s = s.replace(old_dot, new_dot, 1)
elif new_dot not in s:
    raise RuntimeError('No se encontró el anclaje visual del punto')

old_right = '''    # Leave breathing room to the right for the dot/label.\n    try:\n        span = last_x - first_x\n        if span <= pd.Timedelta(0):\n            span = pd.Timedelta(minutes=1)\n        right_edge = max(dot_x, last_x + span * 0.18)\n        fig.update_xaxes(range=[first_x, right_edge])\n    except Exception:\n        pass\n'''
new_right = '''    # Keep a true empty projection area to the right. Historical candles end at\n    # last_x; the signal dot lives in its own future column.\n    try:\n        span = last_x - first_x\n        if span <= pd.Timedelta(0):\n            span = pd.Timedelta(minutes=1)\n        right_edge = max(signal_right_x, last_x + span * 0.16)\n        fig.update_xaxes(range=[first_x, right_edge])\n    except Exception:\n        pass\n'''
if old_right in s:
    s = s.replace(old_right, new_right, 1)
elif new_right not in s:
    raise RuntimeError('No se encontró el margen derecho del gráfico')

old_xaxis = '''    fig.update_xaxes(gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across")\n    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")\n    return fig\n'''
new_xaxis = '''    # TradingView-like temporal axis: clock for intraday, date for larger bars.\n    if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "3h", "4h"):\n        tick_fmt = "%H:%M"\n        hover_fmt = "%d %b %Y · %H:%M"\n    elif timeframe == "1D":\n        tick_fmt = "%d %b"\n        hover_fmt = "%d %b %Y"\n    elif timeframe == "1W":\n        tick_fmt = "%d %b"\n        hover_fmt = "Semana · %d %b %Y"\n    else:\n        tick_fmt = "%b %Y"\n        hover_fmt = "%B %Y"\n\n    fig.update_xaxes(\n        gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across",\n        spikesnap="cursor", tickformat=tick_fmt, hoverformat=hover_fmt,\n        showgrid=True, ticks="outside", ticklabelmode="instant",\n    )\n    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")\n    return fig\n'''
if old_xaxis in s:
    s = s.replace(old_xaxis, new_xaxis, 1)
elif new_xaxis not in s:
    raise RuntimeError('No se encontró el formato del eje X')

# Smaller dot, still obvious, to avoid dominating price action.
s = s.replace('marker={"size": 30, "color": dot_color,', 'marker={"size": 24, "color": dot_color,', 1)

ast.parse(s)
p.write_text(s, encoding='utf-8')
print('signal column and TradingView-like time axis applied')
