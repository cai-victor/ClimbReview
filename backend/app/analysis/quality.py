"""Landmark validity, attempt scale, and detector-specific tracking coverage.

Coverage is observed data availability. It is not event accuracy, it is not a
calibrated probability, and it cannot show that landmarks are correctly aligned.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .config import QualityConfig

SCALE_LANDMARKS = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")

# What each proposed detector needs to be valid at a sample (docs/PROJECT_SPEC.md §6).
DETECTOR_LANDMARKS: dict[str, tuple[str, ...]] = {
    "low_movement": ("left_wrist", "right_wrist", "left_ankle", "right_ankle", "left_hip", "right_hip"),
    "wrist_motion_left": ("left_shoulder", "left_elbow", "left_wrist"),
    "wrist_motion_right": ("right_shoulder", "right_elbow", "right_wrist"),
}


def landmark_invalid_reason(landmark: dict[str, Any] | None, cfg: QualityConfig) -> str | None:
    """Return why a landmark is unavailable, or None when it may be used."""
    if landmark is None:
        return "no_pose"
    x, y = landmark.get("x"), landmark.get("y")
    if x is None or y is None:
        return "non_finite"
    margin = cfg.out_of_frame_margin
    if not (-margin <= x <= 1 + margin and -margin <= y <= 1 + margin):
        return "out_of_frame"
    visibility = landmark.get("visibility")
    if visibility is None:
        return "visibility_missing"
    if visibility < cfg.min_visibility:
        return "low_visibility"
    presence = landmark.get("presence")
    if presence is not None and presence < cfg.min_presence_if_available:
        return "low_presence"
    return None


def landmark_lookup(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {lm["name"]: lm for lm in (record.get("landmarks") or [])}


def invalid_reasons(record: dict[str, Any], names: Sequence[str], cfg: QualityConfig) -> dict[str, str]:
    """Map each listed landmark that is unavailable in this sample to its reason."""
    lookup = landmark_lookup(record)
    reasons = {name: landmark_invalid_reason(lookup.get(name), cfg) for name in names}
    return {name: reason for name, reason in reasons.items() if reason is not None}


def to_pixels(landmark: dict[str, Any], width: int, height: int) -> tuple[float, float]:
    """Normalized coordinates are scaled per axis, so distances must use pixels."""
    return landmark["x"] * width, landmark["y"] * height


def torso_scale(records: Sequence[dict[str, Any]], width: int, height: int, cfg: QualityConfig) -> dict[str, Any]:
    """Median shoulder-midpoint to hip-midpoint length; not a physical calibration."""
    minimum = cfg.min_torso_fraction_of_diagonal * math.hypot(width, height)
    lengths: list[float] = []
    degenerate = 0
    for record in records:
        if invalid_reasons(record, SCALE_LANDMARKS, cfg):
            continue
        lookup = landmark_lookup(record)
        left_s, right_s = (np.array(to_pixels(lookup[n], width, height)) for n in SCALE_LANDMARKS[:2])
        left_h, right_h = (np.array(to_pixels(lookup[n], width, height)) for n in SCALE_LANDMARKS[2:])
        length = float(np.linalg.norm((left_s + right_s) / 2 - (left_h + right_h) / 2))
        if length < minimum:
            degenerate += 1
        else:
            lengths.append(length)
    base = {
        "method": "median_shoulder_midpoint_to_hip_midpoint_px",
        "reliable_samples": len(lengths),
        "degenerate_samples_excluded": degenerate,
        "required_samples": cfg.min_scale_samples,
        "is_physical_calibration": False,
    }
    if len(lengths) < cfg.min_scale_samples:
        return {**base, "status": "unavailable", "L_px": None, "p10_px": None, "p90_px": None,
                "reason": "too_few_reliable_torso_samples"}
    return {
        **base, "status": "available", "reason": None,
        "L_px": round(float(np.median(lengths)), 3),
        "p10_px": round(float(np.percentile(lengths, 10)), 3),
        "p90_px": round(float(np.percentile(lengths, 90)), 3),
    }


def eligible_segments(
    times_ms: Sequence[int], valid: Sequence[bool], max_gap_ms: float, blocked: Sequence[str | None] | None = None,
) -> list[tuple[int, int]]:
    """Merge intervals between consecutive samples that are both valid.

    An interval earns credit only when both endpoints are valid and the samples
    are close enough to count as continuous. A lone valid sample earns none, and
    no interval is ever carried across an invalid sample or a blocked interval.
    """
    segments: list[tuple[int, int]] = []
    for i in range(len(times_ms) - 1):
        if not (valid[i] and valid[i + 1] and times_ms[i + 1] - times_ms[i] <= max_gap_ms):
            continue
        if blocked is not None and blocked[i] is not None:
            continue
        if segments and segments[-1][1] == times_ms[i]:
            segments[-1] = (segments[-1][0], times_ms[i + 1])
        else:
            segments.append((times_ms[i], times_ms[i + 1]))
    return segments


def coverage_gaps(
    segments: Sequence[tuple[int, int]], start_ms: int, end_ms: int, sample_period_ms: float,
) -> list[dict[str, int]]:
    """Attempt time outside eligible segments, ignoring sub-sample edge remainders."""
    gaps: list[dict[str, int]] = []
    cursor = start_ms
    for seg_start, seg_end in [*segments, (end_ms, end_ms)]:
        if seg_start - cursor > sample_period_ms:
            gaps.append({"start_ms": cursor, "end_ms": seg_start, "duration_ms": seg_start - cursor})
        cursor = seg_end
    return gaps


def _torso_length_px(record: dict[str, Any], width: int, height: int) -> float | None:
    lookup = landmark_lookup(record)
    if any(lookup.get(n, {}).get("x") is None or lookup.get(n, {}).get("y") is None for n in SCALE_LANDMARKS):
        return None
    left_s, right_s, left_h, right_h = (np.array(to_pixels(lookup[n], width, height)) for n in SCALE_LANDMARKS)
    return float(np.linalg.norm((left_s + right_s) / 2 - (left_h + right_h) / 2))


@dataclass(frozen=True)
class TrackValidity:
    """Derived usability of each sample; the single source of truth for later stages."""
    scale: dict[str, Any]
    reasons: list[dict[str, str]]        # per sample: landmark name -> reason unavailable
    blocked: list[str | None]            # per interval between samples i and i + 1


def derive_validity(
    records: Sequence[dict[str, Any]], width: int, height: int, cfg: QualityConfig, sample_period_ms: float,
) -> TrackValidity:
    """Per-landmark reasons, pose plausibility, and interval-level exclusions."""
    from .pose import LANDMARK_NAMES

    scale = torso_scale(records, width, height, cfg)
    length = scale["L_px"]
    reasons: list[dict[str, str]] = []
    for record in records:
        sample = invalid_reasons(record, LANDMARK_NAMES, cfg)
        if length:
            torso = _torso_length_px(record, width, height)
            if torso is not None and not (cfg.min_torso_ratio_to_attempt_scale
                                          <= torso / length <= cfg.max_torso_ratio_to_attempt_scale):
                sample = {name: sample.get(name, "implausible_torso_scale") for name in LANDMARK_NAMES}
        reasons.append(sample)

    blocked: list[str | None] = []
    for before, after in zip(records, records[1:]):
        reason = None
        elapsed_s = (after["timestamp_ms"] - before["timestamp_ms"]) / 1000
        shift, response = after.get("camera_shift_px"), after.get("camera_shift_response")
        if after.get("repeated_source_frame"):
            reason = "repeated_source_frame"
        elif (length and shift is not None and response is not None and elapsed_s > 0
              and response >= cfg.camera_min_correlation_response
              and shift / elapsed_s / length > cfg.camera_max_speed_L_per_s):
            reason = "camera_motion"
        blocked.append(reason)
    return TrackValidity(scale, reasons, blocked)


def _detector_coverage(
    names: Sequence[str], records: Sequence[dict[str, Any]], start_ms: int, end_ms: int,
    validity: TrackValidity, cfg: QualityConfig, sample_period_ms: float,
) -> dict[str, Any]:
    attempt_ms = end_ms - start_ms
    times = [r["timestamp_ms"] for r in records]
    per_sample = [{n: sample[n] for n in names if n in sample} for sample in validity.reasons]
    valid = [not reasons for reasons in per_sample]
    segments = eligible_segments(times, valid, sample_period_ms * cfg.max_sample_gap_factor, validity.blocked)
    observed_ms = sum(b - a for a, b in segments)
    scale_available = validity.scale["status"] == "available"

    per_landmark: dict[str, Any] = {}
    for name in names:
        tally: dict[str, int] = {}
        for reasons in per_sample:
            if name in reasons:
                tally[reasons[name]] = tally.get(reasons[name], 0) + 1
        invalid = sum(tally.values())
        per_landmark[name] = {
            "valid_samples": len(records) - invalid,
            "valid_fraction": round((len(records) - invalid) / len(records), 4) if records else None,
            "invalid_reasons": tally,
        }

    if not records:
        reason = "no_samples"
    elif not scale_available:
        reason = "attempt_scale_unavailable"
    elif observed_ms == 0:
        reason = "no_contiguous_eligible_interval"
    else:
        reason = None
    available = reason is None
    return {
        "status": "available" if available else "insufficient_tracking",
        "reason": reason,
        "required_landmarks": list(names),
        "requires_attempt_scale": True,
        "attempt_ms": attempt_ms,
        "sampled_frames": len(records),
        "samples_with_required_landmarks": sum(valid),
        "landmarks_contiguously_valid_ms": observed_ms,
        # Null, not zero: an unavailable detector has no measurable eligible time.
        "eligible_ms": observed_ms if available else None,
        "fraction": round(observed_ms / attempt_ms, 4) if available else None,
        "eligible_segment_count": len(segments),
        "longest_eligible_segment_ms": max((b - a for a, b in segments), default=0),
        "gaps": coverage_gaps(segments, start_ms, end_ms, sample_period_ms),
        "per_landmark": per_landmark,
    }


def compute_coverage(
    records: Sequence[dict[str, Any]], width: int, height: int, start_ms: int, end_ms: int,
    cfg: QualityConfig, sample_period_ms: float, low_movement_target: float,
    validity: TrackValidity | None = None,
) -> dict[str, Any]:
    validity = validity or derive_validity(records, width, height, cfg, sample_period_ms)
    detected = sum(r["pose_detected"] for r in records)
    detectors = {
        name: _detector_coverage(landmarks, records, start_ms, end_ms, validity, cfg, sample_period_ms)
        for name, landmarks in DETECTOR_LANDMARKS.items()
    }
    low_fraction = detectors["low_movement"]["fraction"]
    blocked_counts: dict[str, int] = {}
    for reason in validity.blocked:
        if reason:
            blocked_counts[reason] = blocked_counts.get(reason, 0) + 1
    interval_count = max(len(records) - 1, 0)
    camera_count = blocked_counts.get("camera_motion", 0)
    return {
        "attempt_bounds_ms": {"start": start_ms, "end": end_ms},
        "timebase": "canonical_video_ms",
        "meaning": "Observed landmark availability only. Not alignment accuracy, event accuracy, or a probability.",
        "sampled_frames": len(records),
        "pose_detected_samples": detected,
        "pose_detected_fraction": round(detected / len(records), 4) if records else None,
        "attempt_scale": validity.scale,
        "excluded_intervals": blocked_counts,
        "camera_motion_interval_fraction": round(camera_count / interval_count, 4) if interval_count else None,
        "detectors": detectors,
        "provisional_coverage_target": {
            "detector": "low_movement",
            "target_fraction": low_movement_target,
            "met": None if low_fraction is None else bool(low_fraction >= low_movement_target),
            "note": "Provisional engineering target. Meeting it does not show the skeleton is aligned.",
        },
    }


def timeline_rows(
    records: Sequence[dict[str, Any]], cfg: QualityConfig, validity: TrackValidity | None = None,
) -> list[dict[str, Any]]:
    """One row per sample for the coverage timeline CSV."""
    all_required = sorted({n for names in DETECTOR_LANDMARKS.values() for n in names} | set(SCALE_LANDMARKS))
    rows = []
    for position, record in enumerate(records):
        if validity is None:
            unavailable = invalid_reasons(record, all_required, cfg)
        else:
            unavailable = {n: validity.reasons[position][n] for n in all_required if n in validity.reasons[position]}
        row = {"frame_index": record["frame_index"], "timestamp_ms": record["timestamp_ms"],
               "pose_detected": int(record["pose_detected"])}
        for detector, names in DETECTOR_LANDMARKS.items():
            row[f"{detector}_landmarks_valid"] = int(not any(n in unavailable for n in names))
        row["scale_landmarks_valid"] = int(not any(n in unavailable for n in SCALE_LANDMARKS))
        row["unavailable"] = ";".join(f"{name}:{reason}" for name, reason in unavailable.items())
        rows.append(row)
    return rows
