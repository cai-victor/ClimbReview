"""Synthetic-trajectory tests of detector semantics. No pose model or video involved."""
from __future__ import annotations

import copy

import pytest

from app.analysis import detectors as d
from app.analysis import quality as q
from conftest import no_pose_record, pose_record

WIDTH, HEIGHT = 720, 1280
L_PX = 0.2 * HEIGHT  # torso in the conftest pose
TRACKED = ["left_wrist", "right_wrist", "left_ankle", "right_ankle", "left_hip", "right_hip"]
BASE = {"left_wrist": (0.3, 0.3), "right_wrist": (0.7, 0.3), "left_ankle": (0.4, 0.9), "right_ankle": (0.6, 0.9),
        "left_hip": (0.45, 0.5), "right_hip": (0.55, 0.5), "left_elbow": (0.35, 0.4), "right_elbow": (0.65, 0.4)}


def L_y(length_units):
    """Convert torso lengths to normalized y."""
    return length_units * L_PX / HEIGHT


def build(count, moves=None, times=None, missing=None):
    """moves: name -> function(seconds) returning (dx_L, dy_L). missing: sample index -> names or 'pose'."""
    moves, missing, records = moves or {}, missing or {}, []
    times = times or [i * 100 for i in range(count)]
    for i, t in enumerate(times):
        overrides = {}
        for name, (x, y) in BASE.items():
            dx, dy = moves[name](t / 1000) if name in moves else (0.0, 0.0)
            overrides[name] = {"x": x + dx * L_PX / WIDTH, "y": y + dy * L_PX / HEIGHT}
        if missing.get(i) == "pose":
            records.append(no_pose_record(i * 3, t))
            continue
        for name in missing.get(i, []):
            overrides[name] = None
        records.append(pose_record(i * 3, t, **overrides))
    return records


def detect(records, config, **kwargs):
    validity = q.derive_validity(records, WIDTH, HEIGHT, config.quality, 100.0)
    coverage = q.compute_coverage(records, WIDTH, HEIGHT, records[0]["timestamp_ms"], records[-1]["timestamp_ms"] + 100,
                                  config.quality, 100.0, 0.7, validity)
    return d.run_detectors(records, validity, WIDTH, HEIGHT, coverage, config, **kwargs)


def of(result, kind, hand=None):
    return [e for e in result["events"] if e["type"] == kind and e["hand"] == hand]


def linear(speed_L_per_s, start=0.0, end=1e9, axis=0):
    def move(t):
        distance = speed_L_per_s * max(0.0, min(t, end) - start)
        return (distance, 0.0) if axis == 0 else (0.0, distance)
    return move


def test_complete_stillness_is_one_low_movement_event(config):
    result = detect(build(40), config)
    events = of(result, "low_movement")
    assert len(events) == 1
    assert (events[0]["start_ms"], events[0]["end_ms"]) == (0, 3900)
    assert result["detectors"]["low_movement"]["event_count"] == 1
    assert events[0]["tracking_quality"]["is_calibrated_event_probability"] is False


def test_one_moving_limb_prevents_low_movement(config):
    result = detect(build(40, {"right_ankle": linear(0.5)}), config)
    assert of(result, "low_movement") == []
    assert result["detectors"]["low_movement"]["event_count"] == 0


def test_short_stillness_below_minimum_is_not_an_event(config):
    # still 0-1.5 s then moving
    result = detect(build(30, {"left_wrist": linear(1.0, start=1.5)}), config)
    assert of(result, "low_movement") == []


def test_threshold_boundary_is_strict(config):
    below = detect(build(40, {name: linear(0.14) for name in TRACKED}), config)
    above = detect(build(40, {name: linear(0.16) for name in TRACKED}), config)
    assert len(of(below, "low_movement")) == 1
    assert of(above, "low_movement") == []


def test_stillness_is_never_inferred_from_missing_joint(config):
    records = build(60, missing={i: ["left_ankle"] for i in range(60)})
    result = detect(records, config)
    assert result["detectors"]["low_movement"]["status"] == "insufficient_tracking"
    assert result["detectors"]["low_movement"]["event_count"] is None
    assert of(result, "low_movement") == []


def test_tracking_gap_splits_low_movement_and_is_not_merged(config):
    missing = {30: ["left_wrist"]}
    events = of(detect(build(70, missing=missing), config), "low_movement")
    assert [(e["start_ms"], e["end_ms"]) for e in events] == [(0, 2900), (3100, 6900)]


def test_no_pose_gap_splits_even_when_body_is_identical(config):
    events = of(detect(build(70, missing={30: "pose"}), config), "low_movement")
    assert len(events) == 2 and events[0]["end_ms"] == 2900 and events[1]["start_ms"] == 3100


def test_short_fully_observed_interruption_is_merged(config):
    def blip(t):
        return (0.6, 0.0) if 2.95 <= t < 3.05 else (0.0, 0.0)

    records = build(60, {"left_wrist": blip})
    # Unsmoothed: non-still only at 2.9 and 3.1 s, each a 200 ms interruption, so all merge.
    unsmoothed = of(detect(records, config, smoothing=False), "low_movement")
    assert [(e["start_ms"], e["end_ms"]) for e in unsmoothed] == [(0, 5900)]
    # Smoothing spreads the blip over 2.8-3.2 s; the 300 ms interruptions exceed the merge limit.
    smoothed = of(detect(records, config), "low_movement")
    assert [(e["start_ms"], e["end_ms"]) for e in smoothed] == [(0, 2700), (3300, 5900)]


def test_repeated_source_frames_do_not_count_as_stillness(config):
    records = build(40)
    for record in records[10:]:
        record["repeated_source_frame"] = True
    assert of(detect(records, config), "low_movement") == []  # only 0.9 s of real observation remains


def test_camera_motion_breaks_low_movement(config):
    records = build(40)
    for record in records[1:]:
        record["camera_shift_px"], record["camera_shift_response"] = 50.0, 0.9
    result = detect(records, config)
    assert result["detectors"]["low_movement"]["status"] == "insufficient_tracking"
    assert result["detectors"]["low_movement"]["reason"] == "no_contiguous_eligible_interval"


def test_weak_camera_correlation_is_not_treated_as_motion(config):
    records = build(40)
    for record in records[1:]:
        record["camera_shift_px"], record["camera_shift_response"] = 50.0, 0.05
    assert len(of(detect(records, config), "low_movement")) == 1


def test_wrist_episode_timing_and_evidence(config):
    # 0.8 L/s from 1.0 to 1.8 s, then still: 0.64 L displacement
    moves = {"left_wrist": linear(0.8, start=1.0, end=1.8)}
    events = of(detect(build(40, moves), config), "wrist_motion", "left")
    assert len(events) == 1
    event = events[0]
    assert 900 <= event["start_ms"] <= 1200 and 1700 <= event["end_ms"] <= 2100
    assert event["truncated"] is False
    assert event["evidence"]["max_displacement_L"] == pytest.approx(0.64, abs=0.1)
    assert event["evidence"]["path_length_L"] >= event["evidence"]["max_displacement_L"] - 1e-6


def test_hands_are_independent_and_can_overlap(config):
    moves = {"left_wrist": linear(0.8, start=1.0, end=2.0), "right_wrist": linear(0.8, start=1.2, end=2.2)}
    result = detect(build(40, moves), config)
    left, right = of(result, "wrist_motion", "left"), of(result, "wrist_motion", "right")
    assert len(left) == 1 and len(right) == 1
    assert left[0]["start_ms"] < right[0]["end_ms"] and right[0]["start_ms"] < left[0]["end_ms"]


def test_jitter_does_not_create_wrist_episode(config):
    def jitter(t):
        return (0.01 if round(t * 10) % 2 else -0.01, 0.0)

    assert of(detect(build(40, {"left_wrist": jitter}), config), "wrist_motion", "left") == []


def test_small_displacement_is_rejected(config):
    moves = {"left_wrist": linear(0.5, start=1.0, end=1.3)}  # 0.15 L
    assert of(detect(build(40, moves), config), "wrist_motion", "left") == []


def test_hysteresis_keeps_one_episode_through_a_short_slowdown(config):
    def move(t):
        if t < 1.0:
            return 0.0, 0.0
        if t < 1.8:
            return 1.0 * (t - 1.0), 0.0
        if t < 2.0:
            return 0.8 + 0.1 * (t - 1.8), 0.0  # 0.1 L/s, for less than the 0.25 s dwell
        if t < 2.8:
            return 0.82 + 1.0 * (t - 2.0), 0.0
        return 1.62, 0.0

    records = build(50, {"left_wrist": move})
    assert len(of(detect(records, config), "wrist_motion", "left")) == 1
    assert len(of(detect(records, config, hysteresis=False, smoothing=False), "wrist_motion", "left")) >= 2


def test_movement_cut_by_tracking_gap_is_truncated(config):
    moves = {"left_wrist": linear(0.8, start=1.0)}
    records = build(40, moves, missing={i: ["left_wrist"] for i in range(25, 40)})
    events = of(detect(records, config), "wrist_motion", "left")
    assert len(events) == 1
    assert events[0]["truncated"] is True
    assert events[0]["evidence"]["truncated_end"] is True
    assert events[0]["evidence"]["truncation_cause"] == "tracking_gap"
    assert events[0]["end_ms"] <= 2400


def test_movement_cut_by_attempt_end_is_marked_boundary(config):
    events = of(detect(build(20, {"left_wrist": linear(0.8, start=1.0)}), config), "wrist_motion", "left")
    assert events and events[0]["evidence"]["truncation_cause"] == "attempt_boundary"


def test_gap_splits_wrist_episode_without_bridging(config):
    moves = {"left_wrist": linear(0.8, start=0.5)}
    missing = {20: ["left_elbow"]}
    events = of(detect(build(40, moves, missing=missing), config), "wrist_motion", "left")
    assert len(events) == 2
    assert events[0]["end_ms"] <= 1900 and events[1]["start_ms"] >= 2100


def test_irregular_timestamps_use_elapsed_time(config):
    """Same physical speed sampled unevenly must still be below or above threshold correctly."""
    times = []
    t = 0
    for i in range(50):
        times.append(t)
        t += 80 if i % 2 else 120
    still = detect(build(50, {name: linear(0.1) for name in TRACKED}, times=times), config)
    fast = detect(build(50, {name: linear(0.3) for name in TRACKED}, times=times), config)
    assert len(of(still, "low_movement")) == 1
    assert of(fast, "low_movement") == []


def test_pixel_geometry_affects_speed_on_non_square_video(config):
    """Equal normalized motion along x and y differs in pixels and so in L/s."""
    records_x = build(40)
    records_y = copy.deepcopy(records_x)
    for i, (a, b) in enumerate(zip(records_x, records_y)):
        for lm in a["landmarks"]:
            if lm["name"] == "left_wrist":
                lm["x"] = 0.3 + 0.0012 * i
        for lm in b["landmarks"]:
            if lm["name"] == "left_wrist":
                lm["y"] = 0.3 + 0.0012 * i
    # 0.012 normalized/s is 8.64 px/s along x but 15.36 px/s along y on a 720x1280 frame.
    x_events = of(detect(records_x, config, smoothing=False), "low_movement")
    y_events = of(detect(records_y, config, smoothing=False), "low_movement")
    assert len(x_events) == 1 and len(y_events) == 1
    x_speed = x_events[0]["evidence"]["max_required_joint_speed_L_per_s"]
    y_speed = y_events[0]["evidence"]["max_required_joint_speed_L_per_s"]
    assert y_speed / x_speed == pytest.approx(1280 / 720, abs=0.02)


def test_implausible_torso_invalidates_whole_pose(config):
    records = build(30)
    records.extend(pose_record(i * 3, i * 100, left_hip={"y": 0.32}, right_hip={"y": 0.32},
                               left_shoulder={"y": 0.3}, right_shoulder={"y": 0.3}) for i in range(30, 40))
    validity = q.derive_validity(records, WIDTH, HEIGHT, config.quality, 100.0)
    assert validity.reasons[35]["left_wrist"] == "implausible_torso_scale"
    assert "left_wrist" not in validity.reasons[10]
