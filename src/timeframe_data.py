"""Utilities for TradingView-style timeframes built from real Binance candles."""
from __future__ import annotations
import pandas as pd


def aggregate_market_bars(df: pd.DataFrame, factor: int, unit: str = "fixed") -> pd.DataFrame:
    """Aggregate source candles without inventing OHLCV data.

    Open=first, High=max, Low=min, Close=last. Volume, quote volume, trades
    and taker volumes are summed. A bar is closed only when all its source bars
    are closed. The leading partial bucket is discarded; the trailing current
    partial bucket is preserved so the chart can show the forming candle.
    """
    if factor <= 1:
        return df.copy()
    x = df.copy().sort_values("timestamp").reset_index(drop=True)
    if x.empty:
        return x
    ts = pd.to_datetime(x["timestamp"], utc=True)
    if unit == "months":
        month_num = ts.dt.year * 12 + (ts.dt.month - 1)
        x["_bucket"] = (month_num // int(factor)).astype("int64")
    else:
        if len(ts) < 2:
            return x.iloc[0:0].copy()
        source_seconds = max(1, int(round((ts.iloc[1] - ts.iloc[0]).total_seconds())))
        target_seconds = source_seconds * int(factor)
        epoch_seconds = (ts.astype("int64") // 1_000_000_000).astype("int64")
        x["_bucket"] = epoch_seconds // target_seconds

    agg = x.groupby("_bucket", sort=True).agg(
        timestamp=("timestamp", "first"),
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), quote_volume=("quote_volume", "sum"), trades=("trades", "sum"),
        taker_base=("taker_base", "sum"), taker_quote=("taker_quote", "sum"),
        is_closed=("is_closed", "all"), _count=("timestamp", "size"),
    ).reset_index(drop=True)
    if len(agg) > 1 and int(agg.iloc[0]["_count"]) < int(factor):
        agg = agg.iloc[1:].reset_index(drop=True)
    return agg.drop(columns=["_count"])
