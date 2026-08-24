from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# Idempotent: if this patch is already present, do nothing.
if '"directional_forecasts": directional_forecasts' in s and 'PRÓXIMA SUBIDA' in s and 'PRÓXIMA BAJADA' in s:
    print('Ventanas de subida/bajada ya aplicadas.')
    raise SystemExit(0)

# 1) Always score BOTH directions from the same already-computed evidence.
old_candidates = '''    current_dir = current.get("scenario", "LATERAL")
    candidates = ["SUBIDA", "BAJADA"]
    if current_dir == "SUBIDA":
        candidates = ["BAJADA"]
    elif current_dir == "BAJADA":
        candidates = ["SUBIDA"]

    candidate_rows = []'''
new_candidates = '''    current_dir = current.get("scenario", "LATERAL")
    # Score BOTH directions every time. This does not run extra models: it reuses
    # the same multi-horizon, precursor and leading-timeframe evidence already
    # calculated above. The UI can therefore always show a probable UP window
    # and a probable DOWN window without increasing the heavy model load.
    candidates = ["SUBIDA", "BAJADA"]

    candidate_rows = []'''
if old_candidates not in s:
    raise RuntimeError('No se encontró el bloque de candidatos de dirección')
s = s.replace(old_candidates, new_candidates, 1)

# 2) Build a user-facing forecast for each direction, while keeping the actual
# trend-transition alert restricted to the OPPOSITE direction.
old_best = '''    best = max(candidate_rows, key=lambda x: x["evidence"]) if candidate_rows else None
    transition = None
    early_warning = None
    if best:
        # Two-stage output: very early warning first, then stronger "probable" move.
        if best["evidence"] >= 0.58:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.68 else "MEDIA"
        elif best["evidence"] >= 0.52:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.70))
            early_warning["reliability"] = "TEMPRANA"

    return {
        "current": current,
        "transition": transition,
        "early_warning": early_warning,
        "future": future,
        "sensors": sensors,
        "candidate_rows": candidate_rows,
        "max_horizon": 8,
    }'''
new_best = '''    # Always expose one forecast per direction. A low-evidence direction is kept
    # visible but explicitly marked as not yet having a reliable time window.
    directional_forecasts = {}
    for row in candidate_rows:
        fc = dict(row)
        ev = float(row.get("evidence", 0.5))
        fc["probability"] = float(np.clip(ev, 0.50, 0.85))
        if ev >= 0.58:
            fc["status"] = "PROBABLE"
            fc["reliability"] = "ALTA" if ev >= 0.68 else "MEDIA"
            fc["has_window"] = True
        elif ev >= 0.52:
            fc["status"] = "EN_FORMACION"
            fc["reliability"] = "TEMPRANA"
            fc["has_window"] = True
        else:
            fc["status"] = "SIN_VENTANA_FIABLE"
            fc["reliability"] = "BAJA"
            fc["has_window"] = False
        directional_forecasts[row["to"]] = fc

    # A trend-transition warning must refer to the direction OPPOSITE the trend
    # currently in force. If the market is lateral, choose the stronger side.
    if current_dir == "SUBIDA":
        reversal_rows = [r for r in candidate_rows if r["to"] == "BAJADA"]
    elif current_dir == "BAJADA":
        reversal_rows = [r for r in candidate_rows if r["to"] == "SUBIDA"]
    else:
        reversal_rows = list(candidate_rows)

    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
    transition = None
    early_warning = None
    if best:
        if best["evidence"] >= 0.58:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.68 else "MEDIA"
        elif best["evidence"] >= 0.52:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.70))
            early_warning["reliability"] = "TEMPRANA"

    return {
        "current": current,
        "transition": transition,
        "early_warning": early_warning,
        "future": future,
        "sensors": sensors,
        "candidate_rows": candidate_rows,
        "directional_forecasts": directional_forecasts,
        "max_horizon": 8,
    }'''
if old_best not in s:
    raise RuntimeError('No se encontró el bloque final de trend_transition_forecast')
s = s.replace(old_best, new_best, 1)

# 3) Put both UP and DOWN windows permanently in the simple main view.
old_ui = '''        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label} AHORA")
        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early
        if tr:
            to_icon = "🟢" if tr["to"] == "SUBIDA" else "🔴"
            move = "PROBABLE SUBIDA" if tr["to"] == "SUBIDA" else "PROBABLE BAJADA"
            window = transition_window_text(timeframe, tr, int(trend_info.get("max_horizon", 8)))
            st.markdown(f"## {to_icon} {move} · {window}")
            st.caption(f"Confianza IA {tr.get('probability',0.5)*100:.0f}% · evidencia {str(tr.get('reliability','MEDIA')).lower()}. La IA fusiona patrones históricos, momentum, volumen, impulso, varios horizontes y temporalidades adelantadas.")
        elif early:
            direction = "SUBIDA" if early["to"] == "SUBIDA" else "BAJADA"
            window = transition_window_text(timeframe, early, int(trend_info.get("max_horizon", 8)))
            st.markdown(f"## 🟠 {direction} POSIBLE EN FORMACIÓN · {window}")
            st.caption(f"Señales precursoras detectadas · confianza IA {early.get('probability',0.5)*100:.0f}%. Todavía no alcanza el nivel de 'probable'.")
        else:
            st.caption("Sin giro temprano detectado todavía. Esto NO significa que la tendencia no pueda cambiar; solo que la evidencia precursora aún no es suficiente.")'''
new_ui = '''        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label} AHORA")
        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early

        # ALWAYS show both directional windows. These are computed from the same
        # AI evidence, so displaying both does not add another heavy model pass.
        dirs = trend_info.get("directional_forecasts", {})
        up_fc = dirs.get("SUBIDA")
        down_fc = dirs.get("BAJADA")

        def _render_direction_forecast(fc, direction):
            icon = "🟢" if direction == "SUBIDA" else "🔴"
            title = "PRÓXIMA SUBIDA" if direction == "SUBIDA" else "PRÓXIMA BAJADA"
            if not fc:
                st.markdown(f"### {icon} {title} · sin cálculo disponible")
                return
            prob = float(fc.get("probability", 0.5)) * 100.0
            status = fc.get("status", "SIN_VENTANA_FIABLE")
            if fc.get("has_window"):
                window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
                qualifier = "PROBABLE" if status == "PROBABLE" else "POSIBLE EN FORMACIÓN"
                st.markdown(f"### {icon} {title} {qualifier} · {window}")
                st.caption(f"Confianza IA {prob:.0f}% · evidencia {str(fc.get('reliability','BAJA')).lower()}.")
            else:
                st.markdown(f"### {icon} {title} · sin ventana fiable todavía")
                st.caption(f"Evidencia actual {prob:.0f}% · todavía no alcanza el umbral para estimar cuándo comenzaría.")

        _render_direction_forecast(up_fc, "SUBIDA")
        _render_direction_forecast(down_fc, "BAJADA")

        if tr:
            move = "subida" if tr["to"] == "SUBIDA" else "bajada"
            st.caption(f"⚡ Giro principal detectado: probable {move} {transition_window_text(timeframe, tr, int(trend_info.get('max_horizon', 8)))}.")
        elif early:
            move = "subida" if early["to"] == "SUBIDA" else "bajada"
            st.caption(f"🟠 Giro temprano en formación: posible {move} {transition_window_text(timeframe, early, int(trend_info.get('max_horizon', 8)))}.")
        else:
            st.caption("Sin giro temprano dominante todavía; las dos direcciones siguen visibles arriba con su evidencia actual.")'''
if old_ui not in s:
    raise RuntimeError('No se encontró el bloque visual del modo sencillo')
s = s.replace(old_ui, new_ui, 1)

# 4) Make fallback compatible with the new always-visible UI.
s = s.replace('''                "candidate_rows": [],
                "max_horizon": 8,''', '''                "candidate_rows": [],
                "directional_forecasts": {},
                "max_horizon": 8,''', 1)

# 5) Replace the chart's one-next-move rail with two compact direction rows.
old_chart = '''    tr = trend_info.get("transition")
    early = trend_info.get("early_warning")
    active = tr or early
    if active:
        to = active["to"]
        next_color = "#2ecc71" if to == "SUBIDA" else "#ff5c5c"
        move_label = "PROBABLE SUBIDA" if to == "SUBIDA" else "PROBABLE BAJADA"
        if early and not tr:
            move_label = "SUBIDA EN FORMACIÓN" if to == "SUBIDA" else "BAJADA EN FORMACIÓN"
            next_color = "#f0a43c"
        window = transition_window_text(timeframe, active, int(trend_info.get("max_horizon", 8)))
        second = f"{move_label} · {window}"
        second_color = next_color
    else:
        second = "SIN GIRO TEMPRANO DETECTADO TODAVÍA"
        second_color = "#9aa4ae"

    fig.add_shape(type="circle", xref="paper", yref="paper",
                  x0=1.018, x1=1.058, y0=0.59, y1=0.65,
                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})
    fig.add_annotation(x=1.074, y=0.62, xref="paper", yref="paper",
                       text=f"<b>TENDENCIA AHORA: {cur_label}</b>", showarrow=False,
                       xanchor="left", font={"color": cur_color, "size": 14})
    fig.add_annotation(x=1.074, y=0.52, xref="paper", yref="paper",
                       text=f"<b>{second}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": second_color, "size": 12})
    if active:
        evidence_word = "temprana" if early and not tr else str(active.get("reliability", "MEDIA")).lower()
        fig.add_annotation(x=1.074, y=0.45, xref="paper", yref="paper",
                           text=f"confianza IA {active.get('probability',0.5)*100:.0f}% · evidencia {evidence_word}",
                           showarrow=False, xanchor="left",
                           font={"color": "#8b949e", "size": 11})'''
new_chart = '''    tr = trend_info.get("transition")
    early = trend_info.get("early_warning")
    active = tr or early
    dirs = trend_info.get("directional_forecasts", {})

    def _chart_dir_text(direction):
        fc = dirs.get(direction)
        name = "SUBIDA" if direction == "SUBIDA" else "BAJADA"
        if not fc:
            return f"{name}: SIN CÁLCULO", 0.5
        prob = float(fc.get("probability", 0.5))
        if fc.get("has_window"):
            window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
            return f"{name}: {window} · {prob*100:.0f}%", prob
        return f"{name}: SIN VENTANA FIABLE · {prob*100:.0f}%", prob

    up_text, _ = _chart_dir_text("SUBIDA")
    down_text, _ = _chart_dir_text("BAJADA")

    fig.add_shape(type="circle", xref="paper", yref="paper",
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
                       font={"color": "#ff5c5c", "size": 12})'''
if old_chart not in s:
    raise RuntimeError('No se encontró el bloque de señales del gráfico')
s = s.replace(old_chart, new_chart, 1)

p.write_text(s, encoding='utf-8')
print('Aplicado: subida y bajada siempre visibles con ventanas y confianza IA.')
