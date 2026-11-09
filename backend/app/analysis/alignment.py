"""Check, from the video itself, whether marks on one reference frame still line up later.

Marks may only be compared with tracked joints if the background has not moved relative to
the reference frame. Nothing here trusts a label saying the camera was on a tripod.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

from . import camera_compensation as cc

ALIGNMENT_VERSION = "reference-alignment-v1"
FRAMES_TO_CHECK = 12
MIN_MEASURED_FRAMES = 8
MIN_MEASURED_SHARE = 0.8
MAX_CORNER_MOTION_PX = 8.0        # small next to the default marked-hold radius of about 25 canonical pixels
GEOMETRY_REJECTIONS = {"implausible_scale", "implausible_rotation"}


def _pose_record(sample: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not sample or not sample.get("joints"):
        return []
    return [{"landmarks": [{"x": x, "y": y} for x, y in sample["joints"].values()]}]


def check_times(start_ms: int, end_ms: int, count: int = FRAMES_TO_CHECK) -> list[int]:
    return [int(v) for v in np.linspace(start_ms, max(start_ms, end_ms - 1), count)]


def check_reference(
    read_frame: Callable[[int], np.ndarray], reference_ms: int, times: Sequence[int], nearest_sample: Callable[[int], dict[str, Any] | None],
    limits: cc.TransformLimits = cc.TransformLimits(),
) -> dict[str, Any]:
    """Compare frames across the attempt with the reference frame, excluding the climber in both."""
    reference_rgb = read_frame(reference_ms)
    height, width = reference_rgb.shape[:2]
    reference, scale = cc.frame_gray(reference_rgb)
    reference_pose = _pose_record(nearest_sample(reference_ms))
    motions: list[float] = []
    abstained, moved = 0, False
    for ms in times:
        records = [*reference_pose, *_pose_record(nearest_sample(ms))]
        mask = cc.climber_mask(reference.shape, records, limits) if records else None
        current, _ = cc.frame_gray(read_frame(ms))
        result = cc.estimate_interval(reference, current, mask, scale, limits)
        if result["matrix"] is not None and (result["accepted"] or result["reason"] in GEOMETRY_REJECTIONS):
            corner = cc.largest_corner_motion_px(result["matrix"], width, height, scale)
            motions.append(corner)
            moved = moved or result["reason"] in GEOMETRY_REJECTIONS or corner > MAX_CORNER_MOTION_PX
        else:
            abstained += 1
    measured = len(motions)
    enough = measured >= MIN_MEASURED_FRAMES and measured / max(1, len(times)) >= MIN_MEASURED_SHARE
    status = "camera_moved" if moved else "fixed_verified" if enough else "could_not_verify"
    return {"status": status, "method": ALIGNMENT_VERSION, "frames_checked": len(times), "frames_measured": measured, "frames_abstained": abstained,
            "max_corner_motion_px": round(max(motions), 2) if motions else None, "limit_px": MAX_CORNER_MOTION_PX}
