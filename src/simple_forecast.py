"""Simple, user-facing scenario projections and conditional risk plans.

The functions in this module intentionally separate:
1) probabilistic scenario ranges (up / flat / down), and
2) conditional breakout plans (confirmation + stop + target).

They do not claim an exact future price and they do not rewrite the model's
probabilities. They only translate the existing volatility band and recent
price structure into simpler ranges a non-technical user can read.
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ScenarioZone:
    name: str
    probability: float
    low: float
    high: float

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(frozen=True)
class ConditionalPlan:
    direction: str
    confirmation: float
    stop: float
    target_low: float
    target_high: float
    risk_reward: float | None
    valid: bool
    note: str


@dataclass(frozen=True)
class SimpleForecast:
    dominant: str
    up: ScenarioZone
    flat: ScenarioZone
    down: ScenarioZone
    long_plan: ConditionalPlan
    short_plan: ConditionalPlan


def _safe_move(price: float, band_edge: float | None, atr: float | None, horizon_bars: int, upside: bool) -> float:
    move = None
    if band_edge is not None and math.isfinite(float(band_edge)):
        move = float(band_edge) - price if upside else price - float(band_edge)
    if move is None or move <= 0:
        atr_move = float(atr) * max(1.0, math.sqrt(max(1, horizon_bars) / 4.0)) if atr is not None and math.isfinite(float(atr)) and atr > 0 else 0.0
        move = max(price * 0.01, atr_move)
    return max(float(move), price * 0.001)


def build_simple_forecast(
    df: pd.DataFrame,
    price: float,
    p_up: float,
    p_flat: float,
    p_down: float,
    low68: float | None,
    high68: float | None,
    atr: float | None,
    horizon_bars: int,
    lookback: int = 24,
) -> SimpleForecast:
    if price <= 0:
        raise ValueError("price must be positive")
    if df.empty:
        raise ValueError("df must not be empty")
    if not {"high", "low"}.issubset(df.columns):
        raise ValueError("df must contain high and low columns")

    up_move = _safe_move(price, high68, atr, horizon_bars, True)
    down_move = _safe_move(price, low68, atr, horizon_bars, False)

    # The outer edges come from the existing ~68% statistical band. The inner
    # edges make the three scenarios visually distinct without pretending the
    # model knows one exact future price.
    up = ScenarioZone("SUBIDA", float(p_up), price + 0.45 * up_move, price + up_move)
    flat = ScenarioZone("LATERAL", float(p_flat), max(0.0, price - 0.28 * down_move), price + 0.28 * up_move)
    down = ScenarioZone("BAJADA", float(p_down), max(0.0, price - down_move), max(0.0, price - 0.45 * down_move))

    probs = {"SUBIDA": float(p_up), "LATERAL": float(p_flat), "BAJADA": float(p_down)}
    dominant = max(probs, key=probs.get)

    recent = df.tail(max(5, min(int(lookback), len(df))))
    recent_high = float(recent["high"].max())
    recent_low = float(recent["low"].min())
    atr_v = float(atr) if atr is not None and math.isfinite(float(atr)) and atr > 0 else price * 0.01
    buffer = 0.15 * atr_v

    # Long breakout plan: confirmation above recent structure; stop back below
    # the broken area / ATR. Target remains the scenario projection, never
    # altered merely to manufacture a good R:R.
    up_confirm = max(price + 0.10 * atr_v, recent_high + buffer)
    up_stop = max(0.0, min(up_confirm - 1.50 * atr_v, recent_high - 0.45 * atr_v))
    up_target_low = max(up.low, up_confirm)
    up_target_high = up.high
    up_valid = bool(up_target_high > up_confirm and up_stop < up_confirm)
    up_rr = None
    if up_valid:
        risk = up_confirm - up_stop
        reward = up_target_high - up_confirm
        up_rr = reward / risk if risk > 0 else None
    if not up_valid:
        up_note = "La ruptura quedaría demasiado cerca o por encima del rango proyectado; mejor no perseguir el precio."
    elif up_rr is not None and up_rr < 1.5:
        up_note = "R:R proyectado bajo; conviene esperar una mejor entrada o una proyección más amplia."
    else:
        up_note = "Plan condicional: solo aplica si el precio rompe y sostiene el nivel de confirmación."

    # Short / bearish-breakdown plan mirrors the logic. In spot, this is useful
    # primarily as a risk/exit warning unless the venue supports short exposure.
    down_confirm = min(price - 0.10 * atr_v, recent_low - buffer)
    down_stop = max(down_confirm + 1.50 * atr_v, recent_low + 0.45 * atr_v)
    down_target_low = down.low
    down_target_high = min(down.high, down_confirm)
    down_valid = bool(down_target_low < down_confirm and down_stop > down_confirm)
    down_rr = None
    if down_valid:
        risk = down_stop - down_confirm
        reward = down_confirm - down_target_low
        down_rr = reward / risk if risk > 0 else None
    if not down_valid:
        down_note = "La ruptura bajista quedaría demasiado cerca o por debajo del rango proyectado; mejor no perseguir el movimiento."
    elif down_rr is not None and down_rr < 1.5:
        down_note = "R:R proyectado bajo; conviene esperar una mejor entrada o una proyección más amplia."
    else:
        down_note = "Plan condicional: solo aplica si el precio pierde y sostiene el nivel de confirmación."

    long_plan = ConditionalPlan("SUBIDA", up_confirm, up_stop, up_target_low, up_target_high, up_rr, up_valid, up_note)
    short_plan = ConditionalPlan("BAJADA", down_confirm, down_stop, down_target_low, down_target_high, down_rr, down_valid, down_note)
    return SimpleForecast(dominant, up, flat, down, long_plan, short_plan)
