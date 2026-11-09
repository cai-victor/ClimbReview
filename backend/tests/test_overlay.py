"""Overlay drawing must hide unavailable joints instead of joining across them."""
from __future__ import annotations

import numpy as np

from app.analysis.overlay import draw_skeleton
from conftest import no_pose_record, pose_record


def _arm(**elbow):
    return pose_record(
        0, 0,
        left_shoulder={"x": 0.2, "y": 0.2}, left_elbow={"x": 0.5, "y": 0.2, **elbow}, left_wrist={"x": 0.8, "y": 0.2},
        right_shoulder=None, right_elbow=None, right_wrist=None,
        left_hip=None, right_hip=None, left_knee=None, right_knee=None, left_ankle=None, right_ankle=None,
        left_foot_index=None, right_foot_index=None,
    )


def _isolate_arm(record):
    keep = {"left_shoulder", "left_elbow", "left_wrist"}
    for landmark in record["landmarks"]:
        if landmark["name"] not in keep:
            landmark["visibility"] = None
    return record


def test_valid_bones_are_drawn(config):
    image = np.zeros((400, 400, 3), np.uint8)
    draw_skeleton(image, _isolate_arm(_arm()), config.quality)
    assert image[80, 140].any() and image[80, 260].any()  # midpoints of both bones


def test_invalid_joint_removes_both_adjacent_bones(config):
    image = np.zeros((400, 400, 3), np.uint8)
    draw_skeleton(image, _isolate_arm(_arm(visibility=0.1)), config.quality)
    assert not image[80, 140].any() and not image[80, 200].any() and not image[80, 260].any()
    assert image[80, 80].any() and image[80, 320].any()  # the valid joints themselves remain


def test_no_pose_draws_no_skeleton(config):
    image = np.zeros((200, 200, 3), np.uint8)
    draw_skeleton(image, no_pose_record(0, 0), config.quality)
    assert not image.any()
