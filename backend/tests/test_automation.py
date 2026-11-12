"""Automatic analysis start, rest points, role proposals, tracked-route feedback, and ranking. All inputs are synthetic."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import db
from app.analysis import coaching as co
from app.analysis import route_auto as ra
from app.main import create_app
from app.settings import Settings, load_pipeline_config
from app.worker import Worker
from test_app import noise_clip, upload

W, H, L = 720, 1280, 100.0
LIMBS = ("left_wrist", "right_wrist", "left_foot", "right_foot")
HOME = {"left_wrist": (0.4, 0.3), "right_wrist": (0.6, 0.3), "left_foot": (0.45, 0.8), "right_foot": (0.55, 0.8)}


def series(count=60, paths=None, speeds=None, runs=None):
    limbs = {}
    for limb in LIMBS:
        points = (paths or {}).get(limb, [HOME[limb]] * count)
        limbs[limb] = {"x": [p[0] if p else None for p in points], "y": [p[1] if p else None for p in points],
                       "speed_L_per_s": (speeds or {}).get(limb, [0.0 if p else None for p in points]), "run": (runs or {}).get(limb, [0 if p else None for p in points])}
    return {"t": [i * 100 for i in range(count)], "width": W, "height": H, "L_px": L, "limbs": limbs}


def samples(count=60, joints=None):
    return [{"t": i * 100, "pose": True, "joints": dict(joints or {})} for i in range(count)]


def hold(x, y, use="", role="", radius=0.03):
    return {"id": f"{x}-{y}", "x": x, "y": y, "radius": radius, "use": use, "role": role}


def test_rest_needs_continuous_slow_tracking_for_half_a_second():
    speeds = {"left_foot": [0.0] * 3 + [1.0] * 5 + [0.0] * 52}                      # 0.2 s still, then moving, then still
    rests = [r for r in ra.rest_points(series(speeds=speeds), samples()) if r["limb"] == "left_foot"]
    assert [(r["start_ms"], r["end_ms"]) for r in rests] == [(800, 5900)]


def test_rest_never_spans_a_tracking_gap_or_break():
    gap = [HOME["left_foot"]] * 20 + [None] * 5 + [HOME["left_foot"]] * 35
    rests = [r for r in ra.rest_points(series(paths={"left_foot": gap}), samples()) if r["limb"] == "left_foot"]
    assert [(r["start_ms"], r["end_ms"]) for r in rests] == [(0, 1900), (2500, 5900)]
    broken = [r for r in ra.rest_points(series(runs={"left_foot": [0] * 30 + [1] * 30}), samples()) if r["limb"] == "left_foot"]
    assert [(r["start_ms"], r["end_ms"]) for r in broken] == [(0, 2900), (3000, 5900)]


def test_foot_rest_uses_the_toe_and_hand_rest_extends_past_the_wrist():
    joints = {"left_foot_index": [0.43, 0.83], "right_wrist": [0.6, 0.3], "right_elbow": [0.6, 0.4]}
    rests = {r["limb"]: r for r in ra.rest_points(series(), samples(joints=joints))}
    assert rests["left_foot"]["anchor"] == "toe" and rests["left_foot"]["x"] == pytest.approx(0.43)
    assert rests["right_foot"]["anchor"] == "ankle"
    assert rests["right_wrist"]["anchor"] == "palm_estimate" and rests["right_wrist"]["y"] == pytest.approx(0.3 - 0.35 * 0.1)
    assert rests["left_wrist"]["anchor"] == "wrist"


def test_rests_move_with_the_camera_registration_and_are_dropped_without_one():
    rest = {"limb": "left_foot", "start_ms": 1000, "end_ms": 2000, "x": 0.5, "y": 0.5, "anchor": "toe"}
    shift = [[1, 0, 36], [0, 1, 0], [0, 0, 1]]
    moved = ra.to_reference([rest], [{"t": 1400, "matrix": shift}], W, H)
    assert moved[0]["x"] == pytest.approx(0.55) and moved[0]["y"] == pytest.approx(0.5)
    assert ra.to_reference([rest], [{"t": 9000, "matrix": shift}], W, H) == []          # no lined-up frame within 3 s
    assert ra.to_reference([rest], [], W, H) == []


def test_roles_propose_top_hold_as_finish_and_never_a_start():
    holds = [hold(0.45, 0.82), hold(0.6, 0.27), hold(0.5, 0.1), hold(0.9, 0.9)]
    rests = [{"limb": "left_foot", "start_ms": 0, "end_ms": 900, "x": 0.45, "y": 0.81, "anchor": "toe"},
             {"limb": "right_wrist", "start_ms": 0, "end_ms": 900, "x": 0.6, "y": 0.28, "anchor": "wrist"}]
    result = ra.assign_roles(holds, rests, W, H, L)
    proposed = result["holds"]
    assert [p["role"] for p in proposed] == ["", "", "finish", ""]
    assert [p["use"] for p in proposed] == ["foot", "both", "hand", ""]
    assert any("Choose your start" in note for note in result["notes"]) and "does not show the hold was touched" in result["disclaimer"]
    assert any("A hidden hand or foot may still have used them" in note for note in result["notes"])


def test_a_limb_far_from_every_hold_proposes_nothing():
    rests = [{"limb": "left_foot", "start_ms": 0, "end_ms": 900, "x": 0.1, "y": 0.5, "anchor": "toe"}]
    assert [p["use"] for p in ra.assign_roles([hold(0.5, 0.8), hold(0.5, 0.2)], rests, W, H, L)["holds"]] == ["", "hand"]


def test_visits_respect_hold_use_and_merge_repeats():
    holds = [hold(0.45, 0.8, use="hand"), hold(0.55, 0.8, use="foot")]
    rests = [{"limb": "left_foot", "start_ms": 0, "end_ms": 900, "x": 0.45, "y": 0.8, "anchor": "toe"},
             {"limb": "right_foot", "start_ms": 0, "end_ms": 900, "x": 0.55, "y": 0.8, "anchor": "toe"},
             {"limb": "right_foot", "start_ms": 1500, "end_ms": 2500, "x": 0.55, "y": 0.8, "anchor": "toe"}]
    found = ra.visits(rests, holds, W, H, L)
    assert found[0]["hold_index"] is None                      # a foot is never matched to a hand-only hold
    assert (found[1]["hold_index"], found[1]["end_ms"]) == (1, 2500) and len(found) == 2


def test_observed_route_needs_a_verified_map_and_lists_unapproached_holds():
    holds = [hold(0.45, 0.8), hold(0.55, 0.8), hold(0.5, 0.05)]
    assert co.observed_route(series(), samples(), {"usable": False, "holds": holds, "message": ""}, W, H) is None
    assert co.observed_route(series(), samples(), None, W, H) is None
    route = co.observed_route(series(), samples(), {"usable": True, "holds": holds, "message": ""}, W, H)
    assert route["unvisited"] == [2] and {v["hold_index"] for v in route["visits"]} == {0, 1}
    assert "does not show the hold was touched" in route["note"] and "hidden limb" in route["note"]


def card(kind, start, cid):
    return {"id": cid, "kind": kind, "start_ms": start}


def test_top_cards_take_one_of_each_kind_in_order_of_specificity():
    cards = [card("long_pause", 0, "p1"), card("large_step", 1, "l1"), card("large_step", 2, "l2"), card("hand_foot_together", 3, "t1"), card("extended_reach", 4, "e1")]
    assert co.top_card_ids(cards) == ["e1", "t1", "l1"]
    assert co.top_card_ids([card("long_pause", 0, "p1"), card("long_pause", 5, "p2")]) == ["p1", "p2"]
    assert co.top_card_ids([]) == []


def test_glance_counts_exclude_uncertain_feet_and_flag_hidden_limbs():
    def event(kind, side, start, end, uncertain=False):
        return {"type": kind, "hand": side, "start_ms": start, "end_ms": end, "evidence": {"foot_support": {"anchor_state": "uncertain"}} if uncertain else {}}
    events = [event("wrist_motion", "right", 0, 500), event("foot_motion", "left", 1000, 1500), event("foot_motion", "left", 2000, 2500, uncertain=True), event("foot_motion", "right", 6000, 6500)]
    fractions = {"wrist_motion_left": 0.1, "wrist_motion_right": 0.8, "foot_motion_left": 0.9, "foot_motion_right": 0.9}
    result = {"attempt_bounds_ms": {"start": 0, "end": 8000}, "coverage": {"detectors": {k: {"fraction": v} for k, v in fractions.items()}}}
    glance = co.at_a_glance(result, events)
    assert (glance["hand_moves"], glance["foot_moves"]) == (1, 2)
    assert (glance["longest_gap_ms"], glance["longest_gap_at_ms"]) == (4500, 1500)
    assert len(glance["notes"]) == 1 and "hand moves are undercounted" in glance["notes"][0]


# ---- automatic analysis after import, through the real API and worker

@pytest.fixture()
def env(tmp_path):
    settings = Settings(tmp_path / "appdata")
    return settings, TestClient(create_app(settings)), Worker(settings, load_pipeline_config())


def test_auto_analyze_queues_one_whole_clip_analysis_after_import(env, tmp_path):
    _, client, worker = env
    path = noise_clip(tmp_path / "n.mp4")
    with path.open("rb") as handle:
        attempt = client.post("/api/attempts", files={"file": ("n.mp4", handle, "video/mp4")}, data={"title": "Auto", "auto_analyze": "true"}).json()
    assert worker.process_one()
    state = client.get(f"/api/attempts/{attempt['id']}").json()
    assert state["status"] == "ready" and len(state["analyses"]) == 1
    assert state["analyses"][0]["status"] == "queued" and state["analyses"][0]["attempt_bounds_ms"] == {"start": 0, "end": state["duration_ms"]}


def test_without_the_flag_nothing_is_queued(env, tmp_path):
    _, client, worker = env
    attempt = upload(client, noise_clip(tmp_path / "n.mp4")).json()
    worker.process_one()
    assert client.get(f"/api/attempts/{attempt['id']}").json()["analyses"] == []


def test_failed_import_queues_no_analysis(env, tmp_path):
    _, client, worker = env
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    with bad.open("rb") as handle:
        attempt = client.post("/api/attempts", files={"file": ("bad.mp4", handle, "video/mp4")}, data={"auto_analyze": "true"}).json()
    worker.process_one()
    state = client.get(f"/api/attempts/{attempt['id']}").json()
    assert state["status"] == "failed" and state["analyses"] == []


def test_photo_ignores_auto_analyze(env, tmp_path):
    import cv2
    _, client, worker = env
    path = tmp_path / "wall.png"
    cv2.imwrite(str(path), np.full((200, 120, 3), 200, np.uint8))
    with path.open("rb") as handle:
        attempt = client.post("/api/attempts", files={"file": ("wall.png", handle, "image/png")}, data={"auto_analyze": "true"}).json()
    worker.process_one()
    assert client.get(f"/api/attempts/{attempt['id']}").json()["analyses"] == []
