from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

insert_anchor = '''    # Estimate when each directional phase STARTS.  This is intentionally
'''
insert_block = '''    # Build ONE chronological market path from the actual dominant scenario at
    # each analysed horizon. This prevents independent UP and DOWN candidates
    # from being presented as if both must happen sequentially.
    path_rows = []
    for h, res in zip(horizons, raw_results):
        if not res.get("ok"):
            continue
        pup = float(res.get("pup", 0.0))
        pflat = float(res.get("pflat", 0.0))
        pdown = float(res.get("pdown", 0.0))
        directional_total = pup + pdown
        if directional_total > 1e-9:
            up_share = pup / directional_total
            down_share = pdown / directional_total
        else:
            up_share = down_share = 0.5
        dir_margin = abs(up_share - down_share)

        # Lateral only when it genuinely dominates or UP/DOWN are effectively tied.
        if (pflat >= max(pup, pdown) and pflat >= 0.36) or dir_margin < 0.06:
            direction = "LATERAL"
            confidence = float(max(pflat, 1.0 - dir_margin))
        elif up_share > down_share:
            direction = "SUBIDA"
            confidence = float(up_share)
        else:
            direction = "BAJADA"
            confidence = float(down_share)

        target_price = None
        if direction in ("SUBIDA", "BAJADA"):
            aq = (res.get("analog_quantiles") or {}).get(direction) or {}
            q50 = float(aq.get("q50", np.nan)) if aq else np.nan
            aligned = np.isfinite(q50) and ((direction == "SUBIDA" and q50 > 0) or (direction == "BAJADA" and q50 < 0))
            if aligned:
                target_price = market_price * (1.0 + q50)
            else:
                atr_h = float(res.get("atr", np.nan))
                if not np.isfinite(atr_h) or atr_h <= 0:
                    try:
                        atr_h = float(build_features(closed).iloc[-1].get("atr_14", market_price * 0.01))
                    except Exception:
                        atr_h = market_price * 0.01
                move = max(atr_h, market_price * 0.001) * np.sqrt(max(1, int(h)))
                target_price = market_price + move if direction == "SUBIDA" else market_price - move

        path_rows.append({
            "horizon": int(h),
            "direction": direction,
            "confidence": float(confidence),
            "margin": float(dir_margin),
            "target_price": float(max(target_price, 1e-12)) if target_price is not None else None,
        })

    path_transitions = []
    prev_direction = current_dir if current_dir in ("SUBIDA", "BAJADA") else None
    prev_horizon = 0
    for row in path_rows:
        direction = row.get("direction")
        horizon_h = int(row.get("horizon", 1))
        if direction not in ("SUBIDA", "BAJADA"):
            continue
        if prev_direction is None:
            path_transitions.append({
                "from": "LATERAL", "to": direction,
                "start_bars": 0, "end_bars": horizon_h,
                "target_horizon": horizon_h,
                "target_price": row.get("target_price"),
                "confidence": row.get("confidence", 0.5),
            })
        elif direction != prev_direction:
            path_transitions.append({
                "from": prev_direction, "to": direction,
                "start_bars": int(prev_horizon), "end_bars": horizon_h,
                "target_horizon": horizon_h,
                "target_price": row.get("target_price"),
                "confidence": row.get("confidence", 0.5),
            })
        prev_direction = direction
        prev_horizon = horizon_h

    market_path = {
        "rows": path_rows,
        "transitions": path_transitions,
        "current_direction": current_dir,
        "reference_price": market_price,
    }

'''
if "Build ONE chronological market path" not in s:
    if insert_anchor not in s:
        raise RuntimeError("No se encontro ancla para market_path")
    s = s.replace(insert_anchor, insert_block + insert_anchor, 1)

old_return = '''        "directional_forecasts": directional_forecasts,
        "direction_onsets": direction_onsets,
        "primary_forecast": primary_forecast,
'''
new_return = '''        "directional_forecasts": directional_forecasts,
        "direction_onsets": direction_onsets,
        "market_path": market_path,
        "primary_forecast": primary_forecast,
'''
if new_return not in s:
    if old_return not in s:
        raise RuntimeError("No se encontro payload return")
    s = s.replace(old_return, new_return, 1)

old_ui = '''        sequence = []
        for direction, fc in (("SUBIDA", up_fc), ("BAJADA", down_fc)):
            if not fc or not fc.get("has_window"):
                continue
            onset = onsets.get(direction) or {}
            status = onset.get("status", "VENTANA")
            start_b = int(onset.get("start_bars", 0))
            end_b = int(onset.get("end_bars", max(1, int(fc.get("timing_bars", 1)))))
            if status == "YA_EN_CURSO":
                onset_text = "YA ESTÁ EN CURSO"
                order_key = -1.0
            elif status == "EN_FORMACION":
                onset_text = "EN FORMACIÓN AHORA"
                order_key = 0.0
            else:
                onset_text = _compact_interval(start_b, end_b)
                order_key = float(end_b)
            target_bars = int(fc.get("timing_bars", fc.get("start_bars", 1)))
            target_time = _duration_text(timeframe, target_bars)
            target_price = _market_price_text(fc.get("target_price"), spot_ref)
            sequence.append((order_key, target_bars, direction, onset_text, target_time, target_price))

        sequence.sort(key=lambda x: (x[0], x[1]))
        for idx, (_, _, direction, onset_text, target_time, target_price) in enumerate(sequence):
            icon = "🟢" if direction == "SUBIDA" else "🔴"
            verb = "SUBIR" if direction == "SUBIDA" else "BAJAR"
            prefix = "DESPUÉS · " if idx > 0 else ""
            st.markdown(
                f"## {icon} {prefix}EMPIEZA A {verb}: {onset_text} · "
                f"OBJETIVO A {target_time}: {target_price}"
            )
'''

new_ui = '''        # Use the LIVE/current forming-candle price only as a guard against stale
        # targets. The predictive model still trains on closed candles.
        live_spot = float(chart_simple["close"].iloc[-1]) if not chart_simple.empty else spot_ref
        path = trend_info.get("market_path") or {}
        path_rows = list(path.get("rows") or [])
        transitions = list(path.get("transitions") or [])

        # Current phase: choose the first still-unreached target in the SAME
        # direction. If the old target was already exceeded, do not keep showing
        # it as a future objective.
        if cur in ("SUBIDA", "BAJADA"):
            current_rows = [r for r in path_rows if r.get("direction") == cur]
            next_row = None
            for r in current_rows:
                tp = r.get("target_price")
                if tp is None:
                    continue
                tp = float(tp)
                if (cur == "SUBIDA" and tp > live_spot) or (cur == "BAJADA" and tp < live_spot):
                    next_row = r
                    break
            icon = "🟢" if cur == "SUBIDA" else "🔴"
            label = "SUBIDA" if cur == "SUBIDA" else "BAJADA"
            if next_row is not None:
                target_time = _duration_text(timeframe, int(next_row.get("horizon", 1)))
                target_price = _market_price_text(next_row.get("target_price"), live_spot)
                st.markdown(f"## {icon} {label} EN CURSO · OBJETIVO A {target_time}: {target_price}")
            elif current_rows:
                st.markdown(
                    f"## {icon} {label} EN CURSO · OBJETIVO ANTERIOR SUPERADO · "
                    f"PRECIO ACTUAL: {_market_price_text(live_spot, live_spot)}"
                )

        # Future turns are shown ONLY when the ordered horizon analysis actually
        # flips direction. We no longer manufacture a later DOWN merely because
        # DOWN had its own best independent score at some horizon.
        for event in transitions:
            direction = event.get("to")
            if direction not in ("SUBIDA", "BAJADA"):
                continue
            # Do not repeat the current phase as a future event.
            if event.get("from") == "LATERAL" and direction == cur:
                continue
            onset = onsets.get(direction) or {}
            if onset.get("status") == "EN_FORMACION":
                onset_text = "EN FORMACIÓN AHORA"
            else:
                onset_text = _compact_interval(int(event.get("start_bars", 0)), int(event.get("end_bars", 1)))
            icon = "🟢" if direction == "SUBIDA" else "🔴"
            verb = "SUBIR" if direction == "SUBIDA" else "BAJAR"
            target_h = int(event.get("target_horizon", event.get("end_bars", 1)))
            target_time = _duration_text(timeframe, target_h)
            target_val = event.get("target_price")
            target_price = _market_price_text(target_val, live_spot)

            # If live price has already crossed this projected target before the
            # supposed turn, the old route is stale and must not be presented as
            # intact.
            stale = False
            if target_val is not None:
                target_val = float(target_val)
                stale = ((direction == "SUBIDA" and live_spot >= target_val)
                         or (direction == "BAJADA" and live_spot <= target_val))
            if stale:
                continue
            st.markdown(
                f"## {icon} EMPIEZA A {verb}: {onset_text} · "
                f"OBJETIVO A {target_time}: {target_price}"
            )
'''

if new_ui not in s:
    if old_ui not in s:
        raise RuntimeError("No se encontro bloque UI de secuencia")
    s = s.replace(old_ui, new_ui, 1)

# Add fallback key for defensive rendering.
old_fb = '''                "directional_forecasts": {},
                "primary_forecast": None,
                "interim": None,
'''
new_fb = '''                "directional_forecasts": {},
                "market_path": {"rows": [], "transitions": []},
                "primary_forecast": None,
                "interim": None,
'''
if new_fb not in s and old_fb in s:
    s = s.replace(old_fb, new_fb, 1)

p.write_text(s, encoding="utf-8")
print("Applied ordered horizon path and live target invalidation")
