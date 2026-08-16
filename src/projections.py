"""Transparent probabilistic projection helpers.

These are scenario ranges, not point forecasts. The statistical band assumes
per-bar log-return volatility scales with sqrt(time), and the barrier levels
match the app's triple-barrier labeling convention.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ProjectionBand:
    low68: float | None
    high68: float | None
    barrier_up: float | None
    barrier_down: float | None


def volatility_projection(price: float, per_bar_log_vol: float | None,
                          atr: float | None, horizon_bars: int,
                          barrier_k: float = 1.5) -> ProjectionBand:
    if price <= 0:
        raise ValueError("price must be positive")
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be >= 1")

    low68 = high68 = None
    if per_bar_log_vol is not None and math.isfinite(per_bar_log_vol) and per_bar_log_vol > 0:
        width = per_bar_log_vol * math.sqrt(horizon_bars)
        low68 = price * math.exp(-width)
        high68 = price * math.exp(width)

    barrier_up = barrier_down = None
    if atr is not None and math.isfinite(atr) and atr > 0:
        barrier_up = price + barrier_k * atr
        barrier_down = max(0.0, price - barrier_k * atr)

    return ProjectionBand(low68, high68, barrier_up, barrier_down)
