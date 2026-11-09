"""End-to-end CLI runs with the real MediaPipe model on non-climbing fixtures.

These verify wiring, timestamps, and abstention. They say nothing about how well
pose tracking works on climbing footage.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.analysis import ClimbReviewError
from app.analysis.pipeline import run_analysis
from app.analysis.pose import read_jsonl
from conftest import PROJECT_ROOT, encode_frames, tag_rotation

POSE_IMAGE = PROJECT_ROOT / "data" / "test_assets" / "pose.jpg"
ARTIFACTS = {"canonical.mp4", "poses.jsonl", "coverage.json", "coverage_timeline.csv", "events.json", "overlay.mp4",
             "contact_sheet.jpg", "report.md", "run.json"}


def _cli(*args):
    return subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "analyze_video.py"), *map(str, args)],
                          capture_output=True, text=True, cwd=PROJECT_ROOT)


@pytest.fixture()
def still_person_frame():
    if not POSE_IMAGE.exists():
        pytest.skip("Missing official test image; run scripts/setup_env.sh")
    bgr = cv2.imread(str(POSE_IMAGE))
    return cv2.cvtColor(bgr[: bgr.shape[0] // 2 * 2, : bgr.shape[1] // 2 * 2], cv2.COLOR_BGR2RGB)


@pytest.mark.mediapipe
def test_cli_abstains_on_video_without_a_person(tmp_path):
    rng = np.random.default_rng(317)
    images = [rng.integers(0, 40, (240, 320, 3), np.uint8) for _ in range(45)]
    source = encode_frames(images, tmp_path / "noise.mp4")
    output = tmp_path / "run"
    result = _cli(source, "--output", output, "--provenance", "synthetic_test_media")
    assert result.returncode == 0, result.stderr
    assert "UNVERIFIED" in result.stdout
    assert {p.name for p in output.iterdir()} == ARTIFACTS

    run = json.loads((output / "run.json").read_text())
    assert run["data_provenance"] == "synthetic_test_media"
    assert run["visual_alignment_review"]["status"] == "not_reviewed"
    assert run["coverage"]["pose_detected_samples"] == 0
    for item in run["coverage"]["detectors"].values():
        assert item["status"] == "insufficient_tracking" and item["eligible_ms"] is None and item["fraction"] is None
    records = read_jsonl(output / "poses.jsonl")
    assert [r["timestamp_ms"] for r in records] == [i * 100 for i in range(15)]
    assert all(r["landmarks"] is None for r in records)


@pytest.mark.mediapipe
def test_real_model_returns_landmarks_consistently_after_rotation(tmp_path, still_person_frame):
    """A person image, stored rotated plus metadata, must match the upright run."""
    upright = encode_frames([still_person_frame] * 30, tmp_path / "upright.mp4")
    stored = np.rot90(still_person_frame, k=1).copy()  # rotated CCW; display needs -90 CCW
    rotated = tag_rotation(encode_frames([stored] * 30, tmp_path / "stored.mp4"), tmp_path / "tagged.mp4", -90)

    for name, source in (("a", upright), ("b", rotated)):
        result = _cli(source, "--output", tmp_path / name, "--provenance", "synthetic_test_media",
                      "--attempt-start-ms", 100, "--attempt-end-ms", 900)
        assert result.returncode == 0, result.stderr

    first = read_jsonl(tmp_path / "a" / "poses.jsonl")
    second = read_jsonl(tmp_path / "b" / "poses.jsonl")
    assert [r["timestamp_ms"] for r in first] == list(range(100, 900, 100))
    assert first[0]["pose_detected"] and second[0]["pose_detected"]
    assert len(first[0]["landmarks"]) == 33
    for a, b in zip(first[-1]["landmarks"], second[-1]["landmarks"]):
        if a["visibility"] > 0.8 and b["visibility"] > 0.8:
            assert abs(a["x"] - b["x"]) < 0.05 and abs(a["y"] - b["y"]) < 0.05, a["name"]
    run = json.loads((tmp_path / "a" / "run.json").read_text())
    assert run["pose_model"]["sha256"] == "4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad"
    assert run["pose_model"]["running_mode"] == "VIDEO"
    assert run["attempt_bounds_ms"] == {"start": 100, "end": 900}
    assert len(run["config_hash"]) == 64


def test_cli_reports_actionable_error_for_bad_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("nope")
    result = _cli(bad, "--output", tmp_path / "run")
    assert result.returncode == 2
    assert result.stderr.startswith("error: Video could not be read")
    assert "Traceback" not in result.stderr


def test_failure_leaves_no_partial_output(tmp_path, config):
    source = encode_frames([np.zeros((180, 320, 3), np.uint8)] * 15, tmp_path / "clip.mp4")
    root = tmp_path / "runs"
    with pytest.raises(ClimbReviewError, match="attempt bounds"):
        run_analysis(source, root / "clip", config, PROJECT_ROOT, "clip", 0, 99_999)
    assert list(root.iterdir()) == []


def test_existing_non_run_directory_is_never_replaced(tmp_path, config):
    source = encode_frames([np.zeros((180, 320, 3), np.uint8)] * 15, tmp_path / "clip.mp4")
    keep = tmp_path / "important"
    keep.mkdir()
    (keep / "notes.txt").write_text("keep me")
    with pytest.raises(ClimbReviewError, match="not a previous run"):
        run_analysis(source, keep, config, PROJECT_ROOT, "clip", overwrite=True)
    assert (keep / "notes.txt").exists()
