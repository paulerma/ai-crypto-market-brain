"""Volatility-adaptive triple-barrier labels for UP / FLAT / DOWN.

If both barriers are touched inside the same OHLC candle, the order is unknowable
without lower-timeframe/tick data. Those ambiguous observations are excluded
instead of inventing an order.
"""
import numpy as np
import pandas as pd


def triple_barrier_labels(df: pd.DataFrame, horizon: int, k: float = 1.5,
                           atr_col: str = "atr_14") -> pd.Series:
    n = len(df)
    labels = pd.Series(index=df.index, dtype="float64")
    atr_pct = (df[atr_col] / df["close"]).values
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for t in range(n - horizon):
        if np.isnan(atr_pct[t]) or atr_pct[t] <= 0:
            labels.iloc[t] = np.nan
            continue
        target_up = closes[t] * (1 + k * atr_pct[t])
        target_down = closes[t] * (1 - k * atr_pct[t])
        label = 0
        for j in range(t + 1, min(t + horizon + 1, n)):
            hit_up = highs[j] >= target_up
            hit_down = lows[j] <= target_down
            if hit_up and hit_down:
                label = np.nan
                break
            if hit_up:
                label = 1
                break
            if hit_down:
                label = -1
                break
        labels.iloc[t] = label

    labels.iloc[n - horizon:] = np.nan
    return labels


def build_label_set(df: pd.DataFrame, horizons: dict[str, int], k: float = 1.5) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for name, h in horizons.items():
        out[f"label_{name}"] = triple_barrier_labels(df, horizon=h, k=k)
    return out
