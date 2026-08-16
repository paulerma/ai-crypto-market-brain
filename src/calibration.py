"""Probability calibration for already-fitted time-series classifiers.

Uses sklearn FrozenEstimator (required by modern scikit-learn) so the base
classifier is not re-fitted on the calibration window. Training and calibration
windows must be disjoint; the walk-forward module enforces a purge gap.
"""
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import brier_score_loss, log_loss


def calibrate(base_model, X_cal, y_cal, method: str = "sigmoid"):
    if len(X_cal) < 20:
        raise ValueError("Muy pocas filas para calibrar probabilidades.")
    calibrated = CalibratedClassifierCV(FrozenEstimator(base_model), method=method)
    calibrated.fit(X_cal, y_cal)
    return calibrated


def multiclass_brier_score(y_true: np.ndarray, proba: np.ndarray, classes: list[int]) -> float:
    scores = []
    for i, c in enumerate(classes):
        y_bin = (y_true == c).astype(int)
        scores.append(brier_score_loss(y_bin, proba[:, i]))
    return float(np.mean(scores))


def evaluate_calibration(y_true: np.ndarray, proba: np.ndarray, classes: list[int]) -> dict:
    brier = multiclass_brier_score(y_true, proba, classes)
    try:
        ll = log_loss(y_true, proba, labels=classes)
    except ValueError:
        ll = float("nan")
    return {"brier_score": brier, "log_loss": ll, "n_samples": len(y_true)}


def reliability_bins(y_true: np.ndarray, proba_positive_class: np.ndarray,
                     y_positive_class: int, n_bins: int = 10) -> list[dict]:
    y_bin = (y_true == y_positive_class).astype(int)
    bin_edges = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (proba_positive_class >= lo) & (proba_positive_class < hi if i < n_bins - 1 else proba_positive_class <= hi)
        if mask.sum() == 0:
            continue
        out.append({
            "bin": f"{lo:.0%}-{hi:.0%}", "n": int(mask.sum()),
            "predicted_avg": float(proba_positive_class[mask].mean()),
            "observed_freq": float(y_bin[mask].mean()),
        })
    return out
