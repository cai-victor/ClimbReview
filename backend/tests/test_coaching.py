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


def sample(t, side="right", straight=True, toe=True, straight_legs=False):
    # Shoulder above elbow above wrist: straight when collinear, bent otherwise.
    shoulder = np.array([0.5, 0.3])
    elbow = shoulder + [0, -40 / H] if straight else shoulder + [40 / W, 0]
    wrist = elbow + [0, -40 / H] if straight else elbow + [0, -40 / H]
    joints = {f"{side}_shoulder": list(shoulder), f"{side}_elbow": list(elbow), f"{side}_wrist": list(wrist), "left_hip": [0.45, 0.5], "right_hip": [0.55, 0.5],
              "left_knee": [0.45, 0.65] if straight_legs else [0.3, 0.65], "right_knee": [0.55, 0.65] if straight_legs else [0.7, 0.65],
              "left_ankle": [0.45, 0.8], "right_ankle": [0.55, 0.8]}      # knees out to the side: legs bent, unless straight_legs
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
    result = {"attempt_bounds_ms": {"start": bounds[0], "end": bounds[1]},
              "coverage": {"detectors": {key: {"fraction": 0.9} for key in x.DETECTOR_OF.values()}}}
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


def test_large_step_onto_an_already_straight_leg_is_not_a_stand_up():
    # A foot that lands with the leg extended was reached out to. There is nothing left to stand up on, so no card.
    step = [event("foot_motion", "left", 3000, 4000, up=1.3)]
    output = build(step, samples=[sample(i * 100, straight_legs=True) for i in range(80)])
    assert "large_step" not in kinds(output) and "already nearly straight" in text(output["not_flagged"])
    assert "large_step" in kinds(build(step, samples=[sample(i * 100) for i in range(80)]))


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
    output = build(events, ser=series(260), samples=[sample(i * 100) for i in range(260)], bounds=(0, 26000))
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
                                CREATE TABLE hold_maps(id TEXT PRIMARY KEY, name TEXT);
                                INSERT INTO holds VALUES ('h','m',0.1,0.2,0.03,'r','t','now');""")
    connection.commit()
    connection.close()
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    db._add_missing_columns(connection)
    row = dict(connection.execute("SELECT * FROM holds").fetchone())
    assert row["x"] == 0.1 and row["role"] == "" and row["use"] == ""
    assert "scale" in {r["name"] for r in connection.execute("PRAGMA table_info(hold_maps)")}
    connection.close()


def step_samples(hip_x, rise_after_ms=None, count=120, foot_x=0.55):
    """Hips at `hip_x`; the right ankle sits at `foot_x`. Hips rise 0.6 L at `rise_after_ms` after the step ends at 4000 ms, if given."""
    out = []
    for i in range(count):
        s = sample(i * 100)
        up = 0.6 * L / H if rise_after_ms is not None and i * 100 >= 4000 + rise_after_ms else 0.0
        s["joints"]["left_hip"], s["joints"]["right_hip"] = [hip_x - 0.03, 0.5 - up], [hip_x + 0.03, 0.5 - up]
        s["joints"]["right_ankle"] = [foot_x, 0.55]
        out.append(s)
    return out


def test_high_step_is_judged_by_whether_the_hips_come_over_the_foot_and_rise():
    step = [event("foot_motion", "right", 3000, 4000, up=1.3)]
    far = 0.55 - 1.0 * L / W                                    # hips one torso length to the left of the foot
    stuck = build(step, samples=step_samples(far), bounds=(0, 12000))
    card = next(c for c in stuck["cards"] if c["kind"] == "large_step")
    assert card["title"] == "Hips stayed left of your right foot after a high step"
    assert "1.0 torso lengths to the left" in card["moment"] and "did not rise" in card["moment"]
    assert "move your hips to the right" in card["try_this"] and "intermediate" not in card["try_this"]
    shapes = {shape["type"]: shape for shape in card["highlight"]["shapes"]}
    assert set(shapes) == {"ring", "dot", "arrow"}
    assert shapes["arrow"]["x2"] > shapes["arrow"]["x1"] and abs(shapes["ring"]["x"] - 0.55) < 1e-6   # the arrow points from the hips toward the foot
    assert "not how close they are to the wall" in card["uncertainty"][0]

    smooth = build(step, samples=step_samples(far, rise_after_ms=1000), bounds=(0, 12000))
    assert "large_step" not in kinds(smooth) and "clean stand-up" in text(smooth["not_flagged"])

    slow_over = build(step, samples=step_samples(0.55, rise_after_ms=4000), bounds=(0, 12000))
    card = next(c for c in slow_over["cards"] if c["kind"] == "large_step")
    assert card["title"].startswith("Slow to stand up") and "arrow" not in [shape["type"] for shape in card["highlight"]["shapes"]]

    cut_short = build(step, samples=step_samples(far, count=55), bounds=(0, 5400))
    assert "large_step" not in kinds(cut_short) and "not tracked for long enough" in text(cut_short["cannot_evaluate"])


def test_high_step_followed_by_leaving_the_wall_is_flagged_and_leads_the_list():
    # Steps up at 3 to 4s, hips beside the foot and never rising, then a fast descent at 6s.
    samples = step_samples(0.55 - 1.0 * L / W, count=100)
    for s in samples:
        if s["t"] >= 6000:
            drop = min(1.0, (s["t"] - 6000) / 800) * 3 * L / H
            for hip in ("left_hip", "right_hip"):
                s["joints"][hip][1] += drop
    output = build([event("foot_motion", "right", 3000, 4000, up=1.3)], samples=samples, bounds=(0, 9900))
    card = next(c for c in output["cards"] if c["kind"] == "large_step")
    assert card["stand_up"]["left_wall_after"] and "then you left the wall" in card["moment"]
    assert card["id"] in output["top_card_ids"]
    left = next(c for c in output["cards"] if c["kind"] == "story_left_wall")
    assert "right foot at 00:03.0" in left["moment"] and left["limbs"] == ["right_foot"]
    assert [shape["type"] for shape in left["highlight"]["shapes"]] == ["dot", "arrow"]


# ---- planner rules added after a climber's review: humanly possible moves, low feet, pull direction, alternative start feet

def ladder(**changes):
    """Two start hands, footholds below, alternating hand holds up to a finish, with footholds beside the line."""
    holds = [hold(0.45, 0.60, role="start", use="hand", hid="a"), hold(0.55, 0.60, role="start", use="hand", hid="b"),
             hold(0.45, 0.82, use="foot", hid="c"), hold(0.55, 0.82, use="foot", hid="d"), hold(0.45, 0.72, use="foot", hid="e"), hold(0.55, 0.70, use="foot", hid="f"),
             hold(0.5, 0.52, use="hand", hid="g"), hold(0.5, 0.46, role="finish", use="hand", hid="h")]
    for index, change in changes.items():
        holds[int(index[1:])].update(change)
    return holds


def placements(candidate):
    state = dict(candidate["start"])
    yield dict(state)
    for step in candidate["steps"]:
        state[step["limb"]] = step["to_hold"]
        yield dict(state)


def test_no_candidate_crosses_the_feet_or_takes_a_step_longer_than_a_leg():
    holds = ladder()
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert result["status"] == "ready" and result["method"] == "candidate-beta-v3"
    points = beta.hold_points(holds, W, H, L)
    for candidate in result["candidates"]:
        for state in placements(candidate):
            if state["left_foot"] >= 0 and state["right_foot"] >= 0:
                assert points[state["left_foot"]][0] - points[state["right_foot"]][0] <= beta.MAX_FOOT_CROSS_L
        assert all(s["distance_L"] <= beta.MAX_FOOT_MOVE_OF_LEG * BODY.leg_L for s in candidate["steps"] if s["limb"].endswith("foot"))
        assert len(candidate["figures"]) == len(candidate["steps"]) + 1 and set(candidate["figures"][0]) >= {"head", "left_elbow", "right_knee", "pelvis"}


def test_crossed_feet_and_splits_are_refused_as_positions():
    holds = ladder()
    problem = beta._Problem(holds, beta.hold_points(holds, W, H, L), BODY)
    assert problem.humanly((0, 1, 2, 3)) and not problem.humanly((0, 1, 3, 2))          # left foot far to the right of the right foot
    wide = [*holds, hold(0.05, 0.82, use="foot", hid="w"), hold(0.95, 0.82, use="foot", hid="x")]
    spread = beta._Problem(wide, beta.hold_points(wide, W, H, L), BODY)
    assert not spread.humanly((0, 1, 8, 9))                                               # wider than one and a half leg lengths


def test_low_feet_profile_avoids_a_high_foot_another_profile_accepts():
    labels = {key: value["label"] for key, value in beta.PROFILES.items()}
    assert labels == {"balanced": "Balanced", "fewer_moves": "Fewer moves", "low_feet": "Low feet, small steps"}
    assert beta.PROFILES["low_feet"]["high_foot"] > beta.PROFILES["balanced"]["high_foot"] > beta.PROFILES["fewer_moves"]["high_foot"]
    hands, body = [[0.0, 0.0], [0.4, 0.0]], BODY
    _, _, _, low_when_feet_low = beta.solve_pose(hands, [[0.0, 2.6], [0.4, 2.6]], body)
    _, _, _, low_when_foot_high = beta.solve_pose(hands, [[0.0, 2.6], [0.4, 1.0]], body)
    assert low_when_feet_low >= 0 > low_when_foot_high                                    # a foot one torso length under the hands needs a high step


def test_a_marked_pull_direction_limits_where_the_body_can_be():
    hands, feet = [[0.0, 0.0], [0.6, 0.0]], [[0.0, 2.4], [0.6, 2.4]]
    free = beta.solve_pose(hands, feet, BODY)
    left = beta.solve_pose(hands, feet, BODY, pulls=["left", ""])
    assert left[1][0] + 0.5 * np.sin(left[2]) <= hands[0][0] + beta.PULL_SIDE_L + 1e-6   # shoulders stay on the side the hold is pulled toward
    assert left[0] <= free[0]
    feet = [[0.0, 3.3], [0.6, 3.3]]
    free = beta.solve_pose(hands, feet, BODY)
    under = beta.solve_pose(hands, feet, BODY, pulls=["up", "up"])
    assert under[0] < 0 <= free[0]                                                        # underclings cannot be used from this far below
    marked = ladder(h6={"pull": "up"})
    assert any("Pull directions you marked" in text for text in beta.candidate_sequences(marked, W, H, L, BODY)["assumptions"])


def test_two_alternative_start_footholds_do_not_have_to_be_used_together():
    holds = [hold(0.45, 0.60, role="start", use="hand", hid="a"), hold(0.55, 0.60, role="start", use="hand", hid="b"),
             hold(0.02, 0.80, role="start", use="foot", hid="c"), hold(0.98, 0.80, role="start", use="foot", hid="d"),      # too far apart to stand on both
             hold(0.5, 0.74, use="foot", hid="e"), hold(0.5, 0.52, use="hand", hid="g"), hold(0.5, 0.46, role="finish", use="hand", hid="h")]
    problem = beta._Problem(holds, beta.hold_points(holds, W, H, L), BODY)
    assert not problem.allowed((0, 1, 2, 3))
    assert all(state[2:] != (2, 3) for state in problem.start_states()) and (0, 1, -1, -1) in problem.start_states()
    assert beta.candidate_sequences(holds, W, H, L, BODY)["status"] == "ready"


def test_a_blocked_route_says_how_far_the_search_got():
    holds = [hold(0.45, 0.60, role="start", use="hand", hid="a"), hold(0.55, 0.60, role="start", use="hand", hid="b"), hold(0.5, 0.70, use="foot", hid="c"),
             hold(0.5, 0.56, use="hand", hid="f"), hold(0.5, 0.05, role="finish", use="hand", hid="h")]
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert result["status"] == "no_candidate" and result["stuck"]["hands_reached"] and not result["stuck"]["search_limit_reached"]
    assert "got the hands as far as H" in result["note"] and "does not mean the problem is impossible" in result["note"]


def test_matches_and_top_outs_are_named():
    holds = ladder(h7={"hold_type": "top-out"})
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert all(c["tops_out"] for c in result["candidates"])
    steps = [s for c in result["candidates"] for s in c["steps"]]
    assert all(isinstance(s["match"], bool) and isinstance(s["high_foot"], bool) for s in steps)
    for candidate in result["candidates"]:
        states = list(placements(candidate))
        for step, state in zip(candidate["steps"], states[1:]):
            if step["limb"].endswith("hand"):
                assert step["match"] == (state["left_hand"] == state["right_hand"])       # a match is both hands on one hold


def test_the_body_never_hangs_below_its_feet():
    hands, feet = [[0.0, 0.0], [0.4, 0.0]], [[0.0, 0.3], [0.4, 0.3]]          # feet almost level with the hands
    margin, core, lean, _ = beta.solve_pose(hands, feet, BODY)
    assert core[1] + 0.5 * np.cos(lean) <= 0.3 + beta.HIPS_BELOW_FEET_L + 1e-6   # hips are not below the feet
    core, lean = beta.natural_pose(hands, feet, BODY)
    assert core[1] + 0.5 * np.cos(lean) <= 0.3 + beta.HIPS_BELOW_FEET_L + 1e-6


def test_a_sequence_ends_with_both_hands_on_the_finish():
    result = beta.candidate_sequences(ladder(), W, H, L, BODY)
    assert result["status"] == "ready"
    for candidate in result["candidates"]:
        hands = dict(left_hand=candidate["start"]["left_hand"], right_hand=candidate["start"]["right_hand"])
        for step in candidate["steps"]:
            if step["limb"] in hands:
                hands[step["limb"]] = step["to_hold"]
        assert hands == {"left_hand": 7, "right_hand": 7} and candidate["steps"][-1]["match"]
    assert any("both hands on the finish" in text for text in result["assumptions"])


def test_start_limbs_the_climber_marked_are_used():
    crossed = ladder(h0={"start_limb": "right_hand"}, h1={"start_limb": "left_hand"}, h3={"role": "start", "start_limb": "left_foot"})
    result = beta.candidate_sequences(crossed, W, H, L, BODY)
    assert result["status"] == "ready"
    for candidate in result["candidates"]:
        assert candidate["start"]["right_hand"] == 0 and candidate["start"]["left_hand"] == 1 and candidate["start"]["left_foot"] == 3
    matched = beta.candidate_sequences(ladder(h0={"start_limb": "both_hands"}, h1={"role": ""}), W, H, L, BODY)
    assert all(c["start"]["left_hand"] == 0 and c["start"]["right_hand"] == 0 for c in matched["candidates"]) and matched["candidates"]
    # A start hold given to a foot is not a hand start.
    only_feet = [dict(h, start_limb="left_foot") if h["role"] == "start" else h for h in ladder()]
    assert any("start hold for the hands" in need for need in beta.candidate_sequences(only_feet, W, H, L, BODY)["needs"])


def test_the_hips_never_sit_on_a_foot():
    body, hands, feet = BODY, np.array([[0.0, 0.0], [0.4, 0.0]]), np.array([[0.0, 1.9], [0.4, 1.9]])
    for cores in (beta._grid(np.array([0.2, 1.0]), 2.5, 0.25),):
        for angle in beta.TORSO_ANGLES:
            up = np.array([np.sin(angle), -np.cos(angle)]) * 0.5
            slack = beta._slack(cores + up, cores - up, hands, feet, body, ())
            legs = np.linalg.norm((cores - up)[:, None] - feet[None], axis=2).min(axis=1)
            assert (legs[np.isfinite(slack) & (slack > -np.inf)] >= beta.MIN_LEG_FOLD_OF_LEG * body.leg_L - 1e-9).all()
    result = beta.candidate_sequences(ladder(), W, H, L, BODY)
    scale = L / W, L / H
    for candidate in result["candidates"]:
        for figure in candidate["figures"]:
            pelvis = np.array([figure["pelvis"][0] / scale[0], figure["pelvis"][1] / scale[1]])
            for foot in ("left_foot", "right_foot"):
                point = np.array([figure[foot][0] / scale[0], figure[foot][1] / scale[1]])
                assert np.linalg.norm(point - pelvis) > 0.3 * BODY.leg_L


def test_strain_prefers_hanging_tall_over_a_crouch_or_a_press():
    hands, feet = np.array([[0.0, 0.0], [0.4, 0.0]]), np.array([[0.0, 3.3], [0.4, 3.3]])
    strain = lambda center: float(beta._strain(np.array([center]) + [0, -0.5], np.array([center]) + [0, 0.5], hands, feet, BODY, 0.0)[0])
    tall, crouched, pressing = strain([0.2, 1.3]), strain([0.2, 2.0]), strain([0.2, -0.4])
    assert tall < 0.05 and crouched > tall + 0.15 and pressing > tall + 0.2


def test_a_volume_offers_several_spots_and_is_reported_as_one_hold():
    holds = ladder(h6={"hold_type": "Volume", "use": "", "radius": 0.06})
    spots, points, source = beta.expand_volumes(holds, beta.hold_points(holds, W, H, L), np.array([h["radius"] * W / L for h in holds]))
    assert len(spots) == len(holds) + 2 and source.count(6) == 3
    assert len({tuple(points[i].round(3)) for i, s in enumerate(source) if s == 6}) == 3
    result = beta.candidate_sequences(holds, W, H, L, BODY)
    assert result["status"] == "ready" and any("volume" in text.lower() for text in result["assumptions"])
    for candidate in result["candidates"]:
        assert all(-1 <= step["to_hold"] < len(holds) for step in candidate["steps"])


def test_steps_carry_the_effort_notes():
    step = beta.candidate_sequences(ladder(), W, H, L, BODY)["candidates"][0]["steps"][0]
    assert {"strain", "strenuous", "body_shift_L", "big_shift", "on_volume", "to_point"} <= set(step)
