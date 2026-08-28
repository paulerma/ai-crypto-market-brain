"""Historical-analogue engine for current-state projections.

Important leakage fix versus the early prototype:
- The scaler and nearest-neighbour index are fit on *historical rows only*.
- The current feature vector is transformed separately and never requires a
  future return, so the current state is genuinely the state being queried.
- Recent rows whose forward outcome is not yet known are naturally excluded.

The result is a complementary sanity check, not a replacement for the main ML
probabilities. It is deliberately kept interpretable.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors


# A compact set reduces curse-of-dimensionality risk for k-NN analogues.
ANALOG_FEATURE_COLUMNS = [
    "ret_3", "ret_14", "dist_ema_20", "dist_ema_200",
    "atr_pct", "realized_vol_30", "rsi_14", "macd_hist_pct",
    "bb_pct", "adx_14", "di_spread", "vol_rel_20", "vwap_dist",
]


@dataclass
class SimilarCasesResult:
    n_cases: int
    up_pct: float
    flat_pct: float
    down_pct: float
    mean_forward_return: float
    max_forward_return: float
    min_forward_return: float
    horizon: int
    median_forward_return: float = float("nan")
    q10_forward_return: float = float("nan")
    q25_forward_return: float = float("nan")
    q75_forward_return: float = float("nan")
    q90_forward_return: float = float("nan")
    scenario_quantiles: dict = field(default_factory=dict)

    @property
    def dominant(self) -> str:
        vals = {"SUBIDA": self.up_pct, "LATERAL": self.flat_pct, "BAJADA": self.down_pct}
        return max(vals, key=vals.get)


def _scenario_quantiles(values: np.ndarray) -> dict | None:
    if len(values) < 5:
        return None
    q = np.quantile(values, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {"n": int(len(values)), "q10": float(q[0]), "q25": float(q[1]),
            "q50": float(q[2]), "q75": float(q[3]), "q90": float(q[4])}


def find_similar_cases(features: pd.DataFrame, feature_columns: list[str] | None,
                       forward_returns: pd.Series, horizon: int,
                       k: int = 40, flat_threshold: float = 0.02) -> SimilarCasesResult | None:
    """Find historical states nearest to the *current* state.

    `forward_returns` should be realized return from t to t+horizon, aligned to
    `features`. A scenario-specific return distribution is returned when enough
    comparable cases exist.
    """
    if features.empty:
        return None
    cols = [c for c in (feature_columns or ANALOG_FEATURE_COLUMNS) if c in features.columns]
    if not cols:
        return None

    history = features[cols].join(forward_returns.rename("fwd_ret"))
    history = history.dropna(subset=["fwd_ret"])
    if len(history) < max(20, min(k, 30)):
        return None
    # Drop optional columns that have no historical observations (for example
    # Binance-only microstructure fields when the source is CoinGecko).
    cols = [c for c in cols if history[c].notna().any()]
    if not cols:
        return None
    current = features.iloc[[-1]][cols].copy()
    history = history[cols + ["fwd_ret"]]

    # Require enough observable features; impute only the remainder from the
    # historical training population, never from the current/future outcome.
    min_non_na = max(5, int(len(cols) * 0.70))
    history = history[history[cols].notna().sum(axis=1) >= min_non_na]
    if len(history) < 20 or current[cols].notna().sum(axis=1).iloc[0] < min_non_na:
        return None

    imp = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    X_hist = imp.fit_transform(history[cols])
    X_hist = scaler.fit_transform(X_hist)
    X_current = scaler.transform(imp.transform(current[cols]))

    kk = min(int(k), len(history))
    # Ask for extra candidates, then de-cluster temporally adjacent matches so
    # one historical episode cannot count as 20 separate confirmations.
    pool = min(len(history), max(kk, kk * 5))
    nn = NearestNeighbors(n_neighbors=pool, metric="euclidean")
    nn.fit(X_hist)
    _, idx = nn.kneighbors(X_current)
    original_idx = np.asarray(history.index, dtype=int)
    spacing = max(1, min(int(horizon) // 2, 20))
    chosen = []
    chosen_orig = []
    for pos in idx[0]:
        oi = int(original_idx[pos])
        if all(abs(oi - prev) > spacing for prev in chosen_orig):
            chosen.append(int(pos)); chosen_orig.append(oi)
        if len(chosen) >= kk:
            break
    if len(chosen) < min(10, kk):
        # If the history is too short to de-cluster strongly, fall back to the
        # nearest unique candidates rather than returning nothing.
        chosen = [int(x) for x in idx[0][:kk]]
    matched = history["fwd_ret"].to_numpy(dtype=float)[chosen]

    up_mask = matched > flat_threshold
    down_mask = matched < -flat_threshold
    flat_mask = ~(up_mask | down_mask)
    q = np.quantile(matched, [0.10, 0.25, 0.50, 0.75, 0.90])

    scenarios = {
        "SUBIDA": _scenario_quantiles(matched[up_mask]),
        "LATERAL": _scenario_quantiles(matched[flat_mask]),
        "BAJADA": _scenario_quantiles(matched[down_mask]),
    }
    return SimilarCasesResult(
        n_cases=int(len(matched)),
        up_pct=float(up_mask.mean() * 100),
        flat_pct=float(flat_mask.mean() * 100),
        down_pct=float(down_mask.mean() * 100),
        mean_forward_return=float(np.mean(matched)),
        max_forward_return=float(np.max(matched)),
        min_forward_return=float(np.min(matched)),
        horizon=int(horizon),
        median_forward_return=float(q[2]),
        q10_forward_return=float(q[0]),
        q25_forward_return=float(q[1]),
        q75_forward_return=float(q[3]),
        q90_forward_return=float(q[4]),
        scenario_quantiles=scenarios,
    )


def estimate_time_to_move(features: pd.DataFrame, market: pd.DataFrame,
                          feature_columns: list[str] | None,
                          target_return: float, direction: str,
                          max_bars: int = 8, k: int = 40) -> dict | None:
    """Estimate first-touch time from historical states similar to the current one.

    This is a true time-to-touch calculation, not a forecast-horizon alias.
    Historical neighbors are chosen using information available at each state;
    their subsequent OHLC path is then scanned for the first bar that touched
    a move of the same percentage magnitude as the current target.

    Returns hit-rate and time quantiles only when enough comparable histories
    are available. Recent rows without a complete future path are excluded.
    """
    if features is None or market is None or features.empty or market.empty:
        return None
    if direction not in ("SUBIDA", "BAJADA"):
        return None
    try:
        move = abs(float(target_return))
    except Exception:
        return None
    if not np.isfinite(move) or move <= 0:
        return None
    max_bars = max(1, int(max_bars))

    n = min(len(features), len(market))
    if n < max(80, max_bars + 40):
        return None
    features = features.iloc[:n]
    market = market.iloc[:n]

    cols = [c for c in (feature_columns or ANALOG_FEATURE_COLUMNS) if c in features.columns]
    if not cols:
        return None

    # Historical states must have a fully observed path of max_bars afterwards.
    hist_end = n - max_bars
    history = features.iloc[:hist_end][cols].copy()
    min_non_na = max(5, int(len(cols) * 0.70))
    history = history[history.notna().sum(axis=1) >= min_non_na]
    cols = [c for c in cols if history[c].notna().any()]
    if len(history) < 30 or not cols:
        return None

    current = features.iloc[[-1]][cols].copy()
    if current.notna().sum(axis=1).iloc[0] < max(5, int(len(cols) * 0.70)):
        return None

    imp = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    X_hist = scaler.fit_transform(imp.fit_transform(history[cols]))
    X_current = scaler.transform(imp.transform(current[cols]))

    kk = min(int(k), len(history))
    pool = min(len(history), max(kk, kk * 5))
    nn = NearestNeighbors(n_neighbors=pool, metric="euclidean")
    nn.fit(X_hist)
    _, idx = nn.kneighbors(X_current)

    original_idx = np.asarray(history.index, dtype=int)
    spacing = max(1, min(max_bars // 2, 20))
    chosen_orig = []
    for pos in idx[0]:
        oi = int(original_idx[pos])
        if oi + max_bars >= n:
            continue
        if all(abs(oi - prev) > spacing for prev in chosen_orig):
            chosen_orig.append(oi)
        if len(chosen_orig) >= kk:
            break
    if len(chosen_orig) < 12:
        return None

    hit_times = []
    for oi in chosen_orig:
        try:
            base = float(market["close"].iloc[oi])
        except Exception:
            continue
        if not np.isfinite(base) or base <= 0:
            continue
        level = base * (1.0 + move) if direction == "SUBIDA" else base * (1.0 - move)
        first = None
        for step in range(1, max_bars + 1):
            j = oi + step
            if j >= n:
                break
            try:
                if direction == "SUBIDA":
                    touched = float(market["high"].iloc[j]) >= level
                else:
                    touched = float(market["low"].iloc[j]) <= level
            except Exception:
                touched = False
            if touched:
                first = step
                break
        if first is not None:
            hit_times.append(int(first))

    n_cases = int(len(chosen_orig))
    n_hits = int(len(hit_times))
    hit_rate = float(n_hits / n_cases) if n_cases else 0.0
    if n_hits < 5:
        return {
            "n_cases": n_cases, "n_hits": n_hits, "hit_rate": hit_rate,
            "valid": False, "max_bars": max_bars,
        }

    q = np.quantile(np.asarray(hit_times, dtype=float), [0.25, 0.50, 0.75])
    # Require a majority of comparable cases to touch the move inside the tested
    # window before calling this an ETA.
    valid = bool(n_cases >= 15 and n_hits >= 7 and hit_rate >= 0.55)
    return {
        "n_cases": n_cases,
        "n_hits": n_hits,
        "hit_rate": hit_rate,
        "q25_bars": int(max(1, round(float(q[0])))),
        "median_bars": int(max(1, round(float(q[1])))),
        "q75_bars": int(max(1, round(float(q[2])))),
        "max_bars": max_bars,
        "valid": valid,
    }
