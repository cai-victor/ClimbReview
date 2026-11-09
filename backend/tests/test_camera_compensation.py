"""SYNTHETIC known-transform checks. They cannot establish accuracy on real climbing video."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.analysis import camera_compensation as cc
from conftest import pose_record

W, H = 640, 480
LIMITS = cc.TransformLimits()


def texture(seed=3):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 255, (H, W), np.uint8), (0, 0), 1.2)


def warp(image, dx=0.0, dy=0.0, angle=0.0, scale=1.0):
    matrix = cv2.getRotationMatrix2D((W / 2, H / 2), angle, scale)
    matrix[:, 2] += (dx, dy)
    return cv2.warpAffine(image, matrix, (W, H), flags=cv2.INTER_LINEAR), matrix


@pytest.mark.parametrize("dx,dy,angle,scale", [(8.0, -5.0, 0.0, 1.0), (3.0, 2.0, 0.8, 1.0), (-4.0, 6.0, -0.5, 1.01)])
def test_recovers_known_camera_transform(dx, dy, angle, scale):
    base = texture()
    moved, truth = warp(base, dx, dy, angle, scale)
    result = cc.estimate_interval(base, moved, np.full((H, W), 255, np.uint8), 1.0, LIMITS)
    assert result["accepted"], result["reason"]
    grid = np.array([[100, 100, 1], [500, 100, 1], [320, 380, 1]], float)
    assert np.abs(np.array(result["matrix"]) @ grid.T - truth @ grid.T).max() < 0.5


def test_moving_foreground_outside_mask_does_not_bias_estimate():
    base = texture()
    moved, truth = warp(base, 6.0, 0.0)
    moved = moved.copy()
    moved[120:360, 220:420] = base[100:340, 180:380]  # "climber" moving differently
    mask = np.full((H, W), 255, np.uint8)
    mask[90:390, 170:450] = 0
    result = cc.estimate_interval(base, moved, mask, 1.0, LIMITS)
    assert result["accepted"]
    assert np.array(result["matrix"])[0, 2] == pytest.approx(truth[0, 2], abs=0.5)


@pytest.mark.parametrize("frame_builder,reason", [
    (lambda: (np.full((H, W), 128, np.uint8), np.full((H, W), 128, np.uint8)), "too_few_background_features"),
])
def test_textureless_background_abstains(frame_builder, reason):
    a, b = frame_builder()
    result = cc.estimate_interval(a, b, np.full((H, W), 255, np.uint8), 1.0, LIMITS)
    assert not result["accepted"] and result["reason"] == reason


def test_unrelated_frames_abstain():
    result = cc.estimate_interval(texture(1), texture(2), np.full((H, W), 255, np.uint8), 1.0, LIMITS)
    assert not result["accepted"]


def test_no_pose_means_abstain_because_climber_cannot_be_excluded():
    assert cc.climber_mask((H, W), [{"landmarks": None}], LIMITS) is None
    result = cc.estimate_interval(texture(), texture(), None, 1.0, LIMITS)
    assert result["reason"] == "no_pose_to_exclude_climber"


def _step(dx, accepted=True):
    return {"accepted": accepted, "matrix": [[1.0, 0.0, dx], [0.0, 1.0, 0.0]] if accepted else None}


def test_compensation_removes_camera_motion_and_resets_after_rejection():
    records = [pose_record(i * 3, i * 100, left_wrist={"x": 0.5 + i * 0.05, "y": 0.5}) for i in range(4)]
    steps = [_step(32.0), _step(32.0), _step(0, accepted=False)]  # 32 px = 0.05 of 640
    output = cc.compensated_records(records, steps, 640, 480)
    wrist = [next(lm for lm in r["landmarks"] if lm["name"] == "left_wrist")["x"] for r in output]
    assert wrist[:3] == pytest.approx([0.5, 0.5, 0.5])
    assert wrist[3] == pytest.approx(0.65)                 # chain restarts: no motion inferred across rejection
    assert next(lm for lm in records[3]["landmarks"] if lm["name"] == "left_wrist")["x"] == pytest.approx(0.65)  # raw unchanged


def test_rejected_transform_blocks_eligibility():
    records = [pose_record(i * 3, i * 100) for i in range(3)]
    state = cc.with_transform_camera_state(records, [_step(0.0), _step(0.0, accepted=False)])
    assert state[1]["camera_shift_px"] == 0.0 and state[2]["camera_shift_px"] == 1e9
