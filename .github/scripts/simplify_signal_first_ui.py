from pathlib import Path
import ast

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# 1) Make the fast statistical engine always expose its dominant reading.
# Reliability remains explicit, so a weak reading is not presented as a strong one.
old_gate = '''    # Very selective gate. If evidence disagrees, gray is preferable to a false color.
    if dom in ("SUBIDA", "BAJADA"):
        reliable = (analog_dom == dom and prob >= 0.47 and margin >= 0.075 and confirmations >= 2)
    else:
        reliable = (analog_dom == "LATERAL" and tech == "LATERAL" and prob >= 0.44 and margin >= 0.055)

    state = None
    if reliable:
        high = prob >= 0.60 and margin >= 0.16 and confirmations >= 3
        state = {
            "scenario": dom,
            "probability": prob,
            "reliability": "ALTA" if high else "MEDIA",
            "source": "patrones históricos + tendencia + volumen + ciclo",
        }
'''
new_gate = '''    # SIMPLE mode must always answer the user's main question: what direction is
    # currently most probable in the selected timeframe?  We therefore expose
    # the dominant class even when evidence is weak, but we NEVER hide the
    # uncertainty: strength is labelled BAJA / MEDIA / ALTA.
    high = prob >= 0.60 and margin >= 0.16 and confirmations >= 3
    if dom in ("SUBIDA", "BAJADA"):
        medium = prob >= 0.47 and margin >= 0.07 and confirmations >= 2
    else:
        medium = prob >= 0.44 and margin >= 0.05 and confirmations >= 1
    state = {
        "scenario": dom,
        "probability": prob,
        "reliability": "ALTA" if high else "MEDIA" if medium else "BAJA",
        "source": "patrones históricos + tendencia + momentum + volumen + ciclo",
    }
'''
if old_gate in s:
    s = s.replace(old_gate, new_gate, 1)
elif new_gate not in s:
    raise RuntimeError("No se encontró el bloque de fiabilidad del motor rápido")

# 2) Use timeframe-aware lateral thresholds. A 0.4% flat threshold is far too
# large for a one-minute candle and made 1m look lateral/undefined too often.
old_thr = '''    atr_pct = float(row.get("atr_pct", 0.01))
    flat_thr = float(np.clip(0.35 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))), 0.004, 0.05))
'''
new_thr = '''    atr_pct = float(row.get("atr_pct", 0.01))
    flat_floor = {
        "1m": 0.0004, "2m": 0.0005, "3m": 0.0006, "5m": 0.0008,
        "10m": 0.0010, "15m": 0.0012, "30m": 0.0015, "45m": 0.0018,
        "1h": 0.0020, "2h": 0.0025, "3h": 0.0030, "4h": 0.0035,
        "1D": 0.0050, "1W": 0.0120, "1M": 0.0250,
    }.get(timeframe, 0.0020)
    flat_ceiling = max(flat_floor * 8.0, 0.012)
    flat_thr = float(np.clip(
        0.35 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))),
        flat_floor, flat_ceiling,
    ))
'''
if old_thr in s:
    s = s.replace(old_thr, new_thr, 1)
elif new_thr not in s:
    raise RuntimeError("No se encontró flat_thr para hacerlo dependiente de temporalidad")

# 3) Simple sidebar = only asset + TradingView timeframe.  Chart length and
# projection horizon are automatic; advanced mode keeps the manual controls.
old_controls = '''    timeframe_label = st.selectbox(
        "Temporalidad",
        list(TIMEFRAME_UI.keys()),
        index=list(TIMEFRAME_UI.keys()).index("1 hora"),
        help="Temporalidades estándar: minutos, horas, día, semana y mes. La letra interna del código no se muestra para evitar confundir 'm' con metros.",
    )
    timeframe = TIMEFRAME_UI[timeframe_label]
    chart_bars = st.select_slider("Velas en gráfico", options=VISIBLE_OPTIONS, value=200)

    st.markdown("#### ¿Qué periodo quieres proyectar?")
    horizon_name = st.selectbox("Periodo", list(HORIZONS.keys()), index=1, label_visibility="collapsed")
    horizon = HORIZONS[horizon_name]
    st.caption(f"{horizon_name}: aprox. {horizon_text(timeframe, horizon)}")

    if ui_mode == "Avanzado":
'''
new_controls = '''    if ui_mode == "Sencillo":
        # Exact TradingView-style codes.  Nothing else is required from the user.
        _simple_tfs = list(TIMEFRAME_UI.values())
        timeframe = st.selectbox(
            "Temporalidad",
            _simple_tfs,
            index=_simple_tfs.index("1h"),
            help="El punto de la gráfica indica el rumbo más probable para esta temporalidad.",
        )
        timeframe_label = next(k for k, v in TIMEFRAME_UI.items() if v == timeframe)
        chart_bars = 180
        horizon_name = "Automático"
        # Four candles smooths 1m noise without making the user choose a period.
        # 1m -> ~4 min, 1h -> ~4 h, 1D -> ~4 días, etc.
        horizon = 4
    else:
        timeframe_label = st.selectbox(
            "Temporalidad",
            list(TIMEFRAME_UI.keys()),
            index=list(TIMEFRAME_UI.keys()).index("1 hora"),
            help="Temporalidad de TradingView usada por el análisis.",
        )
        timeframe = TIMEFRAME_UI[timeframe_label]
        chart_bars = st.select_slider("Velas en gráfico", options=VISIBLE_OPTIONS, value=200)
        st.markdown("#### Horizonte de proyección")
        horizon_name = st.selectbox("Periodo", list(HORIZONS.keys()), index=1, label_visibility="collapsed")
        horizon = HORIZONS[horizon_name]
        st.caption(f"{horizon_name}: aprox. {horizon_text(timeframe, horizon)}")

    if ui_mode == "Avanzado":
'''
if old_controls in s:
    s = s.replace(old_controls, new_controls, 1)
elif new_controls not in s:
    raise RuntimeError("No se encontró el bloque de controles del sidebar")

# 4) Use natural Spanish direction words in the SIMPLE chart, instead of
# trading jargon. Advanced mode remains untouched.
s = s.replace('dot_color, short_label = "#2ecc71", "LONG"',
              'dot_color, short_label = "#2ecc71", "SUBE"', 1)
s = s.replace('dot_color, short_label = "#ff5c5c", "SHORT"',
              'dot_color, short_label = "#ff5c5c", "BAJA"', 1)

old_header = '''            label = "LONG" if sc == "SUBIDA" else "SHORT" if sc == "BAJADA" else "LATERAL"
            st.markdown(f"### {icon} {selected} · {label} · {simple_state['probability']*100:.1f}% · {timeframe}")
        else:
            st.markdown(f"### ⚪ {selected} · SIN SEÑAL FIABLE · {timeframe}")
'''
new_header = '''            label = "SUBE" if sc == "SUBIDA" else "BAJA" if sc == "BAJADA" else "LATERAL"
            strength = simple_state.get("reliability", "BAJA").lower()
            st.markdown(f"### {icon} {selected} · {label} · {simple_state['probability']*100:.1f}% · {timeframe}")
            st.caption(f"Evidencia {strength} · el color muestra el rumbo más probable, no una certeza.")
        else:
            st.markdown(f"### ⚪ {selected} · DATOS INSUFICIENTES · {timeframe}")
'''
if old_header in s:
    s = s.replace(old_header, new_header, 1)
elif new_header not in s:
    raise RuntimeError("No se encontró el encabezado del modo simple")

# 5) A stop line is useful only when the directional evidence is at least medium.
old_stop = '''    if state and state.get("scenario") in ("SUBIDA", "BAJADA") and plan is not None:
'''
new_stop = '''    if (state and state.get("scenario") in ("SUBIDA", "BAJADA")
            and state.get("reliability") in ("MEDIA", "ALTA") and plan is not None):
'''
if old_stop in s:
    s = s.replace(old_stop, new_stop, 1)
elif new_stop not in s:
    raise RuntimeError("No se encontró la condición del stop")

# 6) Simplify the explanatory copy.
s = s.replace(
    'st.caption("Pantalla simple: qué es más probable, en qué VELA podría empezar el cambio, rango de precio y stop condicional. Los cálculos avanzados quedan detrás.")',
    'st.caption("Elige activo y temporalidad. El punto de color en la gráfica es la señal principal.")',
    1,
)
s = s.replace(
    'st.caption("Análisis rápido: patrones históricos + tendencia + volumen + contexto de ciclo. El ML pesado queda en Avanzado.")',
    'st.caption("🟢 sube · 🔴 baja · 🟡 lateral. El resto del análisis trabaja por detrás.")',
    1,
)

# 7) Notifications also use the same plain-language labels.
s = s.replace('"LONG" if current_state == "SUBIDA" else\n                   "SHORT" if current_state == "BAJADA" else',
              '"SUBE" if current_state == "SUBIDA" else\n                   "BAJA" if current_state == "BAJADA" else', 1)

ast.parse(s)
p.write_text(s, encoding="utf-8")
print("signal-first simple UI applied")
