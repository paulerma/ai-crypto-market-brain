from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

start = s.index('    probs = score / max(weights, 1e-9)\n')
end = s.index('    confirmations = sum([\n', start)

replacement = '''    probs = score / max(weights, 1e-9)\n    probs = probs / probs.sum()\n\n    # Main SIMPLE signal answers only one question: is price more likely to go UP or DOWN?\n    # LATERAL/SIN DIRECCION is reserved for an almost exact directional tie.\n    up_raw = float(probs[idx[\"SUBIDA\"]])\n    down_raw = float(probs[idx[\"BAJADA\"]])\n    directional_total = up_raw + down_raw\n    if directional_total <= 1e-9:\n        up_cond = down_cond = 0.5\n    else:\n        up_cond = up_raw / directional_total\n        down_cond = down_raw / directional_total\n\n    # Tiny dead-zone only. The user should normally see green or red, not yellow.\n    tie_band = 0.02  # 48%-52% = truly undecided\n    if abs(up_cond - down_cond) <= tie_band:\n        dom = \"LATERAL\"\n        prob = float(max(up_cond, down_cond))\n        margin = float(abs(up_cond - down_cond))\n    elif up_cond > down_cond:\n        dom = \"SUBIDA\"\n        prob = float(up_cond)\n        margin = float(up_cond - down_cond)\n    else:\n        dom = \"BAJADA\"\n        prob = float(down_cond)\n        margin = float(down_cond - up_cond)\n\n'''

s = s[:start] + replacement + s[end:]

# Reliability thresholds are now based on binary directional confidence.
s = s.replace(
'''    high = prob >= 0.60 and margin >= 0.16 and confirmations >= 3\n    if dom in (\"SUBIDA\", \"BAJADA\"):\n        medium = prob >= 0.47 and margin >= 0.07 and confirmations >= 2\n    else:\n        medium = prob >= 0.44 and margin >= 0.05 and confirmations >= 1\n''',
'''    high = dom in (\"SUBIDA\", \"BAJADA\") and prob >= 0.62 and margin >= 0.24 and confirmations >= 3\n    medium = dom in (\"SUBIDA\", \"BAJADA\") and prob >= 0.55 and margin >= 0.10 and confirmations >= 2\n''',
1,
)

# Make the yellow wording explicit and secondary.
s = s.replace('dot_color, short_label = \"#f2c94c\", \"LATERAL\"',
              'dot_color, short_label = \"#f2c94c\", \"SIN DIRECCIÓN\"', 1)
s = s.replace('        if short_label == \"LATERAL\":\n            short_label = \"SIN DIRECCIÓN\"\n', '', 1)

# Update explanatory caption if present.
s = s.replace('🟢 sube · 🔴 baja · 🟡 lateral.', '🟢 sube · 🔴 baja · 🟡 sin dirección clara.')

p.write_text(s, encoding='utf-8')
print('Binary direction patch applied')
