"""Foot episodes, background camera gating, specific explanations, and compatibility. All inputs here are synthetic."""
from __future__ import annotations

import csv
import io
import json
import sqlite3

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import db, report
from app.analysis import camera_compensation as cc
from app.analysis import ClimbReviewError, evaluation as ev
from app.analysis import explain as x
from app.analysis import quality as q
from app.analysis.config import PipelineConfig
from app.main import create_app
from app.settings import Settings
from conftest import pose_record
from test_detectors import BASE, HEIGHT, L_PX, WIDTH, build, detect, linear, of

BASE.update({"left_knee": (0.4, 0.7), "right_knee": (0.6, 0.7), "left_foot_index": (0.38, 0.92), "right_foot_index": (0.62, 0.92),
             "left_heel": (0.42, 0.91), "right_heel": (0.58, 0.91)})


def foot_moves(side, speed=1.0, start=1.0, end=1.8, axis=1, sign=-1):
    parts = (f"{side}_ankle", f"{side}_heel", f"{side}_foot_index")
    def move(t):
        distance = sign * speed * max(0.0, min(t, end) - start)
        return (distance, 0.0) if axis == 0 else (0.0, distance)
    return {name: move for name in parts}


# ---- detector semantics

def test_upward_foot_episode_has_timing_direction_and_displacement(config):
    events = of(detect(build(40, foot_moves("left")), config), "foot_motion", "left")
    assert len(events) == 1
    evidence = events[0]["evidence"]
    assert 800 <= events[0]["start_ms"] <= 1100 and 1700 <= events[0]["end_ms"] <= 2200
    assert evidence["net_up_L"] > 0.6 and abs(evidence["net_image_right_L"]) < 0.01
    assert evidence["direction"] == "up"
    assert evidence["max_displacement_L"] == pytest.approx(0.8, abs=0.1)
    assert evidence["foot_support"]["state"] == "agrees" and evidence["foot_support"]["tracked_point"] == "ankle"


@pytest.mark.parametrize("axis,sign,expected", [(1, 1, "down"), (0, 1, "image_right"), (0, -1, "image_left")])
def test_direction_follows_image_coordinates(config, axis, sign, expected):
    event = of(detect(build(40, foot_moves("right", axis=axis, sign=sign)), config), "foot_motion", "right")[0]
    assert event["evidence"]["direction"] == expected


def test_sides_are_separate_and_one_side_works_without_the_other(config):
    missing = {i: ["right_ankle"] for i in range(40)}
    result = detect(build(40, foot_moves("left"), missing=missing), config)
    assert len(of(result, "foot_motion", "left")) == 1
    assert result["detectors"]["foot_motion_left"]["status"] == "available"
    assert result["detectors"]["foot_motion_right"]["status"] == "insufficient_tracking"
    assert result["detectors"]["foot_motion_right"]["event_count"] is None


def test_foot_jitter_is_not_an_episode(config):
    rng = np.random.default_rng(3)
    noise = {round(i * 0.1, 1): tuple(rng.normal(0, 0.012, 2)) for i in range(40)}
    moves = {"left_ankle": lambda t: noise[round(t, 1)]}
    assert of(detect(build(40, moves), config), "foot_motion", "left") == []


def test_small_foot_shift_below_displacement_rule_is_not_an_episode(config):
    assert of(detect(build(40, foot_moves("left", speed=0.5, end=1.3)), config), "foot_motion", "left") == []


def test_foot_episode_is_not_bridged_across_occlusion(config):
    moves = foot_moves("left", speed=0.8, start=0.5, end=3.5)
    missing = {i: ["left_ankle"] for i in range(18, 21)}
    events = of(detect(build(40, moves, missing=missing), config), "foot_motion", "left")
    assert len(events) == 2 and events[0]["end_ms"] < 1800 and events[1]["start_ms"] > 2000
    assert events[0]["evidence"]["truncation_cause"] == "tracking_gap"


def test_irregular_timestamps_use_real_elapsed_time(config):
    times = [i * 100 for i in range(20)] + [2000 + i * 50 for i in range(20)]
    events = of(detect(build(40, foot_moves("left", speed=1.0, start=2.1, end=2.8), times=times), config), "foot_motion", "left")
    assert len(events) == 1 and events[0]["evidence"]["peak_speed_L_per_s"] == pytest.approx(1.0, abs=0.15)


def _blocked_at(records, index, **fields):
    records[index].update(fields)
    return records


def test_foot_episode_does_not_cross_measured_camera_motion_or_repeated_frames(config):
    for fields in ({"camera_shift_px": 500.0, "camera_shift_response": 0.9}, {"repeated_source_frame": True}):
        records = _blocked_at(build(40, foot_moves("left", speed=0.8, start=0.5, end=3.5)), 20, **fields)
        events = of(detect(records, config), "foot_motion", "left")
        assert len(events) == 2, fields
        assert events[0]["end_ms"] <= 1900 and events[1]["start_ms"] >= 2000


def test_one_usable_support_point_is_named_alone(config):
    missing = {i: ["left_heel"] for i in range(40)}
    event = of(detect(build(40, foot_moves("left"), missing=missing), config), "foot_motion", "left")[0]
    support = event["evidence"]["foot_support"]
    assert support["state"] == "agrees" and support["points_compared"] == ["toe"]
    series = x_series(40)
    x.describe_events([event], series)
    assert "toe point moved the same way" in event["feedback"]["observation"]
    assert "heel" not in event["feedback"]["observation"]


def test_no_support_point_is_reported_unavailable(config):
    missing = {i: ["left_heel", "left_foot_index"] for i in range(40)}
    support = of(detect(build(40, foot_moves("left"), missing=missing), config), "foot_motion", "left")[0]["evidence"]["foot_support"]
    assert support["state"] == "unavailable" and support["points_compared"] == []


def _shin_swing(t):
    return (0.0, 0.2 * np.sin(t * 25))


def _with_ankle_visibility(records, value):
    for record in records:
        next(lm for lm in record["landmarks"] if lm["name"] == "left_ankle")["visibility"] = value
    return records


def test_unstable_shin_with_reduced_visibility_marks_uncertain_but_keeps_the_event(config):
    moves = {"left_knee": _shin_swing, **foot_moves("left")}
    event = of(detect(_with_ankle_visibility(build(40, moves), 0.75), config), "foot_motion", "left")[0]
    assert event["evidence"]["foot_support"]["anchor_state"] == "uncertain"


def test_matched_feet_and_bent_knee_alone_are_not_uncertain(config):
    # Ankles coincide with the other foot and the shin is short, but both stay steady: legitimate climbing positions.
    moves = foot_moves("left")
    records = build(40, moves)
    for record in records:
        lookup = {lm["name"]: lm for lm in record["landmarks"]}
        lookup["right_ankle"].update(x=lookup["left_ankle"]["x"], y=lookup["left_ankle"]["y"])
        lookup["left_knee"].update(x=lookup["left_ankle"]["x"] + 0.03, y=lookup["left_ankle"]["y"] - 0.03)
    event = of(detect(_with_ankle_visibility(records, 0.75), config), "foot_motion", "left")[0]
    assert event["evidence"]["foot_support"]["anchor_state"] == "stable"


def test_config_without_foot_motion_reports_not_run(config):
    old = PipelineConfig.model_validate({**config.model_dump(), "foot_motion": None})
    result = detect(build(40, foot_moves("left")), old)
    assert result["detectors"]["foot_motion_left"] == {"status": "not_run", "reason": "configuration_predates_foot_analysis", "event_count": None}
    assert of(result, "foot_motion", "left") == []


# ---- background camera measurement

def wall(width=320, height=568, seed=5):
    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 200, np.uint8)
    for _ in range(900):
        px, py = int(rng.integers(0, width)), int(rng.integers(0, height))
        color = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.circle(image, (px, py), int(rng.integers(2, 6)), color, -1)
    return image


def measure(before, after, records=None):
    height, width = before.shape[:2]
    first, s = cc.frame_gray(before)
    second, _ = cc.frame_gray(after)
    return cc.measure_camera_motion(first, second, s, width, height, records or [pose_record(0, 0), pose_record(3, 100)])


def warp(image, matrix):
    return cv2.warpAffine(image, matrix, image.shape[1::-1], borderMode=cv2.BORDER_REFLECT)


def test_person_moving_on_a_static_wall_is_not_camera_motion():
    before, after = wall(), wall()
    cv2.rectangle(before, (120, 200), (200, 330), (20, 20, 20), -1)
    cv2.rectangle(after, (150, 225), (230, 355), (20, 20, 20), -1)
    records = [pose_record(0, 0, nose={"x": 0.36, "y": 0.34}, left_ankle={"x": 0.64, "y": 0.64}),
               pose_record(3, 100, nose={"x": 0.45, "y": 0.39}, left_ankle={"x": 0.73, "y": 0.68})]
    measured = measure(before, after, records)
    assert measured["method"] == cc.BACKGROUND_METHOD and measured["shift_px"] < 0.5


def test_real_pan_is_measured():
    image = wall()
    measured = measure(image, warp(image, np.float32([[1, 0, 7], [0, 1, -3]])))
    assert measured["shift_px"] == pytest.approx(np.hypot(7, 3), abs=0.6)


@pytest.mark.parametrize("degrees,scale", [(1.2, 1.0), (0.0, 1.02), (4.0, 1.0), (0.0, 1.06)])
def test_rotation_and_zoom_are_measured_even_when_the_transform_is_large(degrees, scale):
    image = wall()
    height, width = image.shape[:2]
    center = (width / 2, height / 2)
    transform = cv2.getRotationMatrix2D(center, degrees, scale)
    measured = measure(image, warp(image, transform))
    assert measured is not None
    corners = np.array([[0, 0, 1], [width, 0, 1], [0, height, 1], [width, height, 1]], float)
    expected = np.max(np.linalg.norm(corners @ transform.T - corners[:, :2], axis=1))
    assert measured["shift_px"] == pytest.approx(expected, rel=0.2)
    assert measured["shift_px"] > 3


def test_featureless_wall_abstains_so_the_fallback_is_used():
    blank = np.full((568, 320, 3), 180, np.uint8)
    assert measure(blank, blank.copy()) is None


def test_no_pose_abstains_because_the_climber_cannot_be_excluded():
    from conftest import no_pose_record
    image = wall()
    assert measure(image, image.copy(), [no_pose_record(0, 0), no_pose_record(3, 100)]) is None


def test_large_background_motion_blocks_the_interval(config):
    records = build(20)
    records[2].update(camera_shift_px=40.0, camera_shift_response=0.9, camera_shift_method=cc.BACKGROUND_METHOD)
    validity = q.derive_validity(records, WIDTH, HEIGHT, config.quality, 100.0)
    assert validity.blocked[1] == "camera_motion" and validity.blocked[0] is None


# ---- explanations (limb_state and wording)

def x_series(count, runs=None, limb_positions=None):
    times = [i * 100 for i in range(count)]
    limbs = {}
    for limb in x.LIMBS:
        points = (limb_positions or {}).get(limb, [(0.5, 0.5)] * count)
        limbs[limb] = {"x": [p[0] if p else None for p in points], "y": [p[1] if p else None for p in points],
                       "speed_L_per_s": [0.0] * count, "run": (runs or {}).get(limb, [0] * count)}
    return {"t": times, "width": 100, "height": 100, "L_px": 100.0, "limbs": limbs}


def hand_event(start=0, end=1000, **evidence):
    return {"id": "hand", "type": "wrist_motion", "hand": "right", "start_ms": start, "end_ms": end, "truncated": False,
            "evidence": {"duration_ms": end - start, "max_displacement_L": 1.0, "net_displacement_L": 1.0, "net_image_right_L": 0.0, "net_up_L": 1.0,
                         "direction": "up", "peak_speed_L_per_s": 2.0, "peak_speed_ms": 500, **evidence}}


def foot_event(event_id, start, end, side="left", **evidence):
    return {**hand_event(start, end, **evidence), "id": event_id, "type": "foot_motion", "hand": side}


def test_quiet_needs_continuous_tracking_and_small_motion():
    state = x.limb_state(hand_event(), [hand_event()], x_series(11), "left_foot")
    assert state["state"] == "quiet" and state["max_excursion_L"] == 0


def test_blocked_interval_with_valid_endpoints_is_unknown_not_quiet():
    series = x_series(11, runs={"left_foot": [0] * 5 + [1] * 6})
    state = x.limb_state(hand_event(), [hand_event()], series, "left_foot")
    assert state["observed_fraction"] == 1 and state["state"] == "unknown" and state["unknown_reason"] == "tracking_break"
    event = hand_event()
    x.describe_events([event], series)
    assert "left foot moved is unknown here: its tracking was interrupted" in event["feedback"]["context"]
    assert "left foot stayed nearly still" not in event["feedback"]["context"]


def test_slow_drift_without_episode_is_reported_as_movement_not_quiet():
    drift = [(0.5, 0.5 - 0.08 * i) for i in range(11)]
    series = x_series(11, limb_positions={"left_foot": drift})
    event = hand_event()
    state = x.limb_state(event, [event], series, "left_foot")
    assert state["state"] == "drifted" and state["max_excursion_L"] == pytest.approx(0.8)
    x.describe_events([event], series)
    assert "left foot shifted slowly by about 0.80" in event["feedback"]["context"]
    assert "left foot stayed nearly still" not in event["feedback"]["context"] and "Both feet" not in event["feedback"]["context"]


def test_missing_samples_are_unknown_never_quiet():
    points = [(0.5, 0.5)] * 5 + [None] * 6
    state = x.limb_state(hand_event(), [hand_event()], x_series(11, limb_positions={"left_foot": points}), "left_foot")
    assert state["state"] == "unknown" and state["unknown_reason"] == "low_coverage"


def test_uncertain_overlap_is_unknown_not_moved():
    uncertain = foot_event("f", 200, 800, foot_support={"anchor_state": "uncertain"})
    state = x.limb_state(hand_event(), [hand_event(), uncertain], x_series(11), "left_foot")
    assert state["state"] == "unknown" and state["unknown_reason"] == "uncertain_episode"


def test_both_feet_quiet_wording_makes_no_contact_claim():
    event = hand_event()
    x.describe_events([event], x_series(11))
    assert "Both feet stayed nearly still" in event["feedback"]["context"]
    assert "does not show they were on holds" in event["feedback"]["context"]


def test_truncated_neighbor_is_described_as_last_observed():
    hand = hand_event(2000, 3000)
    cut = foot_event("cut", 1000, 1500, truncated_end=True)
    x.describe_events([cut, hand], x_series(40))
    assert "last observed moving 0.5s before" in hand["feedback"]["context"]
    whole = foot_event("whole", 1000, 1500, truncated_end=False)
    hand = hand_event(2000, 3000)
    x.describe_events([whole, hand], x_series(40))
    assert "finished moving 0.5s before" in hand["feedback"]["context"]


def test_truncated_following_neighbor_is_described_as_first_observed():
    hand = hand_event(0, 500)
    late = foot_event("late", 900, 1400, truncated_start=True)
    x.describe_events([hand, late], x_series(40))
    assert "first observed already moving 0.4s after" in hand["feedback"]["context"]


def test_digest_lists_repeats_as_observations_and_limits_as_unknown():
    a, b = foot_event("a", 0, 500, side="right"), foot_event("b", 1000, 1500, side="right")
    x.describe_events([a, b], x_series(40))
    gap = {"start_ms": 0, "end_ms": 900, "duration_ms": 900, "reasons": {"low_visibility": 9}}
    detectors = {d: {"status": "available", "fraction": 0.9, "eligible_ms": 3000, "gaps": []} for d in x.DETECTOR_OF.values()}
    detectors["wrist_motion_left"] = {"status": "available", "fraction": 0.2, "eligible_ms": 800, "gaps": [gap]}
    counts = {d: {"status": "available", "event_count": 0} for d in x.DETECTOR_OF.values()}
    counts["foot_motion_right"]["event_count"] = 2
    digest = x.attempt_digest({"coverage": {"detectors": detectors}, "detection": {"detectors": counts}}, [a, b])
    assert digest["repeated"][0]["count"] == 2 and "not a mistake" in digest["repeated"][0]["text"]
    assert "hidden or poorly seen" in digest["limits"][0]["text"] and "unknown, not absent" in digest["limits"][0]["text"]


# ---- evaluation

def interval(start, end, key="foot_motion_left"):
    return ev.Interval("c", key, start, end)


def unscorable(start, end, applies="all", clip="c", annotator="h1"):
    return {"clip_id": clip, "event_type": "unscorable", "hand": None, "start_ms": start, "end_ms": end, "annotator_id": annotator, "applies_to": applies}


def test_overlapping_unscorable_rows_count_once():
    labels = [unscorable(0, 300), unscorable(0, 300)]
    assert ev._excluded(interval(0, 1000), labels) is False
    assert ev._excluded(interval(0, 1000), [unscorable(0, 300), unscorable(200, 600)]) is True


def evaluation_fixture(tmp_path, detectors=None, events=None):
    run = tmp_path / "run"
    run.mkdir()
    states = detectors or {k: {"status": "available"} for k in ev.EVENT_KEYS}
    (run / "events.json").write_text(json.dumps({"events": events or [], "detectors": states}))
    return [{"clip_id": "c", "split": "dev", "run_dir": "run", "video_duration_ms": "60000"}]


def label(annotator, kind="foot_motion", side="left", start=1000, end=2000):
    return {"clip_id": "c", "event_type": kind, "hand": side, "start_ms": start, "end_ms": end, "annotator_id": annotator, "applies_to": ""}


PREDICTION = {"type": "foot_motion", "hand": "left", "start_ms": 1000, "end_ms": 2000}


def test_two_raters_on_a_clip_stop_with_guidance(tmp_path):
    manifest = evaluation_fixture(tmp_path, events=[PREDICTION])
    with pytest.raises(ClimbReviewError, match="--reference-annotator"):
        ev.evaluate(manifest, [label("h1"), label("h2")], "dev", 0.3, tmp_path)


def test_selected_reference_scores_one_correct_prediction_as_full_recall(tmp_path):
    manifest = evaluation_fixture(tmp_path, events=[PREDICTION])
    original = [label("h1"), label("h2")]
    pooled = ev.evaluate(manifest, original, "dev", 0.3, tmp_path, reference_annotator="h1")["pooled"]["foot_motion_left"]
    assert (pooled["true_positives"], pooled["false_negatives"], pooled["recall"]) == (1, 0, 1.0)
    assert len(original) == 2


def test_selected_reference_must_exist_for_labeled_clips(tmp_path):
    manifest = evaluation_fixture(tmp_path)
    with pytest.raises(ClimbReviewError, match="no rows"):
        ev.evaluate(manifest, [label("h1")], "dev", 0.3, tmp_path, reference_annotator="adjudicated")


def test_single_rater_input_needs_no_selection(tmp_path):
    manifest = evaluation_fixture(tmp_path, events=[PREDICTION])
    assert ev.evaluate(manifest, [label("h1")], "dev", 0.3, tmp_path)["pooled"]["foot_motion_left"]["true_positives"] == 1


def test_old_run_without_foot_detector_does_not_turn_labels_into_misses(tmp_path):
    old = {k: {"status": "available"} for k in ("low_movement", "wrist_motion_left", "wrist_motion_right")}
    manifest = evaluation_fixture(tmp_path, detectors=old)
    result = ev.evaluate(manifest, [label("h1")], "dev", 0.3, tmp_path)["pooled"]["foot_motion_left"]
    assert result["false_negatives"] == 0 and result["clips_analyzed_before_detector_existed"] == 1


def test_foot_motion_csv_needs_a_side(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("clip_id,event_type,hand,start_ms,end_ms,annotator_id,applies_to\nc,foot_motion,,0,500,h1,\n")
    with pytest.raises(ClimbReviewError, match="needs hand"):
        ev.load_annotations(path, {"c": 1000})
    path.write_text("clip_id,event_type,hand,start_ms,end_ms,annotator_id\nc,wrist_motion,left,0,500,h1\n")
    assert ev.load_annotations(path, {"c": 1000})[0]["hand"] == "left"     # a CSV from before this phase still loads


# ---- persistence and compatibility

def test_database_from_before_foot_labels_is_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "old.db"
    schema = db.SCHEMA.replace("'wrist_motion','foot_motion','unscorable'", "'wrist_motion','unscorable'")
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.execute("INSERT INTO attempts(id,title,original_filename,source_ext,status,created_at) VALUES ('t','t','f','.mp4','ready','t')")
    connection.execute("INSERT INTO annotation_sets(id,attempt_id,rater_alias,clip_id,created_at,updated_at) VALUES ('s','t','h1','c','t','t')")
    connection.execute("INSERT INTO annotation_intervals(id,set_id,event_type,hand,start_ms,end_ms,created_at) VALUES ('a','s','wrist_motion','left',1,2,'t')")
    connection.commit()
    connection.close()
    db.initialize(path)
    db.initialize(path)      # safe to repeat
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT id, event_type FROM annotation_intervals").fetchall() == [("a", "wrist_motion")]
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("INSERT INTO annotation_intervals(id,set_id,event_type,hand,start_ms,end_ms,created_at) VALUES ('b','s','foot_motion','right',1,2,'t')")
    connection.close()


OLD_DETECTORS = ("low_movement", "wrist_motion_left", "wrist_motion_right")


def old_result():
    coverage = {name: {"status": "available", "eligible_ms": 1000, "fraction": 0.5, "gaps": []} for name in OLD_DETECTORS}
    return {"attempt_bounds_ms": {"start": 0, "end": 2000}, "coverage": {"detectors": coverage},
            "detection": {"detector_version": "detectors-v1", "detectors": {n: {"status": "available", "event_count": 1} for n in OLD_DETECTORS}}}


OLD_EVENT = {"id": "evt-old", "type": "wrist_motion", "hand": "left", "start_ms": 0, "end_ms": 500, "truncated": False,
             "evidence": {"duration_ms": 500, "max_displacement_L": 0.4}, "tracking_quality": {"label": "good"},
             "feedback": {"template_version": "wrist-motion-v1", "observation": "o", "interpretation": "i", "reflection_question": "q"},
             "review": {"detection_judgment": "confirmed", "usefulness": "useful", "context_tags": [], "note": "kept"}}


def test_summary_and_csv_of_an_old_run_stay_readable():
    summary = report.summarize(old_result(), [OLD_EVENT])
    assert summary["foot_analysis_available"] is False and summary["digest"] is None
    assert summary["foot_episode_counts"] == {"left": None, "right": None}
    row = next(csv.DictReader(io.StringIO(report.events_csv([OLD_EVENT]))))
    assert row["note"] == "kept" and row["limb"] == "left_wrist" and row["direction"] == ""


def test_csv_of_a_foot_event_has_side_direction_and_context():
    event = foot_event("f", 0, 500, side="right")
    x.describe_events([event], x_series(10))
    event.update(tracking_quality={"label": "good"}, review=OLD_EVENT["review"])
    row = next(csv.DictReader(io.StringIO(report.events_csv([event]))))
    assert row["type"] == "foot_motion" and row["hand"] == "right" and row["limb"] == "right_foot" and row["direction"] == "up"


def test_movement_endpoint_says_when_an_old_run_has_no_series(tmp_path):
    settings = Settings(tmp_path / "appdata")
    client = TestClient(create_app(settings))
    with db.session(settings.database) as connection:
        connection.execute("INSERT INTO attempts(id,title,original_filename,source_ext,status,created_at) VALUES (?,?,?,?,?,?)", ("a" * 32, "t", "f.mp4", ".mp4", "ready", "x"))
        connection.execute("INSERT INTO jobs(id,attempt_id,kind,status,stage,created_at) VALUES (?,?,?,?,?,?)", ("b" * 32, "a" * 32, "analysis", "complete", "complete", "x"))
    settings.run_dir("a" * 32, "b" * 32).mkdir(parents=True)
    assert client.get(f"/api/analyses/{'b' * 32}/movement").json() == {"available": False}
