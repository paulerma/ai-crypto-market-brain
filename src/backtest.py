"""Purged walk-forward validation and an event-aligned OOS backtest."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, precision_recall_fscore_support

from models import fit_model, prepare_training_frame
from calibration import calibrate, evaluate_calibration, multiclass_brier_score

ALL_CLASSES = [-1, 0, 1]


def _align_proba(proba, classes):
    out = np.zeros((len(proba), len(ALL_CLASSES)), dtype=float)
    pos = {int(c): i for i, c in enumerate(classes)}
    for j, c in enumerate(ALL_CLASSES):
        if c in pos:
            out[:, j] = proba[:, pos[c]]
    sums = out.sum(axis=1, keepdims=True)
    sums[sums == 0] = 1.0
    return out / sums


def _purge_before_boundary(X, y, boundary_index, purge_bars):
    if purge_bars <= 0 or len(X) == 0:
        return X, y
    idx = np.asarray(X.index, dtype=int)
    keep = idx + int(purge_bars) < int(boundary_index)
    return X.iloc[np.flatnonzero(keep)], y.iloc[np.flatnonzero(keep)]


@dataclass
class FoldResult:
    fold: int
    train_size: int
    test_size: int
    accuracy: float
    balanced_accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    brier_score: float
    brier_skill: float
    log_loss: float
    calibrated: bool


@dataclass
class WalkForwardReport:
    model_name: str
    folds: list = field(default_factory=list)

    def summary(self) -> dict:
        if not self.folds:
            return {"error": "sin folds válidos"}
        bal = np.array([f.balanced_accuracy for f in self.folds], dtype=float)
        f1s = np.array([f.f1_macro for f in self.folds], dtype=float)
        skills = np.array([f.brier_skill for f in self.folds], dtype=float)
        return {
            "n_folds": len(self.folds),
            "accuracy_mean": float(np.mean([f.accuracy for f in self.folds])),
            "balanced_accuracy_mean": float(np.mean(bal)),
            "balanced_accuracy_std": float(np.std(bal, ddof=0)),
            "balanced_accuracy_min": float(np.min(bal)),
            "f1_macro_mean": float(np.mean(f1s)),
            "f1_macro_std": float(np.std(f1s, ddof=0)),
            "brier_score_mean": float(np.mean([f.brier_score for f in self.folds])),
            "brier_skill_mean": float(np.mean(skills)),
            "brier_skill_std": float(np.nanstd(skills, ddof=0)),
            "brier_skill_min": float(np.nanmin(skills)),
            "log_loss_mean": float(np.nanmean([f.log_loss for f in self.folds])),
            "calibrated_folds": int(sum(f.calibrated for f in self.folds)),
        }


def walk_forward_validate(features: pd.DataFrame, labels: pd.Series,
                           feature_columns: list[str], model_name: str,
                           n_folds: int = 5, min_train_size: int = 200,
                           calibration_frac: float = 0.15,
                           calibration_method: str = "sigmoid",
                           purge_bars: int = 0) -> WalkForwardReport:
    X_full, y_full = prepare_training_frame(features, labels, feature_columns)
    n = len(X_full)
    if n < min_train_size + n_folds * 20:
        raise ValueError(f"Datos insuficientes para walk-forward ({n} filas útiles).")

    fold_edges = np.linspace(min_train_size, n, n_folds + 1, dtype=int)
    report = WalkForwardReport(model_name=model_name)

    for i in range(n_folds):
        train_end, test_end = fold_edges[i], fold_edges[i + 1]
        if train_end >= test_end:
            continue
        train_X_all = X_full.iloc[:train_end]
        train_y_all = y_full.iloc[:train_end]
        test_X = X_full.iloc[train_end:test_end]
        test_y = y_full.iloc[train_end:test_end]
        if test_X.empty:
            continue

        train_X_all, train_y_all = _purge_before_boundary(
            train_X_all, train_y_all, test_X.index.min(), purge_bars
        )
        if len(train_X_all) < 120:
            continue

        cal_start = int(len(train_X_all) * (1 - calibration_frac))
        fit_X, fit_y = train_X_all.iloc[:cal_start], train_y_all.iloc[:cal_start]
        cal_X, cal_y = train_X_all.iloc[cal_start:], train_y_all.iloc[cal_start:]
        if cal_X.empty:
            continue
        fit_X, fit_y = _purge_before_boundary(fit_X, fit_y, cal_X.index.min(), purge_bars)
        fit_counts = fit_y.value_counts().reindex(ALL_CLASSES, fill_value=0)
        if (fit_counts < 2).any():
            continue

        trained = fit_model(model_name, fit_X, fit_y)
        calibrated_ok = False
        cal_counts = cal_y.value_counts().reindex(ALL_CLASSES, fill_value=0)
        if (cal_counts >= 2).all():
            try:
                use = calibrate(trained.model, cal_X, cal_y, method=calibration_method)
                raw_proba = use.predict_proba(test_X)
                classes = list(use.classes_)
                calibrated_ok = True
            except Exception:
                raw_proba = trained.model.predict_proba(test_X)
                classes = list(trained.classes_)
        else:
            raw_proba = trained.model.predict_proba(test_X)
            classes = list(trained.classes_)

        proba = _align_proba(raw_proba, classes)
        preds = np.array(ALL_CLASSES)[np.argmax(proba, axis=1)]
        acc = accuracy_score(test_y, preds)
        bal = balanced_accuracy_score(test_y, preds)
        p, r, f1, _ = precision_recall_fscore_support(
            test_y, preds, labels=ALL_CLASSES, average="macro", zero_division=0
        )
        cal_metrics = evaluate_calibration(test_y.values, proba, ALL_CLASSES)

        priors = np.array([(train_y_all == c).mean() for c in ALL_CLASSES], dtype=float)
        priors = priors / priors.sum()
        baseline = np.tile(priors, (len(test_y), 1))
        baseline_brier = multiclass_brier_score(test_y.values, baseline, ALL_CLASSES)
        brier_skill = 1 - cal_metrics["brier_score"] / baseline_brier if baseline_brier > 0 else float("nan")

        report.folds.append(FoldResult(
            fold=i + 1, train_size=len(train_X_all), test_size=len(test_X),
            accuracy=acc, balanced_accuracy=bal, precision_macro=p, recall_macro=r,
            f1_macro=f1, brier_score=cal_metrics["brier_score"], brier_skill=brier_skill,
            log_loss=cal_metrics["log_loss"], calibrated=calibrated_ok,
        ))
    return report


def compare_models(features: pd.DataFrame, labels: pd.Series, feature_columns: list[str],
                   model_names: list[str], **kwargs) -> pd.DataFrame:
    rows = []
    metric_cols = ["n_folds","accuracy_mean","balanced_accuracy_mean","balanced_accuracy_std","balanced_accuracy_min",
                   "f1_macro_mean","f1_macro_std","brier_score_mean","brier_skill_mean","brier_skill_std","brier_skill_min",
                   "log_loss_mean","calibrated_folds"]
    for name in model_names:
        row = {"model": name, **{c: np.nan for c in metric_cols}, "error": None}
        try:
            summary = walk_forward_validate(features, labels, feature_columns, name, **kwargs).summary()
            if "error" in summary:
                row["error"] = summary["error"]
            else:
                row.update(summary)
        except Exception as e:
            row["error"] = str(e)
        rows.append(row)
    return pd.DataFrame(rows)


def walk_forward_predictions(features: pd.DataFrame, labels: pd.Series,
                             feature_columns: list[str], model_name: str,
                             n_folds: int = 4, min_train_size: int = 200,
                             calibration_frac: float = 0.15,
                             calibration_method: str = "sigmoid",
                             purge_bars: int = 0) -> pd.DataFrame:
    X_full, y_full = prepare_training_frame(features, labels, feature_columns)
    n = len(X_full)
    if n < min_train_size + n_folds * 20:
        raise ValueError(f"Datos insuficientes para walk-forward ({n} filas útiles).")
    fold_edges = np.linspace(min_train_size, n, n_folds + 1, dtype=int)
    rows = []
    for i in range(n_folds):
        train_end, test_end = fold_edges[i], fold_edges[i + 1]
        test_X, test_y = X_full.iloc[train_end:test_end], y_full.iloc[train_end:test_end]
        if test_X.empty:
            continue
        train_X_all, train_y_all = X_full.iloc[:train_end], y_full.iloc[:train_end]
        train_X_all, train_y_all = _purge_before_boundary(train_X_all, train_y_all, test_X.index.min(), purge_bars)
        cal_start = int(len(train_X_all) * (1 - calibration_frac))
        fit_X, fit_y = train_X_all.iloc[:cal_start], train_y_all.iloc[:cal_start]
        cal_X, cal_y = train_X_all.iloc[cal_start:], train_y_all.iloc[cal_start:]
        if cal_X.empty:
            continue
        fit_X, fit_y = _purge_before_boundary(fit_X, fit_y, cal_X.index.min(), purge_bars)
        fit_counts = fit_y.value_counts().reindex(ALL_CLASSES, fill_value=0)
        if (fit_counts < 2).any():
            continue
        trained = fit_model(model_name, fit_X, fit_y)
        cal_counts = cal_y.value_counts().reindex(ALL_CLASSES, fill_value=0)
        if (cal_counts >= 2).all():
            try:
                use = calibrate(trained.model, cal_X, cal_y, method=calibration_method)
                raw = use.predict_proba(test_X); classes = list(use.classes_)
            except Exception:
                raw = trained.model.predict_proba(test_X); classes = list(trained.classes_)
        else:
            raw = trained.model.predict_proba(test_X); classes = list(trained.classes_)
        proba = _align_proba(raw, classes)
        preds = np.array(ALL_CLASSES)[np.argmax(proba, axis=1)]
        for pos, (idx, actual) in enumerate(test_y.items()):
            rows.append({
                "index": int(idx), "actual": int(actual), "pred": int(preds[pos]),
                "confidence": float(np.max(proba[pos])),
                "p_down": float(proba[pos,0]), "p_flat": float(proba[pos,1]), "p_up": float(proba[pos,2]),
                "fold": i + 1,
            })
    if not rows:
        return pd.DataFrame(columns=["index","actual","pred","confidence","p_down","p_flat","p_up","fold"])
    return pd.DataFrame(rows).sort_values("index").reset_index(drop=True)


def backtest_model_strategy(features: pd.DataFrame, labels: pd.Series, raw_df: pd.DataFrame,
                            feature_columns: list[str], model_name: str, horizon: int,
                            confidence_threshold: float = 0.55, fee_rate: float = 0.001,
                            n_folds: int = 4, min_train_size: int = 200,
                            barrier_k: float = 1.5, slippage_rate: float = 0.0002):
    """OOS event backtest aligned with the triple-barrier target.

    Exits on first target/stop touch, otherwise at horizon close. If both target
    and stop occur in the same OHLC bar, it assumes the adverse stop first.
    """
    preds = walk_forward_predictions(
        features, labels, feature_columns, model_name,
        n_folds=n_folds, min_train_size=min_train_size, purge_bars=horizon,
    )
    trades = []
    next_free_idx = -1
    for row in preds.itertuples(index=False):
        idx = int(row.index)
        if idx < next_free_idx or row.pred == 0 or row.confidence < confidence_threshold:
            continue
        max_exit_idx = min(idx + int(horizon), len(raw_df) - 1)
        if max_exit_idx <= idx:
            continue
        entry = float(raw_df.loc[idx, "close"])
        atr = float(features.loc[idx, "atr_14"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        if row.pred == 1:
            target, stop = entry + barrier_k * atr, entry - barrier_k * atr
        else:
            target, stop = entry - barrier_k * atr, entry + barrier_k * atr

        exit_price = float(raw_df.loc[max_exit_idx, "close"])
        exit_idx = max_exit_idx
        exit_reason = "HORIZON"
        for j in range(idx + 1, max_exit_idx + 1):
            hi, lo = float(raw_df.loc[j, "high"]), float(raw_df.loc[j, "low"])
            if row.pred == 1:
                hit_target, hit_stop = hi >= target, lo <= stop
            else:
                hit_target, hit_stop = lo <= target, hi >= stop
            if hit_target and hit_stop:
                exit_price, exit_idx, exit_reason = stop, j, "AMBIGUOUS→STOP"
                break
            if hit_stop:
                exit_price, exit_idx, exit_reason = stop, j, "STOP"
                break
            if hit_target:
                exit_price, exit_idx, exit_reason = target, j, "TARGET"
                break

        gross = (exit_price - entry) / entry if row.pred == 1 else (entry - exit_price) / entry
        net_ret = gross - 2 * fee_rate - 2 * slippage_rate
        trades.append({
            "entry_index": idx, "exit_index": exit_idx,
            "entry_time": raw_df.loc[idx, "timestamp"], "exit_time": raw_df.loc[exit_idx, "timestamp"],
            "direction": "LONG" if row.pred == 1 else "SHORT", "confidence": row.confidence,
            "entry": entry, "exit": exit_price, "exit_reason": exit_reason,
            "return": net_ret, "win": net_ret > 0,
        })
        next_free_idx = exit_idx + 1

    tdf = pd.DataFrame(trades)
    if tdf.empty:
        return tdf, pd.DataFrame(), {"trades":0,"win_rate":np.nan,"return":0.0,"max_drawdown":np.nan,"profit_factor":np.nan,"avg_trade":np.nan}
    tdf["equity"] = (1 + tdf["return"]).cumprod()
    peak = tdf["equity"].cummax(); dd = tdf["equity"] / peak - 1
    gains = tdf.loc[tdf["return"] > 0, "return"].sum(); losses = -tdf.loc[tdf["return"] < 0, "return"].sum()
    metrics = {
        "trades": int(len(tdf)), "win_rate": float(tdf["win"].mean()),
        "return": float(tdf["equity"].iloc[-1] - 1), "max_drawdown": float(dd.min()),
        "profit_factor": float(gains/losses) if losses > 0 else np.nan,
        "avg_trade": float(tdf["return"].mean()),
    }
    equity = tdf[["exit_time","equity"]].rename(columns={"exit_time":"timestamp"})
    return tdf, equity, metrics
