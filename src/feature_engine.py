"""Advanced feature engine for crypto OHLCV.

The engine deliberately mixes trend, momentum, volatility, volume and market
structure features. More indicators are not assumed to be better: downstream
models perform feature selection *inside* the training pipeline and are judged
strictly out-of-sample with walk-forward validation.
"""
import numpy as np
import pandas as pd

EPS = 1e-12


def _safe_div(a, b):
    return a / pd.Series(b).replace(0, np.nan).values if not isinstance(b, pd.Series) else a / b.replace(0, np.nan)


def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ret_1"] = df["close"].pct_change(1)
    df["ret_3"] = df["close"].pct_change(3)
    df["ret_7"] = df["close"].pct_change(7)
    df["ret_14"] = df["close"].pct_change(14)
    df["ret_30"] = df["close"].pct_change(30)
    df["log_ret_1"] = np.log(df["close"] / df["close"].shift(1))

    for w in (5, 10, 20, 50, 100, 200):
        df[f"sma_{w}"] = df["close"].rolling(w).mean()
        df[f"dist_sma_{w}"] = (df["close"] - df[f"sma_{w}"]) / df[f"sma_{w}"]
    for w in (9, 20, 50, 100, 200):
        df[f"ema_{w}"] = df["close"].ewm(span=w, adjust=False).mean()
        df[f"dist_ema_{w}"] = (df["close"] - df[f"ema_{w}"]) / df[f"ema_{w}"]

    # Trend slopes: percent change of averages over recent bars.
    df["ema20_slope_5"] = df["ema_20"].pct_change(5)
    df["ema50_slope_10"] = df["ema_50"].pct_change(10)
    df["ema200_slope_20"] = df["ema_200"].pct_change(20)

    for w in (20, 50):
        hi = df["high"].rolling(w).max()
        lo = df["low"].rolling(w).min()
        df[f"high_{w}"] = hi
        df[f"low_{w}"] = lo
        df[f"dist_high_{w}"] = (df["close"] - hi) / hi
        df[f"dist_low_{w}"] = (df["close"] - lo) / lo
        df[f"range_pos_{w}"] = (df["close"] - lo) / (hi - lo).replace(0, np.nan)

    # Candle anatomy / price action.
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = df["close"] - df["open"]
    df["body_pct_range"] = body.abs() / rng
    df["upper_wick_pct"] = (df["high"] - df[["open", "close"]].max(axis=1)) / rng
    df["lower_wick_pct"] = (df[["open", "close"]].min(axis=1) - df["low"]) / rng
    df["close_location"] = (df["close"] - df["low"]) / rng

    # Time-of-day / day-of-week are known at decision time and can capture
    # recurring 24/7 crypto liquidity patterns without peeking into the future.
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        hour = ts.dt.hour + ts.dt.minute / 60.0
        dow = ts.dt.dayofweek.astype(float)
        df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
        df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
        df["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
        df["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
        df["is_weekend"] = (dow >= 5).astype(float)
    else:
        for col in ("hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend"):
            df[col] = np.nan
    return df


def add_volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    prev = df["close"].shift(1)
    df["tr"] = np.maximum(df["high"] - df["low"], np.maximum((df["high"] - prev).abs(), (df["low"] - prev).abs()))
    df["atr_14"] = df["tr"].ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"]
    df["realized_vol_14"] = df["log_ret_1"].rolling(14).std()
    df["realized_vol_30"] = df["log_ret_1"].rolling(30).std()
    df["vol_of_vol"] = df["realized_vol_14"].rolling(14).std()
    df["atr_z_100"] = (df["atr_pct"] - df["atr_pct"].rolling(100).mean()) / df["atr_pct"].rolling(100).std()

    # Parkinson range volatility, useful when intrabar ranges carry information.
    hl = np.log(df["high"] / df["low"].replace(0, np.nan)) ** 2
    df["parkinson_vol_20"] = np.sqrt(hl.rolling(20).mean() / (4 * np.log(2)))
    return df


def add_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    rsi_min = df["rsi_14"].rolling(14).min(); rsi_max = df["rsi_14"].rolling(14).max()
    df["stoch_rsi"] = (df["rsi_14"] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    df["stoch_rsi_k"] = df["stoch_rsi"].rolling(3).mean()
    df["stoch_rsi_d"] = df["stoch_rsi_k"].rolling(3).mean()

    ema12 = df["close"].ewm(span=12, adjust=False).mean(); ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_hist_delta"] = df["macd_hist"].diff()
    # Price-normalized MACD features are more stable across long price regimes.
    df["macd_pct"] = df["macd"] / df["close"]
    df["macd_signal_pct"] = df["macd_signal"] / df["close"]
    df["macd_hist_pct"] = df["macd_hist"] / df["close"]
    df["macd_hist_delta_pct"] = df["macd_hist_pct"].diff()

    sma20 = df["close"].rolling(20).mean(); std20 = df["close"].rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20; df["bb_lower"] = sma20 - 2 * std20
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma20
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

    # Rate of change and Williams %R.
    df["roc_10"] = df["close"].pct_change(10)
    hh14 = df["high"].rolling(14).max(); ll14 = df["low"].rolling(14).min()
    df["williams_r_14"] = -100 * (hh14 - df["close"]) / (hh14 - ll14).replace(0, np.nan)

    # CCI.
    tp = (df["high"] + df["low"] + df["close"]) / 3
    tp_ma = tp.rolling(20).mean(); mad = (tp - tp_ma).abs().rolling(20).mean()
    df["cci_20"] = (tp - tp_ma) / (0.015 * mad.replace(0, np.nan))
    return df


def add_trend_strength_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    up_move = df["high"].diff(); down_move = -df["low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    atr = df["atr_14"].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["plus_di_14"] = plus_di; df["minus_di_14"] = minus_di
    df["adx_14"] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    df["di_spread"] = (plus_di - minus_di) / 100.0

    # Keltner / squeeze context.
    mid = df["ema_20"]
    df["kc_upper"] = mid + 2 * df["atr_14"]; df["kc_lower"] = mid - 2 * df["atr_14"]
    df["bb_inside_kc"] = ((df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])).astype(float)

    # Supertrend-like distance (transparent ATR band, not a stateful black box).
    hl2 = (df["high"] + df["low"]) / 2
    df["atr_band_upper"] = hl2 + 3 * df["atr_14"]
    df["atr_band_lower"] = hl2 - 3 * df["atr_14"]
    df["dist_atr_upper"] = (df["close"] - df["atr_band_upper"]) / df["close"]
    df["dist_atr_lower"] = (df["close"] - df["atr_band_lower"]) / df["close"]
    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df["volume"].isna().all():
        for col in ("vol_rel_20", "vol_change_1", "obv_norm", "vwap_dist", "cmf_20", "mfi_14", "volume_z_50"):
            df[col] = np.nan
        return df

    df["vol_sma_20"] = df["volume"].rolling(20).mean()
    df["vol_rel_20"] = df["volume"] / df["vol_sma_20"].replace(0, np.nan)
    df["vol_change_1"] = df["volume"].pct_change(1)
    df["volume_z_50"] = (df["volume"] - df["volume"].rolling(50).mean()) / df["volume"].rolling(50).std()

    direction = np.sign(df["close"].diff()).fillna(0)
    df["obv"] = (direction * df["volume"]).cumsum()
    obv_scale = df["obv"].rolling(50).std()
    df["obv_norm"] = (df["obv"] - df["obv"].rolling(50).mean()) / obv_scale.replace(0, np.nan)

    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    # Rolling VWAP keeps the feature usable on all timeframes without assuming a session boundary.
    df["vwap_50"] = pv.rolling(50).sum() / df["volume"].rolling(50).sum().replace(0, np.nan)
    df["vwap_dist"] = (df["close"] - df["vwap_50"]) / df["vwap_50"]

    mf_mult = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    mfv = mf_mult * df["volume"]
    df["cmf_20"] = mfv.rolling(20).sum() / df["volume"].rolling(20).sum().replace(0, np.nan)

    pos_flow = pv.where(typical.diff() > 0, 0.0); neg_flow = pv.where(typical.diff() < 0, 0.0)
    ratio = pos_flow.rolling(14).sum() / neg_flow.rolling(14).sum().replace(0, np.nan)
    df["mfi_14"] = 100 - 100 / (1 + ratio)

    # Binance klines expose additional public microstructure fields. They are
    # optional so CoinGecko/legacy data remain compatible. Feature selection is
    # still performed inside each training fold, so adding them does not force
    # the model to use them.
    optional = {
        "quote_volume": "quote_vol_rel_20",
        "trades": "trades_rel_20",
    }
    for raw_col, out_col in optional.items():
        if raw_col in df.columns and not df[raw_col].isna().all():
            base = pd.to_numeric(df[raw_col], errors="coerce")
            df[out_col] = base / base.rolling(20).mean().replace(0, np.nan)
        else:
            df[out_col] = np.nan

    if "taker_base" in df.columns and not df["taker_base"].isna().all():
        taker = pd.to_numeric(df["taker_base"], errors="coerce")
        df["taker_buy_ratio"] = taker / df["volume"].replace(0, np.nan)
        df["taker_imbalance"] = 2.0 * df["taker_buy_ratio"] - 1.0
    else:
        df["taker_buy_ratio"] = np.nan
        df["taker_imbalance"] = np.nan

    if "quote_volume" in df.columns and "trades" in df.columns:
        qv = pd.to_numeric(df["quote_volume"], errors="coerce")
        trn = pd.to_numeric(df["trades"], errors="coerce").replace(0, np.nan)
        avg_trade = qv / trn
        df["avg_trade_quote_rel_20"] = avg_trade / avg_trade.rolling(20).mean().replace(0, np.nan)
    else:
        df["avg_trade_quote_rel_20"] = np.nan
    return df


def build_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv.sort_values("timestamp").reset_index(drop=True).copy()
    df = add_price_features(df)
    df = add_volatility_features(df)
    df = add_momentum_features(df)
    df = add_trend_strength_features(df)
    df = add_volume_features(df)
    return df.replace([np.inf, -np.inf], np.nan)


FEATURE_COLUMNS = [
    # returns / structure
    "ret_1","ret_3","ret_7","ret_14","ret_30",
    "dist_sma_20","dist_sma_50","dist_sma_100","dist_sma_200",
    "dist_ema_9","dist_ema_20","dist_ema_50","dist_ema_100","dist_ema_200",
    "ema20_slope_5","ema50_slope_10","ema200_slope_20",
    "dist_high_20","dist_low_20","range_pos_20","dist_high_50","dist_low_50","range_pos_50",
    "body_pct_range","upper_wick_pct","lower_wick_pct","close_location",
    "hour_sin","hour_cos","dow_sin","dow_cos","is_weekend",
    # volatility
    "atr_pct","realized_vol_14","realized_vol_30","vol_of_vol","atr_z_100","parkinson_vol_20",
    # momentum / trend strength
    "rsi_14","stoch_rsi_k","stoch_rsi_d","macd_pct","macd_signal_pct","macd_hist_pct","macd_hist_delta_pct",
    "bb_width","bb_pct","roc_10","williams_r_14","cci_20","adx_14","di_spread","bb_inside_kc",
    "dist_atr_upper","dist_atr_lower",
    # volume
    "vol_rel_20","vol_change_1","volume_z_50","obv_norm","vwap_dist","cmf_20","mfi_14",
    "quote_vol_rel_20","trades_rel_20","taker_buy_ratio","taker_imbalance","avg_trade_quote_rel_20",
]
