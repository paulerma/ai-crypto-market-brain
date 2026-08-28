from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '''        interim = trend_info.get("interim") or {}
        onsets = trend_info.get("direction_onsets") or {}
        spot_ref = float(closed_simple["close"].iloc[-1])

        def _compact_interval(start_bars: int, end_bars: int) -> str:
            start_bars, end_bars = int(start_bars), int(end_bars)
            if start_bars <= 0 and end_bars <= 0:
                return "ahora"
            if start_bars <= 0:
                return f"dentro de {_duration_text(timeframe, max(1, end_bars))}"
            a = _duration_text(timeframe, start_bars)
            b = _duration_text(timeframe, max(start_bars, end_bars))
            if a == b:
                return a
            ap, bp = a.split(" ", 1), b.split(" ", 1)
            if len(ap) == 2 and len(bp) == 2 and ap[1] == bp[1]:
                return f"entre {ap[0]} y {bp[0]} {ap[1]}"
            return f"entre {a} y {b}"

        if interim.get("is_lateral"):
            i_low = _market_price_text(interim.get("range_low"), spot_ref)
            i_high = _market_price_text(interim.get("range_high"), spot_ref)
            until_txt = _duration_text(timeframe, int(interim.get("until_bars", 1)))
            st.markdown(f"## 🟡 AHORA: LATERALIZA · {i_low}–{i_high} · aprox. {until_txt}")

        # Use the LIVE/current forming-candle price only as a guard against stale
        # targets. The predictive model still trains on closed candles.
        live_spot = float(chart_simple["close"].iloc[-1]) if not chart_simple.empty else spot_ref
'''

new = '''        interim = trend_info.get("interim") or {}
        onsets = trend_info.get("direction_onsets") or {}
        spot_ref = float(closed_simple["close"].iloc[-1])

        # Read LIVE price BEFORE deciding what is happening "AHORA". Predictive
        # features still use closed candles, but stale live-state labels must be
        # invalidated immediately when price leaves the old range.
        live_spot = float(chart_simple["close"].iloc[-1]) if not chart_simple.empty else spot_ref

        def _compact_interval(start_bars: int, end_bars: int) -> str:
            start_bars, end_bars = int(start_bars), int(end_bars)
            if start_bars <= 0 and end_bars <= 0:
                return "ahora"
            if start_bars <= 0:
                return f"dentro de {_duration_text(timeframe, max(1, end_bars))}"
            a = _duration_text(timeframe, start_bars)
            b = _duration_text(timeframe, max(start_bars, end_bars))
            if a == b:
                return a
            ap, bp = a.split(" ", 1), b.split(" ", 1)
            if len(ap) == 2 and len(bp) == 2 and ap[1] == bp[1]:
                return f"entre {ap[0]} y {bp[0]} {ap[1]}"
            return f"entre {a} y {b}"

        # Use the exact same active-signal priority as the chart: a forming turn
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

        # "LATERALIZA" is valid only while live price remains inside the estimated
        # range AND there is no active directional signal. A very small tolerance
        # avoids flicker from a few ticks at the edge without masking a real break.
        _show_lateral = False
        if interim.get("is_lateral") and _ui_active_signal is None:
            try:
                _lo = float(interim.get("range_low"))
                _hi = float(interim.get("range_high"))
                _lo, _hi = min(_lo, _hi), max(_lo, _hi)
                _pad = max((_hi - _lo) * 0.10, live_spot * 0.0005)
                _show_lateral = (_lo - _pad) <= live_spot <= (_hi + _pad)
            except Exception:
                _show_lateral = False

        if _ui_active_signal is not None:
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

if new in s:
    print("Live-state headline fix already applied")
elif old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding="utf-8")
    print("Applied live-state/lateral invalidation fix")
else:
    raise RuntimeError("Expected simple-mode state block not found")
