"""Suggest hold outlines that share the color of a point the user tapped.

This is color grouping, not hold recognition. It cannot tell a hold from tape, a tag, or
clothing of the same color, and it cannot see which route a hold belongs to. Every
suggestion needs the user's confirmation before it becomes a marked hold.
"""
from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from . import camera_compensation as cc

SUGGEST_VERSION = "color-suggest-v1"
TOLERANCES = {"strict": 14.0, "normal": 20.0, "loose": 28.0}   # Lab color distance; lightness counts half
LIGHTNESS_WEIGHT = 0.5
SEED_HALF_PATCH_PX = 3
MIN_RADIUS_FRACTION = 0.006          # of image width; smaller specks are ignored
MAX_AREA_FRACTION = 0.04             # a larger same-colored region is wall or a panel, not a hold
RADIUS_LIMITS = (0.012, 0.15)        # of image width
MAX_SUGGESTIONS = 60
CLEAN_MIN_FRAMES = 5
CLEAN_MAX_CORNER_MOTION_PX = 8.0


class SuggestionError(ValueError):
    """The tap cannot be used; the message says what to do."""


def suggest(image_bgr: np.ndarray, x: float, y: float, tolerance: str = "normal",
            existing: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """Regions colored like the tapped point. Coordinates are normalized; radius is a fraction of width."""
    height, width = image_bgr.shape[:2]
    px, py = int(round(x * (width - 1))), int(round(y * (height - 1)))
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    patch = lab[max(0, py - SEED_HALF_PATCH_PX): py + SEED_HALF_PATCH_PX + 1, max(0, px - SEED_HALF_PATCH_PX): px + SEED_HALF_PATCH_PX + 1]
    seed = np.median(patch.reshape(-1, 3), axis=0)
    difference = lab - seed
    difference[..., 0] *= LIGHTNESS_WEIGHT
    mask = (np.linalg.norm(difference, axis=2) < TOLERANCES[tolerance]).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    max_area = MAX_AREA_FRACTION * width * height
    tapped = labels[py, px]
    if tapped and stats[tapped, cv2.CC_STAT_AREA] > max_area:
        raise SuggestionError("That color covers a large part of the picture, so it looks like wall. Tap directly on a hold, or try the strict setting.")
    min_area = np.pi * (MIN_RADIUS_FRACTION * width) ** 2
    found = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if not min_area <= area <= max_area:
            continue
        points = cv2.findNonZero((labels == label).astype(np.uint8))
        (cx, cy), radius = cv2.minEnclosingCircle(points)
        nx, ny = cx / width, cy / height
        if any(np.hypot((nx - h["x"]) * width, (ny - h["y"]) * height) <= h["radius"] * width for h in existing):
            continue          # already marked
        found.append({"x": round(float(nx), 5), "y": round(float(ny), 5), "radius": round(float(np.clip(radius / width, *RADIUS_LIMITS)), 4), "area_px": area})
    found = sorted(found, key=lambda item: -item["area_px"])[:MAX_SUGGESTIONS]
    found.sort(key=lambda item: -item["y"])
    b, g, r = (int(v) for v in np.median(image_bgr[max(0, py - 3): py + 4, max(0, px - 3): px + 4].reshape(-1, 3), axis=0))
    return {"method": SUGGEST_VERSION, "tolerance": tolerance, "seed_color": f"#{r:02x}{g:02x}{b:02x}", "suggestions": found,
            "note": "Suggestions share the tapped color. They are not confirmed holds, may include other objects, and can miss holds in shadow or of mixed color."}


def clean_wall(reference_bgr: np.ndarray, frames_bgr: Sequence[np.ndarray]) -> tuple[np.ndarray, dict[str, Any]]:
    """Per-pixel median of frames that line up with the reference, which removes a climber who keeps moving.

    Frames are used only if a background transform shows the camera did not move. With too few such frames
    the reference frame is returned unchanged, and the result says so.
    """
    height, width = reference_bgr.shape[:2]
    reference, scale = cc.frame_gray(cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2RGB))
    everything = np.full(reference.shape, 255, np.uint8)
    aligned = []
    for frame in frames_bgr:
        if frame.shape != reference_bgr.shape:
            continue
        current, _ = cc.frame_gray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = cc.estimate_interval(reference, current, everything, scale, cc.TransformLimits())
        if result["accepted"] and cc.largest_corner_motion_px(result["matrix"], width, height, scale) <= CLEAN_MAX_CORNER_MOTION_PX:
            aligned.append(frame)
    if len(aligned) < CLEAN_MIN_FRAMES:
        return reference_bgr, {"basis": "reference_frame", "frames_used": 1,
                               "detail": "Using the reference frame only, so holds hidden behind the climber cannot be suggested."}
    median = np.median(np.stack(aligned), axis=0).astype(np.uint8)
    return median, {"basis": "clean_wall_median", "frames_used": len(aligned),
                    "detail": f"Using a wall picture built from {len(aligned)} video frames, so a moving climber is mostly removed."}
