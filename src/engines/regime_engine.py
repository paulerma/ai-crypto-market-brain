from dataclasses import dataclass
import pandas as pd

@dataclass
class RegimeState:
    regime: str
    phase: str
    rsi: float
    adx: float
    ema200_distance: float
    vwap_distance: float
    realized_vol_30: float


def classify_regime(row: pd.Series) -> RegimeState:
    rsi = float(row.get("rsi_14", float("nan")))
    adx = float(row.get("adx_14", float("nan")))
    e20 = float(row.get("dist_ema_20", 0)); e50 = float(row.get("dist_ema_50", 0)); e200 = float(row.get("dist_ema_200", 0))
    slope = float(row.get("ema200_slope_20", 0)); vwap = float(row.get("vwap_dist", 0))
    trend_strength = adx >= 20 if pd.notna(adx) else False
    bull = e20 > e50 and e200 > 0 and slope >= 0
    bear = e20 < e50 and e200 < 0 and slope <= 0
    if bull and rsi >= 48:
        regime = "ALCISTA"
        phase = "TENDENCIA FUERTE" if trend_strength and rsi > 55 else "ALCISTA / ACUMULACIÓN"
    elif bear and rsi <= 52:
        regime = "BAJISTA"
        phase = "TENDENCIA FUERTE" if trend_strength and rsi < 45 else "BAJISTA / DISTRIBUCIÓN"
    else:
        regime = "LATERAL"
        phase = "COMPRESIÓN" if float(row.get("bb_inside_kc", 0)) > 0 else "CONSOLIDACIÓN / TRANSICIÓN"
    return RegimeState(regime, phase, rsi, adx, e200, vwap, float(row.get("realized_vol_30", float("nan"))))


def regime_series(features: pd.DataFrame) -> pd.Series:
    return features.apply(lambda row: classify_regime(row).regime, axis=1)
