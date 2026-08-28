from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# 1) Restore a meaningful undecided band in the fast engine.
s = s.replace(
'''    # Tiny dead-zone only. The user should normally see green or red, not yellow.
    tie_band = 0.02  # 48%-52% = truly undecided
''',
'''    # Meaningful dead-zone. Do NOT force a direction when UP vs DOWN are close.
    # A forced answer is especially dangerous on leveraged trades.
    tie_band = 0.08  # roughly 46%-54% = direction not strong enough
''')

# 2) Strengthen transition/early-signal gate using independent evidence families.
old_best = '''    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
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
'''

new_best = '''    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
    transition = None
    early_warning = None
    if best:
        family_votes = [
            float(best.get("future_support", 0.5)) >= 0.56,
            float(best.get("precursor", 0.5)) >= 0.60,
            float(best.get("component_support", 0.5)) >= 0.60,
        ]
        if sensors:
            family_votes.append(
                float(best.get("sensor_support", 0.5)) >= 0.56
                and int(best.get("sensor_agree", 0)) >= 1
            )
        required_votes = 3 if sensors else 2
        signal_gate = (
            bool(best.get("timing_ok", False))
            and float(best.get("timing_score", 0.5)) >= 0.55
            and sum(bool(v) for v in family_votes) >= required_votes
        )
        if signal_gate and best["evidence"] >= 0.64:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.70 else "MEDIA"
        elif signal_gate and best["evidence"] >= 0.59:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.72))
            early_warning["reliability"] = "TEMPRANA"
'''

if old_best in s:
    s = s.replace(old_best, new_best, 1)

# 3) Chart point: predictive alert only, NEVER current trend/YA_EN_CURSO.
old_chart = '''    onsets = trend_info.get("direction_onsets") or {}
    signal_candidates = []
    for direction in ("SUBIDA", "BAJADA"):
        onset = onsets.get(direction) or {}
        status = onset.get("status")
        if status not in ("EN_FORMACION", "YA_EN_CURSO"):
            continue
        priority = 2 if status == "EN_FORMACION" else 1
        evidence = float(onset.get("evidence", 0.5))
        signal_candidates.append((priority, evidence, direction, status))
'''

new_chart = '''    onsets = trend_info.get("direction_onsets") or {}
    signal_candidates = []
    predictive_alert = trend_info.get("transition") or trend_info.get("early_warning")
    if predictive_alert:
        direction = predictive_alert.get("to")
        if direction in ("SUBIDA", "BAJADA"):
            status = "CONFIRMADA" if trend_info.get("transition") else "EN_FORMACION"
            evidence = float(predictive_alert.get("evidence", predictive_alert.get("probability", 0.5)))
            signal_candidates.append((2 if status == "CONFIRMADA" else 1, evidence, direction, status))
'''
if old_chart in s:
    s = s.replace(old_chart, new_chart, 1)

s = s.replace(
'status_txt = "GIRO EN FORMACIÓN" if status == "EN_FORMACION" else "SEÑAL ACTIVA"',
'status_txt = "GIRO EN FORMACIÓN" if status == "EN_FORMACION" else "SEÑAL PREDICTIVA ACTIVA"'
)

# 4) Simple-mode headline: predictive signal only; current trend remains descriptive.
old_ui_signal = '''        # Use the exact same active-signal priority as the chart: a forming turn
        # beats a trend already in force. This keeps the headline and signal dot
        # synchronized instead of saying LATERAL while a red/green signal is active.
        _ui_signal_candidates = []
        for _direction in ("SUBIDA", "BAJADA"):
            _onset = onsets.get(_direction) or {}
            _status = _onset.get("status")
            if _status not in ("EN_FORMACION", "YA_EN_CURSO"):
                continue
            _priority = 2 if _status == "EN_FORMACION" else 1
            _evidence = float(_onset.get("evidence", 0.5))
            _ui_signal_candidates.append((_priority, _evidence, _direction, _status))
        _ui_active_signal = (
            max(_ui_signal_candidates, key=lambda x: (x[0], x[1]))
            if _ui_signal_candidates else None
        )
'''

new_ui_signal = '''        # The headline signal must be predictive, not merely the trend already
        # present. A colored signal exists only after the stricter transition gate.
        _ui_active_signal = None
        _predictive = trend_info.get("transition") or trend_info.get("early_warning")
        if _predictive and _predictive.get("to") in ("SUBIDA", "BAJADA"):
            _dir = _predictive.get("to")
            _status = "CONFIRMADA" if trend_info.get("transition") else "EN_FORMACION"
            _evidence = float(_predictive.get("evidence", _predictive.get("probability", 0.5)))
            _ui_active_signal = (2 if _status == "CONFIRMADA" else 1, _evidence, _dir, _status)
'''
if old_ui_signal in s:
    s = s.replace(old_ui_signal, new_ui_signal, 1)

old_headline = '''        if _ui_active_signal is not None:
            _, _ev, _dir, _status = _ui_active_signal
            _icon = "🟢" if _dir == "SUBIDA" else "🔴"
            _word = "SUBIDA" if _dir == "SUBIDA" else "BAJADA"
            _state = "EN FORMACIÓN AHORA" if _status == "EN_FORMACION" else "EN CURSO"
            st.markdown(f"## {_icon} AHORA: {_word} {_state}")
        elif _show_lateral:
            i_low = _market_price_text(interim.get("range_low"), live_spot)
            i_high = _market_price_text(interim.get("range_high"), live_spot)
            until_txt = _duration_text(timeframe, int(interim.get("until_bars", 1)))
            st.markdown(f"## 🟡 AHORA: LATERALIZA · {i_low}–{i_high} · aprox. {until_txt}")
'''

new_headline = '''        if _ui_active_signal is not None:
            _, _ev, _dir, _status = _ui_active_signal
            _icon = "🟢" if _dir == "SUBIDA" else "🔴"
            _word = "SUBIDA" if _dir == "SUBIDA" else "BAJADA"
            _state = "EN FORMACIÓN" if _status == "EN_FORMACION" else "CONFIRMADA POR EL FILTRO"
            st.markdown(f"## {_icon} SEÑAL: {_word} {_state}")
        elif _show_lateral:
            i_low = _market_price_text(interim.get("range_low"), live_spot)
            i_high = _market_price_text(interim.get("range_high"), live_spot)
            until_txt = _duration_text(timeframe, int(interim.get("until_bars", 1)))
            st.markdown(f"## 🟡 AHORA: LATERALIZA · {i_low}–{i_high} · horizonte {until_txt}")
        else:
            _desc_icon = "🟢" if cur == "SUBIDA" else "🔴" if cur == "BAJADA" else "🟡"
            _desc = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "LATERAL"
            st.markdown(f"## {_desc_icon} TENDENCIA ACTUAL: {_desc} · SIN SEÑAL PREDICTIVA VALIDADA")
'''
if old_headline in s:
    s = s.replace(old_headline, new_headline, 1)

# 5) The displayed duration is a forecast horizon, NOT time-to-touch.
s = s.replace(
'text=f"<b>{objective_name} · {target_txt} · aprox. {target_time}</b>",',
'text=f"<b>{objective_name} · {target_txt} · horizonte {target_time}</b>",'
)

p.write_text(s, encoding="utf-8")
print("Applied predictive-signal safety gate and corrected horizon wording")
