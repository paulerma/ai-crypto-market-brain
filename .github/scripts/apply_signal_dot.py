from pathlib import Path
import ast
import re

p = Path("app.py")
s = p.read_text(encoding="utf-8")

new_func = '''def simple_signal_chart(df, symbol, timeframe, horizon, state, simple_forecast=None):
    """Ultra-clean chart: candles plus one dominant signal dot on the right."""
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.timestamp,
        open=df.open,
        high=df.high,
        low=df.low,
        close=df.close,
        name="Precio",
        increasing_line_color="#2ecc71",
        decreasing_line_color="#ff5c5c",
    ))

    last_x = pd.Timestamp(df.timestamp.iloc[-1])
    first_x = pd.Timestamp(df.timestamp.iloc[0])
    last_y = float(df.close.iloc[-1])

    try:
        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))
    except Exception:
        dot_x = last_x

    if state:
        scenario = state["scenario"]
        if scenario == "SUBIDA":
            dot_color, short_label = "#2ecc71", "LONG"
        elif scenario == "BAJADA":
            dot_color, short_label = "#ff5c5c", "SHORT"
        else:
            dot_color, short_label = "#f2c94c", "LATERAL"

        probability = float(state.get("probability", 0.0))
        reliability = str(state.get("reliability", "")).capitalize()
        label = f"{short_label} · {probability*100:.1f}% · {timeframe}"
        hover = (
            f"{short_label}<br>Confianza: {probability*100:.1f}%"
            f"<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}"
        )
    else:
        dot_color, short_label = "#9aa4ae", "SIN SEÑAL FIABLE"
        label = f"SIN SEÑAL FIABLE · {timeframe}"
        hover = f"Sin señal suficientemente fiable<br>Temporalidad: {timeframe}"

    fig.add_trace(go.Scatter(
        x=[dot_x],
        y=[last_y],
        mode="markers",
        marker={
            "size": 26,
            "color": dot_color,
            "line": {"color": "#ffffff", "width": 2},
        },
        hovertemplate=hover + "<extra></extra>",
        name="Señal principal",
        showlegend=False,
    ))

    fig.add_annotation(
        x=dot_x,
        y=last_y,
        text=f"<b>{label}</b>",
        showarrow=False,
        xshift=8,
        yshift=31,
        xanchor="left",
        font={"color": dot_color, "size": 14},
        bgcolor="rgba(8,11,15,.90)",
        bordercolor=dot_color,
        borderwidth=1,
        borderpad=5,
    )

    try:
        span = last_x - first_x
        if span <= pd.Timedelta(0):
            span = pd.Timedelta(minutes=1)
        right_edge = max(dot_x, last_x + span * 0.16)
        fig.update_xaxes(range=[first_x, right_edge])
    except Exception:
        pass

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#080b0f",
        plot_bgcolor="#080b0f",
        height=650,
        margin=dict(l=8, r=18, t=30, b=8),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        dragmode="pan",
        showlegend=False,
        uirevision=f"simple-{symbol}-{timeframe}",
    )
    fig.update_xaxes(gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across")
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig
'''

pattern = r'def simple_signal_chart\(df, symbol, timeframe, horizon, state, simple_forecast=None\):.*?\n(?=def store_df\(key, value\):)'
s, count = re.subn(pattern, new_func + "\n", s, count=1, flags=re.S)
if count != 1:
    raise RuntimeError(f"No se pudo reemplazar simple_signal_chart: {count}")

s = s.replace(
    'f"{timeframe_label} · no se colorea la gráfica hasta que el análisis supere los filtros de fiabilidad."',
    'f"{timeframe_label} · el punto queda gris hasta que el análisis supere los filtros de fiabilidad."',
)

ast.parse(s)
p.write_text(s, encoding="utf-8")
print("Punto principal verde/rojo/amarillo aplicado")
