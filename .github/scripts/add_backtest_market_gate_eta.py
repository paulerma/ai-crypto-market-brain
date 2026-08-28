from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# Import the real historical first-touch ETA estimator.
s = s.replace(
    "from engines.pattern_engine import find_similar_cases, ANALOG_FEATURE_COLUMNS",
    "from engines.pattern_engine import find_similar_cases, estimate_time_to_move, ANALOG_FEATURE_COLUMNS",
)

anchor = '''def _direction_support(scenario: str, probability: float, candidate: str) -> float:
    probability = float(np.clip(probability, 0.0, 1.0))
    if scenario == candidate:
        return probability
    if scenario in ("SUBIDA", "BAJADA") and scenario != candidate:
        return 1.0 - probability
    return 0.5


'''

insert = r'''def _validation_direction_score(features: pd.DataFrame, market: pd.DataFrame, i: int) -> float:
    """Past-only directional score used by the safety backtest.

    Positive = bullish evidence, negative = bearish evidence. This is NOT shown
    as a probability. It exists only as an independent historical safety gate.
    """
    if i < 5 or i >= len(features):
        return 0.0
    row = features.iloc[i]
    prev = features.iloc[i - 3]
    close = market["close"].astype(float)
    try:
        ret1 = float(close.iloc[i] / close.iloc[i - 1] - 1.0)
        ret3 = float(close.iloc[i] / close.iloc[i - 3] - 1.0)
        ret3_prev = float(close.iloc[i - 3] / close.iloc[i - 6] - 1.0) if i >= 6 else ret3
    except Exception:
        ret1 = ret3 = ret3_prev = 0.0

    atr_pct = abs(float(row.get("atr_pct", 0.0)))
    atr_scale = max(atr_pct, 1e-6)

    def sgn(x):
        try:
            v = float(x)
            if not np.isfinite(v) or abs(v) < 1e-12:
                return 0.0
            return 1.0 if v > 0 else -1.0
        except Exception:
            return 0.0

    rsi = float(row.get("rsi_14", 50.0))
    rsi_component = float(np.clip((rsi - 50.0) / 20.0, -1.0, 1.0))
    ret1_component = float(np.clip(ret1 / atr_scale, -1.0, 1.0))
    ret3_component = float(np.clip(ret3 / max(atr_scale * 1.8, 1e-6), -1.0, 1.0))

    macd_delta = float(row.get("macd_hist_pct", 0.0)) - float(prev.get("macd_hist_pct", 0.0))
    di_delta = float(row.get("di_spread", 0.0)) - float(prev.get("di_spread", 0.0))
    rsi_delta = float(row.get("rsi_14", 50.0)) - float(prev.get("rsi_14", 50.0))
    ret_acc = ret3 - ret3_prev

    score = (
        0.12 * sgn(row.get("dist_ema_20", 0.0))
        + 0.08 * sgn(row.get("dist_ema_200", 0.0))
        + 0.10 * sgn(row.get("ret_14", 0.0))
        + 0.14 * sgn(row.get("macd_hist_pct", 0.0))
        + 0.14 * sgn(row.get("di_spread", 0.0))
        + 0.08 * rsi_component
        + 0.05 * sgn(row.get("ema200_slope_20", 0.0))
        + 0.09 * ret1_component
        + 0.06 * ret3_component
        + 0.06 * sgn(macd_delta)
        + 0.04 * sgn(di_delta)
        + 0.02 * sgn(rsi_delta)
        + 0.02 * sgn(ret_acc)
    )
    adx = float(row.get("adx_14", 20.0))
    if adx < 16:
        score *= 0.72
    elif adx < 20:
        score *= 0.88
    return float(np.clip(score, -1.0, 1.0))


def _validation_first_touch(market: pd.DataFrame, features: pd.DataFrame,
                            i: int, horizon: int, direction: str) -> int:
    """Conservative first-touch outcome: 1 target first, 0 otherwise."""
    try:
        base = float(market["close"].iloc[i])
        atr = float(features.iloc[i].get("atr_14", np.nan))
    except Exception:
        return 0
    if not np.isfinite(base) or base <= 0:
        return 0
    if not np.isfinite(atr) or atr <= 0:
        atr = base * 0.01
    distance = max(0.70 * atr, base * 0.0015)
    if direction == "SUBIDA":
        target, adverse = base + distance, base - distance
    else:
        target, adverse = base - distance, base + distance

    for step in range(1, max(1, int(horizon)) + 1):
        j = i + step
        if j >= len(market):
            return 0
        high = float(market["high"].iloc[j])
        low = float(market["low"].iloc[j])
        if direction == "SUBIDA":
            good, bad = high >= target, low <= adverse
        else:
            good, bad = low <= target, high >= adverse
        # Same-bar ambiguity is deliberately counted as a failure.
        if good and bad:
            return 0
        if good:
            return 1
        if bad:
            return 0
    # No target touch inside the horizon = not a successful signal.
    return 0


@st.cache_data(ttl=600, max_entries=96, show_spinner=False)
def historical_signal_backtest_gate(closed: pd.DataFrame, timeframe: str) -> dict:
    """Recent chronological holdout test for the colored predictive signal.

    Threshold is selected on an earlier tuning segment and evaluated only on a
    later holdout segment. This is intentionally conservative and independent of
    the main heuristic detector.
    """
    if closed is None or len(closed) < 220:
        return {"ok": False, "reason": "histórico insuficiente", "directions": {}}
    market = closed.reset_index(drop=True).copy()
    features = build_features(market).reset_index(drop=True)
    n = min(len(market), len(features))
    market, features = market.iloc[:n], features.iloc[:n]
    horizon = 4 if timeframe in ("1D", "1W", "1M") else 2 if timeframe in ("1h", "2h", "3h", "4h") else 4

    start = max(80, min(220, n // 3))
    end = n - horizon - 1
    if end - start < 80:
        return {"ok": False, "reason": "ventana de validación corta", "directions": {}}
    indices = list(range(start, end))
    split = start + int((end - start) * 0.62)
    tune_idx = [i for i in indices if i < split]
    test_idx = [i for i in indices if i >= split]
    thresholds = [0.30, 0.40, 0.50, 0.60, 0.70]

    def stats(idxs, threshold, direction):
        sign = 1.0 if direction == "SUBIDA" else -1.0
        outcomes = []
        last_signal_i = -10_000
        cooldown = max(1, horizon // 2)
        for i in idxs:
            score = _validation_direction_score(features, market, i)
            if sign * score < threshold:
                continue
            if i - last_signal_i <= cooldown:
                continue
            last_signal_i = i
            outcomes.append(_validation_first_touch(market, features, i, horizon, direction))
        n_sig = len(outcomes)
        wins = int(sum(outcomes))
        precision = float(wins / n_sig) if n_sig else 0.0
        return {"n": n_sig, "wins": wins, "precision": precision}

    directions = {}
    current_score = _validation_direction_score(features, market, n - 1)
    for direction in ("SUBIDA", "BAJADA"):
        tuned = []
        for th in thresholds:
            stt = stats(tune_idx, th, direction)
            if stt["n"] >= 12:
                tuned.append((stt["precision"], stt["n"], th))
        if not tuned:
            chosen = 0.70
            tune = stats(tune_idx, chosen, direction)
        else:
            # Tune only on the earlier segment; prefer precision, then sample size.
            _, _, chosen = max(tuned, key=lambda x: (x[0], x[1], x[2]))
            tune = stats(tune_idx, chosen, direction)
        test = stats(test_idx, chosen, direction)
        sign = 1.0 if direction == "SUBIDA" else -1.0
        current_matches = bool(sign * current_score >= chosen)
        validated = bool(
            test["n"] >= 12
            and test["precision"] >= 0.60
            and current_matches
        )
        directions[direction] = {
            "threshold": float(chosen),
            "tune_n": int(tune["n"]),
            "tune_precision": float(tune["precision"]),
            "n": int(test["n"]),
            "wins": int(test["wins"]),
            "precision": float(test["precision"]),
            "current_score": float(current_score),
            "current_matches": current_matches,
            "validated": validated,
            "horizon_bars": int(horizon),
        }
    return {"ok": True, "directions": directions, "current_score": float(current_score)}


@st.cache_data(ttl=90, max_entries=32, show_spinner=False)
def broad_market_context(symbol_code: str, timeframe: str) -> dict:
    """Lightweight BTC/ETH context so an altcoin signal is not judged in isolation."""
    basket = [("BTCUSDT", 0.70), ("ETHUSDT", 0.30)]
    if symbol_code == "BTCUSDT":
        basket = [("ETHUSDT", 1.0)]
    total_w, score = 0.0, 0.0
    states = []
    for sym, w in basket:
        try:
            raw = fetch_timeframe_history(sym, timeframe, 140)
            c = raw[raw.is_closed].drop(columns=["is_closed"]).tail(120).reset_index(drop=True)
            state = current_trend_state(c, timeframe)
            scenario = state.get("scenario", "LATERAL")
            strength = float(state.get("strength", 0.0))
            value = strength if scenario == "SUBIDA" else -strength if scenario == "BAJADA" else 0.0
            score += w * value
            total_w += w
            states.append({"symbol": sym, "scenario": scenario, "strength": strength})
        except Exception:
            pass
    if total_w <= 0:
        return {"ok": False, "score": 0.0, "states": states}
    return {"ok": True, "score": float(np.clip(score / total_w, -1.0, 1.0)), "states": states}


'''

if "def historical_signal_backtest_gate(" not in s:
    if anchor not in s:
        raise RuntimeError("direction support anchor missing")
    s = s.replace(anchor, anchor + insert, 1)

# Add market support to each candidate.
needle = '''        candidate_rows.append({
            "to": candidate,
            "evidence": evidence,
'''
replacement = '''        market_ctx = broad_market_context(symbol_code, timeframe)
        market_score = float(market_ctx.get("score", 0.0)) if market_ctx.get("ok") else 0.0
        market_support = float(np.clip(
            0.5 + 0.45 * market_score * (1.0 if candidate == "SUBIDA" else -1.0),
            0.05, 0.95
        ))

        candidate_rows.append({
            "to": candidate,
            "evidence": evidence,
            "market_support": market_support,
'''
if replacement not in s:
    if needle not in s:
        raise RuntimeError("candidate append anchor missing")
    s = s.replace(needle, replacement, 1)

# Attach real historical ETA to each directional target.
eta_anchor = '''        fc["target_source"] = target_source
        directional_forecasts[row["to"]] = fc
'''
eta_repl = '''        fc["target_source"] = target_source
        try:
            eta_features = build_features(closed)
            move_return = abs(float(fc["target_price"]) / max(market_price, 1e-12) - 1.0)
            eta_max = int(min(12, max(4, timing_bars * 2)))
            fc["eta"] = estimate_time_to_move(
                eta_features, closed, ANALOG_FEATURE_COLUMNS,
                move_return, row["to"], max_bars=eta_max, k=40
            )
        except Exception:
            fc["eta"] = None
        directional_forecasts[row["to"]] = fc
'''
if eta_repl not in s:
    if eta_anchor not in s:
        raise RuntimeError("target source anchor missing")
    s = s.replace(eta_anchor, eta_repl, 1)

# Strengthen final colored-signal gate with chronological historical holdout and market context.
old_gate = '''    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
    transition = None
    early_warning = None
    if best:
        family_votes = [
            float(best.get("future_support", 0.5)) >= 0.56,
            float(best.get("precursor", 0.5)) >= 0.60,
            float(best.get("component_support", 0.5)) >= 0.60,
        ]
        if sensors:
            family_votes.append(
                float(best.get("sensor_support", 0.5)) >= 0.56
                and int(best.get("sensor_agree", 0)) >= 1
            )
        required_votes = 3 if sensors else 2
        signal_gate = (
            bool(best.get("timing_ok", False))
            and float(best.get("timing_score", 0.5)) >= 0.55
            and sum(bool(v) for v in family_votes) >= required_votes
        )
        if signal_gate and best["evidence"] >= 0.64:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.70 else "MEDIA"
        elif signal_gate and best["evidence"] >= 0.59:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.72))
            early_warning["reliability"] = "TEMPRANA"
'''

new_gate = '''    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
    historical_validation = historical_signal_backtest_gate(closed, timeframe)
    transition = None
    early_warning = None
    gate_reason = None
    if best:
        family_votes = [
            float(best.get("future_support", 0.5)) >= 0.56,
            float(best.get("precursor", 0.5)) >= 0.60,
            float(best.get("component_support", 0.5)) >= 0.60,
        ]
        if sensors:
            family_votes.append(
                float(best.get("sensor_support", 0.5)) >= 0.56
                and int(best.get("sensor_agree", 0)) >= 1
            )
        required_votes = 3 if sensors else 2
        val_stats = (historical_validation.get("directions") or {}).get(best.get("to"), {})
        validation_ok = bool(val_stats.get("validated", False))
        market_support = float(best.get("market_support", 0.5))
        market_ok = market_support >= 0.45
        strong_local_override = bool(
            best["evidence"] >= 0.72
            and float(best.get("timing_score", 0.5)) >= 0.62
            and float(best.get("precursor", 0.5)) >= 0.65
            and float(best.get("component_support", 0.5)) >= 0.65
        )
        signal_gate = (
            bool(best.get("timing_ok", False))
            and float(best.get("timing_score", 0.5)) >= 0.55
            and sum(bool(v) for v in family_votes) >= required_votes
            and validation_ok
            and (market_ok or strong_local_override)
        )
        if not validation_ok:
            gate_reason = "validación histórica reciente insuficiente"
        elif not (market_ok or strong_local_override):
            gate_reason = "el contexto BTC/ETH contradice la señal"
        elif not signal_gate:
            gate_reason = "confluencia insuficiente"
        if signal_gate and best["evidence"] >= 0.66:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.72 else "MEDIA"
            transition["validation"] = val_stats
        elif signal_gate and best["evidence"] >= 0.61:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.72))
            early_warning["reliability"] = "TEMPRANA"
            early_warning["validation"] = val_stats
'''

if old_gate not in s:
    raise RuntimeError("current safety gate block not found")
s = s.replace(old_gate, new_gate, 1)

# Return audit info.
ret_anchor = '''        "primary_forecast": primary_forecast,
        "interim": interim,
        "max_horizon": 8,
'''
ret_repl = '''        "primary_forecast": primary_forecast,
        "interim": interim,
        "historical_validation": historical_validation,
        "gate_candidate": best,
        "gate_reason": gate_reason,
        "max_horizon": 8,
'''
if ret_repl not in s:
    if ret_anchor not in s:
        raise RuntimeError("return audit anchor missing")
    s = s.replace(ret_anchor, ret_repl, 1)

# Show true ETA only when historical first-touch evidence is valid.
old_target_line = '''        target_value, target_horizon = pair
        target_txt = _market_price_text(target_value, last_price)
        target_time = _duration_text(timeframe, max(1, int(target_horizon)))
        objective_name = "OBJETIVO SUBIDA" if direction == "SUBIDA" else "OBJETIVO BAJADA"
'''
new_target_line = '''        target_value, target_horizon = pair
        target_txt = _market_price_text(target_value, last_price)
        target_time = _duration_text(timeframe, max(1, int(target_horizon)))
        eta = (dirs.get(direction) or {}).get("eta") or {}
        if eta.get("valid"):
            e1 = int(eta.get("q25_bars", eta.get("median_bars", 1)))
            e2 = int(eta.get("q75_bars", eta.get("median_bars", e1)))
            if e1 == e2:
                time_label = f"ETA hist. {_duration_text(timeframe, e1)}"
            else:
                time_label = f"ETA hist. {_duration_text(timeframe, e1)}–{_duration_text(timeframe, e2)}"
        else:
            time_label = f"horizonte {target_time}"
        objective_name = "OBJETIVO SUBIDA" if direction == "SUBIDA" else "OBJETIVO BAJADA"
'''
if new_target_line not in s:
    if old_target_line not in s:
        raise RuntimeError("target label setup missing")
    s = s.replace(old_target_line, new_target_line, 1)

s = s.replace(
    'text=f"<b>{objective_name} · {target_txt} · horizonte {target_time}</b>",',
    'text=f"<b>{objective_name} · {target_txt} · {time_label}</b>",',
)

# Add a small audit caption under the simple headline.
caption_anchor = '''            st.markdown(f"## {_desc_icon} TENDENCIA ACTUAL: {_desc} · SIN SEÑAL PREDICTIVA VALIDADA")
        path = trend_info.get("market_path") or {}
'''
caption_repl = '''            st.markdown(f"## {_desc_icon} TENDENCIA ACTUAL: {_desc} · SIN SEÑAL PREDICTIVA VALIDADA")

        _val = trend_info.get("historical_validation") or {}
        _candidate = trend_info.get("gate_candidate") or {}
        _cand_dir = _candidate.get("to")
        _vs = (_val.get("directions") or {}).get(_cand_dir, {}) if _cand_dir else {}
        if _ui_active_signal is not None and _vs:
            st.caption(
                f"Filtro histórico reciente aprobado: {_vs.get('precision',0)*100:.0f}% "
                f"de aciertos en {_vs.get('n',0)} señales de prueba."
            )
        elif _cand_dir and _vs:
            _label = "subida" if _cand_dir == "SUBIDA" else "bajada"
            st.caption(
                f"Sin señal operable de {_label}: {_vs.get('precision',0)*100:.0f}% "
                f"en {_vs.get('n',0)} señales de prueba · "
                f"{trend_info.get('gate_reason') or 'filtro no superado'}."
            )
        path = trend_info.get("market_path") or {}
'''
if caption_repl not in s:
    if caption_anchor not in s:
        raise RuntimeError("simple caption anchor missing")
    s = s.replace(caption_anchor, caption_repl, 1)

# Defensive fallback.
fallback_anchor = '''                "primary_forecast": None,
                "interim": None,
                "max_horizon": 8,
'''
fallback_repl = '''                "primary_forecast": None,
                "interim": None,
                "historical_validation": {"ok": False, "directions": {}},
                "gate_candidate": None,
                "gate_reason": "detector no disponible",
                "max_horizon": 8,
'''
if fallback_repl not in s and fallback_anchor in s:
    s = s.replace(fallback_anchor, fallback_repl, 1)

p.write_text(s, encoding="utf-8")
print("Applied chronological backtest gate, BTC/ETH context, and true historical ETA")
