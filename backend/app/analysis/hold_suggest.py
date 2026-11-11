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


CLIMBER_MARGIN = cc.TransformLimits(climber_margin_fraction=0.2)
MIN_CLEAR_SAMPLES = 3


def climber_mask(shape: tuple[int, int], joints: dict[str, Sequence[float]] | None) -> np.ndarray | None:
    """True where the tracked climber may be. None when no body was tracked in this frame."""
    if not joints:
        return None
    background = cc.climber_mask(shape, [{"landmarks": [{"x": x, "y": y} for x, y in joints.values()]}], CLIMBER_MARGIN)
    return None if background is None else background == 0


def clean_wall(reference_bgr: np.ndarray, frames_bgr: Sequence[np.ndarray],
               climber_masks: Sequence[np.ndarray | None] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Combine frames into one picture of the wall without the climber.

    Frames are used only if a background transform shows the camera did not move. With `climber_masks`
    (True where the tracked climber is), each pixel takes the median of the frames where it was clear, so
    a climber who stays in one place for a long time is still removed. Pixels that were never clear fall
    back to the plain median and are reported. With too few usable frames the reference frame is returned.
    """
    height, width = reference_bgr.shape[:2]
    reference, scale = cc.frame_gray(cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2RGB))
    everything = np.full(reference.shape, 255, np.uint8)
    aligned, masks = [], []
    for index, frame in enumerate(frames_bgr):
        if frame is None or frame.shape != reference_bgr.shape:
            continue
        current, _ = cc.frame_gray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = cc.estimate_interval(reference, current, everything, scale, cc.TransformLimits())
        if result["accepted"] and cc.largest_corner_motion_px(result["matrix"], width, height, scale) <= CLEAN_MAX_CORNER_MOTION_PX:
            aligned.append(frame)
            masks.append(None if climber_masks is None else climber_masks[index])
    if len(aligned) < CLEAN_MIN_FRAMES:
        return reference_bgr, {"basis": "reference_frame", "frames_used": 1, "never_clear_fraction": None,
                               "detail": "This is a single video frame, because the camera moved or too few frames could be combined. Holds behind the climber stay hidden."}
    stack = np.stack(aligned).astype(np.float32)
    plain = np.median(stack, axis=0)
    if climber_masks is None:
        return plain.astype(np.uint8), {"basis": "clean_wall_median", "frames_used": len(aligned), "never_clear_fraction": None,
                                        "detail": f"Combined from {len(aligned)} video frames. Without body tracking, a climber who stays in one place may still show."}
    hidden = np.stack([np.zeros((height, width), bool) if m is None else m for m in masks])
    clear_count = (~hidden).sum(axis=0)
    stack[hidden] = np.nan
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            combined = np.nanmedian(stack, axis=0)
    unclear = clear_count < MIN_CLEAR_SAMPLES
    combined[unclear] = plain[unclear]
    fraction = float(unclear.mean())
    detail = f"Combined from {len(aligned)} video frames, with the tracked climber cut out of each one."
    if fraction > 0.001:
        detail += f" About {fraction * 100:.1f}% of the picture was never clear of the climber, so the climber may still show there."
    return combined.astype(np.uint8), {"basis": "clean_wall_pose_masked", "frames_used": len(aligned), "never_clear_fraction": round(fraction, 4), "detail": detail}
