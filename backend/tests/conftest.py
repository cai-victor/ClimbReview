"""Shared fixtures. All media here is generated at test time and is synthetic."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pytest

from app.analysis.config import load_config
from app.analysis.pose import LANDMARK_NAMES
from app.analysis.video import tool_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def config():
    return load_config(PROJECT_ROOT / "config" / "detectors.yaml")


def encode_frames(
    frames: Sequence[np.ndarray], path: Path, fps: float = 30, filters: str | None = None, extra: Sequence[str] = (),
) -> Path:
    """Encode RGB arrays losslessly enough for colour assertions."""
    height, width = frames[0].shape[:2]
    command = [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
    if filters:
        command += ["-vf", filters]
    command += ["-c:v", "libx264", "-qp", "4", "-pix_fmt", "yuv420p", *extra, str(path)]
    subprocess.run(command, input=b"".join(f.tobytes() for f in frames), check=True, capture_output=True)
    return path


def tag_rotation(source: Path, output: Path, degrees: int) -> Path:
    """Attach a display rotation (counter-clockwise degrees) without re-encoding."""
    subprocess.run(
        [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-display_rotation", str(degrees), "-i", str(source),
         "-c", "copy", str(output)], check=True, capture_output=True,
    )
    return output


QUADRANTS = {"top_left": (220, 30, 30), "top_right": (30, 200, 30), "bottom_left": (30, 30, 220),
             "bottom_right": (235, 235, 235)}


def quadrant_frame(width: int, height: int) -> np.ndarray:
    frame = np.zeros((height, width, 3), np.uint8)
    frame[: height // 2, : width // 2] = QUADRANTS["top_left"]
    frame[: height // 2, width // 2 :] = QUADRANTS["top_right"]
    frame[height // 2 :, : width // 2] = QUADRANTS["bottom_left"]
    frame[height // 2 :, width // 2 :] = QUADRANTS["bottom_right"]
    return frame


def assert_quadrants(frame: np.ndarray, tolerance: int = 40) -> None:
    height, width = frame.shape[:2]
    points = {"top_left": (height // 4, width // 4), "top_right": (height // 4, 3 * width // 4),
              "bottom_left": (3 * height // 4, width // 4), "bottom_right": (3 * height // 4, 3 * width // 4)}
    for name, (y, x) in points.items():
        difference = np.abs(frame[y, x].astype(int) - np.array(QUADRANTS[name]))
        assert difference.max() <= tolerance, f"{name}: got {frame[y, x]}, expected {QUADRANTS[name]}"


def landmark(x=0.5, y=0.5, z=0.0, visibility=0.9, presence=0.9) -> dict[str, Any]:
    return {"x": x, "y": y, "z": z, "visibility": visibility, "presence": presence}


def pose_record(frame_index: int, timestamp_ms: int, **overrides) -> dict[str, Any]:
    """A fully valid pose; pass name=None for unusable or name=dict to replace fields."""
    positions = {"left_shoulder": (0.45, 0.3), "right_shoulder": (0.55, 0.3),
                 "left_hip": (0.45, 0.5), "right_hip": (0.55, 0.5)}
    landmarks = []
    for index, name in enumerate(LANDMARK_NAMES):
        x, y = positions.get(name, (0.5, 0.5))
        item = {"id": index, "name": name, **landmark(x, y)}
        if name in overrides:
            override = overrides[name]
            item.update({"x": None, "y": None, "z": None, "visibility": None, "presence": None}
                        if override is None else override)
        landmarks.append(item)
    return {"frame_index": frame_index, "timestamp_ms": timestamp_ms, "pose_detected": True, "landmarks": landmarks}


def no_pose_record(frame_index: int, timestamp_ms: int) -> dict[str, Any]:
    return {"frame_index": frame_index, "timestamp_ms": timestamp_ms, "pose_detected": False, "landmarks": None}


def grid(count: int, period: int = 100, start: int = 0) -> list[tuple[int, int]]:
    return [(i * 3, start + i * period) for i in range(count)]
