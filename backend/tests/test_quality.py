"""Synthetic-track tests for validity, scale, and coverage semantics."""
from __future__ import annotations

import json

import pytest

from app.analysis import pose as pose_module
from app.analysis import quality as q
from app.analysis.video import FrameMap
from conftest import grid, no_pose_record, pose_record


def coverage(records, config, start=0, end=None, width=720, height=1280):
    end = records[-1]["timestamp_ms"] + 100 if end is None else end
    return q.compute_coverage(records, width, height, start, end, config.quality, 100.0, 0.70)


def detector(result, name="low_movement"):
    return result["detectors"][name]


@pytest.mark.parametrize("field,expected", [
    ({"x": None}, "non_finite"), ({"x": 1.01}, "out_of_frame"), ({"y": -0.01}, "out_of_frame"),
    ({"visibility": None}, "visibility_missing"), ({"visibility": 0.59}, "low_visibility"),
    ({"presence": 0.59}, "low_presence"),
])
def test_invalid_landmark_reasons(config, field, expected):
    landmark = {"x": 0.5, "y": 0.5, "visibility": 0.9, "presence": 0.9, **field}
    assert q.landmark_invalid_reason(landmark, config.quality) == expected


def test_threshold_boundary_and_absent_presence_are_valid(config):
    assert q.landmark_invalid_reason({"x": 0.0, "y": 1.0, "visibility": 0.6, "presence": 0.6}, config.quality) is None
    assert q.landmark_invalid_reason({"x": 0.5, "y": 0.5, "visibility": 0.9, "presence": None}, config.quality) is None


def test_all_valid_track_earns_only_observed_intervals(config):
    result = coverage([pose_record(f, t) for f, t in grid(100)], config)
    item = detector(result)
    assert item["status"] == "available"
    assert item["attempt_ms"] == 10_000
    assert item["eligible_ms"] == 9_900  # the final 100 ms has no following sample
    assert item["fraction"] == 0.99
    assert item["gaps"] == []


def test_no_pose_is_unavailable_not_zero(config):
    result = coverage([no_pose_record(f, t) for f, t in grid(50)], config)
    for name in q.DETECTOR_LANDMARKS:
        item = detector(result, name)
        assert item["status"] == "insufficient_tracking"
        assert item["reason"] == "attempt_scale_unavailable"
        assert item["eligible_ms"] is None and item["fraction"] is None
    assert result["attempt_scale"]["L_px"] is None
    assert result["provisional_coverage_target"]["met"] is None


def test_missing_ankles_block_low_movement_but_not_wrists(config):
    records = [pose_record(f, t, left_ankle=None) for f, t in grid(50)]
    result = coverage(records, config)
    low = detector(result)
    assert low["status"] == "insufficient_tracking"
    assert low["reason"] == "no_contiguous_eligible_interval"
    assert low["eligible_ms"] is None
    assert low["per_landmark"]["left_ankle"]["invalid_reasons"] == {"non_finite": 50}
    assert detector(result, "wrist_motion_left")["fraction"] == 0.98


def test_wrists_are_evaluated_independently(config):
    records = [pose_record(f, t, right_elbow={"visibility": 0.1}) for f, t in grid(50)]
    result = coverage(records, config)
    assert detector(result, "wrist_motion_left")["status"] == "available"
    assert detector(result, "wrist_motion_right")["status"] == "insufficient_tracking"


def test_single_invalid_sample_splits_coverage_without_bridging(config):
    records = [pose_record(f, t) if i != 50 else no_pose_record(f, t) for i, (f, t) in enumerate(grid(100))]
    item = detector(coverage(records, config))
    assert item["eligible_ms"] == 9_700
    assert item["eligible_segment_count"] == 2
    assert item["longest_eligible_segment_ms"] == 4_900
    assert item["gaps"] == [{"start_ms": 4_900, "end_ms": 5_100, "duration_ms": 200}]


def test_isolated_valid_sample_earns_no_time(config):
    records = [pose_record(f, t) if i % 2 == 0 else no_pose_record(f, t) for i, (f, t) in enumerate(grid(40))]
    item = detector(coverage(records, config))
    assert item["samples_with_required_landmarks"] == 20
    assert item["landmarks_contiguously_valid_ms"] == 0
    assert item["status"] == "insufficient_tracking"


def test_irregular_timestamps_use_elapsed_time_and_break_on_large_steps(config):
    times = [0, 100, 200, 340, 400, 800, 900]  # 340->400 is short; 400->800 exceeds 150 ms
    assert q.eligible_segments(times, [True] * 7, 150.0) == [(0, 400), (800, 900)]


def test_attempt_bounds_set_the_denominator(config):
    records = [pose_record(f, t) for f, t in grid(21, start=1_000)]
    item = detector(coverage(records, config, start=1_000, end=3_050))
    assert item["attempt_ms"] == 2_050
    assert item["eligible_ms"] == 2_000
    assert item["fraction"] == round(2_000 / 2_050, 4)


def test_scale_uses_pixels_on_non_square_frames(config):
    """Same normalized torso; pixel length must follow the image height."""
    records = [pose_record(f, t) for f, t in grid(20)]
    assert q.torso_scale(records, 720, 1280, config.quality)["L_px"] == pytest.approx(0.2 * 1280)
    assert q.torso_scale(records, 1280, 720, config.quality)["L_px"] == pytest.approx(0.2 * 720)


def test_scale_is_median_and_robust_to_outliers(config):
    records = [pose_record(f, t) for f, t in grid(19)]
    records.append(pose_record(57, 1900, left_hip={"y": 0.95}, right_hip={"y": 0.95}))
    assert q.torso_scale(records, 720, 1280, config.quality)["L_px"] == pytest.approx(0.2 * 1280)


def test_scale_abstains_when_samples_are_few_or_degenerate(config):
    few = [pose_record(f, t) for f, t in grid(9)]
    assert q.torso_scale(few, 720, 1280, config.quality)["status"] == "unavailable"
    collapsed = [pose_record(f, t, left_hip={"y": 0.3}, right_hip={"y": 0.3}) for f, t in grid(30)]
    result = q.torso_scale(collapsed, 720, 1280, config.quality)
    assert result["status"] == "unavailable"
    assert result["degenerate_samples_excluded"] == 30


def test_provisional_target_reports_met_and_unmet(config):
    good = coverage([pose_record(f, t) for f, t in grid(100)], config)
    assert good["provisional_coverage_target"]["met"] is True
    gappy = [pose_record(f, t) if i < 40 else pose_record(f, t, left_wrist=None) for i, (f, t) in enumerate(grid(100))]
    assert coverage(gappy, config)["provisional_coverage_target"]["met"] is False


def test_timeline_marks_detectors_and_reasons(config):
    rows = q.timeline_rows([pose_record(0, 0, left_ankle={"visibility": 0.1}), no_pose_record(3, 100)], config.quality)
    assert rows[0]["low_movement_landmarks_valid"] == 0
    assert rows[0]["wrist_motion_left_landmarks_valid"] == 1
    assert rows[0]["unavailable"] == "left_ankle:low_visibility"
    assert rows[1]["pose_detected"] == 0
    assert "left_wrist:no_pose" in rows[1]["unavailable"]


class _Landmark:
    def __init__(self, x=0.5, y=0.5, z=0.1, visibility=0.9, presence=0.9):
        self.x, self.y, self.z, self.visibility, self.presence = x, y, z, visibility, presence


def test_no_pose_serializes_as_null_never_zero(tmp_path):
    path = tmp_path / "poses.jsonl"
    pose_module.write_jsonl([pose_module.frame_record(0, 0, None)], path)
    loaded = pose_module.read_jsonl(path)[0]
    assert loaded == {"frame_index": 0, "timestamp_ms": 0, "pose_detected": False, "landmarks": None}


def test_non_finite_values_serialize_as_strict_json_null(tmp_path):
    landmarks = [_Landmark() for _ in pose_module.LANDMARK_NAMES]
    landmarks[15] = _Landmark(x=float("nan"), y=float("inf"), visibility=None, presence=None)
    path = tmp_path / "poses.jsonl"
    pose_module.write_jsonl([pose_module.frame_record(3, 100, landmarks)], path)
    text = path.read_text()
    assert "NaN" not in text and "Infinity" not in text
    wrist = json.loads(text)["landmarks"][15]
    assert wrist["name"] == "left_wrist"
    assert wrist["x"] is None and wrist["y"] is None and wrist["visibility"] is None


def test_wrong_landmark_count_is_an_error():
    with pytest.raises(pose_module.ClimbReviewError):
        pose_module.frame_record(0, 0, [_Landmark()] * 5)


def test_sampling_uses_global_grid_inside_half_open_bounds():
    frames = FrameMap(tuple(round(i * 1000 / 30) for i in range(300)), 1000 / 30)
    assert pose_module.sample_frame_indices(frames, 3, 0, 300) == [0, 3, 6]
    assert pose_module.sample_frame_indices(frames, 3, 1_050, 1_400)[:1] == [33]
    assert pose_module.sample_frame_indices(frames, 3, 1_050, 1_400)[-1] == 39  # 1300 ms; 1400 excluded
