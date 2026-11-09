"""Coaching rules, reach geometry, alignment, and persistence. Every input here is synthetic."""
from __future__ import annotations

import sqlite3

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import db
from app.analysis import alignment as al
from app.analysis import beta, coaching as co
from app.analysis import explain as x
from app.main import create_app
from app.settings import Settings

W, H, L = 720, 1280, 100.0


def series(count=80, overrides=None, runs=None):
    limbs = {}
    for limb in x.LIMBS:
        base = {"left_wrist": (0.4, 0.3), "right_wrist": (0.6, 0.3), "left_foot": (0.45, 0.8), "right_foot": (0.55, 0.8)}[limb]
        points = (overrides or {}).get(limb, [base] * count)
        limbs[limb] = {"x": [p[0] if p else None for p in points], "y": [p[1] if p else None for p in points], "speed_L_per_s": [0.0] * count,
                       "run": (runs or {}).get(limb, [0 if p else None for p in points])}
    return {"t": [i * 100 for i in range(count)], "width": W, "height": H, "L_px": L, "limbs": limbs}


def sample(t, side="right", straight=True, toe=True):
    # Shoulder above elbow above wrist: straight when collinear, bent otherwise.
    shoulder = np.array([0.5, 0.3])
    elbow = shoulder + [0, -40 / H] if straight else shoulder + [40 / W, 0]
    wrist = elbow + [0, -40 / H] if straight else elbow + [0, -40 / H]
    joints = {f"{side}_shoulder": list(shoulder), f"{side}_elbow": list(elbow), f"{side}_wrist": list(wrist), "left_hip": [0.45, 0.5], "right_hip": [0.55, 0.5],
              "left_knee": [0.45, 0.6], "right_knee": [0.55, 0.6], "left_ankle": [0.45, 0.8], "right_ankle": [0.55, 0.8]}
    if toe:
        joints.update({"left_foot_index": [0.44, 0.82], "right_foot_index": [0.56, 0.82]})
    return {"t": t, "pose": True, "joints": joints}


def event(kind, side, start, end, up=1.0, right=0.0, eid=None, quality="good", truncated=False, support=None, path=None, context=None):
    ev = {"id": eid or f"{kind}-{side}-{start}", "type": kind, "hand": side, "start_ms": start, "end_ms": end, "truncated": truncated, "tracking_quality": {"label": quality},
          "evidence": {"duration_ms": end - start, "net_up_L": up, "net_image_right_L": right, "net_displacement_L": float(np.hypot(up, right)), "max_displacement_L": float(np.hypot(up, right)),
                       "path_length_L": path if path is not None else float(np.hypot(up, right)), "direction": "up", "peak_speed_L_per_s": 2.0, "peak_speed_ms": start}}
    if support:
        ev["evidence"]["foot_support"] = support
    ev["context"] = context or {"limbs": {f: {"state": "quiet", "max_excursion_L": 0.01} for f in x.LIMBS}, "previous": None, "next": None}
    return ev


def build(events, ser=None, samples=None, context=None, bounds=(0, 8000)):
    result = {"attempt_bounds_ms": {"start": bounds[0], "end": bounds[1]}}
    return co.build_coaching(result, events, ser or series(), samples if samples is not None else [sample(i * 100) for i in range(80)], W, H, context)


def kinds(output):
    return [c["kind"] for c in output["cards"]]


def text(items):
    return " ".join(i["text"] for i in items)


def test_long_straight_reach_from_still_feet_becomes_a_tentative_card():
    output = build([event("wrist_motion", "right", 3000, 3800)])
    assert kinds(output) == ["extended_reach"]
    card = output["cards"][0]
    assert card["status_label"] == "Hypothesis to test" and "2D" in " ".join(card["uncertainty"]) and "skeleton" in card["keep_if"]


def test_bent_arm_at_the_end_of_a_reach_is_a_counterexample():
    output = build([event("wrist_motion", "right", 3000, 3800)], samples=[sample(i * 100, straight=(i * 100 < 3500)) for i in range(80)])
    assert kinds(output) == [] and "still had room" in text(output["not_flagged"])


def test_a_foot_step_before_the_reach_is_not_flagged_even_with_a_straight_arm():
    output = build([event("foot_motion", "left", 2000, 2800, up=0.6), event("wrist_motion", "right", 3000, 3800)])
    assert "extended_reach" not in kinds(output) and "feet were being set up" in text(output["not_flagged"])


def test_step_after_reach_gives_a_timestamped_alternative():
    output = build([event("wrist_motion", "right", 3000, 3800), event("foot_motion", "left", 4000, 4600, up=0.7)])
    card = next(c for c in output["cards"] if c["kind"] == "step_after_reach")
    assert "left foot up first" in card["try_this"] and "00:04.6" in card["try_this"]


def test_missing_foot_tracking_means_cannot_judge_not_a_suggestion():
    points = [(0.45, 0.8)] * 22 + [None] * 10 + [(0.45, 0.8)] * 48
    output = build([event("wrist_motion", "right", 3000, 3800)], ser=series(overrides={"left_foot": points}))
    assert kinds(output) == [] and "foot setup is unknown" in text(output["cannot_evaluate"])


def test_tracking_break_with_valid_endpoints_means_cannot_judge():
    output = build([event("wrist_motion", "right", 3000, 3800)], ser=series(runs={"left_foot": [0] * 20 + [1] * 60}))
    assert kinds(output) == [] and "foot setup is unknown" in text(output["cannot_evaluate"])


def test_uncertain_foot_never_supports_advice():
    unstable = {"anchor_state": "uncertain", "state": "agrees", "points_compared": ["toe"]}
    output = build([event("foot_motion", "left", 2000, 2800, up=1.5, support=unstable)])
    assert kinds(output) == [] and "no advice uses it" in text(output["cannot_evaluate"])
    assert output["placements"] == []


def test_weak_or_cut_off_reach_is_not_judged():
    for fields in ({"quality": "weak"}, {"truncated": True}):
        output = build([event("wrist_motion", "right", 3000, 3800, **fields)])
        assert kinds(output) == [] and "not judged" in text(output["cannot_evaluate"])


def test_small_reach_is_ignored():
    assert build([event("wrist_motion", "right", 3000, 3800, up=0.3)])["reach_tally"]["reaches_evaluated"] == 0


def test_arm_length_needs_enough_samples():
    samples = [sample(i * 100) for i in range(10)] + [{"t": i * 100, "pose": True, "joints": {}} for i in range(10, 80)]
    output = build([event("wrist_motion", "right", 3000, 3800)], samples=samples)
    assert kinds(output) == [] and "tracked too rarely" in text(output["cannot_evaluate"])


def test_hand_and_foot_together_only_when_really_overlapping():
    together = build([event("wrist_motion", "right", 3000, 3800), event("foot_motion", "left", 3100, 3700, up=0.6)])
    assert kinds(together) == ["hand_foot_together"]
    led = build([event("wrist_motion", "right", 3000, 3800), event("foot_motion", "left", 2500, 3200, up=0.6)])
    assert "hand_foot_together" not in kinds(led)


def test_repeat_adjustment_requires_small_net_progress_and_a_reach():
    back = [event("foot_motion", "left", 2000, 2500, up=0.5, path=0.6), event("foot_motion", "left", 3000, 3500, up=-0.5, path=0.6)]
    assert "repeat_foot_adjust" in kinds(build([*back, event("wrist_motion", "right", 4000, 4800)]))
    assert "repeat_foot_adjust" not in kinds(build(back))
    progress = [event("foot_motion", "left", 2000, 2500, up=0.5, path=0.5), event("foot_motion", "left", 3000, 3500, up=0.5, path=0.5)]
    output = build([*progress, event("wrist_motion", "right", 4000, 4800)])
    assert "repeat_foot_adjust" not in kinds(output) and "looks like progress" in text(output["not_flagged"])


def drift_context():
    limbs = {f: {"state": "quiet", "max_excursion_L": 0.01} for f in x.LIMBS}
    limbs["left_foot"] = {"state": "drifted", "max_excursion_L": 0.4}
    return {"limbs": limbs, "previous": None, "next": None}


def test_ankle_shift_with_planted_toe_is_not_a_foot_shift():
    output = build([event("wrist_motion", "right", 3000, 3800, up=0.3, context=drift_context())])
    assert "foot_shift_during_reach" not in kinds(output) and "planted foot" in text(output["not_flagged"])


def test_ankle_shift_without_toe_tracking_cannot_be_judged():
    output = build([event("wrist_motion", "right", 3000, 3800, up=0.3, context=drift_context())], samples=[sample(i * 100, toe=False) for i in range(80)])
    assert "toe was not tracked" in text(output["cannot_evaluate"])


def test_moving_toe_gives_a_shift_card_without_claiming_a_slip():
    samples = [sample(i * 100) for i in range(80)]
    for s in samples:
        if 3000 <= s["t"] <= 3800:
            s["joints"]["left_foot_index"] = [0.44, 0.82 - (s["t"] - 3000) / 800 * 30 / H]
    card = next(c for c in build([event("wrist_motion", "right", 3000, 3800, up=0.3, context=drift_context())], samples=samples)["cards"] if c["kind"] == "foot_shift_during_reach")
    assert "cannot show a slip" in " ".join(card["uncertainty"])


def test_large_step_excludes_leaving_the_ground():
    assert "large_step" in kinds(build([event("foot_motion", "left", 3000, 4000, up=1.3)]))
    output = build([event("foot_motion", "left", 500, 1200, up=1.5)])
    assert "large_step" not in kinds(output) and "leaving the ground" in text(output["not_flagged"])


def test_long_pause_needs_tracked_feet_and_says_hands_may_be_unseen():
    a, b = event("foot_motion", "left", 1000, 1500, up=0.3), event("foot_motion", "right", 6000, 6500, up=0.3)
    points = [None] * 80
    card = next(c for c in build([a, b], ser=series(overrides={"left_wrist": points}))["cards"] if c["kind"] == "long_pause")
    assert "may have moved unseen" in card["moment"] and "planned rest" in card["keep_if"]
    gap = [(0.45, 0.8)] * 30 + [None] * 5 + [(0.45, 0.8)] * 45
    output = build([a, b], ser=series(overrides={"left_foot": gap}))
    assert "long_pause" not in kinds(output) and "cannot be read as a pause" in text(output["cannot_evaluate"])


def test_card_count_is_capped_per_kind_and_overall():
    events = [event("foot_motion", "left", 3000 + i * 3000, 4000 + i * 3000, up=1.3) for i in range(6)]
    output = build(events, ser=series(160), samples=[sample(i * 100) for i in range(160)])
    assert kinds(output).count("large_step") == co.MAX_PER_KIND and output["cards_omitted"] == 3


def test_identical_inputs_give_identical_ids():
    events = [event("wrist_motion", "right", 3000, 3800)]
    assert build(events)["cards"][0]["id"] == build(events)["cards"][0]["id"]


def holds_ctx(items, usable=True):
    return {"usable": usable, "holds": items, "message": "not aligned"}


def hold(x_pos, y_pos, role="", use="", radius=0.035, hid=None):
    return {"id": hid or f"h{x_pos}{y_pos}", "x": x_pos, "y": y_pos, "radius": radius, "role": role, "use": use, "route": "", "hold_type": ""}


def landing():
    return [event("foot_motion", "left", 2000, 2800, up=0.3)]


def test_placement_proximity_is_never_contact_and_no_hold_is_unknown():
    output = build(landing(), context=holds_ctx([hold(0.44, 0.82, use="foot")]))
    assert output["placements"][0]["proximity"] == "within_marked_region" and "contact" not in output["placements"][0]
    far = build(landing(), context=holds_ctx([hold(0.9, 0.2, use="foot")]))
    assert far["placements"][0]["proximity"] == "no_marked_hold_nearby"


def test_hand_only_holds_are_not_foot_placements():
    assert build(landing(), context=holds_ctx([hold(0.44, 0.82, use="hand")]))["placements"][0]["proximity"] == "no_foot_hold_marked"


def test_unverified_map_is_not_used_for_proximity():
    output = build(landing(), context=holds_ctx([hold(0.44, 0.82, use="foot")], usable=False))
    assert output["placements"][0]["proximity"] == "map_unavailable"


def test_placement_needs_the_foot_to_settle():
    moving = [(0.45, 0.8 + (i - 28) * 0.01 if i >= 28 else 0.8) for i in range(80)]
    assert build(landing(), ser=series(overrides={"left_foot": moving}))["placements"] == []


# ---- reach geometry

BODY = beta.Body(1.0, 1.7, 100, 100)


def test_margin_falls_as_a_hand_moves_out_of_reach():
    feet = [[-0.3, 3.2], [0.3, 3.2]]
    near, far, out = (beta.reach_margin([[0, y]], feet, BODY) for y in (1.5, 0.8, -0.6))
    assert near > far > out and out < 0


def test_margin_respects_aspect_ratio_through_hold_points():
    points = beta.hold_points([hold(0.5, 0.5)], W, H, 100.0)
    assert points[0].tolist() == pytest.approx([3.6, 6.4])


def route():
    return [hold(0.45, 0.60, role="start", use="hand", hid="a"), hold(0.55, 0.60, role="start", use="hand", hid="b"), hold(0.45, 0.82, use="foot", hid="c"), hold(0.55, 0.82, use="foot", hid="d"),
            hold(0.45, 0.72, use="foot", hid="e"), hold(0.55, 0.70, use="both", hid="f"), hold(0.5, 0.52, use="hand", hid="g"), hold(0.5, 0.48, role="finish", use="hand", hid="h")]


def test_candidates_refuse_without_required_marks():
    result = beta.candidate_sequences([hold(0.5, 0.5)], W, H, L, BODY)
    assert result["status"] == "setup_needed" and len(result["needs"]) == 2 and result["candidates"] == []


def test_feet_may_start_from_the_ground_but_a_hand_cannot_move_first():
    holds = [hold(0.45, 0.60, role="start", use="hand", hid="a"), hold(0.55, 0.60, role="start", use="hand", hid="b"), hold(0.5, 0.66, use="foot", hid="c"),
             hold(0.5, 0.56, use="hand", hid="f"), hold(0.5, 0.50, role="finish", use="hand", hid="h")]
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert result["status"] == "ready"
    candidate = result["candidates"][0]
    assert candidate["feet_start_off_wall"] and candidate["steps"][0]["limb"].endswith("foot") and candidate["steps"][0]["from_hold"] == beta.OFF_WALL
    assert any("from the ground" in a for a in result["assumptions"])


def test_a_foot_is_never_proposed_above_both_hands():
    result = beta.candidate_sequences(route(), W, H, L, BODY)
    points = beta.hold_points(route(), W, H, L)
    for candidate in result["candidates"]:
        hands = [candidate["start"]["left_hand"], candidate["start"]["right_hand"]]
        for step in candidate["steps"]:
            if step["limb"].endswith("hand"):
                hands["left_hand right_hand".split().index(step["limb"])] = step["to_hold"]
            else:
                assert points[step["to_hold"]][1] > min(points[hands[0]][1], points[hands[1]][1])


def test_candidates_need_a_body_scale():
    result = beta.candidate_sequences(route(), W, H, L, None)
    assert result["status"] == "setup_needed" and "reach lengths" in result["needs"][0]


def test_candidates_reach_the_finish_with_a_hand_and_never_use_marked_limits_wrongly():
    result = beta.candidate_sequences(route(), W, H, L, BODY)
    assert result["status"] == "ready" and "none is the best" in result["note"]
    uses = {i: h["use"] for i, h in enumerate(route())}
    for candidate in result["candidates"]:
        last = candidate["steps"][-1]
        assert last["limb"].endswith("hand") and route()[last["to_hold"]]["role"] == "finish"
        for step in candidate["steps"]:
            assert uses[step["to_hold"]] in ({"hand", "both"} if step["limb"].endswith("hand") else {"foot", "both"})
            assert step["margin_L"] >= -0.01


def test_a_finish_out_of_reach_gives_no_candidate():
    holds = route()
    holds[-1]["y"] = 0.02
    holds[-2]["y"] = 0.5
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert result["status"] == "no_candidate" and "does not mean the problem is impossible" in result["note"]


def test_unset_use_is_disclosed_as_an_assumption():
    holds = route()
    holds[4]["use"] = ""
    assert any("no hand or foot use" in a for a in beta.candidate_sequences(holds, W, H, L, BODY)["assumptions"])


def test_alternative_foot_setup_requires_a_real_gain(monkeypatch):
    monkeypatch.setattr(beta, "body_model", lambda *args: BODY)   # the synthetic poses are not body-proportioned
    # Reach ends high; a higher marked foothold adds margin, a lower one does not.
    feet = {"left_foot": [(0.45, 0.86)] * 80, "right_foot": [(0.55, 0.74)] * 80}
    wrist = [(0.56, 0.66) if i < 38 else (0.56, 0.60) for i in range(80)]
    ser = series(overrides={**feet, "right_wrist": wrist})
    samples = [sample(i * 100) for i in range(80)]
    higher = build([event("wrist_motion", "right", 3000, 3800)], ser=ser, samples=samples, context=holds_ctx([hold(0.5, 0.76, use="foot", hid="up")]))
    card = next(c for c in higher["cards"] if c["kind"] == "extended_reach")
    assert card["alternatives"][0]["hold_id"] == "up" and card["alternatives"][0]["gain_L"] >= co.C["alternative_min_gain_L"]
    lower = build([event("wrist_motion", "right", 3000, 3800)], ser=ser, samples=samples, context=holds_ctx([hold(0.5, 0.95, use="foot")]))
    assert next(c for c in lower["cards"] if c["kind"] == "extended_reach")["alternatives"] == []


def test_card_points_to_marking_when_no_map():
    assert "Mark the holds" in build([event("wrist_motion", "right", 3000, 3800)])["cards"][0]["map_action"]


# ---- reference alignment

def wall(seed=4, width=320, height=568):
    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 190, np.uint8)
    for _ in range(900):
        cv2.circle(image, (int(rng.integers(0, width)), int(rng.integers(0, height))), int(rng.integers(2, 6)), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
    return image


TIMES = list(range(0, 1200, 100))
POSE = {"joints": {"nose": [0.45, 0.4], "left_ankle": [0.55, 0.6]}}


def test_static_wall_with_moving_climber_verifies():
    def frame(ms):
        image = wall()
        cv2.rectangle(image, (140 + ms // 60, 230), (180 + ms // 60, 320), (10, 10, 10), -1)
        return image
    assert al.check_reference(frame, 0, TIMES, lambda ms: POSE)["status"] == "fixed_verified"


def test_a_camera_that_moved_later_is_rejected():
    base = wall()
    def frame(ms):
        return base if ms < 600 else cv2.warpAffine(base, np.float32([[1, 0, 18], [0, 1, 0]]), base.shape[1::-1], borderMode=cv2.BORDER_REFLECT)
    assert al.check_reference(frame, 0, TIMES, lambda ms: POSE)["status"] == "camera_moved"


def test_featureless_video_cannot_be_verified():
    blank = np.full((568, 320, 3), 180, np.uint8)
    assert al.check_reference(lambda ms: blank, 0, TIMES, lambda ms: POSE)["status"] == "could_not_verify"


# ---- persistence and old data

def test_old_database_gains_columns_and_keeps_rows(tmp_path):
    path = tmp_path / "old.db"
    schema = db.SCHEMA.replace('  hold_type TEXT NOT NULL DEFAULT \'\',\n', "  hold_type TEXT NOT NULL DEFAULT '',\n")
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.execute("ALTER TABLE attempts RENAME TO keep")
    connection.execute("ALTER TABLE keep RENAME TO attempts")
    connection.commit()
    connection.close()
    db.initialize(path)
    db.initialize(path)
    connection = sqlite3.connect(path)
    names = {r[1] for r in connection.execute("PRAGMA table_info(holds)")}
    assert {"role", "use"} <= names
    connection.close()


def test_columns_are_added_to_a_database_without_them(tmp_path):
    path = tmp_path / "x.db"
    connection = sqlite3.connect(path)
    connection.executescript("""CREATE TABLE holds(id TEXT PRIMARY KEY, map_id TEXT, x REAL, y REAL, radius REAL, route TEXT, hold_type TEXT, created_at TEXT);
                                CREATE TABLE attempts(id TEXT PRIMARY KEY, title TEXT);
                                INSERT INTO holds VALUES ('h','m',0.1,0.2,0.03,'r','t','now');""")
    connection.commit()
    connection.close()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    db._add_missing_columns(connection)
    row = dict(connection.execute("SELECT * FROM holds").fetchone())
    assert row["x"] == 0.1 and row["role"] == "" and row["use"] == ""
    connection.close()
