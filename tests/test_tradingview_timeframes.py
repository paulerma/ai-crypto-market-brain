import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from candle_forecast import STANDARD_TIMEFRAMES, candle_time_text
from timeframe_data import aggregate_market_bars


def _sample_1m(n=6):
    ts = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="1min")
    return pd.DataFrame({
        "timestamp": ts,
        "open": range(1, n+1),
        "high": [x+1 for x in range(1, n+1)],
        "low": [x-1 for x in range(1, n+1)],
        "close": [x+0.5 for x in range(1, n+1)],
        "volume": [10.0]*n,
        "quote_volume": [100.0]*n,
        "trades": [5]*n,
        "taker_base": [6.0]*n,
        "taker_quote": [60.0]*n,
        "is_closed": [True]*n,
    })


def test_all_tradingview_default_time_intervals_present():
    expected = [
        "1s","5s","10s","15s","30s","45s",
        "1m","2m","3m","5m","10m","15m","30m","45m",
        "1h","2h","3h","4h","1D","1W","1M","3M","6M","12M",
    ]
    assert list(STANDARD_TIMEFRAMES) == expected


def test_two_minute_aggregation_preserves_ohlcv_semantics():
    out = aggregate_market_bars(_sample_1m(), 2)
    assert len(out) == 3
    first = out.iloc[0]
    assert first.open == 1
    assert first.high == 3
    assert first.low == 0
    assert first.close == 2.5
    assert first.volume == 20
    assert first.trades == 10
    assert bool(first.is_closed)


def test_seconds_are_human_readable():
    assert candle_time_text("15s", 1) == "15 s"
    assert candle_time_text("15s", 3) == "45 s"
