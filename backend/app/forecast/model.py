"""Ridge fitting with train-only scaling, grouped model selection, and portable artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import ForecastConfig
from .dataset import constant_velocity_prediction, feature_names


def endpoint_errors(predictions: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Euclidean displacement error per example, in torso lengths."""
    return np.linalg.norm(predictions - targets, axis=1)


def _fit(features: np.ndarray, targets: np.ndarray, alpha: float):
    return make_pipeline(StandardScaler(), Ridge(alpha=alpha)).fit(features, targets)


def select_hyperparameters(
    features: np.ndarray, targets: np.ndarray, groups: np.ndarray, side: str, config: ForecastConfig,
) -> dict[str, Any]:
    """Grouped cross-validation inside the training groups only."""
    folds = min(config.cv_folds, len(np.unique(groups)))
    splitter = list(GroupKFold(n_splits=folds).split(features, targets, groups))
    alpha_scores, window_scores = {}, {}
    for alpha in config.ridge_alphas:
        errors = [endpoint_errors(_fit(features[a], targets[a], alpha).predict(features[b]), targets[b]) for a, b in splitter]
        alpha_scores[alpha] = float(np.mean(np.concatenate(errors)))
    baseline = np.vstack([baseline_predictions(features, side, w, config) for w in config.constant_velocity_windows_ms])
    for position, window in enumerate(config.constant_velocity_windows_ms):
        window_scores[window] = float(np.mean(endpoint_errors(baseline[position * len(features):(position + 1) * len(features)], targets)))
    best_alpha = min(alpha_scores, key=lambda a: (alpha_scores[a], a))
    best_window = min(window_scores, key=lambda w: (window_scores[w], w))
    persistence_mae = float(np.mean(endpoint_errors(np.zeros_like(targets), targets)))
    return {"cv_folds": folds, "alpha": best_alpha, "alpha_scores_cv_mae": alpha_scores, "persistence_train_mae": persistence_mae,
            "constant_velocity_window_ms": best_window, "window_scores_train_mae": window_scores}


def baseline_predictions(features: np.ndarray, side: str, window_ms: int, config: ForecastConfig) -> np.ndarray:
    return np.vstack([constant_velocity_prediction(row, side, window_ms, config.horizon_ms) for row in features])


def fit_side_model(
    features: np.ndarray, targets: np.ndarray, side: str, alpha: float, window_ms: int,
) -> dict[str, Any]:
    pipeline = _fit(features, targets, alpha)
    scaler, ridge = pipeline.named_steps["standardscaler"], pipeline.named_steps["ridge"]
    return {
        "side": side, "alpha": alpha, "constant_velocity_window_ms": window_ms, "feature_names": feature_names(side),
        "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
        "coef": ridge.coef_.tolist(), "intercept": ridge.intercept_.tolist(),
        "n_training_examples": int(len(features)),
    }


def predict(artifact: dict[str, Any], features: np.ndarray) -> np.ndarray:
    """Apply a saved model; no scikit-learn state or future data is involved."""
    scaled = (features - np.array(artifact["scaler_mean"])) / np.array(artifact["scaler_scale"])
    return scaled @ np.array(artifact["coef"]).T + np.array(artifact["intercept"])


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=1, sort_keys=True, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_model(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
