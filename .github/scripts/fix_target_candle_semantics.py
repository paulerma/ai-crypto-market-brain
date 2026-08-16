from pathlib import Path
import re

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) The simple predictor must classify the BODY of the target candle itself,
# not cumulative return from the current close to a future close.
old = '    fwd = features["close"].shift(-int(horizon)) / features["close"] - 1.0\n'
new = ('    # Predict the target candle itself: close(target) vs open(target).\n'
       '    # This makes green/red correspond to the future candle color the user sees.\n'
       '    fwd = features["close"].shift(-int(horizon)) / features["open"].shift(-int(horizon)) - 1.0\n')
if old not in s:
    raise RuntimeError('Target-candle forward label not found')
s = s.replace(old, new, 1)

# 2) On fast charts, yellow should mean a genuinely tiny/doji-like body.
old = '''    flat_floor = {\n        "1m": 0.0004, "2m": 0.0005, "3m": 0.0006, "5m": 0.0008,\n        "10m": 0.0010, "15m": 0.0012, "30m": 0.0015, "45m": 0.0018,\n        "1h": 0.0020, "2h": 0.0025, "3h": 0.0030, "4h": 0.0035,\n        "1D": 0.0050, "1W": 0.0120, "1M": 0.0250,\n    }.get(timeframe, 0.0020)\n'''
new = '''    flat_floor = {\n        "1m": 0.00008, "2m": 0.00010, "3m": 0.00012, "5m": 0.00015,\n        "10m": 0.00020, "15m": 0.00025, "30m": 0.00060, "45m": 0.00080,\n        "1h": 0.0010, "2h": 0.0015, "3h": 0.0020, "4h": 0.0025,\n        "1D": 0.0040, "1W": 0.0100, "1M": 0.0200,\n    }.get(timeframe, 0.0010)\n'''
if old not in s:
    raise RuntimeError('flat_floor block not found')
s = s.replace(old, new, 1)

old = '''    flat_thr = float(np.clip(\n        0.35 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))),\n        flat_floor, flat_ceiling,\n    ))\n'''
new = '''    flat_thr = float(np.clip(\n        0.18 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))),\n        flat_floor, flat_ceiling,\n    ))\n'''
if old not in s:
    raise RuntimeError('flat threshold block not found')
s = s.replace(old, new, 1)

# 3) Yellow on 1m-5m requires strong flat evidence + compression + neutral impulse.
pat = re.compile(r'''    # In very fast timeframes, LATERAL is only valid when price is genuinely\n.*?    # For a forced fast-timeframe directional decision, the meaningful number is''', re.S)
m = pat.search(s)
if not m:
    raise RuntimeError('fast lateral guard block not found')
replacement = '''    # In very fast timeframes, LATERAL is intentionally strict. Yellow means\n    # the target candle is expected to have a genuinely tiny body, not merely\n    # that historical analogues are indecisive.\n    directional_confidence = None\n    if timeframe in ("1m", "2m", "3m", "5m") and dom == "LATERAL":\n        try:\n            recent = closed.tail(6)\n            recent_range = float((recent["high"].max() - recent["low"].min()) / max(price, 1e-9))\n            compression_limit = max(flat_floor * 3.0, max(atr_pct, 1e-6) * 1.10)\n            up_i, flat_i, down_i = idx["SUBIDA"], idx["LATERAL"], idx["BAJADA"]\n            directional_peak = max(float(probs[up_i]), float(probs[down_i]))\n            flat_edge = float(probs[flat_i]) - directional_peak\n            min_flat_prob = 0.50 if timeframe == "1m" else 0.48\n            truly_lateral = (\n                impulse == "LATERAL"\n                and recent_range <= compression_limit\n                and float(probs[flat_i]) >= min_flat_prob\n                and flat_edge >= 0.06\n            )\n        except Exception:\n            truly_lateral = False\n        if not truly_lateral:\n            up_i, down_i = idx["SUBIDA"], idx["BAJADA"]\n            directional_total = float(probs[up_i] + probs[down_i])\n            if directional_total > 1e-9:\n                up_cond = float(probs[up_i] / directional_total)\n                down_cond = float(probs[down_i] / directional_total)\n                if up_cond >= down_cond:\n                    dom_i, dom = up_i, "SUBIDA"\n                    directional_confidence = up_cond\n                else:\n                    dom_i, dom = down_i, "BAJADA"\n                    directional_confidence = down_cond\n            else:\n                directional_confidence = 0.5\n\n    # For a forced fast-timeframe directional decision, the meaningful number is'''
s = s[:m.start()] + replacement + s[m.end():]

# The previous implementation checked locals(); now directional_confidence is explicit.
s = s.replace("    if 'directional_confidence' in locals() and dom in (\"SUBIDA\", \"BAJADA\"):\n",
              "    if directional_confidence is not None and dom in (\"SUBIDA\", \"BAJADA\"):\n", 1)

# 4) Never leave the prediction marker on a candle that has already started.
needle = '''        else:\n            target_time = future_time(last_closed_open.to_pydatetime(), timeframe, 1)\n            prediction_horizon = 1\n\n        cycle = fast_cycle_context(SYMBOLS[selected])\n'''
insert = '''        else:\n            target_time = future_time(last_closed_open.to_pydatetime(), timeframe, 1)\n            prediction_horizon = 1\n\n        # Safety guard against stale market tails: the target must always be in\n        # the future. If a bar boundary already passed, advance to the next one\n        # rather than displaying a prediction on a candle already forming.\n        now_utc = pd.Timestamp.now(tz="UTC")\n        for _ in range(6):\n            _tt = pd.Timestamp(target_time)\n            if _tt.tzinfo is None:\n                _tt = _tt.tz_localize("UTC")\n            if _tt > now_utc:\n                break\n            target_time = future_time(_tt.to_pydatetime(), timeframe, 1)\n            prediction_horizon += 1\n\n        cycle = fast_cycle_context(SYMBOLS[selected])\n'''
if needle not in s:
    raise RuntimeError('target-time block not found')
s = s.replace(needle, insert, 1)

# 5) Put the big point/label in a dedicated strip ABOVE the candle area. Keep only
# a thin vertical guide at the future time inside the plot.
pat = re.compile(r'''    # MAIN INDICATOR: restore a clearly visible large point.*?\n    # Discreet stop-loss / technical invalidation only for validated LONG/SHORT\.\n''', re.S)
m = pat.search(s)
if not m:
    raise RuntimeError('main indicator block not found')
new_block = '''    # MAIN INDICATOR: a dedicated signal strip ABOVE the plot. It remains part\n    # of the chart, but can never cover a candle. The thin vertical guide keeps\n    # the prediction aligned with the exact future candle time.\n    fig.add_vline(x=dot_x, line_width=1, line_dash="dot", line_color=dot_color, opacity=0.55)\n    fig.add_annotation(\n        x=0.985, y=1.105, xref="paper", yref="paper", text="●", showarrow=False,\n        xanchor="right", yanchor="middle",\n        font={"color": dot_color, "size": 38},\n    )\n    fig.add_annotation(\n        x=0.975, y=1.105, xref="paper", yref="paper", text=f"<b>{label}</b>", showarrow=False,\n        xanchor="right", yanchor="middle",\n        font={"color": dot_color, "size": 13},\n        bgcolor="rgba(8,11,15,.94)", bordercolor=dot_color, borderwidth=1, borderpad=5,\n        hovertext=hover,\n    )\n\n    # Discreet stop-loss / technical invalidation only for validated LONG/SHORT.\n'''
s = s[:m.start()] + new_block + s[m.end():]

# More top room for the signal strip, much less blank future space.
s = s.replace('height=650, margin=dict(l=8, r=18, t=58, b=48),',
              'height=650, margin=dict(l=8, r=18, t=105, b=48),', 1)
s = s.replace('right_edge = max(signal_right_x, last_x + span * 0.16)',
              'right_edge = max(signal_right_x, last_x + span * 0.04)', 1)

# 6) Audit candle color with the same strict idea: only near-doji bodies are yellow.
old = '''            neutral = {\n                "1m": 0.00020, "2m": 0.00025, "3m": 0.00030, "5m": 0.00040,\n                "10m": 0.00055, "15m": 0.00070, "30m": 0.0010, "45m": 0.0012,\n                "1h": 0.0015, "2h": 0.0020, "3h": 0.0025, "4h": 0.0030,\n                "1D": 0.0050, "1W": 0.012, "1M": 0.025,\n            }.get(timeframe, 0.0015)\n'''
new = '''            neutral = {\n                "1m": 0.00005, "2m": 0.00007, "3m": 0.00008, "5m": 0.00010,\n                "10m": 0.00015, "15m": 0.00020, "30m": 0.00035, "45m": 0.00045,\n                "1h": 0.00060, "2h": 0.0010, "3h": 0.0013, "4h": 0.0016,\n                "1D": 0.0030, "1W": 0.0080, "1M": 0.0150,\n            }.get(timeframe, 0.00060)\n'''
if old not in s:
    raise RuntimeError('audit neutral block not found')
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('Patched target-candle semantics, strict lateral, future guard, and non-overlapping signal strip.')
