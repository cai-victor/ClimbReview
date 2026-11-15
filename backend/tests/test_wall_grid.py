"""Wall-plane recovery from a bolt grid. Every picture here is drawn from a known camera, so the truth is exact."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.analysis import beta, wall_grid as wg

W, H, FOCAL = 720, 1280, 1000.0


def camera(pitch_deg=0.0, yaw_deg=0.0, roll_deg=0.0, spacing=0.15, distance=4.0, offset=(0.0, 0.0)):
    """Homography from grid steps to pixels for a wall seen by a pinhole camera. Positive pitch leans the top toward the camera."""
    rx, ry, rz = np.radians([pitch_deg, yaw_deg, roll_deg])
    rot_x = np.array([[1, 0, 0], [0, np.cos(rx), -np.sin(rx)], [0, np.sin(rx), np.cos(rx)]])
    rot_y = np.array([[np.cos(ry), 0, np.sin(ry)], [0, 1, 0], [-np.sin(ry), 0, np.cos(ry)]])
    rot_z = np.array([[np.cos(rz), -np.sin(rz), 0], [np.sin(rz), np.cos(rz), 0], [0, 0, 1]])
    rotation = rot_x @ rot_y @ rot_z
    k = np.array([[FOCAL, 0, W / 2], [0, FOCAL, H / 2], [0, 0, 1]])
    return k @ np.column_stack([rotation[:, 0] * spacing, rotation[:, 1] * spacing, [offset[0], offset[1], distance]])


def project(matrix, lattice):
    return cv2.perspectiveTransform(np.asarray(lattice, np.float64).reshape(-1, 1, 2), matrix).reshape(-1, 2)


def draw(matrix, extent=22, clutter=0, seed=1, skip=0.0, extra=None):
    rng = np.random.default_rng(seed)
    image = np.full((H, W, 3), 215, np.uint8)
    for i in range(-extent, extent + 1):
        for j in range(-extent, extent + 1):
            if rng.random() < skip:
                continue
            x, y = project(matrix, [[i, j]])[0]
            if 5 < x < W - 5 and 5 < y < H - 5:
                cv2.circle(image, (int(round(x)), int(round(y))), 2, (25, 25, 25), -1, cv2.LINE_AA)
    for _ in range(clutter):
        cv2.circle(image, (int(rng.integers(5, W - 5)), int(rng.integers(5, H - 5))), 2, (25, 25, 25), -1, cv2.LINE_AA)
    for item in extra or []:
        item(image)
    return image


def fit(image, focus=None):
    return wg.fit_image(image, W, H, focus)


def plane_distance(plane, a, b):
    points = plane.plane([a, b])
    return float(np.linalg.norm(points[1] - points[0]))


def test_tilted_wall_distances_are_recovered_where_the_picture_distorts_them():
    truth = camera(pitch_deg=-25)                            # the top of the wall leans away, as when filming from below
    result = fit(draw(truth))
    assert result["status"] == "ok" and result["inliers"] >= 100
    plane = wg.WallPlane(result, W, H)
    low, high = project(truth, [[0, 6], [0, 10]]), project(truth, [[0, -10], [0, -6]])       # both are 4 grid steps long
    in_picture = np.linalg.norm(low[1] - low[0]) / np.linalg.norm(high[1] - high[0])
    on_wall = plane_distance(plane, *low) / plane_distance(plane, *high)
    assert in_picture > 1.25                                 # the picture makes the far, upper segment look much shorter
    assert on_wall == pytest.approx(1.0, abs=0.03)


@pytest.mark.parametrize("pitch,yaw", [(25, 0), (-20, 0), (0, 30), (18, -22)])
def test_tilt_matches_the_known_camera(pitch, yaw):
    plane = wg.WallPlane(fit(draw(camera(pitch_deg=pitch, yaw_deg=yaw))), W, H)
    tilt = plane.tilt()
    expected = np.degrees(np.arccos(np.cos(np.radians(pitch)) * np.cos(np.radians(yaw))))
    assert tilt["status"] == "ok" and tilt["angle_to_camera_deg"] == pytest.approx(expected, abs=3)
    assert "not to gravity" in tilt["note"]
    if yaw == 0:
        assert np.sign(tilt["top_toward_camera_deg"]) == np.sign(pitch)


def test_wall_facing_the_camera_reports_no_angle_and_needs_no_correction():
    plane = wg.WallPlane(fit(draw(camera())), W, H)
    assert plane.tilt()["status"] == "unknown"
    assert plane.local_scale([360, 200]) == pytest.approx(plane.local_scale([360, 1100]), rel=0.02)


def test_diagonal_grid_missing_holes_and_clutter_are_tolerated():
    truth = camera(pitch_deg=20, roll_deg=45)
    result = fit(draw(truth, clutter=150, skip=0.25))
    assert result["status"] == "ok"
    plane = wg.WallPlane(result, W, H)
    a, b = project(truth, [[0, 0], [5, 0]]), project(truth, [[0, 8], [5, 8]])
    assert plane_distance(plane, *a) / plane_distance(plane, *b) == pytest.approx(1.0, abs=0.04)


def test_random_dots_and_blank_walls_are_refused():
    rng = np.random.default_rng(4)
    scattered = np.full((H, W, 3), 215, np.uint8)
    for _ in range(600):
        cv2.circle(scattered, (int(rng.integers(5, W - 5)), int(rng.integers(5, H - 5))), 2, (25, 25, 25), -1)
    assert fit(scattered)["status"] == "not_found"
    assert fit(np.full((H, W, 3), 215, np.uint8))["status"] == "not_found"


def two_faces():
    """Left half and right half are different planes, each with its own grid."""
    left, right = camera(pitch_deg=10, yaw_deg=-35, offset=(-0.9, 0)), camera(pitch_deg=-15, yaw_deg=40, spacing=0.11, offset=(0.9, 0))
    image = np.full((H, W, 3), 215, np.uint8)
    for matrix, keep in ((left, lambda x: x < W / 2 - 6), (right, lambda x: x > W / 2 + 6)):
        for i in range(-30, 31):
            for j in range(-30, 31):
                x, y = project(matrix, [[i, j]])[0]
                if 5 < x < W - 5 and 5 < y < H - 5 and keep(x):
                    cv2.circle(image, (int(round(x)), int(round(y))), 2, (25, 25, 25), -1, cv2.LINE_AA)
    return image


def test_holds_on_another_wall_face_are_not_treated_as_covered():
    result = fit(two_faces(), focus=(180, 640))
    assert result["status"] == "ok"
    plane = wg.WallPlane(result, W, H)
    assert plane.covers((180, 640)) and plane.covers((200, 300))
    assert not plane.covers((600, 640))


def hold(x, y):
    return {"x": x / W, "y": y / H, "radius": 0.03}


def test_correction_is_withheld_when_the_route_crosses_faces():
    result = fit(two_faces(), focus=(180, 640))
    plane, summary = wg.correction_for(result, [hold(150, 400), hold(200, 800), hold(560, 500), hold(600, 900)], W, H)
    assert plane is None and summary["applied"] is False and "Only 2 of 4 holds" in summary["reason"]
    plane, summary = wg.correction_for(result, [hold(150, 400), hold(200, 800), hold(120, 1000)], W, H)
    assert plane is not None and summary["applied"] and "square grid" in summary["assumption"]


def test_failed_fit_gives_no_plane_and_a_reason():
    plane, summary = wg.correction_for(fit(np.full((H, W, 3), 215, np.uint8)), [hold(100, 100)], W, H)
    assert plane is None and summary["applied"] is False and "Too few bolt holes" in summary["reason"]


def test_planner_reaches_differ_once_measured_on_the_wall():
    truth = camera(pitch_deg=-30)                           # the top leans away, so the picture shrinks the upper holds
    plane = wg.WallPlane(fit(draw(truth)), W, H)
    lattice = [[-1, 9], [1, 9], [0, 12], [0, 4], [0, -1], [0, -6], [1, 8], [-1, 3]]         # the last two are footholds between the hand holds
    pixels = project(truth, lattice)
    holds = [{"id": str(i), "x": p[0] / W, "y": p[1] / H, "radius": 0.02, "role": r, "use": u} for i, (p, (r, u)) in enumerate(zip(pixels, [
        ("start", "hand"), ("start", "hand"), ("", "foot"), ("", "both"), ("", "both"), ("finish", "hand"), ("", "foot"), ("", "foot")]))]
    torso_steps = 3.3                                                        # the climber's torso spans 3.3 grid steps
    on_wall = plane.plane(pixels) / torso_steps
    gaps = np.linalg.norm(np.diff(on_wall[[0, 3, 4, 5]], axis=0), axis=1)
    assert gaps == pytest.approx(np.array([np.hypot(1, 5), 5, 5]) / torso_steps, rel=0.04)     # true spacing, despite the tilt
    body = beta.Body(1.05, 1.75, 100, 100)
    torso_px_low = torso_steps / plane.local_scale(pixels[2])               # what a picture-based scale near the feet would use
    flat = beta.candidate_sequences(holds, W, H, torso_px_low, body)
    corrected = beta.candidate_sequences(holds, W, H, torso_px_low, body, on_wall, beta.plane_to_image(plane, torso_steps, W, H))
    assert flat["status"] == "ready" and corrected["status"] == "ready"
    flat_points = beta.hold_points(holds, W, H, torso_px_low)
    top_flat = float(np.linalg.norm(flat_points[5] - flat_points[4]))
    assert gaps[2] > 1.15 * top_flat                                        # the picture understated the last reach
    figure = corrected["candidates"][0]["figures"][0]                        # the stick figure is drawn back in picture coordinates
    assert figure["left_hand"] == pytest.approx([holds[0]["x"], holds[0]["y"]], abs=0.002) and figure["neck"][1] > figure["left_hand"][1]


def test_dense_speckle_does_not_stall_the_fit():
    """A speckled floor once made the step estimate take minutes. Thousands of stray dots must stay fast."""
    import time
    rng = np.random.default_rng(9)
    speckle = np.column_stack([rng.uniform(0, W, 4000), rng.uniform(900, H, 4000)])
    grid = project(camera(pitch_deg=-15), [[i, j] for i in range(-20, 21) for j in range(-20, 4)])
    grid = grid[(grid[:, 0] > 5) & (grid[:, 0] < W - 5) & (grid[:, 1] > 5) & (grid[:, 1] < 880)]
    points = np.vstack([grid, speckle])
    began = time.perf_counter()
    in_speckle = wg.fit_grid(points, W, H, focus=(360, 1100))
    on_wall = wg.fit_grid(points, W, H, focus=(360, 400))
    assert time.perf_counter() - began < 5
    assert in_speckle["status"] == "not_found" and on_wall["status"] == "ok"


def test_the_grid_is_found_under_wall_speckle_and_the_setting_used_is_reported():
    truth = camera(pitch_deg=-20)
    image = draw(truth)
    rng = np.random.default_rng(3)
    for x, y in zip(rng.integers(4, W - 4, 2500), rng.integers(4, H - 4, 2500)):
        cv2.circle(image, (int(x), int(y)), 2, (178, 178, 178), -1)          # faint dots, far lighter than a bolt hole
    result = wg.fit_image(image, W, H)
    assert result["status"] == "ok" and result["inliers"] >= wg.MIN_INLIERS and result["method"] == "bolt-grid-v2" and result["detection"]
    strict, loose = wg.detect_bolts(image, 0.3), wg.detect_bolts(image, 0.1)
    assert len(loose) > len(strict) >= wg.MIN_INLIERS                          # a lower share lets the faint dots in


def test_a_blank_wall_still_gives_no_fit_under_every_setting():
    result = wg.fit_image(np.full((H, W, 3), 215, np.uint8), W, H)
    assert result["status"] == "not_found" and "Too few bolt holes" in result["reason"]
