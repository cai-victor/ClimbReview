"""Timestamp-aware kinematic features computed only inside contiguous valid segments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .config import FeaturesConfig
from .quality import TrackValidity, landmark_lookup, to_pixels


@dataclass(frozen=True)
class Segment:
    """Samples [first, last] where every required landmark and interval is usable."""
    first: int
    last: int


def contiguous_segments(
    records: Sequence[dict[str, Any]], validity: TrackValidity, names: Sequence[str], max_gap_ms: float,
) -> list[Segment]:
    """Split samples wherever a required landmark is missing or an interval is blocked."""
    segments: list[Segment] = []
    first: int | None = None
    previous = -1
    for index, record in enumerate(records):
        usable = not any(n in validity.reasons[index] for n in names)
        joined = (
            first is not None and index == previous + 1
            and record["timestamp_ms"] - records[previous]["timestamp_ms"] <= max_gap_ms
            and validity.blocked[previous] is None
        )
        if first is not None and not (usable and joined):
            segments.append(Segment(first, previous))
            first = None
        if usable:
            if first is None:
                first = index
            previous = index
    if first is not None:
        segments.append(Segment(first, previous))
    return segments


def joint_positions_px(
    records: Sequence[dict[str, Any]], segment: Segment, name: str, width: int, height: int,
) -> np.ndarray:
    points = []
    for record in records[segment.first: segment.last + 1]:
        points.append(to_pixels(landmark_lookup(record)[name], width, height))
    return np.asarray(points, dtype=float)


def smooth_within_segment(times_ms: np.ndarray, positions: np.ndarray, window_s: float) -> np.ndarray:
    """Centered time-window mean. Called per segment, so it cannot cross a gap."""
    half_ms = window_s * 1000 / 2
    if half_ms <= 0:
        return positions.copy()
    smoothed = np.empty_like(positions)
    for i, t in enumerate(times_ms):
        mask = np.abs(times_ms - t) <= half_ms
        smoothed[i] = positions[mask].mean(axis=0)
    return smoothed


def speed_within_segment(
    times_ms: np.ndarray, positions: np.ndarray, length_px: float, cfg: FeaturesConfig,
) -> np.ndarray:
    """Finite-difference speed in L/s using actual elapsed time; NaN when span is too short."""
    half_ms = cfg.speed_window_s * 1000 / 2
    speeds = np.full(len(times_ms), np.nan)
    for i, t in enumerate(times_ms):
        indices = np.flatnonzero(np.abs(times_ms - t) <= half_ms)
        left, right = indices[0], indices[-1]
        span_ms = times_ms[right] - times_ms[left]
        if span_ms >= cfg.min_speed_span_s * 1000:
            speeds[i] = np.linalg.norm(positions[right] - positions[left]) / length_px / (span_ms / 1000)
    return speeds
