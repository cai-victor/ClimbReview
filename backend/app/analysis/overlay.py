"""Diagnostic overlay rendering for human inspection of landmark alignment.

Each overlay frame is the exact canonical frame the pose was estimated from; no
pose is held, interpolated, or drawn on a frame it did not come from.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from . import ClimbReviewError
from .config import QualityConfig
from .pose import LANDMARK_NAMES
from .quality import DETECTOR_LANDMARKS, invalid_reasons, landmark_lookup, to_pixels
from .video import iter_rgb_frames, tool_path

CONNECTIONS = (
    ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
    ("left_ankle", "left_foot_index"), ("right_ankle", "right_foot_index"),
)
LABELS = {"left_wrist": "LW", "right_wrist": "RW", "left_ankle": "LA", "right_ankle": "RA"}
SHORT_NAMES = {"low_movement": "LOW", "wrist_motion_left": "WRIST-L", "wrist_motion_right": "WRIST-R"}
LEFT_BGR, RIGHT_BGR, CENTER_BGR = (0, 140, 255), (255, 200, 0), (255, 255, 255)
SHEET_FRAMES, SHEET_COLUMNS, SHEET_CELL_WIDTH = 12, 4, 360


def _color(name: str) -> tuple[int, int, int]:
    return LEFT_BGR if name.startswith("left") else RIGHT_BGR if name.startswith("right") else CENTER_BGR


def _text(image: np.ndarray, text: str, origin: tuple[int, int], scale: float, color=(255, 255, 255)) -> None:
    thickness = max(1, round(scale * 2))
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def draw_skeleton(image: np.ndarray, record: dict[str, Any], cfg: QualityConfig) -> None:
    """Draw only valid joints, and bones only when both ends are valid."""
    height, width = image.shape[:2]
    lookup = landmark_lookup(record)
    invalid = invalid_reasons(record, LANDMARK_NAMES, cfg)
    usable = {
        name: tuple(int(round(v)) for v in to_pixels(lm, width, height))
        for name, lm in lookup.items() if name not in invalid
    }
    thickness = max(2, round(min(width, height) / 300))
    for a, b in CONNECTIONS:
        if a in usable and b in usable:
            cv2.line(image, usable[a], usable[b], _color(a if a.split("_")[0] == b.split("_")[0] else "center"),
                     thickness, cv2.LINE_AA)
    font = max(0.45, min(width, height) / 1000)
    for name, point in usable.items():
        if "eye" in name or "ear" in name or "mouth" in name or "pinky" in name or "thumb" in name:
            continue
        cv2.circle(image, point, thickness + 2, _color(name), -1, cv2.LINE_AA)
        if name in LABELS:
            _text(image, LABELS[name], (point[0] + 8, point[1] - 8), font, _color(name))


def draw_status(image: np.ndarray, record: dict[str, Any], cfg: QualityConfig) -> None:
    """Burn in media time and each detector's required-landmark state."""
    height, width = image.shape[:2]
    font = max(0.4, width / 1800)
    line = int(32 * font * 2)
    cv2.rectangle(image, (0, 0), (width, 2 * line + 8), (0, 0, 0), -1)
    time_text = f"t={record['timestamp_ms'] / 1000:.3f}s  frame {record['frame_index']}"
    if not record["pose_detected"]:
        _text(image, f"{time_text}  NO POSE RETURNED", (8, line), font, (80, 80, 255))
    else:
        _text(image, f"{time_text}  L=orange R=blue (model labels)", (8, line), font)
    states = []
    for detector, names in DETECTOR_LANDMARKS.items():
        state = "ok" if not invalid_reasons(record, names, cfg) else "UNAVAIL"
        states.append(f"{SHORT_NAMES[detector]}:{state}")
    _text(image, "  ".join(states), (8, 2 * line), font)


def _annotated(rgb: np.ndarray, record: dict[str, Any], cfg: QualityConfig) -> np.ndarray:
    image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    draw_skeleton(image, record, cfg)
    draw_status(image, record, cfg)
    return image


def _contact_sheet(cells: Sequence[np.ndarray], path: Path) -> None:
    if not cells:
        return
    rows = [cells[i:i + SHEET_COLUMNS] for i in range(0, len(cells), SHEET_COLUMNS)]
    blank = np.zeros_like(cells[0])
    grid = [np.hstack([*row, *[blank] * (SHEET_COLUMNS - len(row))]) for row in rows]
    cv2.imwrite(str(path), np.vstack(grid), [cv2.IMWRITE_JPEG_QUALITY, 88])


def render_overlay(
    video: Path, size: tuple[int, int], records: Sequence[dict[str, Any]], cfg: QualityConfig,
    inference_fps: int, overlay_path: Path, sheet_path: Path,
) -> None:
    if not records:
        raise ClimbReviewError("No sampled frames to render.")
    width, height = size
    by_index = {r["frame_index"]: r for r in records}
    picks = {records[round(i * (len(records) - 1) / max(1, SHEET_FRAMES - 1))]["frame_index"]
             for i in range(SHEET_FRAMES)}
    encoder = subprocess.Popen(
        [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{width}x{height}", "-r", str(inference_fps), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(overlay_path)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert encoder.stdin is not None
    cells: list[np.ndarray] = []
    written = 0
    for index, rgb in iter_rgb_frames(video, width, height):
        record = by_index.get(index)
        if record is None:
            continue
        image = _annotated(rgb, record, cfg)
        encoder.stdin.write(image.tobytes())
        written += 1
        if index in picks:
            cell_height = round(height * SHEET_CELL_WIDTH / width)
            cells.append(cv2.resize(image, (SHEET_CELL_WIDTH, cell_height), interpolation=cv2.INTER_AREA))
        if written == len(records):
            break
    encoder.stdin.close()
    errors = encoder.stderr.read().decode() if encoder.stderr else ""
    if encoder.wait() != 0 or written != len(records):
        raise ClimbReviewError(f"Overlay rendering failed ({written}/{len(records)} frames): {errors[-400:]}")
    _contact_sheet(cells, sheet_path)
