"""Timestamped pose extraction and raw-landmark serialization.

Raw records keep what the model returned. An absent pose is stored as
``landmarks: null`` and a non-finite value as ``null``; a missing coordinate is
never represented as zero. Validity decisions live in ``quality.py``.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

import numpy as np

from . import ClimbReviewError
from .config import PoseModelConfig
from .video import FrameMap, iter_rgb_frames

LANDMARK_NAMES = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right", "left_shoulder", "right_shoulder", "left_elbow",
    "right_elbow", "left_wrist", "right_wrist", "left_pinky", "right_pinky", "left_index", "right_index",
    "left_thumb", "right_thumb", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
    "left_heel", "right_heel", "left_foot_index", "right_foot_index",
)


class PoseDetector(Protocol):
    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> Sequence[Any] | None:
        """Return the 33 landmarks of the single pose, or None when no pose was found."""


class MediaPipePoseDetector:
    """MediaPipe Tasks Pose Landmarker in VIDEO mode, fixed to one pose."""

    def __init__(self, model_path: Path, cfg: PoseModelConfig):
        import mediapipe as mp  # Imported here so non-inference tooling stays light.

        self._mp = mp
        delegate = getattr(mp.tasks.BaseOptions.Delegate, cfg.delegate)
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(
            mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path), delegate=delegate),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=cfg.num_poses,
                min_pose_detection_confidence=cfg.min_pose_detection_confidence,
                min_pose_presence_confidence=cfg.min_pose_presence_confidence,
                min_tracking_confidence=cfg.min_tracking_confidence,
                output_segmentation_masks=False,
            )
        )

    def __enter__(self) -> "MediaPipePoseDetector":
        return self

    def __exit__(self, *_: object) -> None:
        self._landmarker.close()

    def detect(self, rgb: np.ndarray, timestamp_ms: int) -> Sequence[Any] | None:
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return result.pose_landmarks[0] if result.pose_landmarks else None


def finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def landmark_record(index: int, landmark: Any) -> dict[str, Any]:
    return {
        "id": index,
        "name": LANDMARK_NAMES[index],
        "x": finite_or_none(landmark.x),
        "y": finite_or_none(landmark.y),
        "z": finite_or_none(landmark.z),
        "visibility": finite_or_none(getattr(landmark, "visibility", None)),
        "presence": finite_or_none(getattr(landmark, "presence", None)),
    }


def frame_record(frame_index: int, timestamp_ms: int, landmarks: Sequence[Any] | None) -> dict[str, Any]:
    if landmarks is not None and len(landmarks) != len(LANDMARK_NAMES):
        raise ClimbReviewError(f"Pose model returned {len(landmarks)} landmarks; expected {len(LANDMARK_NAMES)}.")
    return {
        "frame_index": frame_index,
        "timestamp_ms": timestamp_ms,
        "pose_detected": landmarks is not None,
        "landmarks": None if landmarks is None else [landmark_record(i, lm) for i, lm in enumerate(landmarks)],
    }


def sample_frame_indices(frames: FrameMap, stride: int, start_ms: int, end_ms: int) -> list[int]:
    """Global grid 0, stride, 2*stride... restricted to [start_ms, end_ms)."""
    return [i for i in range(0, frames.frame_count, stride) if start_ms <= frames.timestamps_ms[i] < end_ms]


CAMERA_ANALYSIS_LONG_SIDE_PX = 160


def _camera_gray(rgb: np.ndarray) -> tuple[np.ndarray, float]:
    import cv2

    height, width = rgb.shape[:2]
    factor = min(1.0, CAMERA_ANALYSIS_LONG_SIDE_PX / max(width, height))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    return small.astype(np.float64), factor


def estimate_camera_shift(previous: np.ndarray, current: np.ndarray, factor: float) -> tuple[float, float]:
    """Dominant image translation between frames, in canonical pixels, with peak response.

    A diagnostic for the stationary-camera assumption. Rotation and zoom are not
    modeled, and a uniform wall offers little texture to correlate.
    """
    import cv2

    window = cv2.createHanningWindow(current.shape[::-1], cv2.CV_64F)
    (dx, dy), response = cv2.phaseCorrelate(previous, current, window)
    return float(np.hypot(dx, dy) / factor), float(response)


def extract_poses(
    video: Path, size: tuple[int, int], frames: FrameMap, indices: Iterable[int], detector: PoseDetector,
    repeated: Sequence[bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """Run inference on the requested frames. `on_progress` may raise to cancel."""
    wanted = list(indices)
    wanted_set = set(wanted)
    records: list[dict[str, Any]] = []
    previous_ms = -1
    previous_gray: np.ndarray | None = None
    width, height = size
    for index, rgb in iter_rgb_frames(video, width, height):
        if index in wanted_set:
            timestamp_ms = frames.timestamps_ms[index]
            if timestamp_ms <= previous_ms:
                raise ClimbReviewError(f"Non-increasing frame timestamp at frame {index}: {timestamp_ms} ms.")
            previous_ms = timestamp_ms
            record = frame_record(index, timestamp_ms, detector.detect(rgb, timestamp_ms))
            gray, factor = _camera_gray(rgb)
            shift, response = None, None
            if previous_gray is not None:
                shift, response = estimate_camera_shift(previous_gray, gray, factor)
            previous_gray = gray
            record["camera_shift_px"] = finite_or_none(shift)
            record["camera_shift_response"] = finite_or_none(response)
            record["repeated_source_frame"] = bool(repeated[len(records)]) if repeated is not None else False
            records.append(record)
            if on_progress is not None:
                on_progress(len(records), len(wanted))
            if len(records) == len(wanted):
                break
    if len(records) != len(wanted):
        raise ClimbReviewError(f"Decoded only {len(records)} of {len(wanted)} requested frames.")
    return records


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> None:
    with path.open("w") as handle:
        for record in records:
            handle.write(json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as handle:
        return [json.loads(line) for line in handle]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_verified_model_manifest(model_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Confirm the local weights are byte-for-byte the recorded official file."""
    fix = "Run: .venv/bin/python scripts/download_model.py"
    if not manifest_path.exists():
        raise ClimbReviewError(f"Model manifest is missing ({manifest_path}). {fix}")
    if not model_path.exists():
        raise ClimbReviewError(f"Pose model is missing ({model_path}). {fix}")
    manifest = json.loads(manifest_path.read_text())
    actual = sha256_file(model_path)
    if actual != manifest["sha256"]:
        raise ClimbReviewError(f"Pose model checksum mismatch: {actual} != {manifest['sha256']}. {fix}")
    return manifest
