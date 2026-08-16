"""Candle-by-candle forecast presentation helpers.

The model rows consumed here are *cumulative-horizon* forecasts (e.g. what is
most likely within the next 1, 2, 3, 5 candles). Therefore the module never
claims an exact deterministic candle. It translates the first stable change in
those cumulative horizons into a practical candle window such as +2 to +3.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class TimeframeSpec:
    label: str
    api_interval: str
    approx_minutes: float
    radar_horizons: tuple[int, ...]
    default_history: int
    direct_ai: bool = True
    # If ``source_interval`` differs from ``api_interval`` the app builds the
    # requested TradingView-style timeframe by aggregating Binance candles.
    source_interval: str | None = None
    aggregate_factor: int = 1
    aggregate_unit: str = "fixed"  # fixed | months

    @property
    def fetch_interval(self) -> str:
        return self.source_interval or self.api_interval

    @property
    def is_synthetic(self) -> bool:
        return self.source_interval is not None and self.source_interval != self.api_interval


# TradingView's documented default *time-based* intervals.
# Ticks and Range are intentionally not here because they are activity/price
# based chart types, not timeframes. Binance has native candles for many of the
# values; the missing ones are built by lossless OHLCV aggregation from the
# nearest divisible native interval.
STANDARD_TIMEFRAMES: dict[str, TimeframeSpec] = {
    # Seconds. Charting is supported, but strict ML is disabled: enough
    # independent history would require many thousands of 1-second requests and
    # microstructure noise makes the current feature set inappropriate.
    "1s": TimeframeSpec("1s", "1s", 1/60, (1, 2, 3, 5), 250, direct_ai=False),
    "5s": TimeframeSpec("5s", "5s", 5/60, (1, 2, 3, 5), 250, direct_ai=False, source_interval="1s", aggregate_factor=5),
    "10s": TimeframeSpec("10s", "10s", 10/60, (1, 2, 3, 5), 250, direct_ai=False, source_interval="1s", aggregate_factor=10),
    "15s": TimeframeSpec("15s", "15s", 15/60, (1, 2, 3, 5), 250, direct_ai=False, source_interval="1s", aggregate_factor=15),
    "30s": TimeframeSpec("30s", "30s", 30/60, (1, 2, 3, 5), 250, direct_ai=False, source_interval="1s", aggregate_factor=30),
    "45s": TimeframeSpec("45s", "45s", 45/60, (1, 2, 3, 5), 250, direct_ai=False, source_interval="1s", aggregate_factor=45),

    # Minutes.
    "1m": TimeframeSpec("1m", "1m", 1, (1, 2, 3, 5), 3000),
    "2m": TimeframeSpec("2m", "2m", 2, (1, 2, 3, 5), 2600, source_interval="1m", aggregate_factor=2),
    "3m": TimeframeSpec("3m", "3m", 3, (1, 2, 3, 5), 2800),
    "5m": TimeframeSpec("5m", "5m", 5, (1, 2, 3, 5), 3000),
    "10m": TimeframeSpec("10m", "10m", 10, (1, 2, 3, 5), 2600, source_interval="5m", aggregate_factor=2),
    "15m": TimeframeSpec("15m", "15m", 15, (1, 2, 3, 5), 3000),
    "30m": TimeframeSpec("30m", "30m", 30, (1, 2, 3, 5), 2800),
    "45m": TimeframeSpec("45m", "45m", 45, (1, 2, 3, 5), 2400, source_interval="15m", aggregate_factor=3),

    # Hours.
    "1h": TimeframeSpec("1h", "1h", 60, (1, 2, 3, 5), 2200),
    "2h": TimeframeSpec("2h", "2h", 120, (1, 2, 3, 5), 2000),
    "3h": TimeframeSpec("3h", "3h", 180, (1, 2, 3, 5), 1800, source_interval="1h", aggregate_factor=3),
    "4h": TimeframeSpec("4h", "4h", 240, (1, 2, 3, 5), 1700),

    # Higher TradingView defaults.
    "1D": TimeframeSpec("1D", "1d", 1440, (1, 2, 3, 5), 1000),
    "1W": TimeframeSpec("1W", "1w", 10080, (1, 2, 3, 4), 520),
    "1M": TimeframeSpec("1M", "1M", 43200, (1, 2, 3), 180, direct_ai=False),
    "3M": TimeframeSpec("3M", "3M", 129600, (1, 2, 3), 120, direct_ai=False, source_interval="1M", aggregate_factor=3, aggregate_unit="months"),
    "6M": TimeframeSpec("6M", "6M", 259200, (1, 2), 80, direct_ai=False, source_interval="1M", aggregate_factor=6, aggregate_unit="months"),
    "12M": TimeframeSpec("12M", "12M", 525960, (1, 2), 50, direct_ai=False, source_interval="1M", aggregate_factor=12, aggregate_unit="months"),
}


def candle_time_text(timeframe: str, bars: int) -> str:
    spec = STANDARD_TIMEFRAMES[timeframe]
    total_seconds = spec.approx_minutes * 60 * int(bars)
    if timeframe in ("1M", "3M", "6M", "12M"):
        months = int(round(spec.approx_minutes / 43200)) * int(bars)
        return f"~{months} mes" if months == 1 else f"~{months} meses"
    if total_seconds < 60:
        seconds = int(round(total_seconds))
        return f"{seconds} s"
    total = total_seconds / 60
    if total < 60:
        return f"{total:g} min"
    if total < 1440:
        return f"{total/60:g} h"
    if total < 10080:
        return f"{total/1440:g} días"
    return f"{total/10080:g} semanas"


def candle_window_text(timeframe: str, start_bar: int, end_bar: int) -> str:
    if start_bar == end_bar:
        return f"vela +{end_bar} ({candle_time_text(timeframe, end_bar)})"
    return f"velas +{start_bar} a +{end_bar} ({candle_time_text(timeframe, start_bar)}–{candle_time_text(timeframe, end_bar)})"


def future_time(now_local: datetime, timeframe: str, bars: int) -> datetime:
    spec = STANDARD_TIMEFRAMES[timeframe]
    return now_local + timedelta(minutes=spec.approx_minutes * int(bars))


def dominant_from_row(row: dict[str, Any]) -> tuple[str, float, float]:
    vals = {
        "SUBIDA": float(row.get("pup", 0.0)),
        "LATERAL": float(row.get("pflat", 0.0)),
        "BAJADA": float(row.get("pdown", 0.0)),
    }
    ordered = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[0][0], ordered[0][1], ordered[0][1] - ordered[1][1]


def infer_candle_onset(
    rows: list[dict[str, Any]],
    scenario: str | None = None,
    min_probability: float = 0.45,
    min_margin: float = 0.06,
) -> dict[str, Any] | None:
    """Find the first stable candle-window where a scenario becomes dominant."""
    valid = [r for r in rows if r.get("ok")]
    valid.sort(key=lambda r: int(r["bars"]))
    if not valid:
        return None

    previous_bar = 0
    for i, row in enumerate(valid):
        dom = row.get("dominant")
        if scenario is not None and dom != scenario:
            previous_bar = int(row["bars"])
            continue
        good = (
            row.get("reliability") in ("MEDIA", "ALTA")
            and float(row.get("probability", 0.0)) >= min_probability
            and float(row.get("margin", 0.0)) >= min_margin
        )
        if not good:
            previous_bar = int(row["bars"])
            continue

        persists = False
        if i + 1 < len(valid):
            nxt = valid[i + 1]
            persists = (
                nxt.get("dominant") == dom
                and nxt.get("reliability") in ("MEDIA", "ALTA")
                and float(nxt.get("probability", 0.0)) >= min_probability
            )
        strong = (
            row.get("reliability") == "ALTA"
            and float(row.get("probability", 0.0)) >= 0.57
            and float(row.get("margin", 0.0)) >= 0.10
        )
        if persists or strong:
            end_bar = int(row["bars"])
            start_bar = max(1, previous_bar + 1)
            return {
                "scenario": dom,
                "start_bar": start_bar,
                "end_bar": end_bar,
                "probability": float(row["probability"]),
                "reliability": row.get("reliability", "BAJA"),
                "row": row,
            }
        previous_bar = int(row["bars"])
    return None


def best_candle_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most useful onset candidate, preferring directional changes."""
    candidates = []
    for sc in ("SUBIDA", "BAJADA", "LATERAL"):
        c = infer_candle_onset(rows, sc)
        if c:
            rank = (0 if sc in ("SUBIDA", "BAJADA") else 1, c["end_bar"], -c["probability"])
            candidates.append((rank, c))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x[0])[0][1]
