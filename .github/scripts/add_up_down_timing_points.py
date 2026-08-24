from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

anchor = '''    up_text, _ = _chart_dir_text("SUBIDA")
    down_text, _ = _chart_dir_text("BAJADA")

    fig.add_shape(type="circle", xref="paper", yref="paper",'''

insert = '''    up_text, _ = _chart_dir_text("SUBIDA")
    down_text, _ = _chart_dir_text("BAJADA")

    # Forecast timing points on the chart. They mark the START of the estimated
    # window, not an exact guaranteed turning timestamp. Green = probable start
    # of an upward move; red = probable start of a downward move.
    last_x = pd.Timestamp(plot_df.timestamp.iloc[-1])
    first_x = pd.Timestamp(plot_df.timestamp.iloc[0])
    price_low = float(plot_df["low"].min())
    price_high = float(plot_df["high"].max())
    price_span = max(price_high - price_low, abs(float(plot_df["close"].iloc[-1])) * 0.002, 1e-9)

    def _marker_time(bars: int):
        bars = max(1, int(bars))
        if timeframe == "1M":
            return last_x + pd.DateOffset(months=bars)
        if timeframe == "1W":
            return last_x + pd.Timedelta(weeks=bars)
        if timeframe == "1D":
            return last_x + pd.Timedelta(days=bars)
        minutes = float(INTERVAL_MINUTES.get(timeframe, 1)) * bars
        return last_x + pd.Timedelta(minutes=minutes)

    marker_end_times = []
    for direction, color, y_pos, text_pos in (
        ("SUBIDA", "#2ecc71", price_low - 0.07 * price_span, "bottom center"),
        ("BAJADA", "#ff5c5c", price_high + 0.07 * price_span, "top center"),
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
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[y_pos], mode="markers+text",
            marker={"size": 18, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[f"{label} · {window}"], textposition=text_pos,
            textfont={"color": color, "size": 11},
            hovertemplate=(f"{label}<br>Inicio estimado de ventana: %{{x}}"
                           f"<br>{window}<br>Confianza IA: {float(fc.get('probability',0.5))*100:.0f}%<extra></extra>"),
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

    fig.add_shape(type="circle", xref="paper", yref="paper",'''

if 'Forecast timing points on the chart' in s:
    print('Timing points already present; no changes needed.')
elif anchor not in s:
    raise RuntimeError('No se encontró el punto de inserción en trend_chart')
else:
    s = s.replace(anchor, insert, 1)
    p.write_text(s, encoding='utf-8')
    print('Added green/red timing points for probable up/down starts.')
