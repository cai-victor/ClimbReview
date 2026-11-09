"""Reach geometry and candidate move sequences on user-marked holds.

This is a 2D planning aid. Margins say how much slack a simple stick figure scaled to
this climber would have in the picture plane. Wall angle, hold quality, friction,
balance, and body rotation are not modeled, so a candidate is something to try on the
wall. It is never the best or easiest beta.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

BETA_VERSION = "candidate-beta-v1"
MIN_BODY_SAMPLES = 30
LIMBS = ("left_hand", "right_hand", "left_foot", "right_foot")
HAND_USES = {"", "hand", "both"}
FOOT_USES = {"", "foot", "both"}
TORSO_ANGLES = np.radians([-40, -20, 0, 20, 40])
COMFORT_MARGIN_L = 0.3            # moves with less 2D slack than this are called tight
MIN_FEASIBLE_MARGIN_L = 0.0
OFF_WALL = -1                     # a foot not yet on any marked hold, for problems that start from the ground
MAX_STATES = 30000
MAX_MOVES = 14
ASSUMPTIONS = [
    "Distances are in the picture plane. Wall angle and depth are not known.",
    "Hold shape, size, friction, and pull direction are not known.",
    "Balance, body rotation, flagging, and dynamic moves are not modeled.",
    "Reach lengths come from this climber's tracked limb lengths in this video.",
    "A foot higher than both hands is never proposed, although a heel hook could use one.",
]


@dataclass(frozen=True)
class Body:
    """Limb lengths in torso lengths, from this attempt's own tracked poses."""
    arm_L: float
    leg_L: float
    arm_samples: int
    leg_samples: int

    def public(self) -> dict[str, Any]:
        return {"arm_L": round(self.arm_L, 3), "leg_L": round(self.leg_L, 3), "arm_samples": self.arm_samples, "leg_samples": self.leg_samples,
                "method": "95th percentile of tracked shoulder-elbow-wrist and hip-knee-ankle lengths in the picture"}


def _segment_sum(joints: dict[str, Sequence[float]], names: Sequence[str], width: int, height: int) -> float | None:
    if any(name not in joints for name in names):
        return None
    points = [np.array([joints[name][0] * width, joints[name][1] * height]) for name in names]
    return float(sum(np.linalg.norm(b - a) for a, b in zip(points, points[1:])))


def body_model(samples: Sequence[dict[str, Any]], width: int, height: int, length_px: float | None) -> Body | None:
    """None when too few samples show the limbs for a length to mean anything."""
    if not length_px:
        return None
    arms, legs = [], []
    for sample in samples:
        for side in ("left", "right"):
            arm = _segment_sum(sample["joints"], (f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist"), width, height)
            leg = _segment_sum(sample["joints"], (f"{side}_hip", f"{side}_knee", f"{side}_ankle"), width, height)
            if arm is not None:
                arms.append(arm)
            if leg is not None:
                legs.append(leg)
    if len(arms) < MIN_BODY_SAMPLES or len(legs) < MIN_BODY_SAMPLES:
        return None
    return Body(float(np.percentile(arms, 95)) / length_px, float(np.percentile(legs, 95)) / length_px, len(arms), len(legs))


def _grid(center: np.ndarray, half: float, step: float) -> np.ndarray:
    axis = np.arange(-half, half + step / 2, step)
    return np.stack(np.meshgrid(center[0] + axis, center[1] + axis), -1).reshape(-1, 2)


def _best_slack(cores: np.ndarray, hands: np.ndarray, feet: np.ndarray, body: Body) -> tuple[float, np.ndarray]:
    """Largest worst-limb slack over torso centers and leans. y grows downward, as in images."""
    best, where = -np.inf, cores[0]
    for angle in TORSO_ANGLES:
        up = np.array([np.sin(angle), -np.cos(angle)]) * 0.5
        shoulders, hips = cores + up, cores - up
        slack = np.full(len(cores), np.inf)
        if len(hands):
            slack = np.minimum(slack, body.arm_L - np.linalg.norm(shoulders[:, None] - hands[None], axis=2).max(axis=1))
        if len(feet):
            slack = np.minimum(slack, body.leg_L - np.linalg.norm(hips[:, None] - feet[None], axis=2).max(axis=1))
        index = int(np.argmax(slack))
        if slack[index] > best:
            best, where = float(slack[index]), cores[index]
    return best, where


def reach_margin(hands: Sequence[Sequence[float]], feet: Sequence[Sequence[float]], body: Body, refine: bool = True) -> float:
    """2D slack in torso lengths for the given contacts, in torso-length coordinates. Negative means out of reach."""
    hand_points = np.asarray(hands, float).reshape(-1, 2)
    foot_points = np.asarray(feet, float).reshape(-1, 2)
    center = np.vstack([hand_points, foot_points]).mean(axis=0)
    best, where = _best_slack(_grid(center, 2.5, 0.25), hand_points, foot_points, body)
    if refine:
        best, _ = _best_slack(_grid(where, 0.3, 0.05), hand_points, foot_points, body)
    return best


def hold_points(holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float) -> np.ndarray:
    return np.array([[h["x"] * width / length_px, h["y"] * height / length_px] for h in holds], float)


def setup_needed(holds: Sequence[dict[str, Any]]) -> list[str]:
    """What the climber still has to mark before any sequence can be proposed."""
    needs: list[str] = []
    if not any(h.get("role") == "start" and h.get("use", "") in HAND_USES for h in holds):
        needs.append("Mark at least one start hold for the hands.")
    if not any(h.get("role") == "finish" and h.get("use", "") in HAND_USES for h in holds):
        needs.append("Mark the finish hold.")
    if not any(h.get("use", "") in FOOT_USES and h.get("role") != "finish" for h in holds):
        needs.append("Mark at least one hold your feet could use.")
    return needs


PROFILES = {
    "fewer_moves": {"label": "Fewer moves", "move": 2.0, "distance": 0.3, "tight": 0.5},
    "shorter_moves": {"label": "Shorter individual moves", "move": 0.5, "distance": 1.0, "tight": 1.0},
    "more_room": {"label": "More reach margin", "move": 0.5, "distance": 0.3, "tight": 4.0},
}


def _start_states(holds, points, body, cache) -> list[tuple[int, int, int, int]]:
    starts = sorted((i for i, h in enumerate(holds) if h.get("role") == "start" and h.get("use", "") in HAND_USES), key=lambda i: holds[i]["x"])
    left, right = starts[0], starts[-1]
    named = [i for i, h in enumerate(holds) if h.get("role") == "start" and h.get("use", "") in {"foot", "both"}]
    top = min(points[left][1], points[right][1])
    below = [i for i, h in enumerate(holds) if h.get("use", "") in FOOT_USES and points[i][1] > top and i not in (left, right)]
    feet = named if len(named) >= 2 else below
    options: list[tuple[float, tuple[int, int, int, int]]] = []
    for a in feet:
        for b in feet:
            if a == b or holds[a]["x"] > holds[b]["x"]:
                continue
            state = (left, right, a, b)
            margin = _margin(state, points, body, cache)
            if margin >= MIN_FEASIBLE_MARGIN_L:
                options.append((margin, state))
    if options:
        return [state for _, state in sorted(options, reverse=True)[:4]]
    return [(left, right, OFF_WALL, OFF_WALL)]


def _margin(state: tuple[int, int, int, int], points: np.ndarray, body: Body, cache: dict) -> float:
    if state not in cache:
        cache[state] = reach_margin(points[list(state[:2])], points[[f for f in state[2:] if f != OFF_WALL]], body, refine=False)
    return cache[state]


def _feet_below_hands(state: tuple[int, int, int, int], points: np.ndarray) -> bool:
    """Excludes a foot higher than both hands, which a heel hook might use but this plain model should not suggest."""
    top_hand = min(points[state[0]][1], points[state[1]][1])
    return all(points[foot][1] > top_hand for foot in state[2:] if foot != OFF_WALL)


def _search(holds, points, body, profile, cache) -> list[tuple[int, int, int, int]] | None:
    """Lowest-cost feasible sequence for this profile, by shortest-path search over limb placements."""
    finish = {i for i, h in enumerate(holds) if h.get("role") == "finish" and h.get("use", "") in HAND_USES}
    hand_ok = [i for i, h in enumerate(holds) if h.get("use", "") in HAND_USES]
    foot_ok = [i for i, h in enumerate(holds) if h.get("use", "") in FOOT_USES and h.get("role") != "finish"]
    costs: dict[tuple[int, int, int, int], float] = {}
    parents: dict[tuple[int, int, int, int], tuple[int, int, int, int] | None] = {}
    moves_used: dict[tuple[int, int, int, int], int] = {}
    queue: list[tuple[float, tuple[int, int, int, int]]] = []
    for state in _start_states(holds, points, body, cache):
        costs[state], parents[state], moves_used[state] = 0.0, None, 0
        heapq.heappush(queue, (0.0, state))
    expanded = 0
    while queue and expanded < MAX_STATES:
        cost, state = heapq.heappop(queue)
        if cost > costs[state]:
            continue
        expanded += 1
        if state[0] in finish or state[1] in finish:
            path = [state]
            while parents[path[-1]] is not None:
                path.append(parents[path[-1]])
            return path[::-1]
        if moves_used[state] >= MAX_MOVES:
            continue
        for limb in range(4):
            if limb < 2 and state[2] == OFF_WALL and state[3] == OFF_WALL:
                continue                    # a hand may not leave until at least one foot is on a marked hold
            for target in (hand_ok if limb < 2 else foot_ok):
                if target == state[limb]:
                    continue
                next_state = tuple(target if i == limb else v for i, v in enumerate(state))
                if not _feet_below_hands(next_state, points):
                    continue
                margin = _margin(next_state, points, body, cache)
                if margin < MIN_FEASIBLE_MARGIN_L:
                    continue
                distance = 0.0 if state[limb] == OFF_WALL else float(np.linalg.norm(points[target] - points[state[limb]]))
                total = cost + profile["move"] + profile["distance"] * distance + profile["tight"] * max(0.0, COMFORT_MARGIN_L - margin)
                if total < costs.get(next_state, np.inf):
                    costs[next_state], parents[next_state], moves_used[next_state] = total, state, moves_used[state] + 1
                    heapq.heappush(queue, (total, next_state))
    return None


def _describe(path, holds, points, body, profile_key) -> dict[str, Any]:
    steps, margins = [], []
    placed = lambda state: points[[f for f in state[2:] if f != OFF_WALL]]
    first = reach_margin(points[list(path[0][:2])], placed(path[0]), body)
    for before, after in zip(path, path[1:]):
        limb = next(i for i in range(4) if before[i] != after[i])
        margin = reach_margin(points[list(after[:2])], placed(after), body)
        distance = 0.0 if before[limb] == OFF_WALL else float(np.linalg.norm(points[after[limb]] - points[before[limb]]))
        margins.append(margin)
        steps.append({"limb": LIMBS[limb], "from_hold": before[limb], "to_hold": after[limb], "distance_L": round(distance, 2),
                      "margin_L": round(margin, 2), "tight": margin < COMFORT_MARGIN_L})
    return {"profile": profile_key, "label": PROFILES[profile_key]["label"],
            "start": {limb: path[0][i] for i, limb in enumerate(LIMBS)}, "feet_start_off_wall": path[0][2] == OFF_WALL, "start_margin_L": round(first, 2), "steps": steps,
            "move_count": len(steps), "total_distance_L": round(sum(s["distance_L"] for s in steps), 2),
            "largest_move_L": max(s["distance_L"] for s in steps), "tightest_margin_L": round(min(margins), 2),
            "tight_moves": sum(s["tight"] for s in steps)}


def candidate_sequences(holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float, body: Body | None) -> dict[str, Any]:
    """Up to three different feasible sequences, each with its tradeoffs. Refuses instead of guessing when marks are missing."""
    base = {"method": BETA_VERSION, "assumptions": ASSUMPTIONS, "candidates": [], "comfort_margin_L": COMFORT_MARGIN_L,
            "note": "These are untested ideas from 2D geometry. Try them on the wall; none is the best or easiest beta."}
    needs = setup_needed(holds)
    if body is None:
        needs.append("This attempt does not show the arms and legs often enough to estimate reach lengths.")
    if needs:
        return {**base, "status": "setup_needed", "needs": needs}
    points = hold_points(holds, width, height, length_px)
    cache: dict = {}
    unspecified = sum(1 for h in holds if not h.get("use"))
    extra = ([] if len(holds) < 1 else ["If the feet start off the wall, the sequence assumes you can step from the ground onto the first marked foothold."]) + ([f"{unspecified} marked holds have no hand or foot use set, so they were treated as possible for both. Mark them to refine this."]
             if unspecified else [])
    seen, found = set(), []
    for key, profile in PROFILES.items():
        path = _search(holds, points, body, profile, cache)
        if path is None or tuple(path) in seen:
            continue
        seen.add(tuple(path))
        found.append(_describe(path, holds, points, body, key))
        if OFF_WALL in path[-1][2:]:
            extra.append(f"The {PROFILES[key]['label'].lower()} candidate ends with a foot off the marked holds, so check where that foot would really go.")
    if not found:
        return {**base, "status": "no_candidate", "needs": [], "assumptions": [*ASSUMPTIONS, *extra],
                "note": "No sequence stayed within this 2D reach model. That does not mean the problem is impossible; dynamic moves and missing holds are not modeled."}
    return {**base, "status": "ready", "needs": [], "assumptions": [*ASSUMPTIONS, *extra], "body": body.public(), "candidates": found}
