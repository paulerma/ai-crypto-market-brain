"""
CYCLE ENGINE — mide, sobre datos reales, cuánto ha durado la fase
actual y cuánto duraron fases similares en el pasado. NO asume la
duración: la calcula a partir de la propia serie de régimen generada
por regime_engine.py sobre el histórico real descargado.

El patrón de ~1,060 días entre mínimos/máximos de ciclo mencionado en
el brief se deja como constante DOCUMENTADA (no como regla) en
CYCLE_LOW_REFERENCE_DAYS / CYCLE_HIGH_REFERENCE_DAYS — es una
referencia externa citada por el usuario, no algo derivado de los
datos de este proyecto. Debe tratarse como una feature más, y su
capacidad predictiva real debe evaluarse con datos suficientes
(varios ciclos completos) antes de darle ningún peso.
"""

from dataclasses import dataclass
import pandas as pd

# Referencia citada por el usuario — NO calculada por este sistema,
# NO es una regla. Ver docstring del módulo.
CYCLE_REFERENCE_DAYS_APPROX = 1060


@dataclass
class CycleState:
    current_regime: str
    days_in_current_phase: int
    n_similar_past_phases: int
    similar_phase_duration_min: int | None
    similar_phase_duration_max: int | None
    similar_phase_duration_mean: float | None


def phase_durations(regime_series: pd.Series) -> pd.DataFrame:
    """A partir de una serie de régimen por vela (ej. la salida de
    regime_engine.regime_series), calcula CADA racha histórica real:
    régimen, duración en velas, índice de inicio/fin. Esto es la base
    real para "duración histórica de situaciones similares" — no un
    número inventado."""
    df = regime_series.reset_index(drop=True).to_frame("regime")
    df["change"] = (df["regime"] != df["regime"].shift(1)).cumsum()
    grouped = df.groupby("change")
    rows = []
    for _, g in grouped:
        rows.append({
            "regime": g["regime"].iloc[0],
            "start_idx": g.index[0],
            "end_idx": g.index[-1],
            "duration": len(g),
        })
    return pd.DataFrame(rows)


def current_cycle_state(regime_series: pd.Series) -> CycleState:
    phases = phase_durations(regime_series)
    if phases.empty:
        raise ValueError("regime_series vacía — no se puede calcular el ciclo.")

    current = phases.iloc[-1]
    current_regime = current["regime"]
    days_in_phase = int(current["duration"])

    past_same_regime = phases.iloc[:-1]
    past_same_regime = past_same_regime[past_same_regime["regime"] == current_regime]

    if past_same_regime.empty:
        return CycleState(
            current_regime=current_regime, days_in_current_phase=days_in_phase,
            n_similar_past_phases=0, similar_phase_duration_min=None,
            similar_phase_duration_max=None, similar_phase_duration_mean=None,
        )

    durations = past_same_regime["duration"]
    return CycleState(
        current_regime=current_regime, days_in_current_phase=days_in_phase,
        n_similar_past_phases=len(durations),
        similar_phase_duration_min=int(durations.min()),
        similar_phase_duration_max=int(durations.max()),
        similar_phase_duration_mean=float(durations.mean()),
    )


# ---------------------------------------------------------------------------
# Long-cycle state analogues
# ---------------------------------------------------------------------------

CYCLE_FEATURES = [
    "ret4", "ret13", "ret26", "drawdown52",
    "dist_ma20", "dist_ma50", "dist_ma100",
    "vol13", "vol_ratio13", "rsi14",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.astype(float).diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / down.replace(0, pd.NA)
    return 100.0 - 100.0 / (1.0 + rs)


def build_cycle_features(weekly: pd.DataFrame) -> pd.DataFrame:
    """State vector for comparing the current weekly cycle with prior eras."""
    import numpy as np

    df = weekly.copy().reset_index(drop=True)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["ret4"] = c.pct_change(4)
    out["ret13"] = c.pct_change(13)
    out["ret26"] = c.pct_change(26)
    out["drawdown52"] = c / c.rolling(52, min_periods=26).max() - 1.0
    for n in (20, 50, 100):
        ma = c.ewm(span=n, adjust=False, min_periods=max(10, n // 2)).mean()
        out[f"dist_ma{n}"] = c / ma - 1.0
    logret = np.log(c).diff()
    out["vol13"] = logret.rolling(13, min_periods=8).std() * np.sqrt(52)
    out["vol_ratio13"] = v / v.rolling(13, min_periods=8).median().replace(0, np.nan)
    out["rsi14"] = _rsi(c, 14).astype(float) / 100.0 - 0.5
    return out.replace([np.inf, -np.inf], np.nan)


def historical_cycle_analogues(weekly: pd.DataFrame, k: int = 18) -> dict:
    """Compare the current weekly state with similar historical states.

    The function deliberately does NOT hard-code a four-year/halving template.
    It searches the actual history for comparable drawdown, momentum, trend,
    volatility and volume states, then measures what happened 4/8/13/26 weeks
    later. This makes prior cycles a context feature instead of a rigid rule.
    """
    import numpy as np

    if weekly is None or len(weekly) < 170:
        return {"ok": False, "reason": "histórico semanal insuficiente"}

    market = weekly.reset_index(drop=True).copy()
    feat = build_cycle_features(market)
    horizons = [4, 8, 13, 26]
    max_h = max(horizons)
    hist_end = len(feat) - max_h
    if hist_end < 130:
        return {"ok": False, "reason": "histórico útil insuficiente"}

    cols = [c for c in CYCLE_FEATURES if c in feat.columns]
    history = feat.iloc[:hist_end][cols].copy()
    current = feat.iloc[[-1]][cols].copy()
    min_obs = max(6, int(len(cols) * 0.75))
    history = history[history.notna().sum(axis=1) >= min_obs]
    if len(history) < 100 or current.notna().sum(axis=1).iloc[0] < min_obs:
        return {"ok": False, "reason": "variables de ciclo insuficientes"}

    means = history.mean()
    stds = history.std().replace(0, np.nan)
    history_z = ((history - means) / stds).fillna(0.0)
    current_z = ((current - means) / stds).fillna(0.0)
    distances = np.sqrt(((history_z - current_z.iloc[0]) ** 2).mean(axis=1))
    ordered = distances.sort_values().index.tolist()

    # De-cluster nearby weeks so one episode is not counted many times.
    chosen = []
    spacing = 10
    for idx in ordered:
        if all(abs(int(idx) - int(prev)) > spacing for prev in chosen):
            chosen.append(int(idx))
        if len(chosen) >= min(int(k), 24):
            break
    if len(chosen) < 8:
        return {"ok": False, "reason": "pocos ciclos comparables"}

    d = np.asarray([float(distances.loc[i]) for i in chosen], dtype=float)
    weights = 1.0 / np.maximum(d, 0.20)
    weights = weights / weights.sum()

    close = market["close"].astype(float).reset_index(drop=True)
    results = {}
    combined = 0.0
    horizon_weights = {4: 0.10, 8: 0.20, 13: 0.30, 26: 0.40}
    for h in horizons:
        vals = np.asarray([float(close.iloc[i + h] / close.iloc[i] - 1.0) for i in chosen], dtype=float)
        direction_score = float(np.sum(weights * np.sign(vals)))
        results[str(h)] = {
            "direction_score": direction_score,
            "median_return": float(np.median(vals)),
            "up_share": float(np.sum(weights[vals > 0])),
            "down_share": float(np.sum(weights[vals < 0])),
            "q25": float(np.quantile(vals, 0.25)),
            "q75": float(np.quantile(vals, 0.75)),
        }
        combined += horizon_weights[h] * direction_score

    timestamps = pd.to_datetime(market.get("timestamp"), utc=True, errors="coerce")
    analogues = []
    for idx, dist in zip(chosen[:6], d[:6]):
        ts = timestamps.iloc[idx] if len(timestamps) > idx else pd.NaT
        analogues.append({
            "index": int(idx),
            "date": ts.isoformat() if pd.notna(ts) else None,
            "distance": float(dist),
        })

    agreement = float(abs(combined))
    if agreement >= 0.55:
        state = "ALCISTA" if combined > 0 else "BAJISTA"
        reliability = "ALTA"
    elif agreement >= 0.25:
        state = "ALCISTA" if combined > 0 else "BAJISTA"
        reliability = "MEDIA"
    else:
        state = "MIXTO"
        reliability = "BAJA"

    return {
        "ok": True,
        "score": float(np.clip(combined, -1.0, 1.0)),
        "state": state,
        "reliability": reliability,
        "n_analogues": int(len(chosen)),
        "horizons": results,
        "analogues": analogues,
    }
