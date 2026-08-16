from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Browser-side countdown without rerunning Python/model every second.
if 'import streamlit.components.v1 as components' not in s:
    s = s.replace('import streamlit as st\n', 'import streamlit as st\nimport streamlit.components.v1 as components\n', 1)

anchor = 'CHART_TZ = ZoneInfo("America/Hermosillo")\n'
helper = r'''


def render_candle_countdown(next_candle_time, timeframe: str):
    """TradingView-like countdown to the close of the currently forming candle.

    `next_candle_time` is the start of the next candle, which is exactly the
    close boundary of the candle forming now. The browser updates the clock; no
    model rerun is required each second.
    """
    target = pd.Timestamp(next_candle_time)
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    target_ms = int(target.tz_convert("UTC").timestamp() * 1000)
    html = f"""
    <div style="display:flex;align-items:center;gap:8px;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;
                color:#c9d1d9;background:#0d1117;border:1px solid #29313a;border-radius:8px;
                width:max-content;padding:5px 10px;margin:0 0 4px 0;font-size:13px">
      <span style="color:#8b949e">VELA ACTUAL · CIERRA EN</span>
      <span id="candleClock" style="font-variant-numeric:tabular-nums;font-weight:800;color:#f0f3f6">--:--</span>
    </div>
    <script>
      const target = {target_ms};
      function tick() {{
        const left = Math.max(0, target - Date.now());
        const total = Math.ceil(left / 1000);
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const sec = total % 60;
        let txt;
        if (h > 0) txt = String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
        else txt = String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
        document.getElementById('candleClock').textContent = txt;
      }}
      tick();
      setInterval(tick, 250);
    </script>
    """
    components.html(html, height=36, scrolling=False)
'''
if 'def render_candle_countdown(' not in s:
    s = s.replace(anchor, anchor + helper, 1)

# 2) Fix forced direction confidence. If LATERAL is rejected on fast TFs, compare
# only UP vs DOWN and expose conditional directional confidence, never 24% red/green.
old = '''        if not truly_lateral:\n            directional = [idx["SUBIDA"], idx["BAJADA"]]\n            dom_i = max(directional, key=lambda i: float(probs[i]))\n            dom = labels[dom_i]\n            second_i = idx["LATERAL"] if probs[idx["LATERAL"]] >= probs[directional[1 if dom_i == directional[0] else 0]] else directional[1 if dom_i == directional[0] else 0]\n\n    prob = float(probs[dom_i])\n    margin = float(probs[dom_i] - probs[second_i])\n'''
new = '''        if not truly_lateral:\n            up_i, down_i = idx["SUBIDA"], idx["BAJADA"]\n            directional_total = float(probs[up_i] + probs[down_i])\n            if directional_total > 1e-9:\n                up_cond = float(probs[up_i] / directional_total)\n                down_cond = float(probs[down_i] / directional_total)\n                if up_cond >= down_cond:\n                    dom_i, dom = up_i, "SUBIDA"\n                    directional_confidence = up_cond\n                else:\n                    dom_i, dom = down_i, "BAJADA"\n                    directional_confidence = down_cond\n            else:\n                directional_confidence = 0.5\n\n    # For a forced fast-timeframe directional decision, the meaningful number is\n    # P(up | up-or-down), not the original three-class share. This prevents\n    # misleading labels such as BAJA 24.6%.\n    if 'directional_confidence' in locals() and dom in ("SUBIDA", "BAJADA"):\n        prob = float(directional_confidence)\n        margin = float(abs(prob - (1.0 - prob)))\n    else:\n        prob = float(probs[dom_i])\n        margin = float(probs[dom_i] - probs[second_i])\n'''
if old in s:
    s = s.replace(old, new, 1)
elif 'directional_confidence = up_cond' not in s:
    raise RuntimeError('No se encontró bloque de confianza direccional')

# 3) Restore the large point. It sits at the FUTURE target x-position and at the
# last price y-value, so it is visible but does not cover a real candle.
old_point = '''    # MAIN INDICATOR: a prediction lane at the TOP of the chart. The x-position\n    # is the future candle start; y uses paper coordinates, so it can never cover price.\n    slot_minutes = max(float(INTERVAL_MINUTES.get(timeframe, 1)), 1.0)\n    half = pd.Timedelta(minutes=slot_minutes * 0.20)\n    fig.add_shape(\n        type="circle", xref="x", yref="paper",\n        x0=dot_x - half, x1=dot_x + half, y0=0.925, y1=0.975,\n        fillcolor=dot_color, line={"color": "#ffffff", "width": 2}, layer="above",\n    )\n    fig.add_vline(x=dot_x, line_width=1, line_dash="dot", line_color=dot_color, opacity=0.55)\n    fig.add_annotation(\n        x=dot_x, y=0.985, xref="x", yref="paper", text=f"<b>{label}</b>", showarrow=False,\n        xanchor="center", yanchor="bottom",\n        font={"color": dot_color, "size": 13},\n        bgcolor="rgba(8,11,15,.92)", bordercolor=dot_color, borderwidth=1, borderpad=4,\n        hovertext=hover,\n    )\n'''
new_point = '''    # MAIN INDICATOR: restore a clearly visible large point at the exact FUTURE\n    # candle start. Because dot_x is to the right of the forming candle, it never\n    # covers a real candle. A dotted guide identifies the target time.\n    fig.add_trace(go.Scatter(\n        x=[dot_x], y=[last_y], mode="markers",\n        marker={"size": 27, "color": dot_color, "line": {"color": "#ffffff", "width": 2}},\n        hovertemplate=hover + "<extra></extra>", showlegend=False, name="Predicción",\n    ))\n    fig.add_vline(x=dot_x, line_width=1, line_dash="dot", line_color=dot_color, opacity=0.60)\n    fig.add_annotation(\n        x=dot_x, y=last_y, xref="x", yref="y", text=f"<b>{label}</b>", showarrow=False,\n        xshift=14, yshift=32, xanchor="left",\n        font={"color": dot_color, "size": 13},\n        bgcolor="rgba(8,11,15,.92)", bordercolor=dot_color, borderwidth=1, borderpad=4,\n        hovertext=hover,\n    )\n'''
if old_point in s:
    s = s.replace(old_point, new_point, 1)
elif 'name="Predicción"' not in s:
    raise RuntimeError('No se encontró bloque del punto')

# 4) Add TradingView-like live countdown immediately before the prediction header.
marker = '''        if simple_state:\n            sc = simple_state["scenario"]\n'''
replacement = '''        # TradingView-style candle countdown. target_time is the next candle start,\n        # therefore also the exact close boundary of the candle currently forming.\n        render_candle_countdown(target_time, timeframe)\n\n        if simple_state:\n            sc = simple_state["scenario"]\n'''
if marker in s and 'render_candle_countdown(target_time, timeframe)' not in s:
    s = s.replace(marker, replacement, 1)

# 5) Add a tiny forward-audit in session state. It resolves prior predictions only
# after their target candle has CLOSED. This makes misses explicit instead of
# rationalizing them after the fact.
audit_anchor = '''        current_state = simple_state["scenario"] if simple_state else "NONE"\n        alert_key = f"fast_last_state::{selected}::{timeframe}"\n'''
audit_block = '''        # Forward audit: store the signal BEFORE the target candle starts, then\n        # score it only after that candle closes. Session-local by design; a\n        # persistent audit can be added later without cluttering simple mode.\n        audit_key = f"forward_audit::{selected}::{timeframe}"\n        audit = st.session_state.get(audit_key, {})\n        target_iso = pd.Timestamp(target_time).isoformat()\n        if simple_state and target_iso not in audit:\n            audit[target_iso] = {\n                "scenario": simple_state["scenario"],\n                "confidence": float(simple_state["probability"]),\n                "resolved": False,\n            }\n        for ts_key, rec in list(audit.items()):\n            if rec.get("resolved"):\n                continue\n            ts = pd.Timestamp(ts_key)\n            hits = full_simple[(full_simple["timestamp"] == ts) & (full_simple["is_closed"])]\n            if hits.empty:\n                continue\n            candle = hits.iloc[-1]\n            move = float(candle["close"] / candle["open"] - 1.0)\n            neutral = {\n                "1m": 0.00020, "2m": 0.00025, "3m": 0.00030, "5m": 0.00040,\n                "10m": 0.00055, "15m": 0.00070, "30m": 0.0010, "45m": 0.0012,\n                "1h": 0.0015, "2h": 0.0020, "3h": 0.0025, "4h": 0.0030,\n                "1D": 0.0050, "1W": 0.012, "1M": 0.025,\n            }.get(timeframe, 0.0015)\n            actual = "SUBIDA" if move > neutral else "BAJADA" if move < -neutral else "LATERAL"\n            rec["actual"] = actual\n            rec["correct"] = bool(actual == rec.get("scenario"))\n            rec["resolved"] = True\n            rec["move"] = move\n        st.session_state[audit_key] = dict(list(audit.items())[-40:])\n        resolved = [r for r in audit.values() if r.get("resolved")]\n        if resolved:\n            last_eval = resolved[-1]\n            mark = "✅" if last_eval.get("correct") else "❌"\n            predicted_txt = "SUBE" if last_eval.get("scenario") == "SUBIDA" else "BAJA" if last_eval.get("scenario") == "BAJADA" else "LATERAL"\n            actual_txt = "SUBIÓ" if last_eval.get("actual") == "SUBIDA" else "BAJÓ" if last_eval.get("actual") == "BAJADA" else "LATERAL"\n            st.caption(f"{mark} Última señal cerrada: predijo {predicted_txt} · resultado {actual_txt}")\n\n        current_state = simple_state["scenario"] if simple_state else "NONE"\n        alert_key = f"fast_last_state::{selected}::{timeframe}"\n'''
if audit_anchor in s and 'forward_audit::' not in s:
    s = s.replace(audit_anchor, audit_block, 1)

p.write_text(s, encoding='utf-8')
