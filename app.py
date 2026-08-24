import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "engines"))

from feature_engine import build_features, FEATURE_COLUMNS
from labeling import triple_barrier_labels
from backtest import compare_models, backtest_model_strategy
from models import fit_model, prepare_training_frame
from calibration import calibrate
from engines.regime_engine import classify_regime
from engines.decision_engine import decide, build_entry_setup, build_risk_plan, confluence_analysis
from engines.pattern_engine import find_similar_cases, ANALOG_FEATURE_COLUMNS
from market_context import market_breadth, fear_greed, derivatives
from projections import volatility_projection
from simple_forecast import build_simple_forecast
from timing_forecast import TIMING_SPECS, scenario_from_probs, reliability_level, infer_transition, transition_text, local_dt_text, first_scenario_window
from candle_forecast import STANDARD_TIMEFRAMES, candle_time_text, candle_window_text, future_time, infer_candle_onset, best_candle_candidate
from volume_radar import analyze_volume, direction_label, volume_alignment
from timeframe_data import aggregate_market_bars

st.set_page_config(
    page_title="AI Crypto Market Brain Pro",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

SYMBOLS = {
    "BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT",
    "XRP/USDT": "XRPUSDT", "BNB/USDT": "BNBUSDT", "ADA/USDT": "ADAUSDT",
    "DOGE/USDT": "DOGEUSDT", "AVAX/USDT": "AVAXUSDT", "LINK/USDT": "LINKUSDT",
}
INTERVALS = {k: v.fetch_interval for k, v in STANDARD_TIMEFRAMES.items()}
INTERVAL_MINUTES = {k: v.approx_minutes for k, v in STANDARD_TIMEFRAMES.items()}
HORIZONS = {"Corto": 4, "Medio": 12, "Largo": 24}
ALL_CLASSES = [-1, 0, 1]

DEFAULT_HISTORY = {k: v.default_history for k, v in STANDARD_TIMEFRAMES.items()}
VISIBLE_OPTIONS = [100, 200, 350, 500, 800]
CHART_TZ = ZoneInfo("America/Hermosillo")



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

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#080b0f;color:#e8edf2}
[data-testid="stHeader"]{background:#080b0f}
[data-testid="stSidebar"]{background:#0d1117;border-right:1px solid #20262d}
.block-container{padding-top:.55rem;max-width:1900px}
.card{background:#0f141a;border:1px solid #252c34;border-radius:12px;padding:14px 16px;box-shadow:0 1px 0 rgba(255,255,255,.02) inset}
.hero{background:#0f141a;border:1px solid #2a323b;border-radius:14px;padding:16px 18px}
.muted{color:#8b949e;font-size:.78rem}.big{font-size:1.55rem;font-weight:800}.tiny{font-size:.72rem;color:#7d8590}
.buy{color:#2ecc71;font-weight:900}.sell{color:#ff5c5c;font-weight:900}.wait{color:#f2c94c;font-weight:900}
.good{color:#2ecc71}.warn{color:#f2c94c}.bad{color:#ff5c5c}
[data-testid="stMetric"]{background:#0f141a;border:1px solid #222a32;padding:10px;border-radius:10px;min-width:0}
[data-testid="stMetricValue"]{font-size:clamp(1.05rem,2vw,1.65rem)!important;white-space:normal!important;overflow:visible!important;text-overflow:clip!important;line-height:1.12!important}
[data-testid="stMetricLabel"] p{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;line-height:1.15!important}
.stTabs [data-baseweb="tab-list"]{gap:8px}.stTabs [data-baseweb="tab"]{background:#0f141a;border-radius:8px;padding:8px 14px}
hr{border-color:#242b33}
</style>
""", unsafe_allow_html=True)


def horizon_text(timeframe: str, bars: int) -> str:
    return candle_time_text(timeframe, bars)


def bars_for_24h(timeframe: str) -> int:
    return max(1, round(1440 / INTERVAL_MINUTES[timeframe]))


def rr_text(rr: float | None) -> str:
    if rr is None or not np.isfinite(rr):
        return "N/A"
    return f"1:{rr:.2f}"


@st.cache_data(ttl=90, max_entries=64, show_spinner=False)
def fetch_binance_history(symbol: str, interval: str, total: int = 1500) -> pd.DataFrame:
    """Fetch recent public Binance klines with pagination."""
    url = "https://data-api.binance.vision/api/v3/klines"
    chunks = []
    end_time = None
    remaining = int(total)
    while remaining > 0:
        take = min(1000, remaining)
        params = {"symbol": symbol, "interval": interval, "limit": take}
        if end_time is not None:
            params["endTime"] = end_time
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        raw = r.json()
        if not raw:
            break
        chunks.append(raw)
        oldest = int(raw[0][0])
        end_time = oldest - 1
        remaining -= len(raw)
        if len(raw) < take:
            break
    if not chunks:
        raise RuntimeError("Binance no devolvió velas.")
    raw = [row for chunk in reversed(chunks) for row in chunk]
    cols = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(raw, columns=cols).drop_duplicates("open_time").sort_values("open_time")
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    numeric_cols = ["open","high","low","close","volume","quote_volume","trades","taker_base","taker_quote"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    now_ms = pd.Timestamp.now(tz="UTC").value // 1_000_000
    df["is_closed"] = pd.to_numeric(df["close_time"], errors="coerce") <= now_ms
    keep = ["timestamp","open","high","low","close","volume","quote_volume","trades","taker_base","taker_quote","is_closed"]
    # Only OHLCV are mandatory. Optional microstructure fields may contain N/A
    # without discarding an otherwise valid candle.
    return (df[keep]
            .dropna(subset=["timestamp","open","high","low","close","volume"])
            .reset_index(drop=True).tail(total).reset_index(drop=True))



@st.cache_data(ttl=90, max_entries=64, show_spinner=False)
def fetch_timeframe_history(symbol: str, timeframe: str, total: int = 1500) -> pd.DataFrame:
    """Fetch any documented TradingView default time interval.

    Binance-native intervals are requested directly. Missing TradingView
    defaults (2m, 10m, 45m, 3h and multi-month bars, plus second aggregates)
    are constructed from real lower-timeframe Binance candles.
    """
    spec = STANDARD_TIMEFRAMES[timeframe]
    if not spec.is_synthetic:
        return fetch_binance_history(symbol, spec.fetch_interval, total)
    raw_needed = int(total) * int(spec.aggregate_factor) + int(spec.aggregate_factor) * 2
    raw = fetch_binance_history(symbol, spec.fetch_interval, raw_needed)
    out = aggregate_market_bars(raw, int(spec.aggregate_factor), spec.aggregate_unit)
    if out.empty:
        raise RuntimeError(f"No se pudieron construir velas {timeframe}.")
    return out.tail(int(total)).reset_index(drop=True)


@st.cache_data(ttl=3, max_entries=64, show_spinner=False)
def fetch_recent_binance_history(symbol: str, interval: str, total: int = 48) -> pd.DataFrame:
    """Fetch only the newest candles with a very short cache.

    The long historical request stays cached for performance; this tiny tail is
    merged on top so a newly closed 1m candle is detected within a few seconds.
    """
    url = "https://data-api.binance.vision/api/v3/klines"
    take = max(3, min(1000, int(total)))
    r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": take}, timeout=10)
    r.raise_for_status()
    raw = r.json()
    if not raw:
        raise RuntimeError("Binance no devolvió velas recientes.")
    cols = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(raw, columns=cols)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open","high","low","close","volume","quote_volume","trades","taker_base","taker_quote"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    now_ms = pd.Timestamp.now(tz="UTC").value // 1_000_000
    df["is_closed"] = pd.to_numeric(df["close_time"], errors="coerce") <= now_ms
    keep = ["timestamp","open","high","low","close","volume","quote_volume","trades","taker_base","taker_quote","is_closed"]
    return (df[keep]
            .dropna(subset=["timestamp","open","high","low","close","volume"])
            .sort_values("timestamp").reset_index(drop=True))


@st.cache_data(ttl=3, max_entries=64, show_spinner=False)
def fetch_recent_timeframe_history(symbol: str, timeframe: str, total: int = 32) -> pd.DataFrame:
    spec = STANDARD_TIMEFRAMES[timeframe]
    if not spec.is_synthetic:
        return fetch_recent_binance_history(symbol, spec.fetch_interval, total)
    raw_needed = int(total) * int(spec.aggregate_factor) + int(spec.aggregate_factor) * 2
    raw = fetch_recent_binance_history(symbol, spec.fetch_interval, raw_needed)
    out = aggregate_market_bars(raw, int(spec.aggregate_factor), spec.aggregate_unit)
    if out.empty:
        raise RuntimeError(f"No se pudieron construir velas recientes {timeframe}.")
    return out.tail(int(total)).reset_index(drop=True)


def fetch_live_quote(symbol: str) -> dict:
    """Near-real-time public quote. Failure returns an error instead of fake values."""
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    r = requests.get(url, params={"symbol": symbol}, timeout=8)
    r.raise_for_status()
    d = r.json()
    return {
        "price": float(d["lastPrice"]),
        "change_pct": float(d["priceChangePercent"]),
        "high": float(d["highPrice"]),
        "low": float(d["lowPrice"]),
        "quote_volume": float(d["quoteVolume"]),
        "time": datetime.now(timezone.utc),
    }


@st.cache_data(ttl=60, show_spinner=False)
def cached_breadth():
    return market_breadth()


@st.cache_data(ttl=300, show_spinner=False)
def cached_fear_greed():
    return fear_greed()


@st.cache_data(ttl=60, show_spinner=False)
def cached_derivatives(symbol):
    return derivatives(symbol)


def _align_one(proba, classes):
    pmap = {int(c): float(p) for c, p in zip(classes, proba)}
    arr = np.array([pmap.get(c, 0.0) for c in ALL_CLASSES], dtype=float)
    return arr / arr.sum() if arr.sum() > 0 else np.array([1/3, 1/3, 1/3])


def _class_counts_ok(y, minimum: int) -> bool:
    counts = pd.Series(y).value_counts().reindex(ALL_CLASSES, fill_value=0)
    return bool((counts >= minimum).all())


@st.cache_data(ttl=900, max_entries=48, show_spinner=False)
def model_signal(df: pd.DataFrame, horizon: int = 12, deep: bool = False):
    """Purged walk-forward comparison + disjoint holdout calibration + weighted ensemble."""
    features = build_features(df)
    labels = triple_barrier_labels(features, horizon=horizon, k=1.5)
    valid = labels.dropna().shape[0]
    if valid < 350:
        return {"ok": False, "reason": f"Histórico útil insuficiente ({valid} etiquetas)."}

    model_names = (["logistic_regression", "random_forest", "gradient_boosting", "extra_trees", "hist_gradient_boosting"]
                   if deep else ["logistic_regression", "random_forest", "hist_gradient_boosting"])
    n_folds = 5 if deep else 4
    comparison = compare_models(
        features, labels, FEATURE_COLUMNS, model_names,
        n_folds=n_folds, min_train_size=max(180, min(450, valid // 2)), purge_bars=horizon,
    )
    usable = comparison.dropna(subset=["brier_score_mean", "f1_macro_mean", "balanced_accuracy_mean", "brier_skill_mean"]).copy()
    if usable.empty:
        errors = comparison["error"].dropna().tolist() if "error" in comparison else []
        reason = errors[0] if errors else "No hubo folds walk-forward válidos."
        return {"ok": False, "reason": reason, "comparison": comparison}

    usable["score"] = (
        usable["brier_score_mean"]
        - 0.10 * usable["f1_macro_mean"]
        - 0.06 * usable["balanced_accuracy_mean"]
        - 0.05 * usable["brier_skill_mean"].clip(lower=-1, upper=1)
    )
    ranked = usable.sort_values("score").reset_index(drop=True)
    best_row = ranked.iloc[0]
    best = best_row["model"]

    # Conservative gate: the mean alone is not enough. We also require
    # reasonable stability across time folds so one lucky period cannot make a
    # weak model look dependable.
    bal_std = float(best_row.get("balanced_accuracy_std", np.nan))
    f1_std = float(best_row.get("f1_macro_std", np.nan))
    skill_std = float(best_row.get("brier_skill_std", np.nan))
    skill_min = float(best_row.get("brier_skill_min", np.nan))
    stability_ok = bool(
        np.isfinite(bal_std) and np.isfinite(f1_std) and np.isfinite(skill_std)
        and bal_std <= 0.11 and f1_std <= 0.11 and skill_std <= 0.18
        and (not np.isfinite(skill_min) or skill_min > -0.20)
    )
    model_validated = bool(
        best_row["n_folds"] >= (4 if deep else 3)
        and best_row["balanced_accuracy_mean"] >= 0.38
        and best_row["f1_macro_mean"] >= 0.34
        and best_row["brier_skill_mean"] >= 0.02
        and stability_ok
        and best_row.get("calibrated_folds", 0) >= 2
    )
    if (best_row["brier_skill_mean"] >= 0.08 and best_row["balanced_accuracy_mean"] >= 0.43
            and best_row["f1_macro_mean"] >= 0.40 and bal_std <= 0.08 and skill_std <= 0.12):
        quality_label = "Sólido OOS"
    elif model_validated:
        quality_label = "Aceptable OOS"
    else:
        quality_label = "Débil / sin ventaja OOS"

    X, y = prepare_training_frame(features, labels, FEATURE_COLUMNS)
    split = max(180, int(len(X) * .84))
    if len(X) - split < 45:
        split = max(140, len(X) - 45)
    fit_X, fit_y = X.iloc[:split], y.iloc[:split]
    cal_X, cal_y = X.iloc[split:], y.iloc[split:]
    if cal_X.empty:
        return {"ok": False, "reason": "No quedó ventana temporal de calibración."}

    fit_keep = np.asarray(fit_X.index, dtype=int) + int(horizon) < int(cal_X.index.min())
    fit_X = fit_X.iloc[np.flatnonzero(fit_keep)]
    fit_y = fit_y.iloc[np.flatnonzero(fit_keep)]
    if not _class_counts_ok(fit_y, 12):
        return {"ok": False, "reason": "El histórico reciente no tiene suficientes ejemplos de subida/lateral/bajada para un ajuste robusto."}

    last = features.iloc[[-1]][FEATURE_COLUMNS]
    ensemble = []
    ensemble_models = []
    individual_probabilities = []
    model_errors = []
    can_calibrate = _class_counts_ok(cal_y, 5)

    # Use all three lightweight candidates in normal mode. Earlier versions
    # said "3-model ensemble" in the UI but actually averaged only two.
    ensemble_n = 3
    for _, mr in ranked.head(ensemble_n).iterrows():
        name = mr["model"]
        try:
            trained = fit_model(name, fit_X, fit_y)
            cal_ok = False
            if can_calibrate:
                try:
                    use = calibrate(trained.model, cal_X, cal_y, method="sigmoid")
                    p = _align_one(use.predict_proba(last)[0], list(use.classes_))
                    cal_ok = True
                except Exception as e:
                    model_errors.append(f"{name}: calibración {type(e).__name__}")
                    p = _align_one(trained.model.predict_proba(last)[0], list(trained.classes_))
            else:
                p = _align_one(trained.model.predict_proba(last)[0], list(trained.classes_))
            skill = max(0.0, float(mr["brier_skill_mean"]))
            quality = (0.05 + skill) * max(.15, float(mr["f1_macro_mean"])) / max(.08, float(mr["brier_score_mean"]))
            ensemble.append((quality, p, cal_ok))
            ensemble_models.append(name)
            individual_probabilities.append({
                "model": name, "pdown": float(p[0]), "pflat": float(p[1]), "pup": float(p[2]),
                "calibrated": bool(cal_ok),
            })
        except Exception as e:
            model_errors.append(f"{name}: {type(e).__name__}: {e}")

    if not ensemble:
        return {"ok": False, "reason": "Ningún modelo final pudo ajustarse.", "comparison": comparison}

    sw = sum(x[0] for x in ensemble)
    probs = sum(w * p for w, p, _ in ensemble) / sw
    pdown, pflat, pup = map(float, probs)
    calibrated_all = all(x[2] for x in ensemble)
    dominant_idx = int(np.argmax(probs))
    model_votes = [int(np.argmax([m["pdown"], m["pflat"], m["pup"]])) for m in individual_probabilities]
    model_agreement = float(np.mean([v == dominant_idx for v in model_votes])) if model_votes else 0.0
    dom_values = np.array([[m["pdown"], m["pflat"], m["pup"]][dominant_idx] for m in individual_probabilities], dtype=float)
    probability_dispersion = float(np.std(dom_values)) if len(dom_values) > 1 else 0.0
    threshold = .58 if calibrated_all else .64
    decision = decide(pup, pflat, pdown, conf_threshold=threshold)
    if not model_validated:
        decision = decide(pup, pflat, pdown, conf_threshold=1.01)

    price = float(df.close.iloc[-1])
    atr = float(features.atr_14.iloc[-1])
    regime = classify_regime(features.iloc[-1])
    setup = build_entry_setup(price, decision.direction, atr) if decision.direction else None
    risk_plan = build_risk_plan(df, price, decision.direction, atr) if decision.direction else None
    confluence = confluence_analysis(features.iloc[-1], decision.direction)

    # Historical analogues are a separate sanity check. They do NOT rewrite the
    # classifier probability; disagreement lowers the user-facing reliability.
    analog = None
    analog_agreement = None
    try:
        atr_pct = float(features["atr_pct"].iloc[-1])
        flat_thr = float(np.clip(0.35 * atr_pct * np.sqrt(max(1, horizon)), 0.004, 0.05))
        fwd = features["close"].shift(-int(horizon)) / features["close"] - 1.0
        analog = find_similar_cases(features, ANALOG_FEATURE_COLUMNS, fwd, int(horizon), k=40, flat_threshold=flat_thr)
        if analog is not None:
            model_dom = ["BAJADA", "LATERAL", "SUBIDA"][dominant_idx]
            analog_agreement = bool(analog.dominant == model_dom)
    except Exception as e:
        model_errors.append(f"análogos: {type(e).__name__}")

    return {
        "ok": True, "features": features, "comparison": comparison,
        "model": "ensemble: " + ", ".join(ensemble_models), "best_model": best,
        "calibrated": calibrated_all, "price": price, "atr": atr,
        "pup": pup, "pflat": pflat, "pdown": pdown, "decision": decision,
        "regime": regime, "setup": setup, "risk_plan": risk_plan, "horizon": horizon,
        "confluence": confluence, "ensemble_models": ensemble_models, "model_errors": model_errors,
        "individual_probabilities": individual_probabilities, "model_agreement": model_agreement,
        "probability_dispersion": probability_dispersion, "analog": analog, "analog_agreement": analog_agreement,
        "model_validated": model_validated, "quality_label": quality_label, "stability_ok": stability_ok,
        "best_balanced_accuracy": float(best_row["balanced_accuracy_mean"]),
        "best_balanced_accuracy_std": bal_std,
        "best_brier_skill": float(best_row["brier_skill_mean"]),
        "best_brier_skill_std": skill_std,
        "best_f1": float(best_row["f1_macro_mean"]), "best_f1_std": f1_std, "deep": deep,
    }


def model_label(res) -> str:
    if not res.get("ok"):
        return "N/A"
    d = res["decision"]
    if d.signal == "NO_OPERAR":
        return "NO OPERAR"
    if d.signal == "ESPERAR":
        return "ESPERAR"
    return "LONG" if d.direction == "SUBIDA" else "SHORT"


def practical_label(res) -> str:
    """User-facing gate. It never changes probabilities, only whether a setup is considered actionable."""
    if not res.get("ok") or not res.get("model_validated"):
        return "NO OPERAR"
    base = model_label(res)
    if base not in ("LONG", "SHORT"):
        return base
    cf = float(res.get("confluence", {}).get("score", 0))
    rp = res.get("risk_plan")
    rr = rp.recommended.rr_to_tp1 if rp else np.nan
    if cf < 60:
        return "ESPERAR"
    if not np.isfinite(rr) or rr < 1.5:
        return "ESPERAR"
    if float(res.get("model_agreement", 0.0)) < (2/3):
        return "ESPERAR"
    if res.get("analog_agreement") is False:
        return "ESPERAR"
    return base


def simple_explanation(signal) -> str:
    if not signal.get("ok"):
        return "No hay suficientes datos confiables para evaluar este activo ahora."
    if not signal.get("model_validated"):
        return "NO OPERAR: el modelo todavía no demuestra una ventaja suficiente fuera de muestra."
    base = model_label(signal)
    practical = practical_label(signal)
    if base == "NO OPERAR":
        return "NO OPERAR: ninguna dirección supera el umbral de confianza exigido."
    if base == "ESPERAR":
        return "ESPERAR: el escenario lateral domina; no hay dirección clara."
    cf = float(signal.get("confluence", {}).get("score", 0))
    rp = signal.get("risk_plan")
    rr = rp.recommended.rr_to_tp1 if rp else np.nan
    if practical == "ESPERAR" and cf < 60:
        return f"ESPERAR: el modelo apunta {base}, pero la confirmación técnica es baja ({cf:.0f}/100)."
    if practical == "ESPERAR" and (not np.isfinite(rr) or rr < 1.5):
        return f"ESPERAR: el modelo apunta {base}, pero la relación riesgo/beneficio todavía no es atractiva."
    if practical == "ESPERAR" and float(signal.get("model_agreement", 0.0)) < (2/3):
        return f"ESPERAR: los modelos no coinciden suficientemente entre sí sobre {base}."
    if practical == "ESPERAR" and signal.get("analog_agreement") is False:
        return f"ESPERAR: el modelo apunta {base}, pero los casos históricos parecidos no confirman esa dirección."
    return f"{base}: modelo validado, confluencia {cf:.0f}/100 y R:R {rr_text(rr)}."


def technical_snapshot(row) -> dict:
    trend_up = bool(row.get("dist_ema_200", 0) > 0 and row.get("ema200_slope_20", 0) >= 0)
    trend_down = bool(row.get("dist_ema_200", 0) < 0 and row.get("ema200_slope_20", 0) < 0)
    if trend_up:
        trend = "Alcista"
    elif trend_down:
        trend = "Bajista"
    else:
        trend = "Mixta"

    momentum_score = sum([
        row.get("rsi_14", 50) >= 50,
        row.get("macd_hist_pct", 0) > 0,
        row.get("di_spread", 0) > 0,
    ])
    momentum = "Alcista" if momentum_score >= 2 else "Bajista"
    volume = "Confirma" if row.get("vol_rel_20", 1) >= 1.10 else "Normal/bajo"
    strength = "Fuerte" if row.get("adx_14", 0) >= 25 else "Débil/lateral"
    return {"trend": trend, "momentum": momentum, "volume": volume, "strength": strength}


def volume_icon(direction: str) -> str:
    return "🟢" if direction == "COMPRADOR" else "🔴" if direction == "VENDEDOR" else "🟡"


def bias_icon(label: str) -> str:
    return "🟢" if label == "LONG" else "🔴" if label == "SHORT" else "🟡"


def projection_band(signal, horizon: int):
    if not signal.get("ok"):
        return None
    price = float(signal["price"])
    features = signal["features"]
    sigma = float(features.realized_vol_30.iloc[-1]) if pd.notna(features.realized_vol_30.iloc[-1]) else None
    atr = float(signal.get("atr")) if signal.get("atr") is not None else None
    band = volatility_projection(price, sigma, atr, horizon, barrier_k=1.5)
    return {
        "low68": np.nan if band.low68 is None else band.low68,
        "high68": np.nan if band.high68 is None else band.high68,
        "barrier_up": np.nan if band.barrier_up is None else band.barrier_up,
        "barrier_down": np.nan if band.barrier_down is None else band.barrier_down,
    }


def scenario_probability(signal, scenario: str) -> float:
    return {"SUBIDA": signal.get("pup", 0.0), "LATERAL": signal.get("pflat", 0.0), "BAJADA": signal.get("pdown", 0.0)}.get(scenario, 0.0)


def zone_text(zone) -> str:
    return f"${zone.low:,.2f} – ${zone.high:,.2f}"


def rr_or_na(value) -> str:
    if value is None or not np.isfinite(value):
        return "N/A"
    return f"1:{value:.2f}"


def quality_plain(signal) -> str:
    if not signal.get("ok"):
        return "No disponible"
    if signal.get("quality_label") == "Sólido OOS":
        return "Alta dentro de lo observado"
    if signal.get("quality_label") == "Aceptable OOS":
        return "Moderada"
    return "Baja: todavía no demuestra ventaja suficiente"


def _scenario_zone(sf, dominant: str):
    return sf.up if dominant == "SUBIDA" else sf.down if dominant == "BAJADA" else sf.flat


def _conservative_zone_with_analogs(signal, sf, dominant: str) -> tuple[float, float, str]:
    """Return a user-facing range and its provenance.

    When historical analogues agree with the ML direction, the range is widened
    to cover both the volatility-based zone and the middle 50% of comparable
    historical outcomes. This avoids fake precision.
    """
    zone = _scenario_zone(sf, dominant)
    low, high = float(zone.low), float(zone.high)
    analog = signal.get("analog")
    if analog is None or signal.get("analog_agreement") is not True:
        return low, high, "volatilidad/ATR"
    aq = (analog.scenario_quantiles or {}).get(dominant)
    if not aq or int(aq.get("n", 0)) < 5:
        return low, high, "volatilidad/ATR"
    price = float(signal["price"])
    a1, a2 = price * (1 + float(aq["q25"])), price * (1 + float(aq["q75"]))
    alow, ahigh = min(a1, a2), max(a1, a2)
    return min(low, alow), max(high, ahigh), "volatilidad + casos históricos parecidos"


@st.cache_data(ttl=900, max_entries=12, show_spinner=False)
def build_timing_rows(symbol_code: str):
    """Run a multi-resolution temporal forecast up to 7 days.

    This is intentionally invoked by a button because it performs several
    independently validated horizon models. All underlying data/model calls are
    cached, so reruns are much faster.
    """
    now_local = datetime.now().astimezone()
    rows = []
    errors = []
    for spec in TIMING_SPECS:
        try:
            raw = fetch_binance_history(symbol_code, spec.interval, spec.history_bars + 2)
            closed = raw[raw.is_closed].drop(columns=["is_closed"]).tail(spec.history_bars).reset_index(drop=True)
            res = model_signal(closed, horizon=spec.horizon_bars, deep=False)
            if not res.get("ok"):
                errors.append(f"{spec.label}: {res.get('reason','sin resultado')}")
                rows.append({
                    "key": spec.key, "label": spec.label, "timeframe": spec.timeframe,
                    "end_hours": spec.end_hours, "end_local": now_local + pd.Timedelta(hours=spec.end_hours),
                    "ok": False, "error": res.get("reason", "sin resultado"),
                })
                continue
            band = projection_band(res, spec.horizon_bars)
            sf = build_simple_forecast(
                closed, float(res["price"]), res["pup"], res["pflat"], res["pdown"],
                band.get("low68") if band else None, band.get("high68") if band else None,
                res.get("atr"), spec.horizon_bars,
            )
            dominant, prob, margin = scenario_from_probs(res["pup"], res["pflat"], res["pdown"])
            zlow, zhigh, zone_source = _conservative_zone_with_analogs(res, sf, dominant)
            rel = reliability_level(res)
            plan = sf.long_plan if dominant == "SUBIDA" else sf.short_plan if dominant == "BAJADA" else None
            rows.append({
                "key": spec.key, "label": spec.label, "timeframe": spec.timeframe,
                "end_hours": spec.end_hours, "end_local": now_local + pd.Timedelta(hours=spec.end_hours),
                "ok": True, "dominant": dominant, "probability": float(prob), "margin": float(margin),
                "reliability": rel, "zone_low": float(zlow), "zone_high": float(zhigh),
                "zone_source": zone_source, "confirmation": float(plan.confirmation) if plan else None,
                "stop": float(plan.stop) if plan else None, "rr": float(plan.risk_reward) if plan and plan.risk_reward is not None else None,
                "model_agreement": float(res.get("model_agreement", 0.0)),
                "analog_agreement": res.get("analog_agreement"), "quality_label": res.get("quality_label", "N/A"),
                "signal": res,
            })
        except Exception as e:
            errors.append(f"{spec.label}: {type(e).__name__}: {e}")
            rows.append({
                "key": spec.key, "label": spec.label, "timeframe": spec.timeframe,
                "end_hours": spec.end_hours, "end_local": now_local + pd.Timedelta(hours=spec.end_hours),
                "ok": False, "error": str(e),
            })
    valid = [r for r in rows if r.get("ok")]
    transition = infer_transition(valid, now_local) if valid else None
    first_windows = {sc: first_scenario_window(valid, sc, now_local) for sc in ("SUBIDA", "LATERAL", "BAJADA")} if valid else {}
    return {"rows": rows, "transition": transition, "first_windows": first_windows, "errors": errors, "generated_at": now_local}



@st.cache_data(ttl=900, max_entries=24, show_spinner=False)
def build_candle_radar(symbol_code: str, timeframe: str, history_bars: int):
    """Estimate the first *window of future candles* where a scenario may dominate.

    Each row is an independently validated cumulative horizon (1, 2, 3, 5...
    candles). The UI converts stable changes between those horizons into a
    practical +N candle window instead of claiming an exact deterministic bar.
    """
    spec = STANDARD_TIMEFRAMES[timeframe]
    if not spec.direct_ai:
        return {"rows": [], "best": None, "windows": {}, "errors": [
            "No se fuerza el radar ML directo en esta temporalidad porque no hay profundidad histórica suficiente para una validación estricta."
        ]}

    raw = fetch_timeframe_history(symbol_code, timeframe, int(history_bars) + 2)
    closed = raw[raw.is_closed].drop(columns=["is_closed"]).tail(int(history_bars)).reset_index(drop=True)
    if closed.empty:
        return {"rows": [], "best": None, "windows": {}, "errors": ["Sin velas cerradas."]}

    # Forecast starts at the close of the last completed candle. Binance's
    # timestamp column is the candle open, so advance one interval.
    last_open = pd.Timestamp(closed.timestamp.iloc[-1])
    if last_open.tzinfo is None:
        last_open = last_open.tz_localize("UTC")
    base_local = (last_open + pd.Timedelta(minutes=spec.approx_minutes)).tz_convert(datetime.now().astimezone().tzinfo).to_pydatetime()

    rows, errors = [], []
    for bars in spec.radar_horizons:
        try:
            res = model_signal(closed, horizon=int(bars), deep=False)
            if not res.get("ok"):
                rows.append({"ok": False, "bars": bars, "error": res.get("reason", "sin resultado")})
                errors.append(f"+{bars}: {res.get('reason','sin resultado')}")
                continue
            band = projection_band(res, int(bars))
            sf = build_simple_forecast(
                closed, float(res["price"]), res["pup"], res["pflat"], res["pdown"],
                band.get("low68") if band else None, band.get("high68") if band else None,
                res.get("atr"), int(bars),
            )
            dom, prob, margin = scenario_from_probs(res["pup"], res["pflat"], res["pdown"])
            zone = sf.up if dom == "SUBIDA" else sf.down if dom == "BAJADA" else sf.flat
            rel = reliability_level(res)
            plan = sf.long_plan if dom == "SUBIDA" else sf.short_plan if dom == "BAJADA" else None
            rows.append({
                "ok": True, "bars": int(bars), "dominant": dom,
                "probability": float(prob), "margin": float(margin), "reliability": rel,
                "pup": float(res["pup"]), "pflat": float(res["pflat"]), "pdown": float(res["pdown"]),
                "zone_low": float(zone.low), "zone_high": float(zone.high),
                "confirmation": float(plan.confirmation) if plan else None,
                "stop": float(plan.stop) if plan else None,
                "rr": float(plan.risk_reward) if plan and plan.risk_reward is not None else None,
                "end_local": future_time(base_local, timeframe, int(bars)),
                "quality_label": res.get("quality_label", "N/A"),
                "model_validated": bool(res.get("model_validated")),
                "model_agreement": float(res.get("model_agreement", 0.0)),
            })
        except Exception as e:
            rows.append({"ok": False, "bars": bars, "error": str(e)})
            errors.append(f"+{bars}: {type(e).__name__}: {e}")

    valid = [r for r in rows if r.get("ok")]
    windows = {sc: infer_candle_onset(valid, sc) for sc in ("SUBIDA", "LATERAL", "BAJADA")}
    best = best_candle_candidate(valid)
    return {"rows": rows, "best": best, "windows": windows, "errors": errors, "base_local": base_local}


def _candle_radar_dataframe(rows, timeframe):
    out = []
    for r in rows:
        if not r.get("ok"):
            out.append({"Vela futura": f"+{r['bars']}", "Tiempo": candle_time_text(timeframe, r['bars']),
                        "Dirección": "N/A", "Probabilidad": "N/A", "Zona estimada": "N/A", "Fiabilidad": "N/A"})
            continue
        icon = "🟢" if r["dominant"] == "SUBIDA" else "🔴" if r["dominant"] == "BAJADA" else "🟡"
        out.append({
            "Vela futura": f"+{r['bars']}", "Tiempo": candle_time_text(timeframe, r["bars"]),
            "Dirección": f"{icon} {direction_label(r['dominant'])}", "Probabilidad": f"{r['probability']*100:.1f}%",
            "Zona estimada": f"${r['zone_low']:,.2f} – ${r['zone_high']:,.2f}",
            "Fiabilidad": r["reliability"].capitalize(),
        })
    return pd.DataFrame(out)


def _timeline_dataframe(rows):
    out = []
    for r in rows:
        if not r.get("ok"):
            out.append({"Periodo": r["label"], "Hasta": local_dt_text(r["end_local"]), "Dirección": "N/A",
                        "Probabilidad": "N/A", "Zona de precio": "N/A", "Fiabilidad": "N/A"})
            continue
        icon = "🟢" if r["dominant"] == "SUBIDA" else "🔴" if r["dominant"] == "BAJADA" else "🟡"
        out.append({
            "Periodo": r["label"], "Hasta": local_dt_text(r["end_local"]),
            "Dirección": f"{icon} {direction_label(r['dominant'])}", "Probabilidad": f"{r['probability']*100:.1f}%",
            "Zona de precio": f"${r['zone_low']:,.2f} – ${r['zone_high']:,.2f}",
            "Fiabilidad": r["reliability"].capitalize(),
        })
    return pd.DataFrame(out)


def price_chart(df, features, symbol, timeframe, signal=None,
                show_ema9=False, show_ema20=True, show_ema50=True, show_ema200=True,
                show_bb=False, show_vwap=False, show_sr=True):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.timestamp, open=df.open, high=df.high, low=df.low, close=df.close,
        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",
    ))
    colors = {9: "#d7aefb", 20: "#ff8a65", 50: "#66d9a3", 200: "#b388ff"}
    for span, enabled in [(9, show_ema9), (20, show_ema20), (50, show_ema50), (200, show_ema200)]:
        if enabled:
            ema = df.close.ewm(span=span, adjust=False).mean()
            fig.add_trace(go.Scatter(x=df.timestamp, y=ema, name=f"EMA {span}", mode="lines", line={"width": 1.35, "color": colors[span]}))
    if show_bb:
        fig.add_trace(go.Scatter(x=df.timestamp, y=features.bb_upper, name="Bollinger superior", line={"width":1,"dash":"dot","color":"#8b949e"}))
        fig.add_trace(go.Scatter(x=df.timestamp, y=features.bb_lower, name="Bollinger inferior", line={"width":1,"dash":"dot","color":"#8b949e"}, fill="tonexty", fillcolor="rgba(139,148,158,.05)"))
    if show_vwap and "vwap_50" in features:
        fig.add_trace(go.Scatter(x=df.timestamp, y=features.vwap_50, name="VWAP 50", line={"width":1.25,"dash":"dash","color":"#4dd0e1"}))
    if show_sr:
        support = float(df.low.tail(min(50, len(df))).min())
        resistance = float(df.high.tail(min(50, len(df))).max())
        fig.add_hline(y=support, line_dash="dot", line_color="#2ecc71", annotation_text="Soporte")
        fig.add_hline(y=resistance, line_dash="dot", line_color="#ffb74d", annotation_text="Resistencia")
    if signal and signal.get("setup"):
        s = signal["setup"]
        fig.add_hrect(y0=s.entry_low, y1=s.entry_high, fillcolor="rgba(80,160,255,.10)", line_width=0, annotation_text="Zona entrada")
        rp = signal.get("risk_plan")
        if rp:
            fig.add_hline(y=rp.recommended.price, line_dash="dash", line_color="#ff5c5c", annotation_text="STOP LOSS")
            for val, name in [(rp.tp1, "TP1"), (rp.tp2, "TP2"), (rp.tp3, "TP3")]:
                fig.add_hline(y=val, line_dash="dot", line_color="#2ecc71", annotation_text=name)
        direction = signal["decision"].direction
        if direction:
            fig.add_trace(go.Scatter(
                x=[df.timestamp.iloc[-1]], y=[df.close.iloc[-1]], mode="markers+text",
                text=["LONG" if direction == "SUBIDA" else "SHORT"], textposition="top center",
                marker={"size": 11, "color": "#2ecc71" if direction == "SUBIDA" else "#ff5c5c"}, name="Señal IA",
            ))

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=570, margin=dict(l=8, r=8, t=42, b=8),
        xaxis_rangeslider_visible=False, hovermode="x unified", dragmode="pan",
        legend=dict(orientation="h", y=1.02),
        uirevision=f"price-{symbol}-{timeframe}",
    )
    fig.update_xaxes(
        gridcolor="#171d24", showspikes=True, spikemode="across", spikesnap="cursor",
        fixedrange=False, showgrid=True,
    )
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig


def volume_chart(df, symbol, timeframe):
    fig = go.Figure(go.Bar(x=df.timestamp, y=df.volume, name="Volumen", marker_color="#607d8b", opacity=.65))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=190, margin=dict(l=8, r=8, t=28, b=8), showlegend=False,
        dragmode="pan", uirevision=f"volume-{symbol}-{timeframe}",
    )
    fig.update_xaxes(gridcolor="#171d24", fixedrange=False)
    fig.update_yaxes(gridcolor="#171d24", side="right")
    return fig


def momentum_chart(df, features, show_rsi=True, show_macd=True):
    fig = go.Figure()
    if show_rsi:
        fig.add_trace(go.Scatter(x=df.timestamp, y=features.rsi_14, name="RSI", line={"width":1.2,"color":"#4dd0e1"}))
        fig.add_hline(y=70, line_dash="dot", line_color="#ff8a65")
        fig.add_hline(y=30, line_dash="dot", line_color="#66d9a3")
    if show_macd:
        # Normalize MACD to percent so it can coexist with RSI more cleanly only when RSI is off.
        if show_rsi:
            pass
        else:
            fig.add_trace(go.Scatter(x=df.timestamp, y=features.macd_hist_pct * 100, name="MACD hist %", line={"width":1.2,"color":"#ffb74d"}))
            fig.add_hline(y=0, line_dash="dot", line_color="#8b949e")
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=230, margin=dict(l=8, r=8, t=28, b=8),
        dragmode="pan", uirevision="momentum-chart",
    )
    fig.update_xaxes(gridcolor="#171d24", fixedrange=False)
    fig.update_yaxes(gridcolor="#171d24", side="right")
    return fig


def plot_config():
    return {
        "displaylogo": False,
        "scrollZoom": True,
        "doubleClick": "reset+autosize",
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "modeBarButtonsToAdd": ["drawline", "drawrect", "eraseshape"],
        "toImageButtonOptions": {"format": "png", "filename": "crypto_chart"},
    }


def render_live_strip(symbol_code: str):
    @st.fragment(run_every="10s")
    def _live():
        try:
            q = fetch_live_quote(symbol_code)
            c1, c2, c3 = st.columns(3)
            c1.metric("🟢 LIVE · Precio", f"${q['price']:,.2f}")
            c2.metric("Cambio 24 h", f"{q['change_pct']:+.2f}%")
            c3.metric("Actualizado", q["time"].strftime("%H:%M:%S UTC"))
            c4, c5 = st.columns(2)
            c4.metric("Máximo 24 h", f"${q['high']:,.2f}")
            c5.metric("Mínimo 24 h", f"${q['low']:,.2f}")
        except Exception:
            st.warning("Precio LIVE temporalmente no disponible. El análisis con velas cerradas sigue funcionando.")
    _live()



def _strict_simple_state(signal):
    """Only color the chart when several independent reliability checks pass."""
    if not signal.get("ok") or not signal.get("model_validated"):
        return None
    rel = reliability_level(signal)
    if rel not in ("MEDIA", "ALTA"):
        return None
    dom, prob, margin = scenario_from_probs(signal["pup"], signal["pflat"], signal["pdown"])
    if prob < 0.45 or margin < 0.06:
        return None
    if float(signal.get("model_agreement", 0.0)) < (2 / 3):
        return None
    if signal.get("analog_agreement") is False:
        return None
    return {
        "scenario": dom,
        "probability": float(prob),
        "reliability": rel,
        "source": "modelos + validación histórica + patrones",
    }



@st.cache_data(ttl=1800, max_entries=96, show_spinner=False)
def cached_simple_signal(symbol_code: str, timeframe: str, horizon: int, history_bars: int, last_closed_key: str):
    """Validated signal cache keyed by market/timeframe/horizon/last closed candle."""
    raw = fetch_timeframe_history(symbol_code, timeframe, int(history_bars) + 2)
    closed = (raw[raw.is_closed]
              .drop(columns=["is_closed"])
              .tail(int(history_bars))
              .reset_index(drop=True))
    if closed.empty:
        return {"ok": False, "reason": "Sin velas cerradas."}
    # last_closed_key deliberately participates in the Streamlit cache key.
    # It is not otherwise needed because `closed` already ends at that candle.
    _ = last_closed_key
    return model_signal(closed, horizon=int(horizon), deep=False)


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
    min_rows = 60 if timeframe == "1M" else 90 if timeframe == "1W" else 180
    if closed is None or closed.empty or len(closed) < min_rows:
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
    flat_floor = {
        "1m": 0.0004, "2m": 0.0005, "3m": 0.0006, "5m": 0.0008,
        "10m": 0.0010, "15m": 0.0012, "30m": 0.0015, "45m": 0.0018,
        "1h": 0.0020, "2h": 0.0025, "3h": 0.0030, "4h": 0.0035,
        "1D": 0.0050, "1W": 0.0120, "1M": 0.0250,
    }.get(timeframe, 0.0020)
    flat_ceiling = max(flat_floor * 8.0, 0.012)
    flat_thr = float(np.clip(
        0.35 * max(atr_pct, 1e-6) * np.sqrt(max(1, int(horizon))),
        flat_floor, flat_ceiling,
    ))
    fwd = features["close"].shift(-int(horizon)) / features["close"] - 1.0
    analog = find_similar_cases(features, ANALOG_FEATURE_COLUMNS, fwd, int(horizon), k=50, flat_threshold=flat_thr)
    if analog is None or analog.n_cases < 12:
        analog_probs = np.array([1/3, 1/3, 1/3], dtype=float)
        analog_dom = None
        analog_cases = 0
    else:
        analog_probs = np.array([analog.up_pct, analog.flat_pct, analog.down_pct], dtype=float) / 100.0
        analog_dom = analog.dominant
        analog_cases = int(analog.n_cases)

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

    probs = score / max(weights, 1e-9)
    probs = probs / probs.sum()

    # Main SIMPLE signal answers only one question: is price more likely to go UP or DOWN?
    # LATERAL/SIN DIRECCION is reserved for an almost exact directional tie.
    up_raw = float(probs[idx["SUBIDA"]])
    down_raw = float(probs[idx["BAJADA"]])
    directional_total = up_raw + down_raw
    if directional_total <= 1e-9:
        up_cond = down_cond = 0.5
    else:
        up_cond = up_raw / directional_total
        down_cond = down_raw / directional_total

    # Tiny dead-zone only. The user should normally see green or red, not yellow.
    tie_band = 0.02  # 48%-52% = truly undecided
    if abs(up_cond - down_cond) <= tie_band:
        dom = "LATERAL"
        prob = float(max(up_cond, down_cond))
        margin = float(abs(up_cond - down_cond))
    elif up_cond > down_cond:
        dom = "SUBIDA"
        prob = float(up_cond)
        margin = float(up_cond - down_cond)
    else:
        dom = "BAJADA"
        prob = float(down_cond)
        margin = float(down_cond - up_cond)

    confirmations = sum([
        analog_dom == dom,
        tech == dom,
        vol_dir == dom,
        impulse == dom,
        cycle_context == dom if cycle_context else False,
    ])

    # SIMPLE mode must always answer the user's main question: what direction is
    # currently most probable in the selected timeframe?  We therefore expose
    # the dominant class even when evidence is weak, but we NEVER hide the
    # uncertainty: strength is labelled BAJA / MEDIA / ALTA.
    high = dom in ("SUBIDA", "BAJADA") and prob >= 0.62 and margin >= 0.24 and confirmations >= 3
    medium = dom in ("SUBIDA", "BAJADA") and prob >= 0.55 and margin >= 0.10 and confirmations >= 2
    state = {
        "scenario": dom,
        "probability": prob,
        "reliability": "ALTA" if high else "MEDIA" if medium else "BAJA",
        "source": "patrones históricos + tendencia + momentum + volumen + impulso inmediato + ciclo",
    }

    return {
        "ok": True,
        "state": state,
        "pup": float(probs[0]), "pflat": float(probs[1]), "pdown": float(probs[2]),
        "price": price, "atr": atr, "sigma": sigma,
        "analog_cases": int(analog_cases), "technical": tech,
        "volume_direction": vol_dir, "impulse": impulse, "cycle": cycle_context,
    }




def _duration_text(timeframe: str, bars: int) -> str:
    """Human readable duration for a number of bars in the selected timeframe."""
    bars = max(1, int(bars))
    if timeframe == "1M":
        return f"{bars} mes" if bars == 1 else f"{bars} meses"
    if timeframe == "1W":
        return f"{bars} semana" if bars == 1 else f"{bars} semanas"
    if timeframe == "1D":
        return f"{bars} día" if bars == 1 else f"{bars} días"
    minutes = float(INTERVAL_MINUTES.get(timeframe, 1)) * bars
    if minutes < 60:
        return f"{int(round(minutes))} min"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.0f} h" if abs(hours - round(hours)) < 1e-9 else f"{hours:.1f} h"
    days = hours / 24.0
    return f"{days:.0f} días" if abs(days - round(days)) < 1e-9 else f"{days:.1f} días"


def current_trend_state(closed: pd.DataFrame, timeframe: str) -> dict:
    """Describe the trend that is already present, without making a future claim."""
    if closed is None or closed.empty or len(closed) < 35:
        return {"scenario": "LATERAL", "strength": 0.0, "score": 0}
    features = build_features(closed)
    row = features.iloc[-1]
    c = closed["close"].astype(float)
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    last = float(c.iloc[-1])
    ret1 = float(c.iloc[-1] / c.iloc[-2] - 1.0) if len(c) >= 2 else 0.0
    ret3 = float(c.iloc[-1] / c.iloc[-4] - 1.0) if len(c) >= 4 else ret1
    slope20 = float(ema20.iloc[-1] / ema20.iloc[-5] - 1.0) if len(ema20) >= 5 else 0.0

    score = 0
    score += 1 if last >= float(ema20.iloc[-1]) else -1
    score += 1 if float(ema20.iloc[-1]) >= float(ema50.iloc[-1]) else -1
    score += 1 if slope20 >= 0 else -1
    score += 1 if float(row.get("macd_hist_pct", 0.0)) >= 0 else -1
    score += 1 if float(row.get("di_spread", 0.0)) >= 0 else -1
    score += 1 if ret3 >= 0 else -1

    if timeframe in ("1m", "2m", "3m", "5m"):
        score += 1 if ret1 >= 0 else -1
        score += 1 if ret3 >= 0 else -1
        max_score = 8
    else:
        max_score = 6

    adx = float(row.get("adx_14", 0.0))
    try:
        recent = closed.tail(8)
        recent_range = float((recent["high"].max() - recent["low"].min()) / max(last, 1e-12))
        atr_pct = float(row.get("atr_pct", 0.0))
        compressed = recent_range <= max(atr_pct * 1.6, 0.0008)
    except Exception:
        compressed = False

    if abs(score) <= 1 and (adx < 18 or compressed):
        scenario = "LATERAL"
    elif score > 0:
        scenario = "SUBIDA"
    else:
        scenario = "BAJADA"
    return {
        "scenario": scenario,
        "strength": float(min(1.0, abs(score) / max(max_score, 1))),
        "score": int(score),
    }


LEADING_TIMEFRAMES = {
    "1m": [],
    "2m": ["1m"],
    "3m": ["1m", "2m"],
    "5m": ["1m", "3m"],
    "10m": ["2m", "5m"],
    "15m": ["3m", "5m"],
    "30m": ["5m", "15m"],
    "45m": ["15m", "30m"],
    "1h": ["15m", "30m"],
    "2h": ["30m", "1h"],
    "3h": ["30m", "1h"],
    "4h": ["1h", "2h"],
    "1D": ["1h", "4h"],
    "1W": ["4h", "1D"],
    "1M": ["1D", "1W"],
}


@st.cache_data(ttl=45, max_entries=128, show_spinner=False)
def leading_sensor_state(symbol_code: str, sensor_tf: str, cycle_context: str | None) -> dict | None:
    """Use a lower timeframe as an early sensor without rerunning the heavy ML stack."""
    try:
        hist = min(int(DEFAULT_HISTORY.get(sensor_tf, 320)), 320)
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
        }
    except Exception:
        return None


def _precursor_strength(closed: pd.DataFrame, target: str) -> float:
    """Score changes that tend to occur before a full trend flip becomes visible."""
    try:
        f = build_features(closed)
        if len(f) < 6:
            return 0.5
        now = f.iloc[-1]
        prev = f.iloc[-4]
        c = closed["close"].astype(float)
        ret_now = float(c.iloc[-1] / c.iloc[-3] - 1.0) if len(c) >= 3 else 0.0
        ret_prev = float(c.iloc[-3] / c.iloc[-6] - 1.0) if len(c) >= 6 else 0.0

        macd_delta = float(now.get("macd_hist_pct", 0.0)) - float(prev.get("macd_hist_pct", 0.0))
        di_delta = float(now.get("di_spread", 0.0)) - float(prev.get("di_spread", 0.0))
        rsi_delta = float(now.get("rsi_14", 50.0)) - float(prev.get("rsi_14", 50.0))
        ret_delta = ret_now - ret_prev

        checks = []
        if target == "SUBIDA":
            checks.extend([macd_delta > 0, di_delta > 0, rsi_delta > 0, ret_delta > 0])
        else:
            checks.extend([macd_delta < 0, di_delta < 0, rsi_delta < 0, ret_delta < 0])

        if "taker_base" in closed.columns and "volume" in closed.columns:
            tail = closed.tail(5)
            volume = tail["volume"].astype(float).replace(0, np.nan)
            ratio = float((tail["taker_base"].astype(float) / volume).replace([np.inf, -np.inf], np.nan).dropna().mean())
            if np.isfinite(ratio):
                checks.append(ratio >= 0.51 if target == "SUBIDA" else ratio <= 0.49)

        if not checks:
            return 0.5
        return float(sum(bool(x) for x in checks) / len(checks))
    except Exception:
        return 0.5


def _direction_support(scenario: str, probability: float, candidate: str) -> float:
    probability = float(np.clip(probability, 0.0, 1.0))
    if scenario == candidate:
        return probability
    if scenario in ("SUBIDA", "BAJADA") and scenario != candidate:
        return 1.0 - probability
    return 0.5


@st.cache_data(ttl=45, max_entries=96, show_spinner=False)
def trend_transition_forecast(symbol_code: str, closed: pd.DataFrame, timeframe: str, cycle_context: str | None) -> dict:
    """Early reversal detector using multi-horizon + lower-timeframe precursor evidence.

    The current trend is descriptive. The reversal layer tries to detect the
    opposite move BEFORE the selected timeframe has fully flipped. It combines:
    historical analogues, trend/momentum, volume, immediate impulse, several
    horizons of the selected timeframe, and lower-timeframe leading sensors.
    """
    current = current_trend_state(closed, timeframe)
    horizons = [1, 2, 4]
    future = []
    raw_results = []
    for h in horizons:
        try:
            res = fast_statistical_signal(closed, timeframe, int(h), cycle_context)
            raw_results.append(res)
            state = res.get("state") if res.get("ok") else None
            if state:
                future.append({
                    "horizon": int(h),
                    "scenario": state.get("scenario", "LATERAL"),
                    "probability": float(state.get("probability", 0.5)),
                    "reliability": state.get("reliability", "BAJA"),
                })
            else:
                future.append({"horizon": int(h), "scenario": "LATERAL", "probability": 0.5, "reliability": "BAJA"})
        except Exception:
            raw_results.append({"ok": False})
            future.append({"horizon": int(h), "scenario": "LATERAL", "probability": 0.5, "reliability": "BAJA"})

    sensors = []
    for tf in LEADING_TIMEFRAMES.get(timeframe, []):
        snap = leading_sensor_state(symbol_code, tf, cycle_context)
        if snap:
            sensors.append(snap)

    current_dir = current.get("scenario", "LATERAL")
    # Score BOTH directions every time. This does not run extra models: it reuses
    # the same multi-horizon, precursor and leading-timeframe evidence already
    # calculated above. The UI can therefore always show a probable UP window
    # and a probable DOWN window without increasing the heavy model load.
    candidates = ["SUBIDA", "BAJADA"]

    candidate_rows = []
    horizon_weights = [0.38, 0.30, 0.20, 0.12]
    for candidate in candidates:
        future_support = sum(
            w * _direction_support(r["scenario"], r["probability"], candidate)
            for w, r in zip(horizon_weights, future)
        )

        sensor_values = []
        sensor_agree = 0
        for snap in sensors:
            tr = snap.get("trend", {})
            fc = snap.get("forecast") or {}
            tr_support = 0.5
            if tr.get("scenario") == candidate:
                tr_support = 0.5 + 0.5 * float(tr.get("strength", 0.0))
                sensor_agree += 1
            elif tr.get("scenario") in ("SUBIDA", "BAJADA"):
                tr_support = 0.5 - 0.35 * float(tr.get("strength", 0.0))
            fc_support = _direction_support(fc.get("scenario", "LATERAL"), fc.get("probability", 0.5), candidate)
            sensor_values.append(0.45 * tr_support + 0.55 * fc_support)
            if fc.get("scenario") == candidate:
                sensor_agree += 1
        sensor_support = float(np.mean(sensor_values)) if sensor_values else 0.5

        precursor = _precursor_strength(closed, candidate)
        weakening = 0.5 if current_dir == "LATERAL" else 1.0 - float(current.get("strength", 0.5))

        immediate = raw_results[0] if raw_results and raw_results[0].get("ok") else {}
        component_dirs = [
            immediate.get("technical"),
            immediate.get("volume_direction"),
            immediate.get("impulse"),
            immediate.get("cycle"),
        ]
        component_support = float(np.mean([
            1.0 if x == candidate else 0.0 if x in ("SUBIDA", "BAJADA") else 0.5
            for x in component_dirs
        ])) if component_dirs else 0.5

        # Lower timeframes and precursor acceleration intentionally have more
        # weight than slow confirmation, because this layer is for EARLY warning.
        evidence = float(
            0.32 * future_support
            + 0.28 * sensor_support
            + 0.24 * precursor
            + 0.10 * component_support
            + 0.06 * weakening
        )

        earliest = None
        for r in future:
            if r["scenario"] == candidate and r["probability"] >= 0.52:
                earliest = int(r["horizon"])
                break
        if earliest is None and sensor_support >= 0.60 and precursor >= 0.60:
            earliest = 1
        if earliest is None:
            earliest = 4 if evidence >= 0.54 else 8

        if earliest <= 1:
            start_bars, end_bars = 1, 2
        elif earliest <= 2:
            start_bars, end_bars = 1, 2
        elif earliest <= 4:
            start_bars, end_bars = 2, 4
        else:
            start_bars, end_bars = 4, 8

        if evidence >= 0.68 and sensor_support >= 0.60 and precursor >= 0.60:
            start_bars, end_bars = 1, min(2, end_bars)

        candidate_rows.append({
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

    # Always expose one forecast per direction. A low-evidence direction is kept
    # visible but explicitly marked as not yet having a reliable time window.
    directional_forecasts = {}
    for row in candidate_rows:
        fc = dict(row)
        ev = float(row.get("evidence", 0.5))
        fc["probability"] = float(np.clip(ev, 0.50, 0.85))
        if ev >= 0.58:
            fc["status"] = "PROBABLE"
            fc["reliability"] = "ALTA" if ev >= 0.68 else "MEDIA"
            fc["has_window"] = True
        elif ev >= 0.52:
            fc["status"] = "EN_FORMACION"
            fc["reliability"] = "TEMPRANA"
            fc["has_window"] = True
        else:
            fc["status"] = "SIN_VENTANA_FIABLE"
            fc["reliability"] = "BAJA"
            fc["has_window"] = False
        directional_forecasts[row["to"]] = fc

    # A trend-transition warning must refer to the direction OPPOSITE the trend
    # currently in force. If the market is lateral, choose the stronger side.
    if current_dir == "SUBIDA":
        reversal_rows = [r for r in candidate_rows if r["to"] == "BAJADA"]
    elif current_dir == "BAJADA":
        reversal_rows = [r for r in candidate_rows if r["to"] == "SUBIDA"]
    else:
        reversal_rows = list(candidate_rows)

    best = max(reversal_rows, key=lambda x: x["evidence"]) if reversal_rows else None
    transition = None
    early_warning = None
    if best:
        if best["evidence"] >= 0.58:
            transition = dict(best)
            transition["probability"] = float(np.clip(best["evidence"], 0.50, 0.85))
            transition["reliability"] = "ALTA" if best["evidence"] >= 0.68 else "MEDIA"
        elif best["evidence"] >= 0.52:
            early_warning = dict(best)
            early_warning["probability"] = float(np.clip(best["evidence"], 0.50, 0.70))
            early_warning["reliability"] = "TEMPRANA"

    return {
        "current": current,
        "transition": transition,
        "early_warning": early_warning,
        "future": future,
        "sensors": sensors,
        "candidate_rows": candidate_rows,
        "directional_forecasts": directional_forecasts,
        "max_horizon": 8,
    }


def transition_window_text(timeframe: str, transition: dict | None, max_horizon: int = 8) -> str:
    if not transition:
        return "sin giro temprano detectado todavía"
    a = _duration_text(timeframe, int(transition["start_bars"]))
    b = _duration_text(timeframe, int(transition["end_bars"]))
    if a == b:
        return f"en {a}"
    return f"entre {a} y {b}"


def trend_chart(df: pd.DataFrame, symbol: str, timeframe: str, trend_info: dict):
    """Clean chart: current trend + early probable next move outside candles."""
    fig = go.Figure()
    plot_df = df.copy()
    plot_ts = pd.to_datetime(plot_df["timestamp"], utc=True)
    plot_df["timestamp"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)
    fig.add_trace(go.Candlestick(
        x=plot_df.timestamp,
        open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,
        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",
    ))

    current = trend_info.get("current", {})
    cur = current.get("scenario", "LATERAL")
    cur_color = "#2ecc71" if cur == "SUBIDA" else "#ff5c5c" if cur == "BAJADA" else "#f2c94c"
    cur_label = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"

    tr = trend_info.get("transition")
    early = trend_info.get("early_warning")
    active = tr or early
    dirs = trend_info.get("directional_forecasts", {})

    def _chart_dir_text(direction):
        fc = dirs.get(direction)
        name = "SUBIDA" if direction == "SUBIDA" else "BAJADA"
        if not fc:
            return f"{name}: SIN CÁLCULO", 0.5
        prob = float(fc.get("probability", 0.5))
        if fc.get("has_window"):
            window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
            return f"{name}: {window} · {prob*100:.0f}%", prob
        return f"{name}: SIN VENTANA FIABLE · {prob*100:.0f}%", prob

    up_text, _ = _chart_dir_text("SUBIDA")
    down_text, _ = _chart_dir_text("BAJADA")

    # Forecast timing points on the chart. They mark the START of the estimated
    # window, not an exact guaranteed turning timestamp. Green = probable start
    # of an upward move; red = probable start of a downward move.
    last_x = pd.Timestamp(plot_df.timestamp.iloc[-1])
    first_x = pd.Timestamp(plot_df.timestamp.iloc[0])
    price_low = float(plot_df["low"].min())
    price_high = float(plot_df["high"].max())
    price_span = max(price_high - price_low, abs(float(plot_df["close"].iloc[-1])) * 0.002, 1e-9)

    def _marker_time(bars: int):
        bars = max(1, int(bars))
        if timeframe == "1M":
            return last_x + pd.DateOffset(months=bars)
        if timeframe == "1W":
            return last_x + pd.Timedelta(weeks=bars)
        if timeframe == "1D":
            return last_x + pd.Timedelta(days=bars)
        minutes = float(INTERVAL_MINUTES.get(timeframe, 1)) * bars
        return last_x + pd.Timedelta(minutes=minutes)

    marker_end_times = []
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

    # Reserve future space so the timing dots are visible to the right of the
    # latest candle instead of overlapping price action.
    try:
        default_future = _marker_time(2)
        right_edge = max(marker_end_times + [default_future])
        historical_span = last_x - first_x
        if historical_span <= pd.Timedelta(0):
            historical_span = pd.Timedelta(minutes=1)
        right_edge = max(right_edge, last_x + historical_span * 0.08)
        fig.update_xaxes(range=[first_x, right_edge])
    except Exception:
        pass

    fig.add_shape(type="circle", xref="paper", yref="paper",
                  x0=1.018, x1=1.058, y0=0.61, y1=0.67,
                  fillcolor=cur_color, line={"color": "#ffffff", "width": 2})
    fig.add_annotation(x=1.074, y=0.64, xref="paper", yref="paper",
                       text=f"<b>TENDENCIA AHORA: {cur_label}</b>", showarrow=False,
                       xanchor="left", font={"color": cur_color, "size": 14})
    fig.add_annotation(x=1.074, y=0.53, xref="paper", yref="paper",
                       text=f"<b>🟢 {up_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#2ecc71", "size": 12})
    fig.add_annotation(x=1.074, y=0.45, xref="paper", yref="paper",
                       text=f"<b>🔴 {down_text}</b>", showarrow=False,
                       xanchor="left", align="left",
                       font={"color": "#ff5c5c", "size": 12})

    if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m"):
        tick_fmt, hover_fmt = "%H:%M", "%d %b %Y · %H:%M"
    elif timeframe in ("30m", "45m", "1h", "2h", "3h", "4h"):
        tick_fmt, hover_fmt = "%d %b\n%H:%M", "%d %b %Y · %H:%M"
    elif timeframe == "1D":
        tick_fmt, hover_fmt = "%d %b", "%d %b %Y"
    elif timeframe == "1W":
        tick_fmt, hover_fmt = "%d %b", "Semana · %d %b %Y"
    else:
        tick_fmt, hover_fmt = "%b %Y", "%B %Y"

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=650, margin=dict(l=8, r=300, t=36, b=48),
        xaxis_rangeslider_visible=False, hovermode="x unified", dragmode="pan",
        showlegend=False, uirevision=f"trend-{symbol}-{timeframe}",
    )
    fig.update_xaxes(
        gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across",
        spikesnap="cursor", tickformat=tick_fmt, hoverformat=hover_fmt,
        showgrid=True, showticklabels=True, ticks="outside", ticklen=5,
        tickcolor="#65707c", tickfont={"size": 11, "color": "#aab4bf"},
        nticks=13, automargin=True,
    )
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig



@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def monthly_consensus_state(symbol_code: str):
    """Monthly state requires daily + weekly validated agreement and monthly cycle alignment."""
    votes = []
    for tf, history, horizon_bars in (("1D", 1000, 30), ("1W", 520, 4)):
        raw = fetch_timeframe_history(symbol_code, tf, history + 2)
        closed = raw[raw.is_closed].drop(columns=["is_closed"]).tail(history).reset_index(drop=True)
        res = model_signal(closed, horizon=horizon_bars, deep=False)
        state = _strict_simple_state(res)
        if state:
            votes.append(state)

    raw_m = fetch_timeframe_history(symbol_code, "1M", DEFAULT_HISTORY["1M"] + 2)
    monthly = raw_m[raw_m.is_closed].drop(columns=["is_closed"]).reset_index(drop=True)
    if len(monthly) < 30 or len(votes) < 2:
        return None

    close = monthly["close"].astype(float)
    ema6 = float(close.ewm(span=6, adjust=False).mean().iloc[-1])
    ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
    ema24 = float(close.ewm(span=24, adjust=False).mean().iloc[-1])
    last = float(close.iloc[-1])
    mom3 = last / float(close.iloc[-4]) - 1.0
    mom6 = last / float(close.iloc[-7]) - 1.0

    monthly_direction = None
    if last > ema6 > ema12 > ema24 and mom3 > 0 and mom6 > 0:
        monthly_direction = "SUBIDA"
    elif last < ema6 < ema12 < ema24 and mom3 < 0 and mom6 < 0:
        monthly_direction = "BAJADA"
    elif abs(mom3) < 0.06 and abs(last / ema12 - 1.0) < 0.06:
        monthly_direction = "LATERAL"

    if votes[0]["scenario"] != votes[1]["scenario"]:
        return None
    dominant = votes[0]["scenario"]
    if monthly_direction != dominant:
        return None

    probability = (votes[0]["probability"] + votes[1]["probability"]) / 2.0
    reliability = "ALTA" if all(v["reliability"] == "ALTA" for v in votes) else "MEDIA"
    return {
        "scenario": dominant,
        "probability": float(probability),
        "reliability": reliability,
        "source": "1D + 1W + ciclo mensual",
    }


def simple_signal_chart(df, symbol, timeframe, horizon, state, simple_forecast=None, target_time=None):
    """Ultra-clean chart: candles + one dominant signal dot + discreet stop."""
    fig = go.Figure()
    plot_df = df.copy()
    plot_ts = pd.to_datetime(plot_df["timestamp"], utc=True)
    plot_df["timestamp"] = plot_ts.dt.tz_convert(CHART_TZ).dt.tz_localize(None)
    fig.add_trace(go.Candlestick(
        x=plot_df.timestamp, open=plot_df.open, high=plot_df.high, low=plot_df.low, close=plot_df.close,
        name="Precio", increasing_line_color="#2ecc71", decreasing_line_color="#ff5c5c",
    ))

    last_x = pd.Timestamp(plot_df.timestamp.iloc[-1])
    first_x = pd.Timestamp(plot_df.timestamp.iloc[0])
    last_y = float(plot_df.close.iloc[-1])
    try:
        if target_time is not None:
            _target = pd.Timestamp(target_time)
            if _target.tzinfo is None:
                _target = _target.tz_localize("UTC")
            dot_x = _target.tz_convert(CHART_TZ).tz_localize(None)
        else:
            dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))
        signal_right_x = pd.Timestamp(future_time(dot_x.to_pydatetime(), timeframe, 3))
    except Exception:
        dot_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, 1))
        signal_right_x = dot_x

    plan = None
    zone = None
    if state:
        scenario = state["scenario"]
        if scenario == "SUBIDA":
            dot_color, short_label = "#2ecc71", "SUBE"
            if simple_forecast is not None:
                zone, plan = simple_forecast.up, simple_forecast.long_plan
        elif scenario == "BAJADA":
            dot_color, short_label = "#ff5c5c", "BAJA"
            if simple_forecast is not None:
                zone, plan = simple_forecast.down, simple_forecast.short_plan
        else:
            dot_color, short_label = "#f2c94c", "SIN DIRECCIÓN"
            if simple_forecast is not None:
                zone = simple_forecast.flat

        probability = float(state.get("probability", 0.0))
        reliability = str(state.get("reliability", "")).capitalize()
        if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "3h", "4h"):
            target_label = dot_x.strftime("%H:%M")
        elif timeframe in ("1D", "1W"):
            target_label = dot_x.strftime("%d %b")
        else:
            target_label = dot_x.strftime("%b %Y")
        label = f"{short_label} · {probability*100:.1f}% · {timeframe}"
        hover = (f"Rumbo más probable: {short_label}"
                 f"<br>Confianza: {probability*100:.1f}%<br>Temporalidad: {timeframe}<br>Evidencia: {reliability}")

        # Very subtle projected zone. It does not cover the candles or compete
        # visually with the main dot.
        if zone is not None:
            try:
                end_x = pd.Timestamp(future_time(last_x.to_pydatetime(), timeframe, int(horizon)))
                fill = ("rgba(46,204,113,.055)" if scenario == "SUBIDA" else
                        "rgba(255,92,92,.055)" if scenario == "BAJADA" else
                        "rgba(242,201,76,.055)")
                fig.add_shape(type="rect", x0=last_x, x1=end_x,
                              y0=float(zone.low), y1=float(zone.high),
                              fillcolor=fill, line_width=0, layer="below")
            except Exception:
                pass
    else:
        dot_color, short_label = "#9aa4ae", "SIN SEÑAL FIABLE"
        label = f"SIN SEÑAL FIABLE · {timeframe}"
        hover = f"Sin señal suficientemente fiable<br>Temporalidad: {timeframe}"

    # MAIN INDICATOR: fixed signal rail OUTSIDE the price plot.
    # It stays visually dominant but can never cover a candle.
    fig.add_shape(
        type="circle", xref="paper", yref="paper",
        x0=1.018, x1=1.060, y0=0.47, y1=0.53,
        fillcolor=dot_color, line={"color": "#ffffff", "width": 2},
        layer="above",
    )
    fig.add_annotation(
        x=1.078, y=0.50, xref="paper", yref="paper", text=f"<b>{label}</b>", showarrow=False,
        xanchor="left", yanchor="middle", align="left",
        font={"color": dot_color, "size": 13},
        bgcolor="rgba(8,11,15,.94)", bordercolor=dot_color, borderwidth=1, borderpad=5,
        hovertext=hover,
    )

    # Discreet stop-loss / technical invalidation only for validated LONG/SHORT.
    if (state and state.get("scenario") in ("SUBIDA", "BAJADA")
            and state.get("reliability") in ("MEDIA", "ALTA") and plan is not None):
        try:
            stop = float(plan.stop)
            fig.add_hline(
                y=stop, line_dash="dot", line_width=1,
                line_color="rgba(255,255,255,.48)",
                annotation_text=f"STOP {stop:,.2f}",
                annotation_position="bottom right",
                annotation_font={"size": 10, "color": "#b8c0c8"},
            )
        except Exception:
            pass

    # Keep only a small amount of price-chart breathing room; the signal itself
    # is outside the plot, so there is no need for a large blank future area.
    try:
        span = last_x - first_x
        if span <= pd.Timedelta(0):
            span = pd.Timedelta(minutes=1)
        min_future = pd.Timedelta(minutes=max(1.0, float(INTERVAL_MINUTES.get(timeframe, 1))) * max(1, int(horizon)))
        right_edge = max(last_x + span * 0.035, last_x + min_future)
        fig.update_xaxes(range=[first_x, right_edge])
    except Exception:
        pass

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#080b0f", plot_bgcolor="#080b0f",
        height=650, margin=dict(l=8, r=220, t=58, b=48),
        xaxis_rangeslider_visible=False, hovermode="x unified", dragmode="pan",
        showlegend=False, uirevision=f"simple-{symbol}-{timeframe}",
    )
    # TradingView-like temporal axis: clock for intraday, date for larger bars.
    if timeframe in ("1m", "2m", "3m", "5m", "10m", "15m"):
        tick_fmt = "%H:%M"
        hover_fmt = "%d %b %Y · %H:%M"
    elif timeframe in ("30m", "45m", "1h", "2h", "3h", "4h"):
        tick_fmt = "%d %b\n%H:%M"
        hover_fmt = "%d %b %Y · %H:%M"
    elif timeframe == "1D":
        tick_fmt = "%d %b"
        hover_fmt = "%d %b %Y"
    elif timeframe == "1W":
        tick_fmt = "%d %b"
        hover_fmt = "Semana · %d %b %Y"
    else:
        tick_fmt = "%b %Y"
        hover_fmt = "%B %Y"

    fig.update_xaxes(
        gridcolor="#171d24", fixedrange=False, showspikes=True, spikemode="across",
        spikesnap="cursor", tickformat=tick_fmt, hoverformat=hover_fmt,
        showgrid=True, showticklabels=True, ticks="outside", ticklen=5,
        tickcolor="#65707c", tickfont={"size": 11, "color": "#aab4bf"},
        nticks=13, automargin=True, ticklabelmode="instant",
    )
    fig.update_yaxes(gridcolor="#171d24", fixedrange=False, side="right")
    return fig

def store_df(key, value):
    st.session_state[key] = value


# ------------------------- Sidebar -------------------------
st.markdown("## AI Crypto Market Brain <span style='font-size:.9rem;color:#7d8590'>PRO · Fase 3.8 TEMPORALIDADES CLARAS</span>", unsafe_allow_html=True)
st.caption("Elige activo y temporalidad. La IA busca la tendencia actual y señales tempranas del próximo giro.")

with st.sidebar:
    st.markdown("### 📌 MERCADO")
    ui_mode = st.radio("Modo", ["Sencillo", "Avanzado"], horizontal=True)
    selected = st.selectbox("Activo", list(SYMBOLS.keys()), index=0)

    # Solo las temporalidades estándar que queremos mostrar al usuario, con nombres claros.
    # Internamente conservamos los códigos de Binance/TradingView para los cálculos.
    TIMEFRAME_UI = {
        "1 minuto": "1m",
        "2 minutos": "2m",
        "3 minutos": "3m",
        "5 minutos": "5m",
        "10 minutos": "10m",
        "15 minutos": "15m",
        "30 minutos": "30m",
        "45 minutos": "45m",
        "1 hora": "1h",
        "2 horas": "2h",
        "3 horas": "3h",
        "4 horas": "4h",
        "1 día": "1D",
        "1 semana": "1W",
        "1 mes": "1M",
    }
    if ui_mode == "Sencillo":
        # Exact TradingView-style codes.  Nothing else is required from the user.
        _simple_tfs = list(TIMEFRAME_UI.values())
        timeframe = st.selectbox(
            "Temporalidad",
            _simple_tfs,
            index=_simple_tfs.index("1h"),
            help="Muestra la tendencia actual y señales tempranas de probable subida o bajada antes del giro completo.",
        )
        timeframe_label = next(k for k, v in TIMEFRAME_UI.items() if v == timeframe)
        chart_bars = 180
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
    else:
        timeframe_label = st.selectbox(
            "Temporalidad",
            list(TIMEFRAME_UI.keys()),
            index=list(TIMEFRAME_UI.keys()).index("1 hora"),
            help="Temporalidad de TradingView usada por el análisis.",
        )
        timeframe = TIMEFRAME_UI[timeframe_label]
        chart_bars = st.select_slider("Velas en gráfico", options=VISIBLE_OPTIONS, value=200)
        st.markdown("#### Horizonte de proyección")
        horizon_name = st.selectbox("Periodo", list(HORIZONS.keys()), index=1, label_visibility="collapsed")
        horizon = HORIZONS[horizon_name]
        st.caption(f"{horizon_name}: aprox. {horizon_text(timeframe, horizon)}")

    if ui_mode == "Avanzado":
        with st.expander("📈 Indicadores del gráfico", expanded=False):
            e9 = st.checkbox("EMA 9", False)
            e20 = st.checkbox("EMA 20", True)
            e50 = st.checkbox("EMA 50", True)
            e200 = st.checkbox("EMA 200", True)
            bb = st.checkbox("Bollinger Bands", False)
            vwap_on = st.checkbox("VWAP", False)
            sr_on = st.checkbox("Soportes / resistencias", True)
            show_volume = st.checkbox("Panel de volumen", True)
            show_rsi = st.checkbox("Panel RSI", True)
            show_macd = st.checkbox("Panel MACD %", False)
        with st.expander("⚙️ Modelo", expanded=False):
            if STANDARD_TIMEFRAMES[timeframe].direct_ai:
                training_bars = int(st.number_input("Velas históricas", min_value=100, max_value=5000, value=int(DEFAULT_HISTORY[timeframe]), step=100))
                st.caption("Más histórico tarda más y no garantiza mejor resultado. La validación prioriza calidad fuera de muestra.")
            else:
                training_bars = DEFAULT_HISTORY[timeframe]
                st.info("Esta temporalidad está disponible para gráfico/contexto, pero el ML estricto se desactiva para evitar probabilidades poco defendibles.")
    else:
        e9, e20, e50, e200 = False, True, True, True
        bb, vwap_on, sr_on = False, False, True
        show_volume, show_rsi, show_macd = True, True, False
        training_bars = DEFAULT_HISTORY[timeframe]

    if st.button("🔄 Actualizar análisis", width="stretch"):
        fetch_binance_history.clear()
        fetch_recent_binance_history.clear()
        fetch_recent_timeframe_history.clear()
        cached_breadth.clear()
        cached_derivatives.clear()
        model_signal.clear()
        cached_simple_signal.clear()
        monthly_consensus_state.clear()
        st.session_state.pop(f"timing_forecast::{selected}", None)
        st.session_state.pop(f"candle_radar::{selected}::{timeframe}", None)
        st.rerun()

    st.markdown("---")
    st.caption("🟢 LIVE se actualiza aprox. cada 10 segundos. La IA usa la última vela CERRADA. El análisis predictivo se valida en minutos, horas, día y semana; mensual se usa como contexto de ciclo.")



# ------------------------- Fast simple mode -------------------------
if ui_mode == "Sencillo":
    _simple_refresh = "10s" if timeframe == "1m" else "15s" if timeframe in ("2m", "3m", "5m") else "30s" if timeframe in ("10m", "15m", "30m", "45m") else "60s"

    @st.fragment(run_every=_simple_refresh)
    def _render_fast_simple_mode():
        fast_history = min(int(training_bars), 800)
        need_simple = max(fast_history + 2, int(chart_bars) + 2)
        try:
            base_simple = fetch_timeframe_history(SYMBOLS[selected], timeframe, need_simple)
            recent_simple = fetch_recent_timeframe_history(SYMBOLS[selected], timeframe, 36)
            full_simple = (pd.concat([base_simple, recent_simple], ignore_index=True)
                           .sort_values("timestamp")
                           .drop_duplicates("timestamp", keep="last")
                           .tail(need_simple)
                           .reset_index(drop=True))
            closed_simple = (full_simple[full_simple.is_closed]
                             .drop(columns=["is_closed"])
                             .tail(fast_history)
                             .reset_index(drop=True))
            chart_simple = full_simple.drop(columns=["is_closed"]).tail(int(chart_bars)).reset_index(drop=True)
        except Exception as e:
            st.error(f"No se pudieron cargar datos de mercado: {e}")
            return

        if closed_simple.empty:
            st.warning("Todavía no hay suficiente histórico cerrado para detectar tendencia.")
            return

        cycle = fast_cycle_context(SYMBOLS[selected])
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
                "directional_forecasts": {},
                "max_horizon": 8,
            }
            st.caption(f"Detector temprano temporalmente limitado: {type(e).__name__}.")
        current = trend_info.get("current", {})
        cur = current.get("scenario", "LATERAL")
        cur_icon = "🟢" if cur == "SUBIDA" else "🔴" if cur == "BAJADA" else "🟡"
        cur_label = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"

        st.markdown(f"### {cur_icon} {selected} · {timeframe} · {cur_label} AHORA")
        tr = trend_info.get("transition")
        early = trend_info.get("early_warning")
        active = tr or early

        # ALWAYS show both directional windows. These are computed from the same
        # AI evidence, so displaying both does not add another heavy model pass.
        dirs = trend_info.get("directional_forecasts", {})
        up_fc = dirs.get("SUBIDA")
        down_fc = dirs.get("BAJADA")

        def _render_direction_forecast(fc, direction):
            icon = "🟢" if direction == "SUBIDA" else "🔴"
            title = "PRÓXIMA SUBIDA" if direction == "SUBIDA" else "PRÓXIMA BAJADA"
            if not fc:
                st.markdown(f"### {icon} {title} · sin cálculo disponible")
                return
            prob = float(fc.get("probability", 0.5)) * 100.0
            status = fc.get("status", "SIN_VENTANA_FIABLE")
            if fc.get("has_window"):
                window = transition_window_text(timeframe, fc, int(trend_info.get("max_horizon", 8)))
                qualifier = "PROBABLE" if status == "PROBABLE" else "POSIBLE EN FORMACIÓN"
                st.markdown(f"### {icon} {title} {qualifier} · {window}")
                st.caption(f"Confianza IA {prob:.0f}% · evidencia {str(fc.get('reliability','BAJA')).lower()}.")
            else:
                st.markdown(f"### {icon} {title} · sin ventana fiable todavía")
                st.caption(f"Evidencia actual {prob:.0f}% · todavía no alcanza el umbral para estimar cuándo comenzaría.")

        _render_direction_forecast(up_fc, "SUBIDA")
        _render_direction_forecast(down_fc, "BAJADA")

        if tr:
            move = "subida" if tr["to"] == "SUBIDA" else "bajada"
            st.caption(f"⚡ Giro principal detectado: probable {move} {transition_window_text(timeframe, tr, int(trend_info.get('max_horizon', 8)))}.")
        elif early:
            move = "subida" if early["to"] == "SUBIDA" else "bajada"
            st.caption(f"🟠 Giro temprano en formación: posible {move} {transition_window_text(timeframe, early, int(trend_info.get('max_horizon', 8)))}.")
        else:
            st.caption("Sin giro temprano dominante todavía; las dos direcciones siguen visibles arriba con su evidencia actual.")

        fig_fast = trend_chart(chart_simple, selected, timeframe, trend_info)
        st.plotly_chart(fig_fast, width="stretch", theme=None,
                        key=f"trend_simple_{selected}_{timeframe}", config=plot_config())

        alert_key = f"trend_state::{selected}::{timeframe}"
        previous = st.session_state.get(alert_key)
        if previous is not None and previous != cur:
            text = "ALCISTA" if cur == "SUBIDA" else "BAJISTA" if cur == "BAJADA" else "SIN TENDENCIA"
            st.toast(f"{selected} · {timeframe}: tendencia cambió → {text}", icon="🔔")
        st.session_state[alert_key] = cur

        watch_key = f"trend_watch::{selected}::{timeframe}"
        watch_now = None if not active else (active.get("to"), active.get("start_bars"), active.get("end_bars"), bool(tr))
        watch_prev = st.session_state.get(watch_key)
        if watch_now is not None and watch_prev != watch_now:
            direction = "SUBIDA" if active["to"] == "SUBIDA" else "BAJADA"
            prefix = "Probable" if tr else "Posible en formación"
            st.toast(f"{prefix} {direction.lower()} · {transition_window_text(timeframe, active, trend_info.get('max_horizon',8))}", icon="🔔")
        st.session_state[watch_key] = watch_now

        sensor_tfs = [x.get("timeframe") for x in trend_info.get("sensors", []) if x.get("timeframe")]
        if sensor_tfs:
            st.caption(f"Sensores adelantados usados: {', '.join(sensor_tfs)} · temporalidad principal: {timeframe}.")
        st.caption("La meta es detectar debilitamiento y giro antes de que la tendencia principal ya haya cambiado. No garantiza anticipar todos los giros.")

    _render_fast_simple_mode()
    st.stop()

# ------------------------- Data -------------------------
need = max(training_bars + 2, chart_bars + 2)
try:
    full_df = fetch_timeframe_history(SYMBOLS[selected], timeframe, need)
    model_df = full_df[full_df.is_closed].drop(columns=["is_closed"]).tail(training_bars).reset_index(drop=True)
    display_df = full_df.drop(columns=["is_closed"]).tail(chart_bars).reset_index(drop=True)
    display_features = build_features(display_df)
    closed_features = build_features(model_df)
except Exception as e:
    st.error(f"No se pudieron cargar datos de mercado: {e}")
    st.stop()

if STANDARD_TIMEFRAMES[timeframe].direct_ai:
    with st.spinner("Validando el modelo fuera de muestra..."):
        signal = model_signal(model_df, horizon=horizon)
else:
    signal = {"ok": False, "reason": "Esta temporalidad se muestra para gráfico/contexto, pero no se fuerza el ML estricto porque no tiene profundidad histórica suficiente con el modelo actual. Usa desde 1 minuto hasta 1 semana para proyecciones validadas."}

simple_band = projection_band(signal, horizon)
simple_forecast = None
if signal.get("ok") and simple_band is not None:
    try:
        simple_forecast = build_simple_forecast(
            model_df, float(signal["price"]), signal["pup"], signal["pflat"], signal["pdown"],
            simple_band.get("low68"), simple_band.get("high68"), signal.get("atr"), horizon,
        )
    except Exception:
        simple_forecast = None


# ------------------------- Ultra-simple main view -------------------------
if ui_mode == "Sencillo":
    if timeframe == "1M":
        with st.spinner("Analizando diario, semanal y ciclo mensual..."):
            simple_state = monthly_consensus_state(SYMBOLS[selected])
    else:
        simple_state = _strict_simple_state(signal)

    if simple_state:
        scenario = simple_state["scenario"]
        icon = "🟢" if scenario == "SUBIDA" else "🔴" if scenario == "BAJADA" else "🟡"
        label = "ALCISTA" if scenario == "SUBIDA" else "BAJISTA" if scenario == "BAJADA" else "LATERAL"
        st.markdown(f"## {icon} {selected} · {label}")
        st.caption(
            f"{timeframe_label} · evidencia {simple_state['reliability'].lower()} · "
            f"probabilidad estimada {simple_state['probability']*100:.1f}%"
        )
    else:
        st.markdown(f"## ⚪ {selected} · SIN SEÑAL CLARA")
        st.caption(
            f"{timeframe_label} · el punto queda gris hasta que el análisis supere los filtros de fiabilidad."
        )

    simple_fig = simple_signal_chart(
        display_df, selected, timeframe, horizon, simple_state, simple_forecast
    )
    st.plotly_chart(
        simple_fig,
        width="stretch",
        theme=None,
        key=f"simple_main_{selected}_{timeframe}_{horizon}",
        config=plot_config(),
    )

    if simple_state:
        alert_key = f"last_simple_state::{selected}::{timeframe}"
        previous = st.session_state.get(alert_key)
        current = simple_state["scenario"]
        if previous is not None and previous != current:
            text = "SUBIDA" if current == "SUBIDA" else "BAJADA" if current == "BAJADA" else "LATERAL"
            st.toast(f"Cambio detectado en {selected} · {timeframe_label}: {text}", icon="🔔")
        st.session_state[alert_key] = current

    with st.expander("Qué está analizando por detrás", expanded=False):
        st.caption(
            "Modelos estadísticos, validación fuera de muestra, patrones históricos, tendencia, volumen y contexto de ciclo. "
            "La pantalla principal solo muestra el resultado cuando la evidencia es suficiente."
        )
    st.stop()

render_live_strip(SYMBOLS[selected])

last_closed_time = model_df.timestamp.iloc[-1]
closed_row = closed_features.iloc[-1]
snap = technical_snapshot(closed_row)
vol_radar = analyze_volume(closed_row)

_top_dom = max((("SUBIDA", signal.get("pup", 0.0)), ("LATERAL", signal.get("pflat", 0.0)), ("BAJADA", signal.get("pdown", 0.0))), key=lambda x: x[1])[0] if signal.get("ok") else "N/A"
c1, c2, c3 = st.columns(3)
c1.metric("Dirección IA", direction_label(_top_dom))
c2.metric("Confianza modelo", f"{signal['decision'].confidence*100:.1f}%" if signal.get("ok") else "N/A")
c3.metric("Último cierre analizado", pd.Timestamp(last_closed_time).strftime("%d %b %H:%M UTC"))
c4, c5, c6 = st.columns(3)
c4.metric("Tendencia", snap["trend"])
c5.metric("Fuerza", snap["strength"])
c6.metric("Volumen", f"{volume_icon(vol_radar.direction)} {vol_radar.direction} · {vol_radar.intensity}/100")
try:
    if timeframe in ("1M", "3M", "6M", "12M"):
        _months = {"1M": 1, "3M": 3, "6M": 6, "12M": 12}[timeframe]
        _next_close = pd.Timestamp(last_closed_time) + pd.DateOffset(months=2 * _months)
    else:
        _next_close = pd.Timestamp(last_closed_time) + pd.Timedelta(minutes=2 * INTERVAL_MINUTES[timeframe])
    st.caption(f"⏱️ Próximo cierre de la vela actual: aprox. {_next_close.strftime('%d %b %H:%M UTC')}")
except Exception:
    pass

st.info("**Qué significa ahora:** " + simple_explanation(signal), icon="🧭")

# ------------------------- Main UI -------------------------
simple_tab, now_tab, projections_tab, opportunities_tab, validation_tab, risk_tab = st.tabs([
    "🎯 RESUMEN FÁCIL", "📊 Gráfico", "🔮 Más periodos", "🔎 Criptos", "🧪 Avanzado", "🛡️ Riesgo"
])

with simple_tab:
    st.subheader(f"{selected} · próximas {horizon_text(timeframe, horizon)}")
    st.caption("La app no promete un precio exacto: muestra el escenario dominante y una zona estadística de precio. El precio LIVE de arriba puede moverse dentro de la vela; la proyección usa la última vela cerrada.")

    if signal.get("ok") and simple_forecast is not None:
        dom = simple_forecast.dominant
        dom_prob = scenario_probability(signal, dom)
        icon = "🟢" if dom == "SUBIDA" else "🔴" if dom == "BAJADA" else "🟡"
        bias = direction_label(dom)
        practical = practical_label(signal)
        st.markdown(
            f'<div class="hero"><div class="muted">DIRECCIÓN MÁS PROBABLE DESPUÉS DEL ÚLTIMO CIERRE</div>'
            f'<div style="font-size:2.45rem;font-weight:950">{bias_icon(bias)} {bias}</div>'
            f'<div style="font-size:1.35rem;font-weight:800">{dom_prob*100:.1f}%</div>'
            f'<div class="muted">Operativa ahora: <b>{practical}</b> · Calidad del modelo: {quality_plain(signal)}</div></div>',
            unsafe_allow_html=True,
        )

        # Plan dominante resumido: una sola lectura práctica sin obligar a buscar niveles más abajo.
        lp = simple_forecast.long_plan
        sp = simple_forecast.short_plan
        st.markdown("#### 📍 Plan rápido del escenario dominante")
        if dom == "SUBIDA":
            p1, p2, p3 = st.columns(3)
            p1.metric("Confirmación LONG", f"${lp.confirmation:,.2f}")
            p2.metric("Stop si confirma", f"${lp.stop:,.2f}")
            p3.metric("Objetivo", f"${lp.target_low:,.0f} – ${lp.target_high:,.0f}")
            st.caption("No entra automáticamente: primero debe superar el nivel de confirmación.")
        elif dom == "BAJADA":
            p1, p2, p3 = st.columns(3)
            p1.metric("Confirmación SHORT", f"${sp.confirmation:,.2f}")
            p2.metric("Stop / invalidación", f"${sp.stop:,.2f}")
            p3.metric("Objetivo", f"${sp.target_low:,.0f} – ${sp.target_high:,.0f}")
            st.caption("No entra automáticamente: primero debe perder el nivel de confirmación.")
        else:
            p1, p2, p3 = st.columns(3)
            p1.metric("Rango lateral", zone_text(simple_forecast.flat))
            p2.metric("Ruptura alcista", f"> ${lp.confirmation:,.2f}")
            p3.metric("Ruptura bajista", f"< ${sp.confirmation:,.2f}")
            st.caption("Mientras siga dentro del rango, la lectura principal es esperar. Los niveles muestran qué ruptura vigilar.")

        st.markdown("#### Probabilidades del horizonte seleccionado")
        pr1, pr2, pr3 = st.columns(3)
        pr1.metric("🟢 Subida", f"{signal['pup']*100:.1f}%")
        pr2.metric("🟡 Lateral", f"{signal['pflat']*100:.1f}%")
        pr3.metric("🔴 Bajada", f"{signal['pdown']*100:.1f}%")

        # Volume radar: simple closed-candle confirmation layer. It detects
        # current participation/aggression; it does not claim future volume is guaranteed.
        va = volume_alignment(bias, vol_radar)
        vic = volume_icon(vol_radar.direction)
        vcol1, vcol2, vcol3 = st.columns([1.4, 1, 1.5])
        with vcol1:
            st.markdown(f"### {vic} Volumen {vol_radar.direction.lower()}")
            st.write(f"**Estado:** {vol_radar.phase}")
        with vcol2:
            st.metric("Intensidad", f"{vol_radar.intensity}/100")
            st.metric("Presión", f"{vol_radar.pressure:+d}")
        with vcol3:
            if va.startswith("CONFIRMA"):
                st.success(va)
            elif va.startswith("CONTRADICE"):
                st.error(va)
            else:
                st.warning(va)
            st.caption(" · ".join(vol_radar.reasons))
        if not signal.get("model_validated"):
            st.warning("La dirección se muestra para que entiendas el escenario, pero el modelo todavía no tiene suficiente ventaja fuera de muestra para tratarlo como una entrada.")

        a, b, c = st.columns(3)
        with a:
            st.markdown("### 🟢 LONG / si sube")
            st.metric("Probabilidad", f"{simple_forecast.up.probability*100:.1f}%")
            st.write(f"**Zona proyectada:** {zone_text(simple_forecast.up)}")
        with b:
            st.markdown("### 🟡 LATERAL")
            st.metric("Probabilidad", f"{simple_forecast.flat.probability*100:.1f}%")
            st.write(f"**Zona proyectada:** {zone_text(simple_forecast.flat)}")
        with c:
            st.markdown("### 🔴 SHORT / si baja")
            st.metric("Probabilidad", f"{simple_forecast.down.probability*100:.1f}%")
            st.write(f"**Zona proyectada:** {zone_text(simple_forecast.down)}")

        st.markdown("---")
        st.markdown("### 🔭 ¿EN QUÉ VELA podría empezar el cambio?")
        st.caption("La IA compara varios horizontes de la MISMA temporalidad después del último cierre. Ejemplo: en 15m, vela +2 equivale a ~30 min. Busca una ventana estable; no afirma que una vela exacta sea segura.")
        radar_key = f"candle_radar::{selected}::{timeframe}"
        if STANDARD_TIMEFRAMES[timeframe].direct_ai:
            if st.button("🔭 Analizar próximas velas", key=f"radar_run::{selected}::{timeframe}", type="primary"):
                with st.spinner("Validando próximas velas. La primera vez puede tardar porque cada horizonte se prueba fuera de muestra..."):
                    st.session_state[radar_key] = build_candle_radar(SYMBOLS[selected], timeframe, training_bars)
            radar = st.session_state.get(radar_key)
            if radar:
                best = radar.get("best")
                if best:
                    br = best["row"]
                    bic = "🟢" if best["scenario"] == "SUBIDA" else "🔴" if best["scenario"] == "BAJADA" else "🟡"
                    st.markdown(
                        f'<div class="hero"><div class="muted">PRIMERA VENTANA DE VELAS CON EVIDENCIA ESTABLE</div>'
                        f'<div style="font-size:1.95rem;font-weight:900">{bic} {direction_label(best["scenario"])}</div>'
                        f'<div style="font-size:1.15rem;font-weight:800">{candle_window_text(timeframe, best["start_bar"], best["end_bar"])}</div>'
                        f'<div class="muted">Probabilidad del horizonte: {best["probability"]*100:.1f}% · Fiabilidad: {best["reliability"].capitalize()}</div></div>',
                        unsafe_allow_html=True,
                    )
                    st.write(f"**Zona estimada:** ${br['zone_low']:,.2f} – ${br['zone_high']:,.2f}")
                    if best["scenario"] == "SUBIDA" and br.get("confirmation") is not None:
                        st.write(f"**Confirma subida:** arriba de ${br['confirmation']:,.2f} · **Stop si confirma:** ${br['stop']:,.2f}")
                    elif best["scenario"] == "BAJADA" and br.get("confirmation") is not None:
                        st.write(f"**Confirma bajada:** debajo de ${br['confirmation']:,.2f} · **Stop / invalidación:** ${br['stop']:,.2f}")
                else:
                    st.info("No aparece una vela de inicio suficientemente estable todavía. La app prefiere decir 'sin ventana fiable' antes que adivinar.")

                w1, w2, w3 = st.columns(3)
                for col, sc, ic in [(w1, "SUBIDA", "🟢"), (w2, "LATERAL", "🟡"), (w3, "BAJADA", "🔴")]:
                    with col:
                        st.markdown(f"**{ic} {direction_label(sc)}**")
                        w = radar.get("windows", {}).get(sc)
                        if w:
                            st.write(candle_window_text(timeframe, w["start_bar"], w["end_bar"]))
                            st.write(f"**{w['probability']*100:.1f}%** · {w['reliability'].lower()}")
                        else:
                            st.write("Sin ventana fiable")
                st.dataframe(_candle_radar_dataframe(radar["rows"], timeframe), width="stretch", hide_index=True)
                if radar.get("errors"):
                    with st.expander("Problemas técnicos de alguna vela", expanded=False):
                        for err in radar["errors"]:
                            st.write("• " + err)
            else:
                st.info("Pulsa el botón para estimar si el cambio aparece en la vela +1, +2, +3 o +5 (según temporalidad).")
        else:
            st.info("En 1 mes no se fuerza una predicción vela-a-vela cuando no existe suficiente historial; se usa como contexto de ciclo. Usa desde 1 minuto hasta 1 semana para el radar validado.")

        st.markdown("---")
        st.markdown("### 🗓️ Fechas probables (opcional)")
        st.caption("Convierte los horizontes a ventanas de tiempo. Es una segunda vista del mismo problema; no inventa una hora exacta.")
        timing_key = f"timing_forecast::{selected}"
        if st.button("🧠 Analizar próximas horas y 7 días", key=f"timing_run::{selected}", type="primary"):
            with st.spinner("Analizando 6 horizontes con validación temporal. La primera vez puede tardar varios minutos..."):
                st.session_state[timing_key] = build_timing_rows(SYMBOLS[selected])

        timing_result = st.session_state.get(timing_key)
        if timing_result:
            transition = timing_result.get("transition")
            if transition:
                tr = transition["row"]
                ticon = "🟢" if transition["scenario"] == "SUBIDA" else "🔴" if transition["scenario"] == "BAJADA" else "🟡"
                st.markdown(
                    f'<div class="hero"><div class="muted">PRIMER CAMBIO TEMPORAL CON EVIDENCIA SUFICIENTE</div>'
                    f'<div style="font-size:1.8rem;font-weight:900">{ticon} {direction_label(transition["scenario"])}</div>'
                    f'<div style="font-size:1.05rem;font-weight:700">{transition_text(transition)}</div>'
                    f'<div class="muted">Probabilidad del horizonte: {transition["probability"]*100:.1f}% · Fiabilidad: {transition["reliability"].capitalize()}</div></div>',
                    unsafe_allow_html=True,
                )
                st.write(f"**Zona estimada en ese horizonte:** ${tr['zone_low']:,.2f} – ${tr['zone_high']:,.2f}")
                if transition["scenario"] == "SUBIDA":
                    st.write(f"**Confirmaría subida:** arriba de ${tr['confirmation']:,.2f} · **Stop de referencia si confirma:** ${tr['stop']:,.2f}")
                elif transition["scenario"] == "BAJADA":
                    st.write(f"**Confirmaría bajada:** debajo de ${tr['confirmation']:,.2f} · **Stop / invalidación si confirma:** ${tr['stop']:,.2f}")
            else:
                st.info("No aparece una fecha/ventana de cambio suficientemente fiable hasta 7 días. Eso es preferible a forzar una predicción.")

            st.markdown("#### Primera ventana con evidencia para cada escenario")
            fw = timing_result.get("first_windows", {})
            wc1, wc2, wc3 = st.columns(3)
            for col, sc, ic in [(wc1, "SUBIDA", "🟢"), (wc2, "LATERAL", "🟡"), (wc3, "BAJADA", "🔴")]:
                with col:
                    w = fw.get(sc)
                    st.markdown(f"**{ic} {direction_label(sc)}**")
                    if w:
                        st.write(f"{local_dt_text(w['start'])} → {local_dt_text(w['end'])}")
                        st.write(f"**{w['probability']*100:.1f}%** · fiabilidad {w['reliability'].lower()}")
                    else:
                        st.write("Sin ventana fiable todavía")

            st.markdown("#### Línea temporal sencilla")
            st.dataframe(_timeline_dataframe(timing_result["rows"]), width="stretch", hide_index=True)
            st.caption(f"Actualizado: {local_dt_text(timing_result['generated_at'])}. Las ventanas se recalculan con velas cerradas y pueden cambiar cuando entra información nueva.")
            if timing_result.get("errors"):
                with st.expander("Ver problemas técnicos de horizontes que no pudieron calcularse", expanded=False):
                    for err in timing_result["errors"]:
                        st.write("• " + err)
        else:
            st.info("Pulsa el botón una vez para construir la línea temporal. Después queda guardada mientras uses esta sesión.")

        st.markdown("---")
        st.markdown("### 🛡️ ¿Dónde pondría el Stop si el movimiento se confirma?")
        st.caption("Son planes CONDICIONALES: primero debe romper el nivel de confirmación. No se coloca un stop solo porque la probabilidad sea la mayor.")
        lcol, scol = st.columns(2)
        lp = simple_forecast.long_plan
        sp = simple_forecast.short_plan
        with lcol:
            st.markdown("#### 🟢 Si comienza una SUBIDA")
            st.write(f"**Confirmación:** arriba de **${lp.confirmation:,.2f}**")
            st.write(f"**Stop Loss de referencia:** **${lp.stop:,.2f}**")
            st.write(f"**Objetivo proyectado:** ${lp.target_low:,.2f} – ${lp.target_high:,.2f}")
            st.write(f"**R:R al extremo de la zona:** {rr_or_na(lp.risk_reward)}")
            if lp.valid and (lp.risk_reward is None or lp.risk_reward >= 1.5):
                st.success(lp.note)
            else:
                st.warning(lp.note)
        with scol:
            st.markdown("#### 🔴 Si comienza una BAJADA")
            st.write(f"**Confirmación:** debajo de **${sp.confirmation:,.2f}**")
            st.write(f"**Stop / invalidación:** **${sp.stop:,.2f}**")
            st.write(f"**Objetivo proyectado:** ${sp.target_low:,.2f} – ${sp.target_high:,.2f}")
            st.write(f"**R:R al extremo de la zona:** {rr_or_na(sp.risk_reward)}")
            if sp.valid and (sp.risk_reward is None or sp.risk_reward >= 1.5):
                st.success(sp.note)
            else:
                st.warning(sp.note)
            st.caption("En mercado spot, el plan bajista puede usarse como nivel de salida/protección. Operar SHORT requiere un producto que permita posiciones cortas.")

        st.markdown("---")
        st.markdown("### 📉 Gráfico simple")
        easy_fig = price_chart(display_df, display_features, selected, timeframe, None, False, False, False, True, False, False, True)
        easy_fig.add_hline(y=lp.confirmation, line_dash="dash", line_color="#2ecc71", annotation_text="Confirma subida")
        easy_fig.add_hline(y=lp.stop, line_dash="dot", line_color="#6fcf97", annotation_text="Stop si sube")
        easy_fig.add_hline(y=sp.confirmation, line_dash="dash", line_color="#ff5c5c", annotation_text="Confirma bajada")
        easy_fig.add_hline(y=sp.stop, line_dash="dot", line_color="#ff9b9b", annotation_text="Stop si baja")
        easy_fig.update_layout(height=480, legend=dict(orientation="h", y=1.02))
        st.plotly_chart(easy_fig, width="stretch", theme=None, key=f"easy_{selected}_{timeframe}_{horizon}", config=plot_config())
        st.caption("EMA 200 + soporte/resistencia + niveles de confirmación. Arrastra para mover, rueda/trackpad para zoom y doble clic para restaurar.")
    else:
        st.warning("No hay suficientes datos/modelo disponible para construir una proyección simple ahora.")

with now_tab:
    left, right = st.columns([4.4, 1.35], gap="medium")
    with left:
        st.caption("🖱️ **Mover:** arrastra el gráfico · **Zoom:** rueda/trackpad · **Reset:** doble clic. El zoom se conserva al actualizar widgets.")
        chart_signal = signal if practical_label(signal) in ("LONG", "SHORT") else None
        fig = price_chart(
            display_df, display_features, selected, timeframe,
            chart_signal,
            e9, e20, e50, e200, bb, vwap_on, sr_on,
        )
        st.plotly_chart(fig, width="stretch", theme=None, key=f"price_{selected}_{timeframe}", config=plot_config())

        if show_volume:
            with st.expander("📊 Volumen", expanded=(ui_mode == "Sencillo")):
                st.plotly_chart(volume_chart(display_df, selected, timeframe), width="stretch", theme=None, key=f"vol_{selected}_{timeframe}", config=plot_config())

        if show_rsi or show_macd:
            with st.expander("📉 Momentum (RSI / MACD)", expanded=False):
                if show_rsi:
                    st.plotly_chart(momentum_chart(display_df, display_features, True, False), width="stretch", theme=None, key=f"rsi_{selected}_{timeframe}", config=plot_config())
                if show_macd:
                    st.plotly_chart(momentum_chart(display_df, display_features, False, True), width="stretch", theme=None, key=f"macd_{selected}_{timeframe}", config=plot_config())

    with right:
        st.markdown("### 🤖 Lectura rápida")
        if signal.get("ok"):
            practical = practical_label(signal)
            cls = "buy" if practical == "LONG" else "sell" if practical == "SHORT" else "wait"
            st.markdown(
                f'<div class="card"><div class="muted">QUÉ HACER</div><div class="big {cls}">{practical}</div>'
                f'<div class="muted">Confianza del modelo</div><div class="big">{signal["decision"].confidence*100:.1f}%</div>'
                '<div class="tiny">No es probabilidad garantizada de ganar.</div></div>',
                unsafe_allow_html=True,
            )
            st.write("")
            qicon = "✅" if signal["model_validated"] else "⚠️"
            st.write(f"**Modelo:** {qicon} {signal['quality_label']}")
            st.write(f"**Régimen:** {signal['regime'].regime}")
            st.write(f"**Horizonte:** {horizon_text(timeframe, horizon)}")
            st.write(f"**Volumen:** {volume_icon(vol_radar.direction)} {vol_radar.direction} · {vol_radar.intensity}/100 · {vol_radar.phase}")
            st.write(f"**Volumen vs dirección:** {volume_alignment(direction_label(_top_dom), vol_radar)}")
            cf = signal.get("confluence", {})
            st.write(f"**Confirmación técnica:** {cf.get('score',0):.0f}/100")
            st.progress(signal["pup"], text=f"Subida {signal['pup']*100:.1f}%")
            st.progress(signal["pflat"], text=f"Lateral {signal['pflat']*100:.1f}%")
            st.progress(signal["pdown"], text=f"Bajada {signal['pdown']*100:.1f}%")

            if signal.get("risk_plan"):
                rp = signal["risk_plan"]
                st.markdown("---")
                st.write(f"**Entrada ref.:** ${rp.entry:,.2f}")
                st.write(f"**Stop Loss:** ${rp.recommended.price:,.2f}")
                st.write(f"**TP1:** ${rp.tp1:,.2f}")
                st.write(f"**R:R:** {rr_text(rp.recommended.rr_to_tp1)}")

            st.markdown("---")
            st.markdown("**Lectura técnica simple**")
            st.write(f"Tendencia: **{snap['trend']}**")
            st.write(f"Momentum: **{snap['momentum']}**")
            st.write(f"Volumen: **{snap['volume']}**")
            st.write(f"Fuerza: **{snap['strength']}**")

            with st.expander("¿Por qué dice eso?"):
                if cf.get("support"):
                    st.success("Confirma: " + " · ".join(cf["support"][:6]))
                if cf.get("conflict"):
                    st.warning("Contradice: " + " · ".join(cf["conflict"][:6]))
                st.caption(f"Balanced accuracy OOS {signal['best_balanced_accuracy']*100:.1f}% · F1 {signal['best_f1']*100:.1f}% · Brier skill {signal['best_brier_skill']*100:+.1f}%")
        else:
            st.warning(signal.get("reason", "Modelo no disponible"))

    with st.expander("ℹ️ Cómo leer la pantalla", expanded=False):
        st.markdown(
            "**LONG** = sesgo alcista validado. **SHORT** = sesgo bajista (en spot no implica que puedas vender en corto). "
            "**ESPERAR** = hay una dirección posible pero falta confirmación o R:R. **NO OPERAR** = no hay ventaja suficiente. "
            "La EMA 200 resume tendencia de fondo; RSI/MACD ayudan a confirmar momentum. El Radar de Volumen clasifica el flujo de la última vela cerrada como COMPRADOR, NEUTRAL o VENDEDOR y te dice si confirma o contradice LONG/SHORT."
        )

with projections_tab:
    st.subheader("Comparar otros periodos")
    st.caption("Si quieres comparar corto, medio y largo. La pantalla RESUMEN FÁCIL ya muestra el periodo que seleccionaste.")
    projection_state_key = f"projection_results::{selected}::{timeframe}"
    if st.button("🔮 Calcular corto / medio / largo", key="proj_run"):
        if not STANDARD_TIMEFRAMES[timeframe].direct_ai:
            st.warning("Esta temporalidad se conserva para gráfico/contexto. Para proyecciones probabilísticas validadas usa desde 1 minuto hasta 1 semana.")
        else:
            proj_rows = []
            progress = st.progress(0)
            for i, (name, h) in enumerate(HORIZONS.items()):
                res = model_signal(model_df, horizon=h)
                band = projection_band(res, h)
                proj_rows.append((name, h, res, band))
                progress.progress((i + 1) / len(HORIZONS))
            st.session_state[projection_state_key] = proj_rows

    proj_rows = st.session_state.get(projection_state_key)
    if proj_rows:
        cols = st.columns(3)
        for col, (name, h, res, band) in zip(cols, proj_rows):
            with col:
                if not res.get("ok"):
                    st.warning(f"{name}: {res.get('reason','N/A')}")
                    continue
                plabel = practical_label(res)
                st.markdown(f"### {name} · {horizon_text(timeframe, h)}")
                st.metric("Lectura", plabel)
                st.progress(res["pup"], text=f"Subida {res['pup']*100:.1f}%")
                st.progress(res["pflat"], text=f"Lateral {res['pflat']*100:.1f}%")
                st.progress(res["pdown"], text=f"Bajada {res['pdown']*100:.1f}%")
                if band:
                    if np.isfinite(band["low68"]):
                        st.write(f"**Rango estadístico ~68%:** ${band['low68']:,.2f} – ${band['high68']:,.2f}")
                    st.caption(f"Barreras del modelo: ↓ ${band['barrier_down']:,.2f} · ↑ ${band['barrier_up']:,.2f}")
                st.caption(f"Calidad: {res['quality_label']}. No es una predicción garantizada.")
    else:
        st.info("Pulsa el botón para calcular las tres proyecciones. Se hace bajo demanda para no volver lenta la app.")

with opportunities_tab:
    scan_sub, mtf_sub, context_sub = st.tabs(["Scanner", "Multi-timeframe", "Contexto global"])

    with scan_sub:
        st.subheader("Market Scanner multicripto")
        st.caption("Busca oportunidades; si ninguna pasa calidad OOS + confianza + confluencia + R:R, dice que no hay oportunidad en vez de forzar una.")
        scan_assets = st.multiselect("Activos", list(SYMBOLS.keys()), default=list(SYMBOLS.keys())[:6])
        scan_state_key = f"scan_df::{timeframe}::{horizon}"
        if not STANDARD_TIMEFRAMES[timeframe].direct_ai:
            st.info("Para el scanner probabilístico usa desde 1 minuto hasta 1 semana. El mensual se conserva como contexto de mercado.")
        if st.button("🔎 Ejecutar scanner", key="scan_run", disabled=not STANDARD_TIMEFRAMES[timeframe].direct_ai):
            rows = []
            prog = st.progress(0)
            for i, name in enumerate(scan_assets):
                try:
                    sdf = fetch_timeframe_history(SYMBOLS[name], timeframe, 1202)
                    sdf = sdf[sdf.is_closed].drop(columns=["is_closed"]).tail(1200).reset_index(drop=True)
                    sres = model_signal(sdf, horizon=horizon)
                    if sres.get("ok"):
                        cf = sres.get("confluence", {}).get("score", 0) / 100
                        rp = sres.get("risk_plan")
                        rr = rp.recommended.rr_to_tp1 if rp else np.nan
                        p_label = practical_label(sres)
                        direction_ok = p_label in ("LONG", "SHORT")
                        score = sres["decision"].confidence * (0.35 + 0.65 * cf) * (1.0 if direction_ok else .20) * (min(1.2, rr / 2) if pd.notna(rr) else .5)
                        sband = projection_band(sres, horizon)
                        sf = build_simple_forecast(sdf, float(sres["price"]), sres["pup"], sres["pflat"], sres["pdown"], sband.get("low68") if sband else None, sband.get("high68") if sband else None, sres.get("atr"), horizon)
                        dom_zone = sf.up if sf.dominant == "SUBIDA" else sf.flat if sf.dominant == "LATERAL" else sf.down
                        _sv = analyze_volume(sres["features"].iloc[-1])
                        rows.append({
                            "Activo": name, "Dirección": direction_label(sf.dominant),
                            "Prob. escenario %": round(scenario_probability(sres, sf.dominant) * 100, 1),
                            "Volumen": f"{volume_icon(_sv.direction)} {_sv.direction}", "Volumen 0-100": _sv.intensity,
                            "Rango proyectado": zone_text(dom_zone), "¿Operar?": p_label,
                            "Lectura": p_label, "Confianza %": round(sres["decision"].confidence * 100, 1),
                            "Confluencia %": round(cf * 100, 0), "Calidad OOS": sres["quality_label"],
                            "Régimen": sres["regime"].regime, "R:R": round(rr, 2) if pd.notna(rr) else np.nan,
                            "Score": round(score, 3), "Error": "",
                        })
                    else:
                        rows.append({"Activo": name, "Dirección": "N/A", "Prob. escenario %": np.nan, "Volumen": "N/A", "Volumen 0-100": np.nan, "Rango proyectado": "N/A", "¿Operar?": "N/A", "Lectura": "N/A", "Confianza %": np.nan, "Confluencia %": np.nan, "Calidad OOS": "N/A", "Régimen": "N/A", "R:R": np.nan, "Score": 0, "Error": sres.get("reason", "")})
                except Exception as e:
                    rows.append({"Activo": name, "Dirección": "ERROR", "Prob. escenario %": np.nan, "Volumen": "N/A", "Volumen 0-100": np.nan, "Rango proyectado": "N/A", "¿Operar?": "ERROR", "Lectura": "ERROR", "Confianza %": np.nan, "Confluencia %": np.nan, "Calidad OOS": "N/A", "Régimen": "N/A", "R:R": np.nan, "Score": 0, "Error": str(e)[:90]})
                prog.progress((i + 1) / max(1, len(scan_assets)))
            scan = pd.DataFrame(rows).sort_values(["Score", "Confianza %"], ascending=False, na_position="last")
            st.session_state[scan_state_key] = scan

        scan = st.session_state.get(scan_state_key)
        if scan is not None:
            simple_cols = [c for c in ["Activo", "Dirección", "Prob. escenario %", "Volumen", "Volumen 0-100", "Rango proyectado", "¿Operar?"] if c in scan.columns]
            st.dataframe(scan[simple_cols], width="stretch", hide_index=True)
            with st.expander("Ver detalles técnicos del scanner", expanded=False):
                st.dataframe(scan, width="stretch", hide_index=True)
            candidates = scan[(scan["Lectura"].isin(["LONG", "SHORT"])) & (scan["Confianza %"] >= 58) & (scan["Confluencia %"] >= 60) & (scan["R:R"] >= 1.5) & (scan["Calidad OOS"].isin(["Sólido OOS", "Aceptable OOS"]))]
            if not candidates.empty:
                best = candidates.iloc[0]
                st.success(f"Mejor oportunidad cuantitativa: {best['Activo']} · {best['Lectura']} · confianza {best['Confianza %']:.1f}% · R:R {rr_text(best['R:R'])}.")
            else:
                st.warning("Ahora mismo no hay una oportunidad que pase todos los filtros. No se fuerza una entrada.")
        else:
            st.info("El scanner corre solo cuando lo pides para mantener la app rápida.")

    with mtf_sub:
        st.subheader(f"Multi-timeframe · {selected}")
        st.caption("Compara las temporalidades estándar de TradingView usadas para análisis: 1 minuto, 5 minutos, 15 minutos, 1 hora, 4 horas, 1 día y 1 semana. El mensual queda como contexto de ciclo.")
        mtf_list = ["1m", "5m", "15m", "1h", "4h", "1D", "1W"]
        mtf_state_key = f"mtf_df::{selected}::tradingview_standard"
        if st.button("▶ Analizar temporalidades", key="mtf_run"):
            rows = []
            prog = st.progress(0)
            for i, tf in enumerate(mtf_list):
                try:
                    tdf = fetch_timeframe_history(SYMBOLS[selected], tf, 1202)
                    tdf = tdf[tdf.is_closed].drop(columns=["is_closed"]).tail(1200).reset_index(drop=True)
                    tres = model_signal(tdf, horizon=12)
                    rows.append({
                        "Temporalidad": {"1m":"1 minuto","5m":"5 minutos","15m":"15 minutos","1h":"1 hora","4h":"4 horas","1D":"1 día","1W":"1 semana"}.get(tf, tf), "Horizonte real": horizon_text(tf, 12), "Lectura": practical_label(tres),
                        "Confianza %": round(tres["decision"].confidence * 100, 1) if tres.get("ok") else np.nan,
                        "Calidad OOS": tres.get("quality_label", "N/A"),
                        "Régimen": tres["regime"].regime if tres.get("ok") else "N/A",
                    })
                except Exception as e:
                    rows.append({"Temporalidad": {"1m":"1 minuto","5m":"5 minutos","15m":"15 minutos","1h":"1 hora","4h":"4 horas","1D":"1 día","1W":"1 semana"}.get(tf, tf), "Horizonte real": horizon_text(tf, 12), "Lectura": "ERROR", "Confianza %": np.nan, "Calidad OOS": str(e)[:40], "Régimen": "N/A"})
                prog.progress((i + 1) / len(mtf_list))
            st.session_state[mtf_state_key] = pd.DataFrame(rows)

        mtf = st.session_state.get(mtf_state_key)
        if mtf is not None:
            st.dataframe(mtf, width="stretch", hide_index=True)
            directional = mtf[mtf["Lectura"].isin(["LONG", "SHORT"])]
            if len(directional) >= 2 and directional["Lectura"].nunique() == 1:
                st.success(f"Alineación: {directional['Lectura'].iloc[0]} en {len(directional)} timeframes.")
            else:
                st.info("Alineación mixta o insuficiente; mejor esperar confirmación.")
        else:
            st.info("Pulsa el botón cuando quieras un análisis multi-timeframe.")

    with context_sub:
        st.subheader("Contexto global")
        st.caption("Ayuda a interpretar riesgo; no modifica ni infla las probabilidades del modelo.")
        a, b, c = st.columns(3)
        try:
            breadth = cached_breadth()
            if breadth:
                a.metric("Breadth positivo", f"{breadth['positive_pct']:.1f}%", breadth["state"])
                b.metric("Mediana 24h", f"{breadth['median_change']:+.2f}%")
                c.metric("Retorno ponderado vol.", f"{breadth['volume_weighted_change']:+.2f}%")
                st.info(f"Mercado **{breadth['state']}** sobre {breadth['n']} pares USDT líquidos.")
        except Exception as e:
            st.info(f"Breadth no disponible: {e}")

        f1, f2, f3 = st.columns(3)
        try:
            fg = cached_fear_greed()
            f1.metric("Fear & Greed", str(fg["value"]), fg["classification"])
        except Exception:
            f1.metric("Fear & Greed", "N/A")
        try:
            der = cached_derivatives(SYMBOLS[selected])
            f2.metric("Funding", f"{der['funding']:+.4f}%" if der.get("funding") is not None else "N/A")
            f3.metric("Open Interest", f"{der['open_interest']:,.0f}" if der.get("open_interest") is not None else "N/A")
        except Exception:
            f2.metric("Funding", "N/A")
            f3.metric("Open Interest", "N/A")

        row = closed_row
        tech = pd.DataFrame([
            ["EMA 200", "Encima" if row.dist_ema_200 > 0 else "Debajo", row.dist_ema_200 * 100],
            ["VWAP 50", "Encima" if row.vwap_dist > 0 else "Debajo", row.vwap_dist * 100],
            ["ADX", "Tendencia fuerte" if row.adx_14 >= 25 else "Tendencia débil", row.adx_14],
            ["DMI", "+DI domina" if row.di_spread > 0 else "-DI domina", row.di_spread * 100],
            ["CMF", "Entrada de flujo" if row.cmf_20 > 0 else "Salida de flujo", row.cmf_20],
            ["MFI", "Sobrecomprado" if row.mfi_14 > 80 else "Sobrevendido" if row.mfi_14 < 20 else "Neutral", row.mfi_14],
            ["Stoch RSI", "Alto" if row.stoch_rsi_k > .8 else "Bajo" if row.stoch_rsi_k < .2 else "Medio", row.stoch_rsi_k * 100],
            ["Bollinger/Keltner", "Squeeze" if row.bb_inside_kc > 0 else "Expandido", row.bb_width * 100],
        ], columns=["Factor", "Lectura", "Valor"])
        st.dataframe(tech, width="stretch", hide_index=True)

with validation_tab:
    st.subheader("Validación y backtest")
    st.caption("Aquí se comprueba si el modelo realmente tuvo ventaja fuera de muestra. Una interfaz bonita no sustituye esta prueba.")
    if signal.get("ok"):
        st.markdown("### Calidad actual del modelo")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Balanced accuracy OOS", f"{signal['best_balanced_accuracy']*100:.1f}%")
        q2.metric("F1 macro", f"{signal['best_f1']*100:.1f}%")
        q3.metric("Brier skill", f"{signal['best_brier_skill']*100:+.1f}%")
        q4.metric("Estado", signal["quality_label"])
        st.caption("La pantalla principal usa un ensemble rápido de 3 modelos/4 folds. Puedes lanzar abajo una auditoría profunda de 5 modelos/5 folds cuando quieras.")

        deep_key = f"deep_signal::{selected}::{timeframe}::{horizon}"
        if st.button("🔬 Auditoría profunda (5 modelos)", key="deep_run"):
            with st.spinner("Comparando 5 modelos con walk-forward; puede tardar... "):
                st.session_state[deep_key] = model_signal(model_df, horizon=horizon, deep=True)
        deep_signal = st.session_state.get(deep_key)
        comparison_source = deep_signal if deep_signal and deep_signal.get("ok") else signal
        if deep_signal and deep_signal.get("ok"):
            st.success(f"Auditoría profunda lista · mejor modelo: {deep_signal['best_model']} · {deep_signal['quality_label']}")

        model_options = list(comparison_source["comparison"].dropna(subset=["brier_score_mean"])["model"])
        if model_options:
            preferred_model = comparison_source.get("best_model")
            bmodel = st.selectbox("Modelo para backtest", model_options, index=model_options.index(preferred_model) if preferred_model in model_options else 0)
            threshold = st.slider("Confianza mínima", 0.45, 0.80, 0.58, 0.01)
            fee_bps = st.number_input("Comisión por lado (bps)", min_value=0.0, max_value=50.0, value=10.0, step=1.0)
            bt_state_key = f"bt_result::{selected}::{timeframe}::{horizon}::{bmodel}::{threshold:.2f}::{fee_bps:.1f}"
            if st.button("🧪 Ejecutar backtest OOS", key="bt_run"):
                labels = triple_barrier_labels(signal["features"], horizon=horizon, k=1.5)
                valid = labels.dropna().shape[0]
                try:
                    trades, equity, metrics = backtest_model_strategy(
                        signal["features"], labels, model_df, FEATURE_COLUMNS, bmodel, horizon,
                        threshold, fee_bps / 10000, n_folds=4, min_train_size=max(140, min(350, valid // 2))
                    )
                    st.session_state[bt_state_key] = (trades, equity, metrics)
                except Exception as e:
                    st.error(f"Backtest no disponible: {e}")

            bt_result = st.session_state.get(bt_state_key)
            if bt_result:
                trades, equity, metrics = bt_result
                k1, k2, k3, k4, k5, k6 = st.columns(6)
                k1.metric("Trades", metrics["trades"])
                k2.metric("Win rate", f"{metrics['win_rate']*100:.1f}%" if pd.notna(metrics["win_rate"]) else "N/A")
                k3.metric("Retorno sim.", f"{metrics['return']*100:+.1f}%")
                k4.metric("Max DD", f"{metrics['max_drawdown']*100:.1f}%" if pd.notna(metrics["max_drawdown"]) else "N/A")
                k5.metric("Profit factor", f"{metrics['profit_factor']:.2f}" if pd.notna(metrics["profit_factor"]) else "N/A")
                k6.metric("Promedio/trade", f"{metrics['avg_trade']*100:+.2f}%" if pd.notna(metrics["avg_trade"]) else "N/A")
                if metrics["trades"] < 20:
                    st.warning("Muestra pequeña: menos de 20 operaciones. No conviene sacar conclusiones fuertes todavía.")
                if not equity.empty:
                    eqfig = go.Figure(go.Scatter(x=equity.timestamp, y=equity.equity, mode="lines", name="Equity"))
                    eqfig.update_layout(template="plotly_dark", height=350, paper_bgcolor="#080b0f", plot_bgcolor="#080b0f", title="Equity curve · fuera de muestra", dragmode="pan", uirevision="equity")
                    st.plotly_chart(eqfig, width="stretch", theme=None, config=plot_config())
                    st.dataframe(trades[["entry_time","exit_time","direction","confidence","entry","exit","exit_reason","return","win"]].tail(100), width="stretch", hide_index=True)
                else:
                    st.warning("No hubo operaciones con el umbral elegido.")

            st.markdown("#### Comparación de modelos")
            cols = [c for c in ["model","n_folds","balanced_accuracy_mean","f1_macro_mean","brier_score_mean","brier_skill_mean","calibrated_folds","error"] if c in comparison_source["comparison"].columns]
            st.dataframe(comparison_source["comparison"][cols], width="stretch", hide_index=True)
            st.caption("Los SHORT del backtest son simulaciones cuantitativas; no incluyen financiación/borrow específico de derivados.")
    else:
        st.info("La validación aparecerá cuando haya suficientes datos.")

with risk_tab:
    st.subheader("Stop Loss + Take Profit + tamaño de posición")
    st.caption("Los niveles usan ATR + estructura reciente. Son referencias cuantitativas, no garantías de ejecución.")
    if signal.get("ok") and signal.get("risk_plan"):
        rp = signal["risk_plan"]
        stop_rows = []
        for opt in [rp.tight, rp.standard, rp.conservative]:
            stop_rows.append({
                "Opción": opt.name, "Stop Loss": opt.price, "Distancia %": round(opt.distance_pct, 2),
                "R:R a TP1": rr_text(opt.rr_to_tp1), "Base": opt.basis,
            })
        st.dataframe(pd.DataFrame(stop_rows), width="stretch", hide_index=True, column_config={"Stop Loss": st.column_config.NumberColumn(format="$%.2f")})
        st.success(f"Recomendado: entrada ${rp.entry:,.2f} · SL ${rp.recommended.price:,.2f} · TP1 ${rp.tp1:,.2f} · TP2 ${rp.tp2:,.2f} · TP3 ${rp.tp3:,.2f} · R:R {rr_text(rp.recommended.rr_to_tp1)}")
        if rp.recommended.distance_pct < .35:
            st.warning("El stop queda muy cerca; el ruido normal puede activarlo.")
        elif rp.recommended.distance_pct > 5:
            st.warning("El stop queda amplio; reduce el tamaño de posición para conservar el mismo riesgo monetario.")
    else:
        st.info("El plan aparece cuando hay una dirección LONG o SHORT. Si dice NO OPERAR/ESPERAR, no fuerza niveles de entrada.")

    st.markdown("---")
    st.subheader("Calculadora de posición")
    capital = st.number_input("Capital", min_value=100.0, value=100000.0, step=1000.0)
    risk_pct = st.slider("Riesgo por operación (%)", 0.1, 5.0, 1.0, 0.1)
    entry_default = float(signal["risk_plan"].entry) if signal.get("ok") and signal.get("risk_plan") else float(model_df.close.iloc[-1])
    entry = st.number_input("Entrada", min_value=0.0, value=entry_default, format="%.6f")
    stop_default = float(signal["risk_plan"].recommended.price) if signal.get("ok") and signal.get("risk_plan") else entry * .98
    stop = st.number_input("Stop Loss", min_value=0.0, value=max(0.0, stop_default), format="%.6f")
    distance = abs(entry - stop)
    risk_money = capital * risk_pct / 100
    units = risk_money / distance if distance > 0 else 0
    position_value = units * entry
    a, b, c = st.columns(3)
    a.metric("Riesgo monetario", f"${risk_money:,.2f}")
    b.metric("Unidades", f"{units:,.6f}")
    c.metric("Valor posición", f"${position_value:,.2f}")
    if position_value > capital * 1.02:
        st.warning("El valor de la posición supera el capital indicado; eso implicaría apalancamiento o una posición no financiable al contado.")
    if entry > 0 and distance > 0:
        st.write(f"Distancia entrada → stop: **{distance / entry * 100:.2f}%**")
        if signal.get("ok") and signal.get("risk_plan"):
            rp = signal["risk_plan"]
            for name, tp in [("TP1", rp.tp1), ("TP2", rp.tp2), ("TP3", rp.tp3)]:
                reward = abs(tp - entry)
                st.write(f"{name}: ganancia potencial **${units * reward:,.2f}** · R:R **{rr_text(reward / distance)}**")
    st.caption("Calculadora matemática. Slippage, gaps, comisiones, apalancamiento, funding y liquidaciones pueden cambiar la pérdida real.")

st.caption("AI Crypto Market Brain PRO · Fase 3.5 radar de velas · Precio LIVE aproximado cada 10 s · Señales sobre velas cerradas · Proyecciones probabilísticas · Sin ejecución de órdenes reales.")
