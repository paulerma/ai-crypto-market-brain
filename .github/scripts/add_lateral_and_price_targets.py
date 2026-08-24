from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

# 1) Expose historical-analogue return quantiles from the fast engine so price
# targets can come from comparable past situations when enough cases exist.
old = '''        "analog_cases": int(analog_cases), "technical": tech,
        "volume_direction": vol_dir, "impulse": impulse, "cycle": cycle_context,
    }'''
new = '''        "analog_cases": int(analog_cases), "technical": tech,
        "volume_direction": vol_dir, "impulse": impulse, "cycle": cycle_context,
        "analog_quantiles": (analog.scenario_quantiles if analog is not None else {}),
    }'''
if old not in s:
    raise RuntimeError('No se encontró return de fast_statistical_signal')
s = s.replace(old, new, 1)

# 2) Add a compact reusable price formatter next to duration formatting.
anchor = '''def current_trend_state(closed: pd.DataFrame, timeframe: str) -> dict:
'''
helper = '''def _market_price_text(value: float | None, reference: float | None = None) -> str:
    """TradingView-like compact price formatting for simple forecast labels."""
    if value is None:
        return "N/A"
    try:
        v = float(value)
        ref = abs(float(reference if reference is not None else v))
        if not np.isfinite(v):
            return "N/A"
    except Exception:
        return "N/A"
    if ref >= 100:
        decimals = 2
    elif ref >= 1:
        decimals = 4
    elif ref >= 0.01:
        decimals = 5
    else:
        decimals = 8
    return f"${v:,.{decimals}f}"


'''
if anchor not in s:
    raise RuntimeError('No se encontró current_trend_state')
s = s.replace(anchor, helper + anchor, 1)

# 3) Replace directional-forecast export with market-derived target prices and
# an interim regime/range that explains what may happen before the next move.
old = '''    directional_forecasts = {}
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
new = '''    directional_forecasts = {}
    market_price = float(closed["close"].iloc[-1])
    for row in candidate_rows:
        fc = dict(row)
        timing_score = float(row.get("timing_score", 0.5))
        timing_bars = int(row.get("timing_bars", 1))
        fc["probability"] = float(np.clip(timing_score, 0.0, 1.0))
        fc["status"] = "ESTIMACION_IA"
        fc["reliability"] = "ALTA" if timing_score >= 0.66 else "MEDIA" if timing_score >= 0.56 else "BAJA"
        fc["has_window"] = bool(row.get("timing_ok", False))
        fc["start_bars"] = timing_bars
        fc["end_bars"] = timing_bars

        # Price objective: prefer the median realized move among historically
        # similar cases for this exact horizon/direction. If the analogue sample
        # is unavailable, fall back to an ATR-scaled move from current volatility.
        timing_res = next((res for h, res in zip(horizons, raw_results)
                           if int(h) == timing_bars and res.get("ok")), {})
        aq = (timing_res.get("analog_quantiles") or {}).get(row["to"]) or {}
        q50 = float(aq.get("q50", np.nan)) if aq else np.nan
        q25 = float(aq.get("q25", np.nan)) if aq else np.nan
        q75 = float(aq.get("q75", np.nan)) if aq else np.nan
        aligned_q50 = np.isfinite(q50) and ((row["to"] == "SUBIDA" and q50 > 0) or (row["to"] == "BAJADA" and q50 < 0))

        if aligned_q50:
            target_price = market_price * (1.0 + q50)
            zone_a = market_price * (1.0 + q25) if np.isfinite(q25) else target_price
            zone_b = market_price * (1.0 + q75) if np.isfinite(q75) else target_price
            target_low, target_high = min(zone_a, zone_b), max(zone_a, zone_b)
            target_source = "casos históricos similares"
        else:
            atr = float(timing_res.get("atr", np.nan)) if timing_res else np.nan
            if not np.isfinite(atr) or atr <= 0:
                try:
                    atr = float(build_features(closed).iloc[-1].get("atr_14", market_price * 0.01))
                except Exception:
                    atr = market_price * 0.01
            strength_mult = 0.90 + 0.65 * min(1.0, abs(timing_score - 0.5) * 2.0)
            move = max(atr, market_price * 0.001) * np.sqrt(max(1, timing_bars)) * strength_mult
            target_price = market_price + move if row["to"] == "SUBIDA" else market_price - move
            target_low = target_price - 0.22 * move
            target_high = target_price + 0.22 * move
            target_source = "volatilidad/ATR"

        # Never let a directional target land on the wrong side of spot.
        if row["to"] == "SUBIDA" and target_price <= market_price:
            target_price = market_price + abs(target_price - market_price)
        elif row["to"] == "BAJADA" and target_price >= market_price:
            target_price = market_price - abs(target_price - market_price)

        fc["target_price"] = float(max(target_price, 1e-12))
        fc["target_low"] = float(max(min(target_low, target_high), 1e-12))
        fc["target_high"] = float(max(max(target_low, target_high), 1e-12))
        fc["target_source"] = target_source
        directional_forecasts[row["to"]] = fc

    # Explain the gap between now and the first directional timing. The immediate
    # horizon determines whether price is more likely to range or keep a bias.
    valid_timing = [int(r.get("timing_bars", 1)) for r in candidate_rows if r.get("timing_ok")]
    first_move_bars = min(valid_timing) if valid_timing else 1
    interim_bars = max(1, first_move_bars - 1) if first_move_bars > 1 else 1
    immediate_res = raw_results[0] if raw_results and raw_results[0].get("ok") else {}
    up0 = float(immediate_res.get("pup", 0.0))
    flat0 = float(immediate_res.get("pflat", 0.0))
    down0 = float(immediate_res.get("pdown", 0.0))
    try:
        adx0 = float(build_features(closed).iloc[-1].get("adx_14", 20.0))
    except Exception:
        adx0 = 20.0
    directional0 = up0 + down0
    up_share0 = up0 / directional0 if directional0 > 1e-9 else 0.5
    down_share0 = down0 / directional0 if directional0 > 1e-9 else 0.5
    is_lateral = (
        current_dir == "LATERAL"
        or (flat0 >= 0.30 and adx0 < 24)
        or (abs(up_share0 - down_share0) <= 0.12 and adx0 < 22)
    )
    if is_lateral:
        interim_label = "LATERALIZA"
    elif up_share0 >= down_share0:
        interim_label = "SESGO ALCISTA"
    else:
        interim_label = "SESGO BAJISTA"

    # Lateral range: prefer historical lateral quantiles; otherwise use ATR plus
    # recent structure so the range is tied to observed market behavior.
    lateral_q = (immediate_res.get("analog_quantiles") or {}).get("LATERAL") or {}
    lq25 = float(lateral_q.get("q25", np.nan)) if lateral_q else np.nan
    lq75 = float(lateral_q.get("q75", np.nan)) if lateral_q else np.nan
    if is_lateral and np.isfinite(lq25) and np.isfinite(lq75):
        interim_low = market_price * (1.0 + min(lq25, lq75))
        interim_high = market_price * (1.0 + max(lq25, lq75))
        interim_source = "casos históricos similares"
    else:
        atr0 = float(immediate_res.get("atr", np.nan)) if immediate_res else np.nan
        if not np.isfinite(atr0) or atr0 <= 0:
            try:
                atr0 = float(build_features(closed).iloc[-1].get("atr_14", market_price * 0.01))
            except Exception:
                atr0 = market_price * 0.01
        width = max(atr0, market_price * 0.001) * np.sqrt(max(1, interim_bars)) * (0.65 if is_lateral else 0.85)
        recent = closed.tail(min(24, len(closed)))
        recent_low = float(recent["low"].quantile(0.20)) if not recent.empty else market_price - width
        recent_high = float(recent["high"].quantile(0.80)) if not recent.empty else market_price + width
        interim_low = max(min(market_price, recent_low), market_price - width)
        interim_high = min(max(market_price, recent_high), market_price + width)
        if interim_high <= interim_low:
            interim_low, interim_high = market_price - width, market_price + width
        interim_source = "estructura reciente + ATR"

    interim = {
        "label": interim_label,
        "is_lateral": bool(is_lateral),
        "until_bars": int(interim_bars),
        "range_low": float(max(interim_low, 1e-12)),
        "range_high": float(max(interim_high, 1e-12)),
        "source": interim_source,
    }
'''
if old not in s:
    raise RuntimeError('No se encontró directional_forecasts actual')
s = s.replace(old, new, 1)

# Add interim to return payload.
old = '''        "directional_forecasts": directional_forecasts,
        "primary_forecast": primary_forecast,
        "max_horizon": 8,
'''
new = '''        "directional_forecasts": directional_forecasts,
        "primary_forecast": primary_forecast,
        "interim": interim,
        "max_horizon": 8,
'''
if old not in s:
    raise RuntimeError('No se encontró return payload de trend_transition_forecast')
s = s.replace(old, new, 1)

# 4) Put forecast points at their projected PRICE, not artificial top/bottom
# positions. The dot now conveys both WHEN and HOW FAR.
old = '''    marker_end_times = []
    for direction, color, y_pos, text_pos in (
        ("SUBIDA", "#2ecc71", price_low - 0.07 * price_span, "bottom center"),
        ("BAJADA", "#ff5c5c", price_high + 0.07 * price_span, "top center"),
    ):
        fc = dirs.get(direction)
        if not fc or not fc.get("has_window"):
            continue
        start_bars = max(1, int(fc.get("start_bars", 1)))
        end_bars = max(start_bars, int(fc.get("end_bars", start_bars)))
        marker_x = _marker_time(start_bars)
        marker_end_times.append(_marker_time(end_bars))
        window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[y_pos], mode="markers+text",
            marker={"size": 18, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[f"{label} · {window}"], textposition=text_pos,
            textfont={"color": color, "size": 11},
            hovertemplate=(f"{label}<br>Inicio estimado de ventana: %{{x}}"
                           f"<br>{window}<br>Confianza IA: {float(fc.get('probability',0.5))*100:.0f}%<extra></extra>"),
            name=f"{label} probable",
            showlegend=False,
            cliponaxis=False,
        ))
'''
new = '''    marker_end_times = []
    for direction, color, text_pos in (
        ("SUBIDA", "#2ecc71", "top center"),
        ("BAJADA", "#ff5c5c", "bottom center"),
    ):
        fc = dirs.get(direction)
        if not fc or not fc.get("has_window"):
            continue
        start_bars = max(1, int(fc.get("start_bars", 1)))
        end_bars = max(start_bars, int(fc.get("end_bars", start_bars)))
        marker_x = _marker_time(start_bars)
        marker_end_times.append(_marker_time(end_bars))
        window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
        label = "SUBE" if direction == "SUBIDA" else "BAJA"
        y_pos = float(fc.get("target_price", last_price))
        target_txt = _market_price_text(y_pos, last_price)
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[y_pos], mode="markers+text",
            marker={"size": 18, "color": color, "line": {"color": "#ffffff", "width": 2}},
            text=[f"{label} · {window} · {target_txt}"], textposition=text_pos,
            textfont={"color": color, "size": 11},
            hovertemplate=(f"{label}<br>Tiempo estimado: {window}"
                           f"<br>Objetivo aproximado: {target_txt}"
                           f"<br>Confianza IA: {float(fc.get('probability',0.5))*100:.0f}%<extra></extra>"),
            name=f"{label} probable",
            showlegend=False,
            cliponaxis=False,
        ))
'''
if old not in s:
    raise RuntimeError('No se encontró bloque de puntos de timing')
s = s.replace(old, new, 1)

# 5) Simple UI: one interim line plus up/down timing and approximate targets.
old = '''        st.markdown(f"## 🟢 SUBE EN: {_compact_timing(up_fc)}")
        st.markdown(f"## 🔴 BAJA EN: {_compact_timing(down_fc)}")
'''
new = '''        interim = trend_info.get("interim") or {}
        spot_ref = float(closed_simple["close"].iloc[-1])
        interim_label = str(interim.get("label", "LATERALIZA"))
        if interim.get("is_lateral"):
            i_low = _market_price_text(interim.get("range_low"), spot_ref)
            i_high = _market_price_text(interim.get("range_high"), spot_ref)
            until_txt = _duration_text(timeframe, int(interim.get("until_bars", 1)))
            st.markdown(f"## 🟡 MIENTRAS: {interim_label} · {i_low}–{i_high} · aprox. {until_txt}")
        else:
            st.markdown(f"## 🟡 MIENTRAS: {interim_label}")

        up_target = _market_price_text(up_fc.get("target_price") if up_fc else None, spot_ref)
        down_target = _market_price_text(down_fc.get("target_price") if down_fc else None, spot_ref)
        st.markdown(f"## 🟢 SUBE EN: {_compact_timing(up_fc)} · HASTA APROX.: {up_target}")
        st.markdown(f"## 🔴 BAJA EN: {_compact_timing(down_fc)} · HASTA APROX.: {down_target}")
'''
if old not in s:
    raise RuntimeError('No se encontró bloque simple SUBE/BAJA')
s = s.replace(old, new, 1)

# Fallback payload must include interim so UI remains safe if detector fails.
old = '''                "primary_forecast": None,
                "max_horizon": 8,
'''
new = '''                "primary_forecast": None,
                "interim": None,
                "max_horizon": 8,
'''
if old in s:
    s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')
print('Añadidos lateralización, rango intermedio y objetivos de precio para subida/bajada.')
