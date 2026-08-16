from pathlib import Path
import ast

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# Insert a lightweight statistical engine for SIMPLE mode. The full walk-forward
# ML engine remains untouched for Advanced mode.
marker = '@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)\ndef monthly_consensus_state'
if 'def fast_statistical_signal(' not in s:
    helpers = r'''
@st.cache_data(ttl=900, max_entries=32, show_spinner=False)
def fast_cycle_context(symbol_code: str):
    """Fast long-cycle context from daily and weekly closed candles."""
    votes = []
    for tf, hist in (("1D", 500), ("1W", 260)):
        try:
            raw = fetch_timeframe_history(symbol_code, tf, hist + 2)
            closed = raw[raw.is_closed].drop(columns=["is_closed"]).tail(hist).reset_index(drop=True)
            if len(closed) < 80:
                continue
            f = build_features(closed)
            r = f.iloc[-1]
            score = 0
            score += 1 if float(r.get("dist_ema_20", 0)) > 0 else -1
            score += 1 if float(r.get("dist_ema_200", 0)) > 0 else -1
            score += 1 if float(r.get("ret_14", 0)) > 0 else -1
            score += 1 if float(r.get("macd_hist_pct", 0)) > 0 else -1
            if float(r.get("adx_14", 0)) < 17:
                votes.append("LATERAL")
            elif score >= 2:
                votes.append("SUBIDA")
            elif score <= -2:
                votes.append("BAJADA")
            else:
                votes.append("LATERAL")
        except Exception:
            pass
    if not votes:
        return None
    if votes.count("SUBIDA") == len(votes):
        return "SUBIDA"
    if votes.count("BAJADA") == len(votes):
        return "BAJADA"
    if votes.count("LATERAL") >= max(1, len(votes) - 1):
        return "LATERAL"
    return None


@st.cache_data(ttl=300, max_entries=96, show_spinner=False)
def fast_statistical_signal(closed: pd.DataFrame, timeframe: str, horizon: int, cycle_context: str | None):
    """Fast evidence engine: historical analogues + trend + momentum + volume + cycle.

    This avoids retraining the heavy walk-forward ML stack whenever the user changes
    timeframe. It is deliberately selective: disagreement returns no colored signal.
    The rigorous ML/backtest engine is still available in Advanced mode.
    """
    if closed is None or closed.empty or len(closed) < 180:
        return {"ok": False, "reason": "Histórico insuficiente"}

    features = build_features(closed)
    row = features.iloc[-1]
    price = float(closed.close.iloc[-1])
    atr = float(row.get("atr_14", np.nan))
    sigma = float(row.get("realized_vol_30", np.nan))
    if not np.isfinite(atr):
        atr = max(price * 0.01, 1e-9)
    if not np.isfinite(sigma):
        sigma = None

    atr_pct = float(row.get("atr_pct", 0.01))
    flat_thr = float(np.clip(0.35 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))), 0.004, 0.05))
    fwd = features["close"].shift(-int(horizon)) / features["close"] - 1.0
    analog = find_similar_cases(features, ANALOG_FEATURE_COLUMNS, fwd, int(horizon), k=50, flat_threshold=flat_thr)
    if analog is None or analog.n_cases < 20:
        return {"ok": False, "reason": "Sin suficientes patrones históricos comparables"}

    analog_probs = np.array([analog.up_pct, analog.flat_pct, analog.down_pct], dtype=float) / 100.0

    # Technical direction from multiple independent measurements.
    tech_score = 0
    tech_score += 1 if float(row.get("dist_ema_20", 0)) > 0 else -1
    tech_score += 1 if float(row.get("dist_ema_200", 0)) > 0 else -1
    tech_score += 1 if float(row.get("ret_14", 0)) > 0 else -1
    tech_score += 1 if float(row.get("macd_hist_pct", 0)) > 0 else -1
    tech_score += 1 if float(row.get("di_spread", 0)) > 0 else -1
    adx = float(row.get("adx_14", 0))
    rsi = float(row.get("rsi_14", 50))
    if adx < 18 and 42 <= rsi <= 58:
        tech = "LATERAL"
    elif tech_score >= 2:
        tech = "SUBIDA"
    elif tech_score <= -2:
        tech = "BAJADA"
    else:
        tech = "LATERAL"

    try:
        vr = analyze_volume(row)
        vol_dir = "SUBIDA" if vr.direction == "COMPRADOR" else "BAJADA" if vr.direction == "VENDEDOR" else "LATERAL"
        vol_strength = float(np.clip(vr.intensity / 100.0, 0.0, 1.0))
    except Exception:
        vol_dir, vol_strength = "LATERAL", 0.35

    idx = {"SUBIDA": 0, "LATERAL": 1, "BAJADA": 2}
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

    if cycle_context in idx:
        cyc = np.full(3, 0.15)
        cyc[idx[cycle_context]] = 0.70
        score += 0.11 * cyc
        weights += 0.11

    probs = score / max(weights, 1e-9)
    probs = probs / probs.sum()
    ordered = np.argsort(probs)[::-1]
    dom_i, second_i = int(ordered[0]), int(ordered[1])
    labels = ["SUBIDA", "LATERAL", "BAJADA"]
    dom = labels[dom_i]
    prob = float(probs[dom_i])
    margin = float(probs[dom_i] - probs[second_i])

    analog_dom = analog.dominant
    confirmations = sum([
        analog_dom == dom,
        tech == dom,
        vol_dir == dom,
        cycle_context == dom if cycle_context else False,
    ])

    # Very selective gate. If evidence disagrees, gray is preferable to a false color.
    if dom in ("SUBIDA", "BAJADA"):
        reliable = (analog_dom == dom and prob >= 0.47 and margin >= 0.075 and confirmations >= 2)
    else:
        reliable = (analog_dom == "LATERAL" and tech == "LATERAL" and prob >= 0.44 and margin >= 0.055)

    state = None
    if reliable:
        high = prob >= 0.60 and margin >= 0.16 and confirmations >= 3
        state = {
            "scenario": dom,
            "probability": prob,
            "reliability": "ALTA" if high else "MEDIA",
            "source": "patrones históricos + tendencia + volumen + ciclo",
        }

    return {
        "ok": True,
        "state": state,
        "pup": float(probs[0]), "pflat": float(probs[1]), "pdown": float(probs[2]),
        "price": price, "atr": atr, "sigma": sigma,
        "analog_cases": int(analog.n_cases), "technical": tech,
        "volume_direction": vol_dir, "cycle": cycle_context,
    }


'''
    s = s.replace(marker, helpers + marker, 1)

start = 'if ui_mode == "Sencillo":\n    @st.fragment(run_every="90s")\n    def _render_fast_simple_mode():'
end = '    _render_fast_simple_mode()\n    st.stop()\n\n# ------------------------- Data -------------------------'
if start not in s or end not in s:
    raise RuntimeError('No se encontró el bloque simple rápido actual')

new_block = r'''if ui_mode == "Sencillo":
    @st.fragment(run_every="60s")
    def _render_fast_simple_mode():
        # Keep SIMPLE mode intentionally lean. 1,200 candles are enough for the
        # analogue engine; daily/weekly cycle context is fetched separately and cached.
        fast_history = min(int(training_bars), 1200)
        need_simple = max(fast_history + 2, int(chart_bars) + 2)
        try:
            full_simple = fetch_timeframe_history(SYMBOLS[selected], timeframe, need_simple)
            closed_simple = (full_simple[full_simple.is_closed]
                             .drop(columns=["is_closed"])
                             .tail(fast_history)
                             .reset_index(drop=True))
            chart_simple = full_simple.drop(columns=["is_closed"]).tail(int(chart_bars)).reset_index(drop=True)
        except Exception as e:
            st.error(f"No se pudieron cargar datos de mercado: {e}")
            return

        if closed_simple.empty:
            st.warning("Todavía no hay una vela cerrada disponible.")
            return

        # Statistical/cycle engine: no walk-forward retraining on timeframe changes.
        cycle = fast_cycle_context(SYMBOLS[selected])
        fast_result = fast_statistical_signal(closed_simple, timeframe, int(horizon), cycle)
        simple_state = fast_result.get("state") if fast_result.get("ok") else None

        simple_forecast_fast = None
        if fast_result.get("ok"):
            try:
                band = volatility_projection(
                    float(fast_result["price"]), fast_result.get("sigma"),
                    float(fast_result["atr"]), int(horizon), barrier_k=1.5,
                )
                simple_forecast_fast = build_simple_forecast(
                    closed_simple, float(fast_result["price"]),
                    float(fast_result["pup"]), float(fast_result["pflat"]), float(fast_result["pdown"]),
                    band.low68, band.high68, float(fast_result["atr"]), int(horizon),
                )
            except Exception:
                simple_forecast_fast = None

        if simple_state:
            sc = simple_state["scenario"]
            icon = "🟢" if sc == "SUBIDA" else "🔴" if sc == "BAJADA" else "🟡"
            label = "LONG" if sc == "SUBIDA" else "SHORT" if sc == "BAJADA" else "LATERAL"
            st.markdown(f"### {icon} {selected} · {label} · {simple_state['probability']*100:.1f}% · {timeframe}")
        else:
            st.markdown(f"### ⚪ {selected} · SIN SEÑAL FIABLE · {timeframe}")

        fig_fast = simple_signal_chart(
            chart_simple, selected, timeframe, int(horizon), simple_state, simple_forecast_fast
        )
        st.plotly_chart(fig_fast, width="stretch", theme=None,
                        key=f"fast_simple_{selected}_{timeframe}_{horizon}", config=plot_config())

        current_state = simple_state["scenario"] if simple_state else "NONE"
        alert_key = f"fast_last_state::{selected}::{timeframe}"
        previous_state = st.session_state.get(alert_key)
        if previous_state is not None and previous_state != current_state:
            txt = ("LONG" if current_state == "SUBIDA" else
                   "SHORT" if current_state == "BAJADA" else
                   "LATERAL" if current_state == "LATERAL" else "SIN SEÑAL FIABLE")
            st.toast(f"{selected} · {timeframe}: {txt}", icon="🔔")
        st.session_state[alert_key] = current_state

        st.caption("Análisis rápido: patrones históricos + tendencia + volumen + contexto de ciclo. El ML pesado queda en Avanzado.")

    _render_fast_simple_mode()
    st.stop()

# ------------------------- Data -------------------------'''

s = s.replace(s[s.index(start):s.index(end)+len(end)], new_block, 1)
ast.parse(s)
p.write_text(s, encoding='utf-8')
print('Fast statistical simple mode applied')
