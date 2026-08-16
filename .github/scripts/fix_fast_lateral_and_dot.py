from pathlib import Path
import ast

p = Path('app.py')
s = p.read_text(encoding='utf-8')

old_score = '''    idx = {"SUBIDA": 0, "LATERAL": 1, "BAJADA": 2}
    score = 0.62 * analog_probs
    weights = 0.62

    tech_dist = np.full(3, 0.15)
    tech_dist[idx[tech]] = 0.70
    score += 0.20 * tech_dist
    weights += 0.20

    vol_dist = np.full(3, 0.20)
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
        cyc = np.full(3, 0.15)
        cyc[idx[cycle_context]] = 0.70
        score += 0.11 * cyc
        weights += 0.11
'''

new_score = '''    idx = {"SUBIDA": 0, "LATERAL": 1, "BAJADA": 2}

    # Weighting changes with timeframe. On 1m-5m, recent impulse and volume
    # matter more than old analogues/cycle context; otherwise the engine reacts
    # too slowly after a sharp turn and tends to over-label LATERAL.
    if timeframe in ("1m", "2m", "3m", "5m"):
        analog_w, tech_w, vol_w, impulse_w, cycle_w = 0.30, 0.18, 0.14, 0.34, 0.04
    elif timeframe in ("10m", "15m", "30m", "45m"):
        analog_w, tech_w, vol_w, impulse_w, cycle_w = 0.42, 0.22, 0.11, 0.20, 0.05
    else:
        analog_w, tech_w, vol_w, impulse_w, cycle_w = 0.56, 0.22, 0.08, 0.09, 0.05

    score = analog_w * analog_probs
    weights = analog_w

    tech_dist = np.full(3, 0.15)
    tech_dist[idx[tech]] = 0.70
    score += tech_w * tech_dist
    weights += tech_w

    vol_dist = np.full(3, 0.20)
    vol_dist[idx[vol_dir]] = 0.60 + 0.20 * vol_strength
    vol_dist = vol_dist / vol_dist.sum()
    score += vol_w * vol_dist
    weights += vol_w

    impulse_dist = np.full(3, 0.14)
    impulse_dist[idx[impulse]] = 0.72
    impulse_dist = impulse_dist / impulse_dist.sum()
    score += impulse_w * impulse_dist
    weights += impulse_w

    if cycle_context in idx:
        cyc = np.full(3, 0.15)
        cyc[idx[cycle_context]] = 0.70
        score += cycle_w * cyc
        weights += cycle_w
'''

if old_score in s:
    s = s.replace(old_score, new_score, 1)
elif new_score not in s:
    raise RuntimeError('No se encontró el bloque de ponderaciones')

old_dom = '''    dom_i, second_i = int(ordered[0]), int(ordered[1])
    labels = ["SUBIDA", "LATERAL", "BAJADA"]
    dom = labels[dom_i]
    prob = float(probs[dom_i])
    margin = float(probs[dom_i] - probs[second_i])
'''

new_dom = '''    dom_i, second_i = int(ordered[0]), int(ordered[1])
    labels = ["SUBIDA", "LATERAL", "BAJADA"]
    dom = labels[dom_i]

    # In very fast timeframes, LATERAL is only valid when price is genuinely
    # compressed AND the immediate impulse is also neutral. A directional turn
    # should not be painted yellow merely because historical analogues are flat.
    if timeframe in ("1m", "2m", "3m", "5m") and dom == "LATERAL":
        try:
            recent = closed.tail(6)
            recent_range = float((recent["high"].max() - recent["low"].min()) / max(price, 1e-9))
            compression_limit = max(flat_floor * 3.0, max(atr_pct, 1e-6) * 1.35)
            truly_lateral = impulse == "LATERAL" and recent_range <= compression_limit
        except Exception:
            truly_lateral = impulse == "LATERAL"
        if not truly_lateral:
            directional = [idx["SUBIDA"], idx["BAJADA"]]
            dom_i = max(directional, key=lambda i: float(probs[i]))
            dom = labels[dom_i]
            second_i = idx["LATERAL"] if probs[idx["LATERAL"]] >= probs[directional[1 if dom_i == directional[0] else 0]] else directional[1 if dom_i == directional[0] else 0]

    prob = float(probs[dom_i])
    margin = float(probs[dom_i] - probs[second_i])
'''

if old_dom in s:
    s = s.replace(old_dom, new_dom, 1)
elif new_dom not in s:
    raise RuntimeError('No se encontró el bloque de selección dominante')

old_dot = '''    try:
        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))
    except Exception:
        dot_x = last_x
'''
new_dot = '''    try:
        # Visual anchor only: place the signal two slots to the right so it never
        # covers the live/last candle. The forecast horizon itself is unchanged.
        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 2))
    except Exception:
        dot_x = last_x
'''
if old_dot in s:
    s = s.replace(old_dot, new_dot, 1)
elif new_dot not in s:
    raise RuntimeError('No se encontró la posición del punto')

ast.parse(s)
p.write_text(s, encoding='utf-8')
print('fast lateral guard + right-side dot applied')
