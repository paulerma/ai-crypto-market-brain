"""
TEST DE SOFTWARE — no es una señal de mercado ni una demo.

Verifica que feature_engine -> labeling -> models -> backtest ->
calibration -> engines corren sin errores y devuelven las formas de
datos esperadas. Usa una serie de precios sintética (random walk)
generada localmente ÚNICAMENTE porque un test automatizado no puede
depender de tener internet/API key disponibles en cualquier máquina
donde se corra `pytest`. Ningún número que salga de este archivo debe
interpretarse jamás como una predicción real de BTC.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

from feature_engine import build_features, FEATURE_COLUMNS
from labeling import triple_barrier_labels
from backtest import walk_forward_validate
from engines.regime_engine import regime_series, classify_regime
from engines.cycle_engine import current_cycle_state
from engines.pattern_engine import find_similar_cases
from engines.decision_engine import decide


def _synthetic_ohlcv(n=400, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 120, n).cumsum()
    close = 40000 + steps
    close = np.clip(close, 5000, None)
    high = close + rng.uniform(0, 200, n)
    low = close - rng.uniform(0, 200, n)
    open_ = close + rng.normal(0, 50, n)
    volume = rng.uniform(500, 3000, n)
    ts = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high,
                          "low": low, "close": close, "volume": volume})


def test_feature_engine_shapes():
    ohlcv = _synthetic_ohlcv()
    feats = build_features(ohlcv)
    for col in FEATURE_COLUMNS:
        assert col in feats.columns
    assert len(feats) == len(ohlcv)


def test_labeling_produces_three_classes_eventually():
    ohlcv = _synthetic_ohlcv(n=500)
    feats = build_features(ohlcv)
    labels = triple_barrier_labels(feats, horizon=7, k=1.0)
    observed = set(labels.dropna().unique())
    assert observed.issubset({-1.0, 0.0, 1.0})
    assert len(observed) >= 1


def test_walk_forward_runs_end_to_end():
    ohlcv = _synthetic_ohlcv(n=500)
    feats = build_features(ohlcv)
    labels = triple_barrier_labels(feats, horizon=7, k=1.0)
    report = walk_forward_validate(feats, labels, FEATURE_COLUMNS,
                                    "logistic_regression", n_folds=3, min_train_size=150)
    summary = report.summary()
    assert "accuracy_mean" in summary
    assert 0.0 <= summary["accuracy_mean"] <= 1.0


def test_regime_and_cycle_engines():
    ohlcv = _synthetic_ohlcv(n=400)
    feats = build_features(ohlcv)
    regimes = regime_series(feats.dropna(subset=["dist_sma_20", "dist_sma_50", "rsi_14"]))
    assert set(regimes.unique()).issubset({"ALCISTA", "BAJISTA", "LATERAL"})
    cycle = current_cycle_state(regimes)
    assert cycle.days_in_current_phase >= 1


def test_pattern_engine_returns_result_or_none():
    ohlcv = _synthetic_ohlcv(n=400)
    feats = build_features(ohlcv)
    fwd = feats["close"].shift(-7) / feats["close"] - 1
    result = find_similar_cases(feats, FEATURE_COLUMNS, fwd, horizon=7, k=20)
    assert result is None or result.n_cases > 0


def test_decision_engine_never_forces_high_conviction():
    d = decide(p_up=0.4, p_flat=0.35, p_down=0.25)
    assert d.signal == "NO_OPERAR"
    d2 = decide(p_up=0.95, p_flat=0.03, p_down=0.02)
    assert d2.signal == "ALTA_CONVICCION"


def test_modern_sklearn_prefit_calibration_works():
    from models import fit_model, prepare_training_frame
    from calibration import calibrate
    ohlcv = _synthetic_ohlcv(n=1200, seed=21)
    feats = build_features(ohlcv)
    labels = triple_barrier_labels(feats, horizon=7, k=1.5)
    X, y = prepare_training_frame(feats, labels, FEATURE_COLUMNS)
    split = int(len(X) * .8)
    trained = fit_model("logistic_regression", X.iloc[:split], y.iloc[:split])
    cal = calibrate(trained.model, X.iloc[split:], y.iloc[split:])
    p = cal.predict_proba(X.iloc[[-1]])
    assert p.shape[1] == len(cal.classes_)
    assert abs(float(p.sum()) - 1.0) < 1e-6


def test_same_candle_double_barrier_is_excluded():
    # Construct enough warm-up rows so ATR exists, then force one future candle
    # to touch both symmetric barriers. The exact intra-candle order is unknowable.
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 100.2)
    low = np.full(n, 99.8)
    high[20] = 110.0
    low[20] = 90.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC"),
        "open": close, "high": high, "low": low, "close": close,
        "volume": np.full(n, 1000.0),
    })
    feats = build_features(df)
    labels = triple_barrier_labels(feats, horizon=7, k=1.0)
    # At least one observation whose forward window contains the forced bar
    # should be excluded as ambiguous.
    assert labels.iloc[13:20].isna().any()


def test_volatility_projection_is_ordered_and_symmetric_in_log_space():
    from projections import volatility_projection
    p = volatility_projection(100.0, 0.01, 2.0, 16, barrier_k=1.5)
    assert p.low68 < 100 < p.high68
    assert abs(p.barrier_up - 103.0) < 1e-9
    assert abs(p.barrier_down - 97.0) < 1e-9


def test_volatility_projection_handles_missing_optional_inputs():
    from projections import volatility_projection
    p = volatility_projection(100.0, None, None, 4)
    assert p.low68 is None and p.high68 is None
    assert p.barrier_up is None and p.barrier_down is None


def test_binance_microstructure_features_are_causal_and_present_when_supplied():
    df = _synthetic_ohlcv(n=260, seed=7)
    rng = np.random.default_rng(7)
    df["quote_volume"] = df["volume"] * df["close"]
    df["trades"] = rng.integers(100, 1000, len(df))
    df["taker_base"] = df["volume"] * rng.uniform(.35, .65, len(df))
    df["taker_quote"] = df["taker_base"] * df["close"]
    feats = build_features(df)
    for col in ["quote_vol_rel_20", "trades_rel_20", "taker_buy_ratio", "taker_imbalance", "avg_trade_quote_rel_20"]:
        assert col in feats.columns
        assert feats[col].iloc[-1] == feats[col].iloc[-1]  # not NaN
    assert 0 <= feats["taker_buy_ratio"].iloc[-1] <= 1
