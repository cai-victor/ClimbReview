"""EXPERIMENTAL background-based camera compensation for handheld development clips.

Estimates per-interval similarity transforms from background features, excluding the
climber region, and abstains when support is weak. It is not part of the default
pipeline. Raw landmarks and original videos are never changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import cv2
import numpy as np

METHOD_VERSION = "background-similarity-v1"
ANALYSIS_LONG_SIDE_PX = 640


@dataclass(frozen=True)
class TransformLimits:
    min_inliers: int = 40
    min_inlier_ratio: float = 0.6
    max_median_residual_px: float = 1.0        # in canonical pixels
    max_scale_change: float = 0.03
    max_rotation_deg: float = 2.0
    climber_margin_fraction: float = 0.35      # of the pose box's longest side


def climber_mask(shape: tuple[int, int], records: Sequence[dict[str, Any]], limits: TransformLimits) -> np.ndarray | None:
    """255 where background may be used. None when a pose box is unavailable, since the climber cannot be excluded."""
    height, width = shape
    boxes = []
    for record in records:
        points = [(lm["x"], lm["y"]) for lm in (record.get("landmarks") or []) if lm["x"] is not None and lm["y"] is not None]
        if not points:
            return None
        xs, ys = zip(*points)
        boxes.append((min(xs) * width, min(ys) * height, max(xs) * width, max(ys) * height))
    mask = np.full(shape, 255, np.uint8)
    for x0, y0, x1, y1 in boxes:
        margin = limits.climber_margin_fraction * max(x1 - x0, y1 - y0)
        cv2.rectangle(mask, (int(x0 - margin), int(y0 - margin)), (int(x1 + margin), int(y1 + margin)), 0, -1)
    return mask


def estimate_interval(
    previous: np.ndarray, current: np.ndarray, mask: np.ndarray | None, full_scale: float, limits: TransformLimits,
) -> dict[str, Any]:
    """Similarity transform from `previous` to `current`. Returned matrix is in canonical pixels."""
    result: dict[str, Any] = {"accepted": False, "reason": None, "matrix": None, "inliers": 0, "inlier_ratio": None,
                              "median_residual_px": None, "scale": None, "rotation_deg": None}
    if mask is None:
        result["reason"] = "no_pose_to_exclude_climber"
        return result
    corners = cv2.goodFeaturesToTrack(previous, maxCorners=500, qualityLevel=0.01, minDistance=7, mask=mask)
    if corners is None or len(corners) < limits.min_inliers:
        result["reason"] = "too_few_background_features"
        return result
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, corners, None, winSize=(21, 21), maxLevel=3)
    good = status.ravel() == 1
    source, target = corners[good], tracked[good]
    if len(source) < limits.min_inliers:
        result["reason"] = "too_few_tracked_features"
        return result
    matrix, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=2000, confidence=0.99, refineIters=10)
    if matrix is None or inliers is None:
        result["reason"] = "no_transform"
        return result
    kept = inliers.ravel() == 1
    count, ratio = int(kept.sum()), float(kept.mean())
    predicted = (matrix[:, :2] @ source[kept].reshape(-1, 2).T).T + matrix[:, 2]
    residual = float(np.median(np.linalg.norm(predicted - target[kept].reshape(-1, 2), axis=1))) / full_scale
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    rotation = float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0])))
    full = matrix.copy()
    full[:, 2] /= full_scale
    result.update(inliers=count, inlier_ratio=ratio, median_residual_px=residual, scale=scale, rotation_deg=rotation, matrix=full.tolist())
    if count < limits.min_inliers:
        result["reason"] = "too_few_inliers"
    elif ratio < limits.min_inlier_ratio:
        result["reason"] = "low_inlier_ratio"
    elif residual > limits.max_median_residual_px:
        result["reason"] = "high_residual"
    elif abs(scale - 1) > limits.max_scale_change:
        result["reason"] = "implausible_scale"
    elif abs(rotation) > limits.max_rotation_deg:
        result["reason"] = "implausible_rotation"
    else:
        result["accepted"] = True
    return result


BACKGROUND_METHOD = "background_similarity_v1"
FALLBACK_METHOD = "phase_correlation_fallback"
_GEOMETRY_REJECTIONS = {"implausible_scale", "implausible_rotation"}


def frame_gray(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    """Grayscale at the analysis size, and the factor from canonical pixels to it."""
    height, width = rgb.shape[:2]
    scale = min(1.0, ANALYSIS_LONG_SIDE_PX / max(width, height))
    return cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale


def largest_corner_motion_px(matrix: Sequence[Sequence[float]], width: int, height: int, scale: float) -> float:
    """Farthest any image corner moves, in canonical pixels. Unlike translation, this also sees rotation and zoom."""
    transform = np.array(matrix, dtype=float)
    corners = np.array([[0, 0], [width, 0], [0, height], [width, height]], dtype=float) * scale
    moved = (transform[:, :2] @ corners.T).T + transform[:, 2] * scale
    return float(np.max(np.linalg.norm(moved - corners, axis=1))) / scale


def measure_camera_motion(
    previous: np.ndarray, current: np.ndarray, scale: float, width: int, height: int,
    records: Sequence[dict[str, Any]], limits: TransformLimits = TransformLimits(),
) -> dict[str, Any] | None:
    """Background-only camera motion for eligibility. None means abstain, and the caller uses its fallback.

    The climber region is excluded, so a person moving on a static wall is not camera motion. A large but
    well-supported rotation or zoom counts as measured motion instead of an abstention. This measures every
    clip; it does not trust any label saying the camera was fixed.
    """
    result = estimate_interval(previous, current, climber_mask(previous.shape, records, limits), scale, limits)
    usable = result["accepted"] or result["reason"] in _GEOMETRY_REJECTIONS
    if not usable or result["matrix"] is None:
        return None
    return {"method": BACKGROUND_METHOD, "shift_px": largest_corner_motion_px(result["matrix"], width, height, scale),
            "response": float(result["inlier_ratio"]), "inliers": result["inliers"]}


def estimate_track(video_frames: dict[int, np.ndarray], records: Sequence[dict[str, Any]], limits: TransformLimits) -> list[dict[str, Any]]:
    """One result per interval between consecutive samples."""
    results: list[dict[str, Any]] = []
    previous_gray, previous_record = None, None
    for record in records:
        rgb = video_frames[record["frame_index"]]
        height, width = rgb.shape[:2]
        scale = min(1.0, ANALYSIS_LONG_SIDE_PX / max(width, height))
        gray = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if previous_gray is not None:
            mask = climber_mask(previous_gray.shape, [previous_record, record], limits)
            results.append(estimate_interval(previous_gray, gray, mask, scale, limits))
        previous_gray, previous_record = gray, record
    return results


def _homogeneous(matrix: Sequence[Sequence[float]]) -> np.ndarray:
    return np.vstack([np.array(matrix, dtype=float), [0.0, 0.0, 1.0]])


def compensated_records(
    records: Sequence[dict[str, Any]], intervals: Sequence[dict[str, Any]], width: int, height: int,
) -> list[dict[str, Any]]:
    """Copies of `records` with joints mapped back to the frame at the start of each reliable chain.

    The chain resets at any rejected interval, and detectors also break segments there, so
    no motion is inferred across an unreliable transform. The originals are not modified.
    """
    output: list[dict[str, Any]] = []
    cumulative = np.eye(3)
    for index, record in enumerate(records):
        if index > 0:
            step = intervals[index - 1]
            cumulative = _homogeneous(step["matrix"]) @ cumulative if step["accepted"] else np.eye(3)
        inverse = np.linalg.inv(cumulative)
        copy = {**record}
        if record.get("landmarks"):
            mapped = []
            for landmark in record["landmarks"]:
                item = {**landmark}
                if landmark["x"] is not None and landmark["y"] is not None:
                    point = inverse @ np.array([landmark["x"] * width, landmark["y"] * height, 1.0])
                    item["x"], item["y"] = float(point[0] / width), float(point[1] / height)
                mapped.append(item)
            copy["landmarks"] = mapped
        output.append(copy)
    return output


def with_transform_camera_state(records: Sequence[dict[str, Any]], intervals: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark accepted intervals as compensated and rejected ones as moving, for eligibility."""
    output = [{**records[0]}]
    for record, step in zip(records[1:], intervals):
        output.append({**record, "camera_shift_px": 0.0 if step["accepted"] else 1e9, "camera_shift_response": 1.0})
    return output
