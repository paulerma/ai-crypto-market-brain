from pathlib import Path
import re

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Add a market-derived timing score for each direction at each already-computed
# horizon. This uses the existing evidence engine (historical analogues, trend,
# momentum, volume, impulse and cycle) plus lower-timeframe sensors and precursor
# acceleration. It does NOT gate the user-facing estimate behind arbitrary UI thresholds.
old = '''        candidate_rows.append({
            "to": candidate,
            "evidence": evidence,
            "future_support": future_support,
            "sensor_support": sensor_support,
            "precursor": precursor,
            "component_support": component_support,
            "sensor_agree": sensor_agree,
            "start_bars": int(start_bars),
            "end_bars": int(end_bars),
        })
'''
new = '''        # Best timing estimate for this direction. Each horizon gets its own
        # directional score from the raw UP/DOWN probabilities, then lower-TF
        # sensors, precursor acceleration and immediate components refine it.
        horizon_scores = []
        valid_horizons = 0
        for h, res in zip(horizons, raw_results):
            if res.get("ok"):
                up_raw = float(res.get("pup", 0.0))
                down_raw = float(res.get("pdown", 0.0))
                directional_total = up_raw + down_raw
                if directional_total > 1e-9:
                    base_support = (up_raw / directional_total) if candidate == "SUBIDA" else (down_raw / directional_total)
                else:
                    base_support = 0.5
                valid_horizons += 1
            else:
                base_support = 0.5

            # Near horizons listen more to early sensors; farther horizons lean
            # more on the horizon-specific historical/statistical forecast.
            sensor_w = {1: 0.24, 2: 0.18, 4: 0.12}.get(int(h), 0.12)
            precursor_w = {1: 0.20, 2: 0.17, 4: 0.14}.get(int(h), 0.14)
            component_w = 0.08
            base_w = max(0.0, 1.0 - sensor_w - precursor_w - component_w)
            timing_score = float(
                base_w * base_support
                + sensor_w * sensor_support
                + precursor_w * precursor
                + component_w * component_support
            )
            horizon_scores.append({"horizon": int(h), "score": timing_score})

        if horizon_scores:
            best_timing = max(horizon_scores, key=lambda x: (x["score"], -x["horizon"]))
            timing_bars = int(best_timing["horizon"])
            timing_score = float(best_timing["score"])
        else:
            timing_bars = 1
            timing_score = 0.5

        candidate_rows.append({
            "to": candidate,
            "evidence": evidence,
            "future_support": future_support,
            "sensor_support": sensor_support,
            "precursor": precursor,
            "component_support": component_support,
            "sensor_agree": sensor_agree,
            "start_bars": int(timing_bars),
            "end_bars": int(timing_bars),
            "timing_bars": int(timing_bars),
            "timing_score": float(timing_score),
            "timing_ok": bool(valid_horizons > 0),
            "horizon_scores": horizon_scores,
        })
'''
if old not in s:
    raise RuntimeError('No se encontró candidate_rows actual')
s = s.replace(old, new, 1)

# 2) If UP and DOWN peak at the same horizon, keep the stronger one there and
# place the weaker one at its best alternative horizon. This produces a useful
# path-like sequence (e.g. UP +1h, DOWN +2h) instead of two identical timestamps.
marker = '''    # Always expose one forecast per direction. A low-evidence direction is kept
    # visible but explicitly marked as not yet having a reliable time window.
    directional_forecasts = {}
'''
insert = '''    # If both directions peak at the same time bucket, use the second-best
    # independently analysed horizon for the weaker direction. This avoids a
    # meaningless "sube y baja al mismo tiempo" display while staying grounded
    # in the horizon scores already calculated from market data.
    if len(candidate_rows) == 2:
        a, b = candidate_rows[0], candidate_rows[1]
        if a.get("timing_ok") and b.get("timing_ok") and a.get("timing_bars") == b.get("timing_bars"):
            stronger, weaker = (a, b) if float(a.get("timing_score", 0.5)) >= float(b.get("timing_score", 0.5)) else (b, a)
            alternatives = [x for x in weaker.get("horizon_scores", []) if int(x.get("horizon", 0)) != int(stronger.get("timing_bars", 0))]
            if alternatives:
                alt = max(alternatives, key=lambda x: (x["score"], -x["horizon"]))
                weaker["timing_bars"] = int(alt["horizon"])
                weaker["timing_score"] = float(alt["score"])
                weaker["start_bars"] = int(alt["horizon"])
                weaker["end_bars"] = int(alt["horizon"])

    # Always expose one best market-derived estimate per direction. The UI no
    # longer hides timings because of a display threshold; thresholds remain
    # useful internally for transition alerts only.
    directional_forecasts = {}
'''
if marker not in s:
    raise RuntimeError('No se encontró marcador directional_forecasts')
s = s.replace(marker, insert, 1)

# 3) Replace the old threshold-gated directional forecast block.
pattern = re.compile(r'''    directional_forecasts = \{\}\n    for row in candidate_rows:\n        fc = dict\(row\)\n        ev = float\(row\.get\("evidence", 0\.5\)\)\n        fc\["probability"\] = float\(np\.clip\(ev, 0\.50, 0\.85\)\)\n        if ev >= 0\.58:\n            fc\["status"\] = "PROBABLE"\n            fc\["reliability"\] = "ALTA" if ev >= 0\.68 else "MEDIA"\n            fc\["has_window"\] = True\n        elif ev >= 0\.52:\n            fc\["status"\] = "EN_FORMACION"\n            fc\["reliability"\] = "TEMPRANA"\n            fc\["has_window"\] = True\n        else:\n            fc\["status"\] = "SIN_VENTANA_FIABLE"\n            fc\["reliability"\] = "BAJA"\n            fc\["has_window"\] = False\n        directional_forecasts\[row\["to"\]\] = fc\n''')
replacement = '''    directional_forecasts = {}
    for row in candidate_rows:
        fc = dict(row)
        timing_score = float(row.get("timing_score", 0.5))
        fc["probability"] = float(np.clip(timing_score, 0.0, 1.0))
        fc["status"] = "ESTIMACION_IA"
        fc["reliability"] = "ALTA" if timing_score >= 0.66 else "MEDIA" if timing_score >= 0.56 else "BAJA"
        fc["has_window"] = bool(row.get("timing_ok", False))
        fc["start_bars"] = int(row.get("timing_bars", 1))
        fc["end_bars"] = int(row.get("timing_bars", 1))
        directional_forecasts[row["to"]] = fc
'''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise RuntimeError('No se pudo reemplazar el bloque de umbrales directional_forecasts')

# 4) Ultra-simple display: show the best analysed time, not "sin señal clara".
old_ui = '''        def _compact_timing(fc):
            if not fc or not fc.get("has_window"):
                return "SIN SEÑAL CLARA"
            a = _duration_text(timeframe, int(fc.get("start_bars", 1)))
            b = _duration_text(timeframe, int(fc.get("end_bars", fc.get("start_bars", 1))))
            if a == b:
                return a
            ap = a.split(" ", 1)
            bp = b.split(" ", 1)
            if len(ap) == 2 and len(bp) == 2 and ap[1] == bp[1]:
                return f"{ap[0]}–{bp[0]} {ap[1]}"
            return f"{a}–{b}"

        st.markdown(f"## 🟢 SUBE EN: {_compact_timing(up_fc)}")
        st.markdown(f"## 🔴 BAJA EN: {_compact_timing(down_fc)}")
'''
new_ui = '''        def _compact_timing(fc):
            if not fc or not fc.get("has_window"):
                return "SIN DATOS"
            bars = int(fc.get("timing_bars", fc.get("start_bars", 1)))
            return _duration_text(timeframe, bars)

        st.markdown(f"## 🟢 SUBE EN: {_compact_timing(up_fc)}")
        st.markdown(f"## 🔴 BAJA EN: {_compact_timing(down_fc)}")
'''
if old_ui not in s:
    raise RuntimeError('No se encontró UI compacta actual')
s = s.replace(old_ui, new_ui, 1)

p.write_text(s, encoding='utf-8')
print('Market timing: best analysed UP/DOWN estimate applied.')
