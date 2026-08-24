from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Lower-timeframe sensors must be lightweight. They are early context,
# not full analogue engines. This prevents Streamlit startup from exploding
# into several expensive historical-similarity calculations.
old_sensor = '''        hist = min(int(DEFAULT_HISTORY.get(sensor_tf, 600)), 700)
        base = fetch_timeframe_history(symbol_code, sensor_tf, hist + 2)
        recent = fetch_recent_timeframe_history(symbol_code, sensor_tf, 36)
        full = (pd.concat([base, recent], ignore_index=True)
                .sort_values("timestamp")
                .drop_duplicates("timestamp", keep="last")
                .tail(hist + 2)
                .reset_index(drop=True))
        closed = full[full.is_closed].drop(columns=["is_closed"]).tail(hist).reset_index(drop=True)
        if len(closed) < 60:
            return None
        trend = current_trend_state(closed, sensor_tf)
        fast = fast_statistical_signal(closed, sensor_tf, 1, cycle_context)
        state = fast.get("state") if fast.get("ok") else None
        return {
            "timeframe": sensor_tf,
            "trend": trend,
            "forecast": state,
            "impulse": fast.get("impulse") if fast.get("ok") else None,
            "volume": fast.get("volume_direction") if fast.get("ok") else None,
        }'''

new_sensor = '''        hist = min(int(DEFAULT_HISTORY.get(sensor_tf, 320)), 320)
        base = fetch_timeframe_history(symbol_code, sensor_tf, hist + 2)
        recent = fetch_recent_timeframe_history(symbol_code, sensor_tf, 24)
        full = (pd.concat([base, recent], ignore_index=True)
                .sort_values("timestamp")
                .drop_duplicates("timestamp", keep="last")
                .tail(hist + 2)
                .reset_index(drop=True))
        closed = full[full.is_closed].drop(columns=["is_closed"]).tail(hist).reset_index(drop=True)
        if len(closed) < 60:
            return None
        trend = current_trend_state(closed, sensor_tf)
        # Lightweight directional sensor. The expensive historical analogue
        # engine remains on the selected/main timeframe only.
        scenario = trend.get("scenario", "LATERAL")
        strength = float(trend.get("strength", 0.0))
        state = {
            "scenario": scenario,
            "probability": float(0.50 + 0.40 * min(1.0, strength)) if scenario in ("SUBIDA", "BAJADA") else 0.50,
            "reliability": "MEDIA" if strength >= 0.50 else "BAJA",
        }
        return {
            "timeframe": sensor_tf,
            "trend": trend,
            "forecast": state,
            "impulse": None,
            "volume": None,
        }'''

if old_sensor not in s:
    raise RuntimeError('No se encontró el bloque actual de leading_sensor_state')
s = s.replace(old_sensor, new_sensor, 1)

# 2) Three horizons are enough for the live early-warning layer. 8 bars can
# still be inferred as a broad fallback window, but we avoid a fourth full
# analogue calculation on every refresh.
s = s.replace('    horizons = [1, 2, 4, 8]\n    future = []\n    raw_results = []',
              '    horizons = [1, 2, 4]\n    future = []\n    raw_results = []', 1)

# Preserve the broad user-facing horizon when no early turn is detected.
s = s.replace('        "max_horizon": horizons[-1],\n    }\n\n\ndef transition_window_text',
              '        "max_horizon": 8,\n    }\n\n\ndef transition_window_text', 1)

# 3) Main simple mode: reduce the heavy history slightly and never let a
# transition-engine exception prevent the app from rendering.
s = s.replace('        fast_history = min(int(training_bars), 1200)',
              '        fast_history = min(int(training_bars), 800)', 1)

old_call = '''        cycle = fast_cycle_context(SYMBOLS[selected])
        trend_info = trend_transition_forecast(SYMBOLS[selected], closed_simple, timeframe, cycle)
        current = trend_info.get("current", {})'''
new_call = '''        cycle = fast_cycle_context(SYMBOLS[selected])
        try:
            trend_info = trend_transition_forecast(SYMBOLS[selected], closed_simple, timeframe, cycle)
        except Exception as e:
            # Availability first: if the early-warning layer has a runtime issue,
            # render the current trend instead of taking down the whole app.
            trend_info = {
                "current": current_trend_state(closed_simple, timeframe),
                "transition": None,
                "early_warning": None,
                "future": [],
                "sensors": [],
                "candidate_rows": [],
                "max_horizon": 8,
            }
            st.caption(f"Detector temprano temporalmente limitado: {type(e).__name__}.")
        current = trend_info.get("current", {})'''
if old_call not in s:
    raise RuntimeError('No se encontró la llamada actual a trend_transition_forecast')
s = s.replace(old_call, new_call, 1)

p.write_text(s, encoding='utf-8')
print('Startup hotfix aplicado: sensores ligeros, menos carga y fallback seguro.')
