"""Rule-based detectors for low visible movement and per-wrist movement episodes.

Events describe image-space observations. A low-movement interval is not hesitation
or fatigue; a wrist episode is not proof of a grip change or hold contact. Thresholds
are unvalidated starting values.
"""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

from .config import PipelineConfig
from .features import (Segment, contiguous_segments, joint_positions_px, smooth_within_segment,
                       speed_within_segment)
from .quality import DETECTOR_LANDMARKS, TrackValidity, landmark_lookup

DETECTOR_VERSION = "detectors-v1"
QUALITY_METHOD_VERSION = "quality-rules-v1"
GOOD_MEDIAN_VISIBILITY = 0.85
FAIR_MEDIAN_VISIBILITY = 0.70


def _tracking_quality(records: Sequence[dict[str, Any]], first: int, last: int, names: Sequence[str]) -> dict[str, Any]:
    """Descriptive label from visibility of the required landmarks; not a probability."""
    visibilities = [min(landmark_lookup(r)[n]["visibility"] for n in names) for r in records[first: last + 1]]
    median = float(np.median(visibilities))
    label = "good" if median >= GOOD_MEDIAN_VISIBILITY else "fair" if median >= FAIR_MEDIAN_VISIBILITY else "weak"
    return {"label": label, "method_version": QUALITY_METHOD_VERSION,
            "median_min_required_visibility": round(median, 3), "is_calibrated_event_probability": False}


def _event_id(kind: str, hand: str | None, start_ms: int, end_ms: int) -> str:
    return "evt-" + hashlib.sha256(f"{kind}|{hand}|{start_ms}|{end_ms}".encode()).hexdigest()[:12]


def _segment_times(records: Sequence[dict[str, Any]], segment: Segment) -> np.ndarray:
    return np.array([r["timestamp_ms"] for r in records[segment.first: segment.last + 1]], dtype=float)


def _joint_speeds(
    records, segment: Segment, name: str, width: int, height: int, length_px: float, config: PipelineConfig,
    smoothing: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    times = _segment_times(records, segment)
    raw = joint_positions_px(records, segment, name, width, height)
    positions = smooth_within_segment(times, raw, config.features.smoothing_window_s) if smoothing else raw
    return times, positions, speed_within_segment(times, positions, length_px, config.features)


def _detector_available(coverage: dict[str, Any]) -> bool:
    return coverage["status"] == "available"


def detect_low_movement(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, config: PipelineConfig,
    smoothing: bool = True,
) -> list[dict[str, Any]]:
    cfg = config.low_movement
    length = validity.scale["L_px"]
    names = DETECTOR_LANDMARKS["low_movement"]
    max_gap = 1000 / config.analysis.inference_fps * config.quality.max_sample_gap_factor
    events: list[dict[str, Any]] = []
    for segment in contiguous_segments(records, validity, names, max_gap):
        if segment.last == segment.first:
            continue
        times = _segment_times(records, segment)
        joint_speeds = np.vstack([
            _joint_speeds(records, segment, name, width, height, length, config, smoothing)[2] for name in names
        ])
        with np.errstate(invalid="ignore"):
            movement = np.max(joint_speeds, axis=0)
            movement[np.isnan(joint_speeds).any(axis=0)] = np.nan
            still = movement < cfg.max_joint_speed_L_per_s

        runs: list[list[int]] = []
        for i, is_still in enumerate(still):
            if not is_still:
                continue
            if runs and i == runs[-1][1] + 1:
                runs[-1][1] = i
            elif runs and times[i] - times[runs[-1][1]] <= cfg.max_fully_observed_interruption_s * 1000:
                runs[-1][1] = i  # interruption lies inside this segment, so it is fully observed
            else:
                runs.append([i, i])

        for run_first, run_last in runs:
            start_ms, end_ms = int(times[run_first]), int(times[run_last])
            if end_ms - start_ms < cfg.min_duration_s * 1000:
                continue
            window = movement[run_first: run_last + 1]
            events.append({
                "id": _event_id("low_movement", None, start_ms, end_ms),
                "type": "low_movement",
                "hand": None,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "truncated": False,
                "evidence": {
                    "duration_ms": end_ms - start_ms,
                    "max_required_joint_speed_L_per_s": round(float(np.nanmax(window)), 4),
                    "median_required_joint_speed_L_per_s": round(float(np.nanmedian(window)), 4),
                    "configured_speed_limit_L_per_s": cfg.max_joint_speed_L_per_s,
                    "required_joints": list(names),
                    "attempt_scale_px": length,
                    "samples": run_last - run_first + 1,
                },
                "tracking_quality": _tracking_quality(
                    records, segment.first + run_first, segment.first + run_last, names),
            })
    return events


def _finish_wrist_episode(
    records, segment: Segment, side: str, times: np.ndarray, positions: np.ndarray, speeds: np.ndarray,
    first: int, last: int, length: float, config: PipelineConfig, truncated_start: bool, truncated_end: bool,
    names: Sequence[str], end_is_attempt_boundary: bool, start_is_attempt_boundary: bool,
) -> dict[str, Any] | None:
    cfg = config.wrist_motion
    start_ms, end_ms = int(times[first]), int(times[last])
    path = positions[first: last + 1]
    displacement = float(np.max(np.linalg.norm(path - path[0], axis=1))) / length
    if end_ms - start_ms < cfg.min_duration_s * 1000 or displacement < cfg.min_displacement_L:
        return None
    path_length = float(np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1))) / length
    window = speeds[first: last + 1]
    return {
        "id": _event_id("wrist_motion", side, start_ms, end_ms),
        "type": "wrist_motion",
        "hand": side,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "truncated": truncated_start or truncated_end,
        "evidence": {
            "duration_ms": end_ms - start_ms,
            "max_displacement_L": round(displacement, 4),
            "path_length_L": round(path_length, 4),
            "peak_speed_L_per_s": round(float(np.nanmax(window)), 4),
            "configured_onset_L_per_s": cfg.onset_speed_L_per_s,
            "configured_offset_L_per_s": cfg.offset_speed_L_per_s,
            "attempt_scale_px": length,
            "truncated_start": truncated_start,
            "truncated_end": truncated_end,
            "truncation_cause": ("attempt_boundary" if (truncated_end and end_is_attempt_boundary)
                                 or (truncated_start and start_is_attempt_boundary) else
                                 "tracking_gap" if truncated_start or truncated_end else None),
        },
        "tracking_quality": _tracking_quality(records, segment.first + first, segment.first + last, names),
    }


def detect_wrist_motion(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, side: str,
    config: PipelineConfig, smoothing: bool = True, hysteresis: bool = True,
) -> list[dict[str, Any]]:
    cfg = config.wrist_motion
    length = validity.scale["L_px"]
    names = DETECTOR_LANDMARKS[f"wrist_motion_{side}"]
    wrist = f"{side}_wrist"
    max_gap = 1000 / config.analysis.inference_fps * config.quality.max_sample_gap_factor
    onset = cfg.onset_speed_L_per_s
    offset = cfg.offset_speed_L_per_s if hysteresis else cfg.onset_speed_L_per_s
    dwell_ms = cfg.offset_dwell_s * 1000 if hysteresis else 0.0
    events: list[dict[str, Any]] = []
    last_sample = len(records) - 1

    for segment in contiguous_segments(records, validity, names, max_gap):
        if segment.last == segment.first:
            continue
        times, positions, speeds = _joint_speeds(records, segment, wrist, width, height, length, config, smoothing)
        started: int | None = None
        below_from: int | None = None
        start_truncated = False
        for i, speed in enumerate(speeds):
            if np.isnan(speed):
                continue
            if started is None:
                if speed > onset:
                    started, below_from = i, None
                    start_truncated = i <= 1
                continue
            if speed >= offset:
                below_from = None
                continue
            if below_from is None:
                below_from = i
            if times[i] - times[below_from] >= dwell_ms:
                event = _finish_wrist_episode(
                    records, segment, side, times, positions, speeds, started, below_from, length, config,
                    start_truncated, False, names, False, segment.first == 0)
                if event:
                    events.append(event)
                started, below_from = None, None
        if started is not None:
            end = below_from if below_from is not None else len(times) - 1
            event = _finish_wrist_episode(
                records, segment, side, times, positions, speeds, started, end, length, config,
                start_truncated, below_from is None, names, segment.last == last_sample, segment.first == 0)
            if event:
                events.append(event)
    return events


def run_detectors(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int,
    coverage: dict[str, Any], config: PipelineConfig, smoothing: bool = True, hysteresis: bool = True,
) -> dict[str, Any]:
    """Run each detector only if its coverage allows; an unavailable detector has a null count."""
    results: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    detectors = coverage["detectors"]
    for name in ("low_movement", "wrist_motion_left", "wrist_motion_right"):
        if not _detector_available(detectors[name]):
            results[name] = {"status": "insufficient_tracking", "reason": detectors[name]["reason"], "event_count": None}
            continue
        if name == "low_movement":
            found = detect_low_movement(records, validity, width, height, config, smoothing)
        else:
            found = detect_wrist_motion(records, validity, width, height, name.rsplit("_", 1)[1], config,
                                        smoothing, hysteresis)
        results[name] = {"status": "available", "reason": None, "event_count": len(found)}
        events.extend(found)
    events.sort(key=lambda e: (e["start_ms"], e["type"], e["hand"] or ""))
    return {"detector_version": DETECTOR_VERSION, "detectors": results, "events": events}
