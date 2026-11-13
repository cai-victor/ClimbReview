"""Synthetic hip tracks for the climb story: stops, joined stays, fast descents, gaps, and what coaching does with them."""
from __future__ import annotations

from app.analysis import coaching
from app.analysis.story import C, build_story, find_drop, find_stalls, hip_track

W, H, L = 720, 1280, 100.0          # one torso length is 100 px


def sample(t: int, y_px: float | None, x_px: float = 360.0) -> dict:
    """A 10 Hz overlay sample with both hips at the given picture position, or no hips at all."""
    if y_px is None:
        return {"t": t, "pose": False, "joints": {}}
    return {"t": t, "pose": True, "joints": {"left_hip": [(x_px - 10) / W, y_px / H], "right_hip": [(x_px + 10) / W, y_px / H]}}


def track_of(points: list[tuple[int, float | None]]):
    samples = [sample(t, y) for t, y in points]
    return samples, hip_track(samples, W, H, L, 0, points[-1][0])


def climb(segments: list[tuple[float, float, float]], start_y: float = 1000.0) -> list[tuple[int, float | None]]:
    """Segments of (seconds, torso lengths gained, 1 if tracked else 0). Height gained moves the hips up the picture."""
    points, t, y = [], 0, start_y
    for seconds, gain, tracked in segments:
        steps = int(seconds * 10)
        for k in range(steps):
            y -= gain * L / steps
            points.append((t, y if tracked else None))
            t += 100
    return points


def result(end: int) -> dict:
    return {"attempt_bounds_ms": {"start": 0, "end": end}}


def test_a_stay_in_one_place_is_a_stop_and_steady_progress_is_not():
    points = climb([(4, 2, 1), (6, 0, 1), (4, 2, 1)])
    _, track = track_of(points)
    stalls = find_stalls(track, points[-1][0])
    assert len(stalls) == 1
    assert 3200 <= stalls[0]["start_ms"] <= 4500 and 9500 <= stalls[0]["end_ms"] <= 10800
    _, moving = track_of(climb([(10, 5, 1)]))
    assert find_stalls(moving, 10_000) == []


def test_slow_drift_is_joined_into_one_stay_but_a_real_move_is_not():
    drift = climb([(2, 1, 1), (4, 0, 1), (1, 0.35, 1), (4, 0, 1), (2, 1, 1)])
    _, track = track_of(drift)
    stalls = find_stalls(track, drift[-1][0])
    assert len(stalls) == 1 and stalls[0]["end_ms"] - stalls[0]["start_ms"] >= 8000
    assert stalls[0]["spread_L"] <= C["area_spread_L"]
    moved = climb([(2, 1, 1), (4, 0, 1), (1, 1.5, 1), (4, 0, 1)])
    _, track = track_of(moved)
    assert len(find_stalls(track, moved[-1][0])) == 2


def test_a_stop_is_never_read_across_a_long_tracking_gap():
    points = climb([(2, 0, 1), (3, 0, 0), (2, 0, 1)])          # 2 s seen, 3 s unseen, 2 s seen, all at one height
    _, track = track_of(points)
    assert find_stalls(track, points[-1][0]) == []               # neither seen part is long enough alone
    assert len(set(track["run"][track["valid"]])) == 2


def test_fast_descent_ends_the_time_on_the_wall_and_slow_downclimb_does_not():
    fall = climb([(5, 3, 1), (4, 0, 1), (1, -2.5, 1), (3, 0, 1)])
    samples, track = track_of(fall)
    drop = find_drop(track)
    assert drop and 8000 <= drop["start_ms"] <= 9300 and drop["drop_L"] >= 2
    story = build_story(result(fall[-1][0]), [], samples, W, H, L)
    assert story["on_wall"]["ended_by"] == "fast_descent" and story["on_wall"]["end_ms"] == drop["start_ms"]
    assert story["phases"][-1]["kind"] == "off_wall"
    kinds = [item["kind"] for item in story["takeaways"]]
    assert "left_wall" in kinds
    left = next(item for item in story["takeaways"] if item["kind"] == "left_wall")
    assert "cannot tell a fall from a jump down" in left["verify"]
    assert not any(stop["end_ms"] > drop["start_ms"] for stop in story["stops"])      # standing on the mat afterwards is not a stop on the wall
    _, slow = track_of(climb([(5, 3, 1), (6, -2.5, 1)]))
    assert find_drop(slow) is None


def test_too_little_hip_tracking_gives_no_story():
    points = climb([(3, 1, 1), (7, 1, 0)])
    samples, _ = track_of(points)
    story = build_story(result(points[-1][0]), [], samples, W, H, L)
    assert story["available"] is False and "30%" in story["reason"]
    assert build_story(result(1000), [], samples, W, H, None)["available"] is False


def foot(start: int, size: float, side: str = "left") -> dict:
    return {"id": f"f{start}", "type": "foot_motion", "hand": side, "start_ms": start, "end_ms": start + 400, "evidence": {"max_displacement_L": size, "net_displacement_L": size}}


def test_long_stay_takeaway_reads_the_limb_pattern_without_claiming_contact():
    points = climb([(3, 2, 1), (12, 0, 1), (3, 2, 1)])
    samples, _ = track_of(points)
    events = [foot(4000, 0.3), foot(6000, 0.25, "right"), foot(8000, 0.3), foot(11000, 0.2, "right")]
    story = build_story(result(points[-1][0]), events, samples, W, H, L)
    stay = next(item for item in story["takeaways"] if item["kind"] == "longest_stop")
    assert stay["pattern"] == "feet_busy" and "4 foot movements and 0 hand movements" in stay["observed"]
    small = next(item for item in story["takeaways"] if item["kind"] == "small_foot_moves")
    assert small["title"].startswith("4 of 4")
    text = " ".join(f"{i['title']} {i['observed']} {i['try_this']} {i['why']}" for i in story["takeaways"]).lower()
    for word in ("score", "fatigue", "injur", "optimal", "center of mass", "slipped", "weak"):
        assert word not in text
    quiet = build_story(result(points[-1][0]), [], samples, W, H, L)
    assert next(item for item in quiet["takeaways"] if item["kind"] == "longest_stop")["pattern"] == "still"


def test_story_is_deterministic_and_stats_add_up():
    points = climb([(3, 2, 1), (5, 0, 1), (3, 2, 1)])
    samples, _ = track_of(points)
    first, second = build_story(result(points[-1][0]), [], samples, W, H, L), build_story(result(points[-1][0]), [], samples, W, H, L)
    assert first == second
    stats = first["stats"]
    assert stats["moving_ms"] + stats["stopped_ms"] == stats["on_wall_ms"]
    assert abs(stats["height_gained_L"] - 4) < 0.3
    assert first["profile"][0]["h"] <= 0.1 and abs(first["profile"][-1]["h"] - 4) < 0.3


def test_story_cards_lead_the_list_and_keep_the_card_shape():
    points = climb([(3, 2, 1), (12, 0, 1), (3, 2, 1)])
    samples, _ = track_of(points)
    story = build_story(result(points[-1][0]), [], samples, W, H, L)
    cards = coaching._story_cards(story)
    assert cards and all(card["scope"] == "attempt" and card["status_label"] == "Whole attempt" for card in cards)
    for key in ("id", "title", "moment", "why", "try_this", "keep_if", "measurements", "uncertainty", "alternatives", "limbs"):
        assert key in cards[0]
    moment = {"id": "m1", "kind": "large_step"}
    assert coaching.top_card_ids([*cards, moment])[0] == cards[0]["id"]


def standing(t: int, hip_y: float, ankle_y: float, other_ankle: float | None = None) -> dict:
    """A sample with hips and ankles: one leg straight down to `ankle_y`."""
    joints = {"left_hip": [350 / W, hip_y / H], "right_hip": [370 / W, hip_y / H], "left_ankle": [350 / W, ankle_y / H]}
    if other_ankle is not None:
        joints["right_ankle"] = [370 / W, other_ankle / H]
    return {"t": t, "pose": True, "joints": joints}


def test_standing_on_the_ground_before_pulling_on_is_not_counted_as_climbing():
    from app.analysis.story import find_lift_off
    samples = [standing(t, 900, 1100, 1100) for t in range(0, 6000, 100)]                       # 6 s standing: legs 200 px tall
    samples += [standing(6000 + k * 100, 900 - k * 5, 1000 - k * 5, 980 - k * 5) for k in range(100)]   # then climbing with bent legs, feet off the ground
    ground = find_lift_off(samples, H, L, 0, 16_000)
    assert ground and 5500 <= ground["end_ms"] <= 6100
    story = build_story(result(15_900), [], samples, W, H, L)
    assert story["on_wall"]["started_by"] == "left_the_ground" and story["on_wall"]["start_ms"] == ground["end_ms"]
    assert story["phases"][0]["kind"] == "before_start"
    assert not any(stop["start_ms"] < ground["end_ms"] for stop in story["stops"])               # standing still is not a stop on the wall
    assert "ground or your first foothold" in story["headline"]
    # A clip that begins with the climber already above the lowest foot level has no ground phase.
    already = [standing(k * 100, 900 - k * 5, 1000 - k * 5, 980 - k * 5) for k in range(100)]
    already += [standing(10_000 + k * 100, 1000, 1200, 1200) for k in range(20)]                # lands and stands at the end only
    assert find_lift_off(already, H, L, 0, 12_000) is None


def test_lowering_into_a_sit_start_is_not_leaving_the_wall():
    points = climb([(1, 0, 1), (1, -1.8, 1), (4, 0, 1), (20, 3, 1)])          # goes down early, then climbs for 20 s
    samples, _ = track_of(points)
    story = build_story(result(points[-1][0]), [], samples, W, H, L)
    assert story["on_wall"]["started_by"] == "lowered_into_start" and story["on_wall"]["ended_by"] == "end_of_clip"
    assert not any(item["kind"] == "left_wall" for item in story["takeaways"])
    assert 1500 <= story["on_wall"]["start_ms"] <= 3000


def test_a_steady_climb_gets_a_reference_card_and_a_stop_or_a_fall_does_not():
    steady, _ = track_of(climb([(15, 6, 1)]))
    kinds = lambda story: [item["kind"] for item in story["takeaways"]]
    assert kinds(build_story(result(14_900), [], steady, W, H, L)) == ["steady"]
    stopped, _ = track_of(climb([(4, 2, 1), (10, 0, 1), (4, 2, 1)]))
    assert "steady" not in kinds(build_story(result(17_900), [], stopped, W, H, L))
    fell, _ = track_of(climb([(12, 5, 1), (1, -3, 1), (2, 0, 1)]))
    assert "steady" not in kinds(build_story(result(14_900), [], fell, W, H, L))
