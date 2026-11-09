"""Causal example construction for the wrist-motion forecast.

`features_from_history` receives only the samples up to prediction time t, so no
future value can reach an input. Scaling is the median torso length of that history;
there is no smoothing. A later pose estimate is used only for the target and for
deciding whether an example has a reliable target.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..analysis.config import QualityConfig
from ..analysis.quality import landmark_invalid_reason, landmark_lookup
from .config import ForecastConfig

SIDES = ("left", "right")
ELIGIBLE_PRIMARY = "eligible_primary"
ELIGIBLE_STRESS = "eligible_camera_moving_stress"
WRIST_LAGS = tuple(range(11))
ARM_LAGS = (0, 5, 10)
VELOCITY_WINDOWS_MS = (100, 200, 300, 500, 1000)


def feature_names(side: str) -> list[str]:
    names = [f"wrist_{axis}_lag{lag}" for lag in WRIST_LAGS for axis in "xy"]
    names += [f"{joint}_{axis}_lag{lag}" for joint in ("elbow", "shoulder") for lag in ARM_LAGS for axis in "xy"]
    names += [f"wrist_v{axis}_{w}ms" for w in VELOCITY_WINDOWS_MS for axis in "xy"]
    names += ["wrist_visibility_mean", "wrist_visibility_min", "elbow_visibility_mean", "torso_min_over_max"]
    return [f"{side}_{name}" for name in names]


def _pixels(record: dict[str, Any], name: str, width: int, height: int) -> np.ndarray:
    landmark = landmark_lookup(record)[name]
    return np.array([landmark["x"] * width, landmark["y"] * height], dtype=float)


def _hip_midpoint(record: dict[str, Any], width: int, height: int) -> np.ndarray:
    return (_pixels(record, "left_hip", width, height) + _pixels(record, "right_hip", width, height)) / 2


def body_relative(record: dict[str, Any], name: str, width: int, height: int) -> np.ndarray:
    """Joint position relative to the hip midpoint, in pixels. Not wall-space movement."""
    return _pixels(record, name, width, height) - _hip_midpoint(record, width, height)


def torso_length_px(record: dict[str, Any], width: int, height: int) -> float:
    shoulders = (_pixels(record, "left_shoulder", width, height) + _pixels(record, "right_shoulder", width, height)) / 2
    return float(np.linalg.norm(shoulders - _hip_midpoint(record, width, height)))


def _required(side: str) -> tuple[str, ...]:
    return (f"{side}_wrist", f"{side}_elbow", "left_shoulder", "right_shoulder", "left_hip", "right_hip")


def _all_valid(record: dict[str, Any], names: Sequence[str], quality: QualityConfig) -> bool:
    lookup = landmark_lookup(record)
    return all(landmark_invalid_reason(lookup.get(name), quality) is None for name in names)


def features_from_history(
    history: Sequence[dict[str, Any]], side: str, width: int, height: int,
) -> tuple[np.ndarray, float]:
    """Features and scale from history[-1] back in time; history holds only past samples."""
    latest = history[-1]
    scale = float(np.median([torso_length_px(r, width, height) for r in history]))
    wrist = f"{side}_wrist"
    values: list[float] = []
    for lag in WRIST_LAGS:
        values.extend(body_relative(history[-1 - lag], wrist, width, height) / scale)
    for joint in (f"{side}_elbow", f"{side}_shoulder"):
        for lag in ARM_LAGS:
            values.extend(body_relative(history[-1 - lag], joint, width, height) / scale)
    now_position = body_relative(latest, wrist, width, height)
    for window_ms in VELOCITY_WINDOWS_MS:
        lag = window_ms // 100
        earlier = history[-1 - lag]
        elapsed = (latest["timestamp_ms"] - earlier["timestamp_ms"]) / 1000
        values.extend((now_position - body_relative(earlier, wrist, width, height)) / scale / elapsed)
    wrist_vis = [landmark_lookup(r)[wrist]["visibility"] for r in history]
    elbow_vis = [landmark_lookup(r)[f"{side}_elbow"]["visibility"] for r in history]
    lengths = [torso_length_px(r, width, height) for r in history]
    values.extend([float(np.mean(wrist_vis)), float(np.min(wrist_vis)), float(np.mean(elbow_vis)), min(lengths) / max(lengths)])
    return np.array(values, dtype=float), scale


def target_displacement(
    now: dict[str, Any], future: dict[str, Any], side: str, width: int, height: int, scale: float,
) -> np.ndarray:
    """Change in wrist-minus-hip-midpoint from t to the horizon, in history torso lengths."""
    wrist = f"{side}_wrist"
    return (body_relative(future, wrist, width, height) - body_relative(now, wrist, width, height)) / scale


def constant_velocity_prediction(features: np.ndarray, side: str, window_ms: int, horizon_ms: int) -> np.ndarray:
    names = feature_names(side)
    return np.array([features[names.index(f"{side}_wrist_v{axis}_{window_ms}ms")] * horizon_ms / 1000 for axis in "xy"])


def _step_ok(earlier: dict[str, Any], later: dict[str, Any], config: ForecastConfig) -> bool:
    return abs(later["timestamp_ms"] - earlier["timestamp_ms"] - config.sample_period_ms) <= config.step_tolerance_ms


def _camera_steady(after: dict[str, Any], before: dict[str, Any], scale: float, config: ForecastConfig) -> bool:
    """Known-steady interval; an unknown estimate does not count as steady."""
    shift, response = after.get("camera_shift_px"), after.get("camera_shift_response")
    if shift is None or response is None or response < config.camera_min_correlation_response:
        return False
    elapsed = (after["timestamp_ms"] - before["timestamp_ms"]) / 1000
    return shift / elapsed / scale <= config.camera_max_speed_L_per_s


@dataclass(frozen=True)
class Example:
    t_ms: int
    side: str
    status: str
    reason: str | None
    features: np.ndarray | None
    target: np.ndarray | None
    scale_px: float | None


def build_example(
    records: Sequence[dict[str, Any]], index: int, side: str, width: int, height: int,
    quality: QualityConfig, config: ForecastConfig,
) -> Example:
    t_ms = records[index]["timestamp_ms"]
    reject = lambda reason, scale=None: Example(t_ms, side, "rejected", reason, None, None, scale)  # noqa: E731

    first = index - config.history_steps
    if first < 0:
        return reject("insufficient_history")
    history = records[first: index + 1]
    if not all(_step_ok(a, b, config) for a, b in zip(history, history[1:])):
        return reject("non_contiguous_history")
    if any(r.get("repeated_source_frame") for r in history[1:]):
        return reject("repeated_source_frame_in_history")
    required = _required(side)
    if not all(_all_valid(r, required, quality) for r in history):
        return reject("history_landmark_unavailable")
    lengths = [torso_length_px(r, width, height) for r in history]
    scale = float(np.median(lengths))
    if scale < config.min_torso_fraction_of_diagonal * math.hypot(width, height):
        return reject("degenerate_history_scale")
    if not all(config.torso_ratio_min <= length / scale <= config.torso_ratio_max for length in lengths):
        return reject("implausible_torso_in_history", scale)

    last = index + config.horizon_steps
    if last >= len(records):
        return reject("no_target_sample", scale)
    horizon = records[index: last + 1]
    if not all(_step_ok(a, b, config) for a, b in zip(horizon, horizon[1:])):
        return reject("non_contiguous_horizon", scale)
    if any(r.get("repeated_source_frame") for r in horizon[1:]):
        return reject("repeated_source_frame_in_horizon", scale)
    if not all(_all_valid(r, required, quality) for r in horizon[1:]):
        return reject("target_or_horizon_landmark_unavailable", scale)
    target_length = torso_length_px(records[last], width, height)
    if not config.torso_ratio_min <= target_length / scale <= config.torso_ratio_max:
        return reject("implausible_torso_at_target", scale)

    features, _ = features_from_history(history, side, width, height)
    target = target_displacement(records[index], records[last], side, width, height, scale)
    steady = all(_camera_steady(b, a, scale, config) for a, b in zip(history, history[1:])) and \
        all(_camera_steady(b, a, scale, config) for a, b in zip(horizon, horizon[1:]))
    status = ELIGIBLE_PRIMARY if steady else ELIGIBLE_STRESS
    return Example(t_ms, side, status, None, features, target, scale)


def build_clip_examples(
    records: Sequence[dict[str, Any]], width: int, height: int, quality: QualityConfig, config: ForecastConfig,
) -> list[Example]:
    return [build_example(records, i, side, width, height, quality, config)
            for side in SIDES for i in range(len(records))]
