"""Rule-based detectors for low visible movement and per-wrist movement episodes.

Events describe image-space observations. A low-movement interval is not hesitation
or fatigue; a wrist episode is not proof of a grip change or hold contact. Thresholds
are unvalidated starting values.
"""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

from .config import PipelineConfig, QualityConfig
from .features import (Segment, contiguous_segments, joint_positions_px, smooth_within_segment,
                       speed_within_segment)
from .quality import DETECTOR_LANDMARKS, TrackValidity, invalid_reasons, landmark_lookup, to_pixels

DETECTOR_VERSION = "detectors-v2-footwork"
QUALITY_METHOD_VERSION = "quality-rules-v1"
GOOD_MEDIAN_VISIBILITY = 0.85
FAIR_MEDIAN_VISIBILITY = 0.70
CLEAR_NET_DISPLACEMENT_L = 0.15     # below this, a limb ended about where it started
FOOT_SUPPORT_MIN_VALID = 0.8        # heel or toe must be usable for this share of the episode to count
FOOT_SUPPORT_ABS_L = 0.25           # allowed difference from the ankle's net displacement
FOOT_SUPPORT_RELATIVE = 0.6         # or this share of the ankle's own net displacement, whichever is larger


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


def direction_label(x_L: float, up_L: float) -> str:
    """Image-plane direction of a net displacement. 'image left' is the viewer's left, not the climber's."""
    if float(np.hypot(x_L, up_L)) < CLEAR_NET_DISPLACEMENT_L:
        return "no_clear_net_direction"
    vertical = "up" if up_L > 0 else "down"
    lateral = "image_right" if x_L > 0 else "image_left"
    if abs(up_L) >= 2 * abs(x_L):
        return vertical
    return lateral if abs(x_L) >= 2 * abs(up_L) else f"{vertical}_and_{lateral}"


def _unstable_ankle_fraction(
    records, first: int, last: int, side: str, width: int, height: int, length: float, foot,
) -> float:
    """Share of samples where knee-to-ankle length swings while the ankle is less certain.

    A shin keeps its length; its picture changes smoothly as the leg turns. Rapid swings together with lower
    visibility were seen when the model guessed a hidden foot. Short or matched feet and bent knees alone do not trigger this.
    """
    def shin(record) -> float | None:
        lookup = landmark_lookup(record)
        knee, ankle = lookup.get(f"{side}_knee"), lookup.get(f"{side}_ankle")
        if not knee or not ankle or None in (knee["x"], knee["y"], ankle["x"], ankle["y"]):
            return None
        return float(np.hypot((knee["x"] - ankle["x"]) * width, (knee["y"] - ankle["y"]) * height)) / length

    flagged = 0
    half_ms = foot.unstable_half_window_s * 1000
    for index in range(first, last + 1):
        center = records[index]
        lookup = landmark_lookup(center).get(f"{side}_ankle") or {}
        lengths = [value for r in records if abs(r["timestamp_ms"] - center["timestamp_ms"]) <= half_ms
                   and r.get("landmarks") and (value := shin(r)) is not None]
        visibility = lookup.get("visibility")
        if len(lengths) >= 3 and visibility is not None and visibility < foot.unstable_max_ankle_visibility \
                and float(np.std(lengths)) > foot.unstable_shin_std_L:
            flagged += 1
    return flagged / (last - first + 1)


def _foot_support(
    records, segment: Segment, side: str, first: int, last: int, width: int, height: int, length: float,
    cfg: QualityConfig, ankle_net_px: np.ndarray, foot,
) -> dict[str, Any]:
    """How the heel and toe points moved during an ankle episode. They support the ankle; they never create an event."""
    rows = records[segment.first + first: segment.first + last + 1]
    agreement: dict[str, bool] = {}
    support: dict[str, Any] = {}
    for label, name in (("heel", f"{side}_heel"), ("toe", f"{side}_foot_index")):
        valid = [i for i, r in enumerate(rows) if not invalid_reasons(r, (name,), cfg)]
        fraction = len(valid) / len(rows)
        net = None
        if fraction >= FOOT_SUPPORT_MIN_VALID and len(valid) >= 2:
            begin = np.array(to_pixels(landmark_lookup(rows[valid[0]])[name], width, height))
            end = np.array(to_pixels(landmark_lookup(rows[valid[-1]])[name], width, height))
            net = (end - begin) / length
            allowed = max(FOOT_SUPPORT_ABS_L, FOOT_SUPPORT_RELATIVE * float(np.linalg.norm(ankle_net_px)) / length)
            agreement[label] = float(np.linalg.norm(net - ankle_net_px / length)) <= allowed
        support[f"{label}_valid_fraction"] = round(fraction, 3)
        support[f"{label}_net_displacement_L"] = None if net is None else round(float(np.linalg.norm(net)), 4)
    state = "unavailable" if not agreement else "agrees" if all(agreement.values()) else "differs"
    unstable = _unstable_ankle_fraction(records, segment.first + first, segment.first + last, side, width, height, length, foot)
    return {**support, "state": state, "points_compared": sorted(agreement), "tracked_point": "ankle", "anchor_unstable_fraction": round(unstable, 3),
            "anchor_state": "uncertain" if unstable >= foot.uncertain_min_fraction else "stable",
            "limitation": "The ankle landmark stands in for the foot. It does not locate the shoe sole or show contact."}


def _finish_limb_episode(
    records, segment: Segment, side: str, kind: str, cfg, times: np.ndarray, positions: np.ndarray, speeds: np.ndarray,
    first: int, last: int, length: float, config: PipelineConfig, truncated_start: bool, truncated_end: bool,
    names: Sequence[str], end_is_attempt_boundary: bool, start_is_attempt_boundary: bool, width: int, height: int,
) -> dict[str, Any] | None:
    start_ms, end_ms = int(times[first]), int(times[last])
    path = positions[first: last + 1]
    displacement = float(np.max(np.linalg.norm(path - path[0], axis=1))) / length
    if end_ms - start_ms < cfg.min_duration_s * 1000 or displacement < cfg.min_displacement_L:
        return None
    path_length = float(np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1))) / length
    window = speeds[first: last + 1]
    net_px = path[-1] - path[0]
    x_L, up_L = float(net_px[0]) / length, -float(net_px[1]) / length   # image y grows downward
    evidence = {
        "duration_ms": end_ms - start_ms,
        "max_displacement_L": round(displacement, 4),
        "path_length_L": round(path_length, 4),
        "net_displacement_L": round(float(np.hypot(x_L, up_L)), 4),
        "net_image_right_L": round(x_L, 4),
        "net_up_L": round(up_L, 4),
        "direction": direction_label(x_L, up_L),
        "peak_speed_L_per_s": round(float(np.nanmax(window)), 4),
        "peak_speed_ms": int(times[first + int(np.nanargmax(window))]),
        "configured_onset_L_per_s": cfg.onset_speed_L_per_s,
        "configured_offset_L_per_s": cfg.offset_speed_L_per_s,
        "attempt_scale_px": length,
        "truncated_start": truncated_start,
        "truncated_end": truncated_end,
        "truncation_cause": ("attempt_boundary" if (truncated_end and end_is_attempt_boundary)
                             or (truncated_start and start_is_attempt_boundary) else
                             "tracking_gap" if truncated_start or truncated_end else None),
    }
    if kind == "foot_motion":
        evidence["foot_support"] = _foot_support(records, segment, side, first, last, width, height, length,
                                                 config.quality, net_px, config.foot_motion)
    return {
        "id": _event_id(kind, side, start_ms, end_ms),
        "type": kind,
        "hand": side,   # the body side; the name is kept so stored events and label files stay compatible
        "start_ms": start_ms,
        "end_ms": end_ms,
        "truncated": truncated_start or truncated_end,
        "evidence": evidence,
        "tracking_quality": _tracking_quality(records, segment.first + first, segment.first + last, names),
    }


def _detect_limb_motion(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, side: str, kind: str,
    anchor: str, cfg, config: PipelineConfig, smoothing: bool, hysteresis: bool,
) -> list[dict[str, Any]]:
    length = validity.scale["L_px"]
    names = DETECTOR_LANDMARKS[f"{kind}_{side}"]
    max_gap = 1000 / config.analysis.inference_fps * config.quality.max_sample_gap_factor
    onset = cfg.onset_speed_L_per_s
    offset = cfg.offset_speed_L_per_s if hysteresis else cfg.onset_speed_L_per_s
    dwell_ms = cfg.offset_dwell_s * 1000 if hysteresis else 0.0
    events: list[dict[str, Any]] = []
    last_sample = len(records) - 1

    def finish(segment, times, positions, speeds, first, last, truncated_start, truncated_end, end_boundary):
        return _finish_limb_episode(records, segment, side, kind, cfg, times, positions, speeds, first, last, length, config,
                                    truncated_start, truncated_end, names, end_boundary, segment.first == 0, width, height)

    for segment in contiguous_segments(records, validity, names, max_gap):
        if segment.last == segment.first:
            continue
        times, positions, speeds = _joint_speeds(records, segment, anchor, width, height, length, config, smoothing)
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
                event = finish(segment, times, positions, speeds, started, below_from, start_truncated, False, False)
                if event:
                    events.append(event)
                started, below_from = None, None
        if started is not None:
            end = below_from if below_from is not None else len(times) - 1
            event = finish(segment, times, positions, speeds, started, end, start_truncated, below_from is None,
                           segment.last == last_sample)
            if event:
                events.append(event)
    return events


def detect_wrist_motion(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, side: str,
    config: PipelineConfig, smoothing: bool = True, hysteresis: bool = True,
) -> list[dict[str, Any]]:
    return _detect_limb_motion(records, validity, width, height, side, "wrist_motion", f"{side}_wrist", config.wrist_motion,
                               config, smoothing, hysteresis)


def detect_foot_motion(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, side: str,
    config: PipelineConfig, smoothing: bool = True, hysteresis: bool = True,
) -> list[dict[str, Any]]:
    """Left or right ankle movement episodes, each gated only by that side's own ankle."""
    return _detect_limb_motion(records, validity, width, height, side, "foot_motion", f"{side}_ankle", config.foot_motion,
                               config, smoothing, hysteresis)


def run_detectors(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int,
    coverage: dict[str, Any], config: PipelineConfig, smoothing: bool = True, hysteresis: bool = True,
) -> dict[str, Any]:
    """Run each detector only if its coverage allows; an unavailable detector has a null count."""
    results: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    detectors = coverage["detectors"]
    for name in ("low_movement", "wrist_motion_left", "wrist_motion_right", "foot_motion_left", "foot_motion_right"):
        if name.startswith("foot") and config.foot_motion is None:
            results[name] = {"status": "not_run", "reason": "configuration_predates_foot_analysis", "event_count": None}
            continue
        if not _detector_available(detectors[name]):
            results[name] = {"status": "insufficient_tracking", "reason": detectors[name]["reason"], "event_count": None}
            continue
        if name == "low_movement":
            found = detect_low_movement(records, validity, width, height, config, smoothing)
        elif name.startswith("wrist"):
            found = detect_wrist_motion(records, validity, width, height, name.rsplit("_", 1)[1], config,
                                        smoothing, hysteresis)
        else:
            found = detect_foot_motion(records, validity, width, height, name.rsplit("_", 1)[1], config,
                                       smoothing, hysteresis)
        results[name] = {"status": "available", "reason": None, "event_count": len(found)}
        events.extend(found)
    events.sort(key=lambda e: (e["start_ms"], e["type"], e["hand"] or ""))
    return {"detector_version": DETECTOR_VERSION, "detectors": results, "events": events}


LIMB_ANCHORS = {"left_wrist": ("wrist_motion_left", "left_wrist"), "right_wrist": ("wrist_motion_right", "right_wrist"),
                "left_foot": ("foot_motion_left", "left_ankle"), "right_foot": ("foot_motion_right", "right_ankle")}


def movement_series(
    records: Sequence[dict[str, Any]], validity: TrackValidity, width: int, height: int, config: PipelineConfig,
) -> dict[str, Any]:
    """Per-limb position and speed at every sample, null wherever that limb's detector could not use the sample."""
    count = len(records)
    length = validity.scale["L_px"]
    max_gap = 1000 / config.analysis.inference_fps * config.quality.max_sample_gap_factor
    limbs: dict[str, Any] = {}
    for limb, (detector, anchor) in LIMB_ANCHORS.items():
        x: list[float | None] = [None] * count
        y: list[float | None] = [None] * count
        speed: list[float | None] = [None] * count
        run: list[int | None] = [None] * count   # a line may only connect samples with the same run number
        if length:
            segments = contiguous_segments(records, validity, DETECTOR_LANDMARKS[detector], max_gap)
            for number, segment in enumerate(s for s in segments if s.last > s.first):
                _, positions, speeds = _joint_speeds(records, segment, anchor, width, height, length, config, True)
                for offset in range(segment.last - segment.first + 1):
                    index = segment.first + offset
                    x[index] = round(float(positions[offset][0]) / width, 5)
                    y[index] = round(float(positions[offset][1]) / height, 5)
                    speed[index] = None if np.isnan(speeds[offset]) else round(float(speeds[offset]), 4)
                    run[index] = number
        limbs[limb] = {"detector": detector, "anchor": anchor, "x": x, "y": y, "speed_L_per_s": speed, "run": run}
    return {"timebase": "canonical_video_ms", "width": width, "height": height, "L_px": length,
            "t": [r["timestamp_ms"] for r in records], "limbs": limbs,
            "meaning": "Smoothed within continuous valid tracking only. Null means not analyzable, never zero."}
