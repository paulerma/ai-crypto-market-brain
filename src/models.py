"""Candidate models with deterministic, train-only feature selection."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.impute import SimpleImputer

# More variables are not automatically better. 24 is deliberately conservative
# for the 1k-3k bar datasets used by the desktop app.
SELECT_K = 24


def _mutual_info_deterministic(X, y):
    return mutual_info_classif(X, y, random_state=42)


def _selector():
    return SelectKBest(score_func=_mutual_info_deterministic, k=SELECT_K)


def get_candidate_models() -> dict:
    return {
        "logistic_regression": Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("select", _selector()),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=3000, class_weight="balanced", C=0.65, random_state=42)),
        ]),
        "random_forest": Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("select", _selector()),
            ("clf", RandomForestClassifier(n_estimators=400, max_depth=8, min_samples_leaf=12,
                                            max_features="sqrt", class_weight="balanced_subsample",
                                            random_state=42, n_jobs=-1)),
        ]),
        "gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("select", _selector()),
            ("clf", GradientBoostingClassifier(n_estimators=220, max_depth=2, learning_rate=0.04,
                                                min_samples_leaf=12, random_state=42)),
        ]),
        "extra_trees": Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("select", _selector()),
            ("clf", ExtraTreesClassifier(n_estimators=400, max_depth=9, min_samples_leaf=10,
                                          max_features="sqrt", class_weight="balanced",
                                          random_state=43, n_jobs=-1)),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("select", _selector()),
            ("clf", HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                                    min_samples_leaf=18, l2_regularization=0.8,
                                                    random_state=44)),
        ]),
    }


@dataclass
class TrainedModel:
    name: str
    model: object
    feature_columns: list[str]
    classes_: np.ndarray


def prepare_training_frame(features: pd.DataFrame, labels: pd.Series, feature_columns: list[str]):
    frame = features[feature_columns].join(labels.rename("y"))
    frame = frame.dropna(subset=["y"])
    min_non_na = max(8, int(len(feature_columns) * .70))
    frame = frame[frame[feature_columns].notna().sum(axis=1) >= min_non_na]
    return frame[feature_columns], frame["y"].astype(int)


def fit_model(model_name: str, X: pd.DataFrame, y: pd.Series) -> TrainedModel:
    candidates = get_candidate_models()
    if model_name not in candidates:
        raise ValueError(f"Modelo desconocido: {model_name}")
    model = candidates[model_name]
    model.fit(X, y)
    classes = model.classes_ if hasattr(model, "classes_") else model.named_steps["clf"].classes_
    return TrainedModel(model_name, model, list(X.columns), classes)


def predict_proba_row(trained: TrainedModel, x_row: pd.DataFrame) -> dict:
    proba = trained.model.predict_proba(x_row[trained.feature_columns])[0]
    return {int(c): float(p) for c, p in zip(trained.classes_, proba)}
