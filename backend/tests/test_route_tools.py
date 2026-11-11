"""Hold suggestions, photo import, scale, and planning from entered measurements. All images here are synthetic."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis import beta, hold_suggest as hs
from app.main import create_app
from app.settings import Settings, load_pipeline_config
from app.worker import Worker

BLUE, RED, WALL = (200, 120, 30), (40, 40, 210), (225, 228, 230)       # BGR
SPOTS = [(100, 500), (140, 380), (90, 260), (150, 140)]


def wall(width=240, height=600, spots=SPOTS, color=BLUE):
    image = np.full((height, width, 3), WALL, np.uint8)
    for x, y in spots:
        cv2.circle(image, (x, y), 9, color, -1)
    cv2.circle(image, (200, 300), 9, RED, -1)
    return image


def tap(image, spot):
    return spot[0] / image.shape[1], spot[1] / image.shape[0]


def test_same_color_holds_are_suggested_and_other_colors_are_not():
    image = wall()
    found = hs.suggest(image, *tap(image, SPOTS[0]))["suggestions"]
    assert len(found) == 4
    centers = sorted((round(s["x"] * 240), round(s["y"] * 600)) for s in found)
    assert centers == sorted(SPOTS)                     # x and y are scaled separately, so the tall image keeps its shape
    assert all(s["radius"] == pytest.approx(9 / 240, abs=0.02) for s in found)


def test_existing_marks_are_not_suggested_again():
    image = wall()
    marked = [{"x": SPOTS[1][0] / 240, "y": SPOTS[1][1] / 600, "radius": 0.05}]
    assert len(hs.suggest(image, *tap(image, SPOTS[0]), existing=marked)["suggestions"]) == 3


def test_tapping_the_wall_is_refused_instead_of_marking_everything():
    image = wall()
    with pytest.raises(hs.SuggestionError, match="looks like wall"):
        hs.suggest(image, 0.5, 0.05)


def test_specks_are_ignored_and_tolerance_widens_the_match():
    image = wall()
    cv2.circle(image, (60, 60), 1, BLUE, -1)                                   # a speck
    cv2.circle(image, (200, 500), 9, (175, 128, 58), -1)                        # a duller blue
    strict = hs.suggest(image, *tap(image, SPOTS[0]), tolerance="strict")["suggestions"]
    loose = hs.suggest(image, *tap(image, SPOTS[0]), tolerance="loose")["suggestions"]
    assert len(strict) == 4 and len(loose) == 5


def test_result_says_it_is_not_confirmation():
    image = wall()
    assert "not confirmed holds" in hs.suggest(image, *tap(image, SPOTS[0]))["note"]


def textured(seed=2):
    rng = np.random.default_rng(seed)
    image = np.full((568, 320, 3), 200, np.uint8)
    for _ in range(700):
        cv2.circle(image, (int(rng.integers(0, 320)), int(rng.integers(0, 568))), int(rng.integers(2, 5)), tuple(int(v) for v in rng.integers(0, 255, 3)), -1)
    return image


def test_clean_wall_removes_a_moving_climber():
    base = textured()
    frames = []
    for i in range(9):
        frame = base.copy()
        cv2.rectangle(frame, (20 + i * 30, 200), (60 + i * 30, 320), (0, 255, 0), -1)
        frames.append(frame)
    image, info = hs.clean_wall(frames[0], frames)
    assert info["basis"] == "clean_wall_median" and info["frames_used"] >= 5
    assert np.abs(image[260, 40].astype(int) - base[260, 40].astype(int)).max() < 12        # where the climber stood in the reference


def test_clean_wall_falls_back_when_frames_show_a_different_view():
    base = textured()
    other = [textured(seed=50 + i) for i in range(9)]                       # nothing in common with the reference
    image, info = hs.clean_wall(base, other)
    assert info["basis"] == "reference_frame" and np.array_equal(image, base)


def test_small_camera_shift_is_lined_up_before_combining():
    base = textured()
    reference = base.copy()
    cv2.rectangle(reference, (140, 240), (180, 330), (0, 255, 0), -1)        # the climber hides this part of the reference
    frames = []
    for i in range(9):
        moved = cv2.warpAffine(base, np.float32([[1, 0, 12 + i], [0, 1, -8]]), (320, 568), borderMode=cv2.BORDER_CONSTANT)
        cv2.rectangle(moved, (20 + i * 5, 400), (50 + i * 5, 470), (0, 255, 0), -1)
        frames.append(moved)
    image, info = hs.clean_wall(reference, frames)
    assert info["frames_realigned"] >= 5 and "shifted to line up" in info["detail"]
    for y, x in ((285, 160), (100, 60), (500, 250)):                         # behind the reference climber and elsewhere
        assert np.abs(image[y, x].astype(int) - base[y, x].astype(int)).max() < 30, (y, x)


def test_rotation_and_zoom_between_frames_are_corrected():
    base = textured()
    frames = [cv2.warpAffine(base, cv2.getRotationMatrix2D((160, 284), 0.6 + 0.1 * i, 1.01), (320, 568), borderMode=cv2.BORDER_CONSTANT) for i in range(8)]
    image, info = hs.clean_wall(base, frames)
    assert info["frames_realigned"] >= 5
    assert np.abs(image[200:400:40, 100:250:30].astype(int) - base[200:400:40, 100:250:30].astype(int)).mean() < 14


# ---- measurements and scale

def test_reach_lengths_scale_with_height_and_wingspan():
    short, tall = beta.body_from_measurements(160, 160), beta.body_from_measurements(190, 190)
    assert short.torso_cm == pytest.approx(46.1, abs=0.1) and short.leg_cm == pytest.approx(78.6, abs=0.1) and short.arm_cm == pytest.approx(54.2, abs=0.1)
    assert tall.body.leg_L == pytest.approx(short.body.leg_L)            # same proportions in torso units
    long_arms = beta.body_from_measurements(170, 185)
    assert long_arms.body.arm_L > beta.body_from_measurements(170, 170).body.arm_L


def test_scale_uses_pixel_distance_so_aspect_ratio_is_kept():
    horizontal = beta.torso_px({"x1": 0.25, "y1": 0.5, "x2": 0.75, "y2": 0.5, "cm": 100}, 720, 1280, 50)
    vertical = beta.torso_px({"x1": 0.5, "y1": 0.25, "x2": 0.5, "y2": 0.75, "cm": 100}, 720, 1280, 50)
    assert horizontal == pytest.approx(180) and vertical == pytest.approx(320)


def test_a_longer_reach_can_make_a_route_plannable():
    holds = [{"id": str(i), "x": x, "y": y, "radius": 0.03, "role": role, "use": use} for i, (x, y, role, use) in enumerate([
        (0.45, 0.70, "start", "hand"), (0.55, 0.70, "start", "hand"), (0.5, 0.86, "", "foot"), (0.5, 0.78, "", "foot"), (0.5, 0.55, "", "hand"),
        (0.5, 0.40, "finish", "hand")])]
    scale = {"x1": 0.5, "y1": 0.2, "x2": 0.5, "y2": 0.8, "cm": 300}        # the 1000 px picture shows 5 m of wall
    results = {}
    for name, (height, span) in {"short": (150, 140), "tall": (195, 205)}.items():
        measured = beta.body_from_measurements(height, span)
        results[name] = beta.candidate_sequences(holds, 600, 1000, beta.torso_px(scale, 600, 1000, measured.torso_cm), measured.body)["status"]
    assert results == {"short": "no_candidate", "tall": "ready"}


# ---- photo import through the real API and worker

@pytest.fixture()
def env(tmp_path):
    settings = Settings(tmp_path / "appdata")
    return settings, TestClient(create_app(settings)), Worker(settings, load_pipeline_config())


def photo_attempt(env, tmp_path, name="wall.png"):
    _, client, worker = env
    path = tmp_path / name
    cv2.imwrite(str(path), wall(width=241, height=601))                    # odd size on purpose
    with path.open("rb") as handle:
        created = client.post("/api/attempts", files={"file": (name, handle, "image/png")}, data={"title": "Synthetic wall"})
    assert created.status_code == 201 and created.json()["kind"] == "photo"
    assert worker.process_one()
    return client.get(f"/api/attempts/{created.json()['id']}").json()


def test_photo_becomes_a_markable_still_and_cannot_be_analyzed(env, tmp_path):
    _, client, _ = env
    attempt = photo_attempt(env, tmp_path)
    assert attempt["status"] == "ready" and (attempt["width"], attempt["height"]) == (240, 600) and attempt["duration_ms"] == 1000
    assert client.post(f"/api/attempts/{attempt['id']}/analyses").status_code == 409
    frame = client.get(f"/api/attempts/{attempt['id']}/frame?ms=0")
    assert frame.status_code == 200
    decoded = cv2.imdecode(np.frombuffer(frame.content, np.uint8), cv2.IMREAD_COLOR)
    blue = decoded[SPOTS[0][1], SPOTS[0][0]].astype(int)
    assert blue[0] > 150 and blue[2] < 90                                   # the blue hold is where it was in the photo


def test_text_file_named_as_photo_fails_with_a_message(env, tmp_path):
    _, client, worker = env
    bad = tmp_path / "bad.jpg"
    bad.write_text("not an image")
    with bad.open("rb") as handle:
        created = client.post("/api/attempts", files={"file": ("bad.jpg", handle, "image/jpeg")}).json()
    worker.process_one()
    state = client.get(f"/api/attempts/{created['id']}").json()
    assert state["status"] == "failed" and "photo could not be read" in state["error"]


def test_suggest_confirm_scale_and_plan_on_a_photo(env, tmp_path):
    _, client, _ = env
    attempt = photo_attempt(env, tmp_path)
    hold_map = client.post(f"/api/attempts/{attempt['id']}/hold-maps", json={"name": "Blue", "reference_frame_ms": 0}).json()
    mid = hold_map["id"]
    assert hold_map["scale"] is None
    result = client.post(f"/api/hold-maps/{mid}/suggestions", json={"x": SPOTS[0][0] / 240, "y": SPOTS[0][1] / 600}).json()
    assert len(result["suggestions"]) == 4 and result["image"]["basis"] == "reference_frame"
    assert client.get(f"/api/hold-maps/{mid}").json()["holds"] == []                       # nothing is added until the user confirms
    assert client.post(f"/api/hold-maps/{mid}/suggestions", json={"x": 0.5, "y": 0.05}).status_code == 422

    roles = {0: ("start", "both"), 1: ("", "both"), 2: ("", "both"), 3: ("finish", "hand")}
    for index, item in enumerate(result["suggestions"]):                                   # sorted bottom first
        role, use = roles[index]
        client.post(f"/api/hold-maps/{mid}/holds", json={"x": item["x"], "y": item["y"], "radius": item["radius"], "route": "", "hold_type": "", "role": role, "use": use})
    assert client.post(f"/api/hold-maps/{mid}/suggestions", json={"x": SPOTS[0][0] / 240, "y": SPOTS[0][1] / 600}).json()["suggestions"] == []
    client.post(f"/api/hold-maps/{mid}/holds", json={"x": 0.45, "y": 0.95, "radius": 0.03, "route": "", "hold_type": "", "role": "", "use": "foot"})   # added by hand

    plan = client.get(f"/api/hold-maps/{mid}/plan?height_cm=170&wingspan_cm=172").json()
    assert plan["status"] == "setup_needed" and any("scale" in need for need in plan["needs"])
    assert client.put(f"/api/hold-maps/{mid}/scale", json={"x1": 0.5, "y1": 0.5, "x2": 0.51, "y2": 0.5, "cm": 50}).status_code == 422
    assert client.put(f"/api/hold-maps/{mid}/scale", json={"x1": 0.5, "y1": 0.1, "x2": 0.5, "y2": 0.9, "cm": 240}).status_code == 200
    plan = client.get(f"/api/hold-maps/{mid}/plan?height_cm=170&wingspan_cm=172").json()
    assert plan["status"] == "ready" and plan["body"]["arm_cm"] == pytest.approx(58.3, abs=0.1)
    assert any("average body proportions" in a for a in plan["assumptions"]) and not any("tracked limb" in a for a in plan["assumptions"])
    assert plan["candidates"][0]["steps"][-1]["limb"].endswith("hand")
    assert client.get(f"/api/hold-maps/{mid}/plan?height_cm=40&wingspan_cm=172").status_code == 422
    assert client.get(f"/api/hold-maps/{mid}").json()["scale"]["cm"] == 240


# ---- combined wall picture

def parked_climber_frames(base, count=12, parked=9):
    """A green block stays at one place for most frames, then moves away."""
    frames, masks = [], []
    for i in range(count):
        x = 100 if i < parked else 220
        frame = base.copy()
        cv2.rectangle(frame, (x, 200), (x + 40, 320), (0, 255, 0), -1)
        mask = np.zeros(base.shape[:2], bool)
        mask[190:330, x - 10:x + 50] = True
        frames.append(frame)
        masks.append(mask)
    return frames, masks


def test_tracked_masks_remove_a_climber_who_stays_in_one_place():
    base = textured()
    frames, masks = parked_climber_frames(base)
    plain, plain_info = hs.clean_wall(frames[0], frames)
    assert plain_info["basis"] == "clean_wall_median" and plain[260, 120].tolist() == [0, 255, 0]          # the plain median keeps the ghost
    image, info = hs.clean_wall(frames[0], frames, masks)
    assert info["basis"] == "clean_wall_pose_masked" and info["never_clear_fraction"] == 0
    assert np.abs(image[260, 120].astype(int) - base[260, 120].astype(int)).max() < 12


def test_region_never_clear_is_reported_not_hidden():
    base = textured()
    frames, masks = parked_climber_frames(base, parked=12)                   # never moves away
    _, info = hs.clean_wall(frames[0], frames, masks)
    assert info["never_clear_fraction"] > 0.03 and "never clear of the climber" in info["detail"]


def test_frame_without_a_tracked_body_is_used_whole():
    assert hs.climber_mask((100, 100), {}) is None
    mask = hs.climber_mask((100, 100), {"nose": [0.5, 0.4], "left_ankle": [0.55, 0.7]})
    assert mask[50, 52] and not mask[5, 5]


def test_photo_wall_picture_is_the_photo_itself(env, tmp_path):
    _, client, _ = env
    attempt = photo_attempt(env, tmp_path)
    mid = client.post(f"/api/attempts/{attempt['id']}/hold-maps", json={"name": "Blue", "reference_frame_ms": 0}).json()["id"]
    info = client.get(f"/api/hold-maps/{mid}/wall-info").json()
    assert info["combined"] is False and info["basis"] == "reference_frame"
    assert client.get(f"/api/hold-maps/{mid}/wall-image").headers["content-type"] == "image/png"
