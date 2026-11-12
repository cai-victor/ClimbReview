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


REGISTER_MIN_INLIERS = 60
REGISTER_MIN_INLIER_RATIO = 0.5
REGISTER_MAX_RESIDUAL_PX = 1.5        # median, at the analysis size
REGISTER_MAX_CORNER_SHIFT = 0.15      # of image width; larger means a different view, not a small shift
MOVED_PX = 2.0                        # frames shifted more than this count as lined up, not as still


def register_to_reference(reference_gray: np.ndarray, frame_gray: np.ndarray, scale: float, width: int, height: int,
                          climber: np.ndarray | None) -> tuple[np.ndarray, float] | None:
    """Homography taking full-size frame pixels to reference pixels, with its largest corner shift. None when unreliable."""
    allowed = np.full(reference_gray.shape, 255, np.uint8)
    if climber is not None:
        allowed[cv2.resize(climber.astype(np.uint8), reference_gray.shape[::-1], interpolation=cv2.INTER_NEAREST) > 0] = 0
    corners = cv2.goodFeaturesToTrack(frame_gray, maxCorners=600, qualityLevel=0.01, minDistance=7, mask=allowed)
    if corners is None or len(corners) < REGISTER_MIN_INLIERS:
        return None
    tracked, status, _ = cv2.calcOpticalFlowPyrLK(frame_gray, reference_gray, corners, None, winSize=(31, 31), maxLevel=4)
    good = status.ravel() == 1
    if good.sum() < REGISTER_MIN_INLIERS:
        return None
    source, target = corners[good].reshape(-1, 2), tracked[good].reshape(-1, 2)
    matrix, inliers = cv2.findHomography(source, target, cv2.RANSAC, 2.0)
    if matrix is None or inliers is None:
        return None
    kept = inliers.ravel() == 1
    if kept.sum() < REGISTER_MIN_INLIERS or kept.mean() < REGISTER_MIN_INLIER_RATIO:
        return None
    projected = cv2.perspectiveTransform(source[kept].reshape(-1, 1, 2), matrix).reshape(-1, 2)
    if float(np.median(np.linalg.norm(projected - target[kept], axis=1))) > REGISTER_MAX_RESIDUAL_PX:
        return None
    shrink = np.diag([scale, scale, 1.0])
    full = np.linalg.inv(shrink) @ matrix @ shrink
    box = np.float32([[0, 0], [width, 0], [0, height], [width, height]]).reshape(-1, 1, 2)
    shift = float(np.max(np.linalg.norm(cv2.perspectiveTransform(box, full).reshape(-1, 2) - box.reshape(-1, 2), axis=1)))
    return (full, shift) if shift <= REGISTER_MAX_CORNER_SHIFT * width else None


def clean_wall(reference_bgr: np.ndarray, frames_bgr: Sequence[np.ndarray],
               climber_masks: Sequence[np.ndarray | None] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Stitch frames into one picture of the wall, in the reference frame's coordinates, without the climber.

    Each frame is lined up with the reference using background features, so a small camera shift is corrected
    and a frame that cannot be lined up reliably is left out. With `climber_masks` (True where the tracked climber
    is), each pixel takes the median of the frames where it was clear, so a climber who stays in one place is
    still removed. Pixels that were never clear keep the reference frame's own content and are reported. With too few
    usable frames the reference frame is returned unchanged.
    """
    height, width = reference_bgr.shape[:2]
    reference, scale = cc.frame_gray(cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2RGB))
    aligned, hidden, shifted = [], [], 0
    used: list[dict[str, Any]] = []       # which frames went in, and how each maps onto the reference frame
    for index, frame in enumerate(frames_bgr):
        if frame is None or frame.shape != reference_bgr.shape:
            continue
        climber = None if climber_masks is None else climber_masks[index]
        current, _ = cc.frame_gray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        registered = register_to_reference(reference, current, scale, width, height, climber)
        if registered is None:
            continue
        matrix, shift = registered
        blocked = np.zeros((height, width), np.uint8) if climber is None else climber.astype(np.uint8)
        if shift > MOVED_PX:
            shifted += 1
            frame = cv2.warpPerspective(frame, matrix, (width, height), flags=cv2.INTER_LINEAR)
            inside = cv2.warpPerspective(np.full((height, width), 255, np.uint8), matrix, (width, height), flags=cv2.INTER_NEAREST)
            blocked = cv2.warpPerspective(blocked * 255, matrix, (width, height), flags=cv2.INTER_NEAREST) // 255
            blocked[inside == 0] = 1                 # nothing was seen outside the shifted frame
        aligned.append(frame)
        hidden.append(blocked.astype(bool))
        used.append({"index": index, "matrix": np.asarray(matrix, float).round(6).tolist()})
    if len(aligned) < CLEAN_MIN_FRAMES:
        return reference_bgr, {"basis": "reference_frame", "frames_used": 1, "frames_realigned": 0, "never_clear_fraction": None,
                               "detail": "This is a single video frame, because too few frames could be lined up with it. Holds behind the climber stay hidden."}
    stack = np.stack(aligned).astype(np.float32)
    masks = np.stack(hidden)
    stack[masks] = np.nan
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        combined = np.nanmedian(stack, axis=0)
    unclear = (~masks).sum(axis=0) < MIN_CLEAR_SAMPLES
    combined[unclear] = reference_bgr[unclear]          # shown as the original frame, and reported below
    moved = f" {shifted} of them were shifted to line up, because the camera moved slightly." if shifted else ""
    if climber_masks is None:
        return combined.astype(np.uint8), {"basis": "clean_wall_median", "frames_used": len(aligned), "frames_realigned": shifted, "never_clear_fraction": None, "registered": used,
                                           "detail": f"Combined from {len(aligned)} video frames.{moved} Without body tracking, a climber who stays in one place may still show."}
    fraction = float(unclear.mean())
    detail = f"Combined from {len(aligned)} video frames, with the tracked climber cut out of each one.{moved}"
    if fraction > 0.001:
        detail += f" About {fraction * 100:.1f}% of the picture was never clear of the climber or was outside the lined-up frames. Those parts show the original frame, so the climber may still appear there."
    return combined.astype(np.uint8), {"basis": "clean_wall_pose_masked", "frames_used": len(aligned), "frames_realigned": shifted,
                                       "never_clear_fraction": round(fraction, 4), "registered": used, "detail": detail}
