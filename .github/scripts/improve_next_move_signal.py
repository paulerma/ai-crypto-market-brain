from pathlib import Path
import ast

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Automatic forecast horizon per TradingView timeframe.
old = '''        chart_bars = 180
        horizon_name = "Automático"
        # Four candles smooths 1m noise without making the user choose a period.
        # 1m -> ~4 min, 1h -> ~4 h, 1D -> ~4 días, etc.
        horizon = 4
'''
new = '''        chart_bars = 180
        horizon_name = "Automático"
        # The simple signal answers the NEXT move. Faster charts use a shorter
        # horizon so 1m does not average away an immediate directional move.
        _auto_horizon = {
            "1m": 1, "2m": 1, "3m": 1,
            "5m": 2, "10m": 2, "15m": 2,
            "30m": 3, "45m": 3,
            "1h": 3, "2h": 3, "3h": 3, "4h": 3,
            "1D": 2, "1W": 2, "1M": 1,
        }
        horizon = _auto_horizon.get(timeframe, 2)
'''
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise RuntimeError('No se encontró el horizonte automático simple')

# 2) Add short-term impulse as an independent evidence layer. This makes very
# short timeframes react to a genuine acceleration instead of relying mainly on
# slower trend/analogue features.
needle = '''    try:
        vr = analyze_volume(row)
        vol_dir = "SUBIDA" if vr.direction == "COMPRADOR" else "BAJADA" if vr.direction == "VENDEDOR" else "LATERAL"
        vol_strength = float(np.clip(vr.intensity / 100.0, 0.0, 1.0))
    except Exception:
        vol_dir, vol_strength = "LATERAL", 0.35

    idx = {"SUBIDA": 0, "LATERAL": 1, "BAJADA": 2}
'''
replacement = '''    try:
        vr = analyze_volume(row)
        vol_dir = "SUBIDA" if vr.direction == "COMPRADOR" else "BAJADA" if vr.direction == "VENDEDOR" else "LATERAL"
        vol_strength = float(np.clip(vr.intensity / 100.0, 0.0, 1.0))
    except Exception:
        vol_dir, vol_strength = "LATERAL", 0.35

    # Immediate impulse: last closed candle + last three candles, normalized by
    # the volatility of the selected timeframe. It is strongest on 1m-5m.
    try:
        c = closed["close"].astype(float)
        r1 = float(c.iloc[-1] / c.iloc[-2] - 1.0)
        r3 = float(c.iloc[-1] / c.iloc[-4] - 1.0) if len(c) >= 4 else r1
        impulse_value = r1 + 0.45 * r3
        impulse_thr = max(flat_floor * 0.55, max(atr_pct, 1e-6) * 0.16)
        if impulse_value > impulse_thr:
            impulse = "SUBIDA"
        elif impulse_value < -impulse_thr:
            impulse = "BAJADA"
        else:
            impulse = "LATERAL"
    except Exception:
        impulse = "LATERAL"

    idx = {"SUBIDA": 0, "LATERAL": 1, "BAJADA": 2}
'''
if needle in s:
    s = s.replace(needle, replacement, 1)
elif 'impulse_value = r1 + 0.45 * r3' not in s:
    raise RuntimeError('No se encontró bloque de volumen para añadir impulso')

needle2 = '''    vol_dist = np.full(3, 0.20)
    vol_dist[idx[vol_dir]] = 0.60 + 0.20 * vol_strength
    vol_dist = vol_dist / vol_dist.sum()
    score += 0.07 * vol_dist
    weights += 0.07

    if cycle_context in idx:
'''
replacement2 = '''    vol_dist = np.full(3, 0.20)
    vol_dist[idx[vol_dir]] = 0.60 + 0.20 * vol_strength
    vol_dist = vol_dist / vol_dist.sum()
    score += 0.07 * vol_dist
    weights += 0.07

    impulse_weight = 0.22 if timeframe in ("1m", "2m", "3m", "5m") else 0.15 if timeframe in ("10m", "15m", "30m", "45m") else 0.10
    impulse_dist = np.full(3, 0.14)
    impulse_dist[idx[impulse]] = 0.72
    impulse_dist = impulse_dist / impulse_dist.sum()
    score += impulse_weight * impulse_dist
    weights += impulse_weight

    if cycle_context in idx:
'''
if needle2 in s:
    s = s.replace(needle2, replacement2, 1)
elif 'impulse_weight = 0.22' not in s:
    raise RuntimeError('No se encontró bloque de score para añadir impulso')

needle3 = '''    confirmations = sum([
        analog_dom == dom,
        tech == dom,
        vol_dir == dom,
        cycle_context == dom if cycle_context else False,
    ])
'''
replacement3 = '''    confirmations = sum([
        analog_dom == dom,
        tech == dom,
        vol_dir == dom,
        impulse == dom,
        cycle_context == dom if cycle_context else False,
    ])
'''
if needle3 in s:
    s = s.replace(needle3, replacement3, 1)
elif 'impulse == dom' not in s:
    raise RuntimeError('No se encontró bloque de confirmaciones')

s = s.replace(
    '"source": "patrones históricos + tendencia + momentum + volumen + ciclo",',
    '"source": "patrones históricos + tendencia + momentum + volumen + impulso inmediato + ciclo",',
    1,
)

# Expose impulse for diagnostics in advanced/debug contexts.
old_return = '''        "analog_cases": int(analog_cases), "technical": tech,
        "volume_direction": vol_dir, "cycle": cycle_context,
'''
new_return = '''        "analog_cases": int(analog_cases), "technical": tech,
        "volume_direction": vol_dir, "impulse": impulse, "cycle": cycle_context,
'''
if old_return in s:
    s = s.replace(old_return, new_return, 1)

# 3) Make it visually explicit that the point is a forecast, not a description
# of the candle that just finished.
s = s.replace(
    'label = f"{short_label} · {probability*100:.1f}% · {timeframe}"',
    'label = f"PRÓXIMO: {short_label} · {probability*100:.1f}% · {timeframe}"',
    1,
)
s = s.replace(
    'st.markdown(f"### {icon} {selected} · {label} · {simple_state[\'probability\']*100:.1f}% · {timeframe}")',
    'st.markdown(f"### {icon} {selected} · PRÓXIMO: {label} · {simple_state[\'probability\']*100:.1f}% · {timeframe}")',
    1,
)

# Helpful but short explanation beneath chart.
s = s.replace(
    'st.caption("🟢 sube · 🔴 baja · 🟡 lateral. El resto del análisis trabaja por detrás.")',
    'st.caption(f"Señal para las próximas {horizon} vela(s) de {timeframe}. 🟢 sube · 🔴 baja · 🟡 lateral.")',
    1,
)

ast.parse(s)
p.write_text(s, encoding='utf-8')
print('next-move signal refinement applied')
