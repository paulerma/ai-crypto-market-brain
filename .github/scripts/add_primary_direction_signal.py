from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Build a single primary direction from the two directional evidence scores.
old = '''    # A trend-transition warning must refer to the direction OPPOSITE the trend
    # currently in force. If the market is lateral, choose the stronger side.
    if current_dir == "SUBIDA":
'''
new = '''    # PRIMARY DIRECTION: compare UP vs DOWN directly.  The two evidence scores
    # are normalized into one complementary directional confidence so the user
    # gets one clear answer instead of two apparently competing probabilities.
    up_row = next((r for r in candidate_rows if r.get("to") == "SUBIDA"), None)
    down_row = next((r for r in candidate_rows if r.get("to") == "BAJADA"), None)
    primary_forecast = None
    if up_row is not None and down_row is not None:
        up_ev = max(1e-9, float(up_row.get("evidence", 0.5)))
        down_ev = max(1e-9, float(down_row.get("evidence", 0.5)))
        total_ev = up_ev + down_ev
        up_share = up_ev / total_ev
        down_share = down_ev / total_ev
        primary_dir = "SUBIDA" if up_share >= down_share else "BAJADA"
        primary_share = up_share if primary_dir == "SUBIDA" else down_share
        primary_fc = directional_forecasts.get(primary_dir) or {}
        primary_forecast = {
            "direction": primary_dir,
            "confidence": float(primary_share),
            "advantage": float(abs(up_share - down_share)),
            "window": primary_fc if primary_fc.get("has_window") else None,
            "status": primary_fc.get("status", "SIN_VENTANA_FIABLE"),
            "reliability": primary_fc.get("reliability", "BAJA"),
            "up_share": float(up_share),
            "down_share": float(down_share),
        }

    # A trend-transition warning must refer to the direction OPPOSITE the trend
    # currently in force. If the market is lateral, choose the stronger side.
    if current_dir == "SUBIDA":
'''
if old not in s:
    raise RuntimeError('No se encontró el bloque para insertar primary_forecast')
s = s.replace(old, new, 1)

old = '''        "candidate_rows": candidate_rows,
        "directional_forecasts": directional_forecasts,
        "max_horizon": 8,
'''
new = '''        "candidate_rows": candidate_rows,
        "directional_forecasts": directional_forecasts,
        "primary_forecast": primary_forecast,
        "max_horizon": 8,
'''
if old not in s:
    raise RuntimeError('No se encontró el return del trend pack')
s = s.replace(old, new, 1)

# 2) Add a large clear primary verdict to the chart rail.
old = '''    tr = trend_info.get("transition")
    early = trend_info.get("early_warning")
    active = tr or early
    dirs = trend_info.get("directional_forecasts", {})
'''
new = '''    tr = trend_info.get("transition")
    early = trend_info.get("early_warning")
    active = tr or early
    dirs = trend_info.get("directional_forecasts", {})
    primary = trend_info.get("primary_forecast") or {}
'''
if old not in s:
    raise RuntimeError('No se encontró el encabezado de trend_chart')
s = s.replace(old, new, 1)

old = '''    fig.add_shape(type="circle", xref="paper", yref="paper",
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
new = '''    primary_dir = primary.get("direction")
    primary_conf = float(primary.get("confidence", 0.5))
    primary_color = "#2ecc71" if primary_dir == "SUBIDA" else "#ff5c5c" if primary_dir == "BAJADA" else "#f2c94c"
    primary_label = "SUBIDA" if primary_dir == "SUBIDA" else "BAJADA" if primary_dir == "BAJADA" else "SIN VENTAJA"
    primary_window = primary.get("window")
    if primary_window:
        primary_when = transition_window_text(timeframe, primary_window, int(trend_info.get("max_horizon", 8)))
    else:
        primary_when = "sin ventana fiable todavía"

    fig.add_annotation(x=1.074, y=0.73, xref="paper", yref="paper",
                       text=(f"<b>RUMBO MÁS PROBABLE</b><br>"
                             f"<span style='font-size:17px'><b>{primary_label}</b></span><br>"
                             f"{primary_conf*100:.0f}% · {primary_when}"),
                       showarrow=False, xanchor="left", align="left",
                       font={"color": primary_color, "size": 13},
                       bgcolor="rgba(8,11,15,.94)", bordercolor=primary_color,
                       borderwidth=1, borderpad=6)

    fig.add_shape(type="circle", xref="paper", yref="paper",
                  x0=1.018, x1=1.058, y0=0.58, y1=0.64,
                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})
    fig.add_annotation(x=1.074, y=0.61, xref="paper", yref="paper",
                       text=f"<b>TENDENCIA AHORA: {cur_label}</b>", showarrow=False,
                       xanchor="left", font={"color": cur_color, "size": 13})
    fig.add_annotation(x=1.074, y=0.50, xref="paper", yref="paper",
                       text=f"<b>🟢 {up_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#2ecc71", "size": 11})
    fig.add_annotation(x=1.074, y=0.42, xref="paper", yref="paper",
                       text=f"<b>🔴 {down_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#ff5c5c", "size": 11})
'''
if old not in s:
    raise RuntimeError('No se encontró el rail actual del gráfico')
s = s.replace(old, new, 1)

# 3) Add the single verdict at the top of simple mode, before the detailed windows.
old = '''        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label} AHORA")
        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early

        # ALWAYS show both directional windows. These are computed from the same
'''
new = '''        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early
        primary = trend_info.get("primary_forecast") or {}
        primary_dir = primary.get("direction")
        primary_conf = float(primary.get("confidence", 0.5))
        primary_adv = float(primary.get("advantage", 0.0))
        primary_window = primary.get("window")

        if primary_dir in ("SUBIDA", "BAJADA"):
            primary_icon = "🟢" if primary_dir == "SUBIDA" else "🔴"
            primary_word = "SUBIDA" if primary_dir == "SUBIDA" else "BAJADA"
            if primary_window:
                primary_when = transition_window_text(timeframe, primary_window, int(trend_info.get("max_horizon", 8)))
            else:
                primary_when = "sin ventana fiable todavía"
            if primary_conf >= 0.62:
                primary_grade = "ventaja clara"
            elif primary_conf >= 0.56:
                primary_grade = "ventaja moderada"
            else:
                primary_grade = "ventaja leve"
            st.markdown(f"## {primary_icon} RUMBO MÁS PROBABLE: {primary_word}")
            st.markdown(f"### Inicio estimado: {primary_when}")
            st.caption(
                f"Confianza direccional {primary_conf*100:.0f}% · {primary_grade}. "
                f"La IA compara directamente evidencia de subida vs bajada; no es una garantía."
            )
        else:
            st.markdown("## 🟡 RUMBO MÁS PROBABLE: SIN VENTAJA CLARA")

        st.markdown(f"### {cur_icon} Tendencia actual: {cur_label} · {timeframe}")

        # ALWAYS show both directional windows. These are computed from the same
'''
if old not in s:
    raise RuntimeError('No se encontró el encabezado actual del modo sencillo')
s = s.replace(old, new, 1)

# Keep fallback shape compatible with the new UI.
s = s.replace('''                "directional_forecasts": {},
                "max_horizon": 8,
''', '''                "directional_forecasts": {},
                "primary_forecast": None,
                "max_horizon": 8,
''', 1)

p.write_text(s, encoding='utf-8')
print('Primary direction signal added.')
