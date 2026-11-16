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

BETA_VERSION = "candidate-beta-v3"
MIN_BODY_SAMPLES = 30
PALM_OF_FOREARM = 0.35            # the same share used to place a resting hand beyond its tracked wrist
REFINE_BAND_L = 0.2               # placements this close to the limit are solved on the fine grid before being ruled in or out
LIMBS = ("left_hand", "right_hand", "left_foot", "right_foot")
HAND_USES = {"", "hand", "both"}
FOOT_USES = {"", "foot", "both"}
TORSO_ANGLES = np.radians([-40, -20, 0, 20, 40])
COMFORT_MARGIN_L = 0.3            # moves with less 2D slack than this are called tight
MIN_FEASIBLE_MARGIN_L = 0.0
OFF_WALL = -1                     # a foot not yet on any marked hold, for problems that start from the ground
MAX_STATES = 30000
MAX_MOVES = 40                    # long problems need many small moves once giant steps are ruled out
MAX_FOOT_CROSS_L = 0.35           # how far the left foot may be placed to the right of the right foot, and the reverse
MAX_HAND_CROSS_L = 1.0            # hands cross more freely than feet
MAX_FOOT_MOVE_OF_LEG = 1.1        # one step cannot carry a foot farther than about a leg length
MAX_HAND_MOVE_OF_ARM = 2.0        # one reach cannot carry a hand farther than from full stretch below to full stretch above
MAX_FOOT_SPREAD_OF_LEG = 1.5      # feet farther apart than this share of leg length would need the splits
LOW_FOOT_BELOW_HIP_L = 0.8        # a placement is a high foot when no position keeps every foot this far below the hips
HIPS_BELOW_FEET_L = 0.2           # the hips may sag this far below the lowest foot, no farther
MIN_LEG_FOLD_OF_LEG = 0.35        # a hip cannot come closer than this share of leg length to the foot it stands on
CROSS_NOTE_L = 0.1
# Strain is a rough stand-in for effort: 0 for hanging on nearly straight arms with the hips well above the feet.
FREE_ARM_BEND = 0.15              # arms shortened by less than this share cost nothing
FREE_LEG_FOLD = 0.4               # legs shortened by less than this share cost nothing
HIPS_ABOVE_FEET_OF_LEG = 0.5      # hips closer than this share of leg length above the lowest foot count as a deep squat
STRAIN_BENT_ARM, STRAIN_PRESS, STRAIN_FOLDED_LEG, STRAIN_SQUAT, STRAIN_LEAN = 1.0, 2.0, 1.5, 1.5, 0.6
HARD_STRAIN = 0.45                # a position at least this strained is called strenuous
BIG_SHIFT_L = 1.0                 # the body travelling this far in one move is called a big body shift
VOLUME_TYPE = "volume"
VOLUME_SPOTS = ((0.0, -0.6), (-0.6, -0.2), (0.6, -0.2))     # usable spots on a volume, as shares of its marked radius: top, left, right
START_LIMBS = ("", "left_hand", "right_hand", "both_hands", "left_foot", "right_foot")
PULL_SIDE_L = 0.15                # a sidepull keeps the shoulders on the side it is pulled toward, give or take this
PULL_UNDER_L = 0.3                # an undercling needs the shoulders no lower than this below the hold
PULL_OVER_L = 0.5                 # a hold pulled downward stops working once the shoulders are this far above it
SHOULDER_HALF_L, HIP_HALF_L = 0.33, 0.2
TOP_OUT_TYPE = "top-out"
ASSUMPTIONS = [
    "Distances are in the picture plane. Wall angle and depth are not known.",
    "Hold shape, size, and friction are not known. Pull direction is used only where you marked it.",
    "Balance, body rotation, flagging, and dynamic moves are not modeled.",
    "Reach lengths come from this climber's tracked limb lengths in this video.",
    "A foot higher than both hands is never proposed, although a heel hook could use one.",
    "The hips stay above the lowest foot and no closer to a foot than a deep squat allows.",
    "Effort is approximated from the sketch: bent arms, deeply folded legs, hips low over the feet, pressing down on a hold, and moving the body a long way in one move all count against a sequence. It is not a measurement of force.",
    "A sequence ends with both hands on the finish.",
    "One step moves a foot no farther than about a leg length, and one reach moves a hand no farther than two arm lengths.",
    "Feet are not crossed far past each other or spread wider than about one and a half leg lengths, and hands are not crossed by more than a torso length.",
    "The stick figure shows one position that fits the reach lengths. It is a sketch, not the position you must use.",
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
                "method": "95th percentile of tracked shoulder-elbow-wrist length plus a palm allowance, and of hip-knee-ankle length, in the picture"}


def _segment_sum(joints: dict[str, Sequence[float]], names: Sequence[str], width: int, height: int, plane=None) -> float | None:
    if any(name not in joints for name in names):
        return None
    points = [np.array([joints[name][0] * width, joints[name][1] * height]) for name in names]
    if plane is not None:
        points = list(plane.plane(points))
    return float(sum(np.linalg.norm(b - a) for a, b in zip(points, points[1:])))


def plane_torso(samples: Sequence[dict[str, Any]], width: int, height: int, plane) -> float | None:
    """Median shoulder-to-hip length measured on the wall plane, in the plane's units. Assumes the body is close to the wall."""
    lengths = []
    for sample in samples:
        joints = sample["joints"]
        if all(name in joints for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")):
            points = plane.plane([[joints[n][0] * width, joints[n][1] * height] for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")])
            lengths.append(float(np.linalg.norm((points[0] + points[1]) / 2 - (points[2] + points[3]) / 2)))
    return float(np.median(lengths)) if len(lengths) >= MIN_BODY_SAMPLES else None


def body_model(samples: Sequence[dict[str, Any]], width: int, height: int, length_px: float | None, plane=None) -> Body | None:
    """None when too few samples show the limbs for a length to mean anything. With `plane`, lengths are measured on the wall plane."""
    if not length_px:
        return None
    arms, legs = [], []
    for sample in samples:
        for side in ("left", "right"):
            arm = _segment_sum(sample["joints"], (f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist"), width, height, plane)
            forearm = _segment_sum(sample["joints"], (f"{side}_elbow", f"{side}_wrist"), width, height, plane)
            if arm is not None and forearm is not None:
                arm += PALM_OF_FOREARM * forearm          # a hold is gripped past the wrist, so reach runs to the middle of the palm
            leg = _segment_sum(sample["joints"], (f"{side}_hip", f"{side}_knee", f"{side}_ankle"), width, height, plane)
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


def _pull_ok(shoulders: np.ndarray, hand: np.ndarray, pull: str) -> np.ndarray:
    """Torso positions from which a hold can be pulled the way the climber marked it. y grows downward."""
    if pull == "left":
        return shoulders[:, 0] <= hand[0] + PULL_SIDE_L
    if pull == "right":
        return shoulders[:, 0] >= hand[0] - PULL_SIDE_L
    if pull == "up":
        return shoulders[:, 1] <= hand[1] + PULL_UNDER_L
    if pull == "down":
        return shoulders[:, 1] >= hand[1] - PULL_OVER_L
    return np.ones(len(shoulders), bool)


def _strain(shoulders: np.ndarray, hips: np.ndarray, hands: np.ndarray, feet: np.ndarray, body: Body, angle: float) -> np.ndarray:
    """A rough effort score for each torso position. Zero is hanging on nearly straight arms, standing tall on the feet."""
    reach = np.linalg.norm(shoulders[:, None] - hands[None], axis=2)
    total = STRAIN_BENT_ARM * np.clip((body.arm_L - reach) / body.arm_L - FREE_ARM_BEND, 0, None).mean(axis=1)
    total = total + STRAIN_PRESS * np.clip(hands[None, :, 1] - shoulders[:, None, 1], 0, None).mean(axis=1) + STRAIN_LEAN * abs(angle)
    if len(feet):
        legs = np.linalg.norm(hips[:, None] - feet[None], axis=2)
        total = total + STRAIN_FOLDED_LEG * np.clip((body.leg_L - legs) / body.leg_L - FREE_LEG_FOLD, 0, None).mean(axis=1)
        total = total + STRAIN_SQUAT * np.clip(HIPS_ABOVE_FEET_OF_LEG * body.leg_L - (feet[:, 1].max() - hips[:, 1]), 0, None) / body.leg_L
    return total


def _slack(shoulders: np.ndarray, hips: np.ndarray, hands: np.ndarray, feet: np.ndarray, body: Body, pulls: Sequence[str]) -> np.ndarray:
    """Worst-limb slack of each torso position; minus infinity where the position is ruled out."""
    slack = np.full(len(shoulders), np.inf)
    if len(hands):
        slack = np.minimum(slack, body.arm_L - np.linalg.norm(shoulders[:, None] - hands[None], axis=2).max(axis=1))
    if len(feet):
        legs = np.linalg.norm(hips[:, None] - feet[None], axis=2)
        slack = np.minimum(slack, body.leg_L - legs.max(axis=1))
        slack = np.where(legs.min(axis=1) >= MIN_LEG_FOLD_OF_LEG * body.leg_L, slack, -np.inf)       # a leg folds only so far
        slack = np.where(hips[:, 1] <= feet[:, 1].max() + HIPS_BELOW_FEET_L, slack, -np.inf)         # the hips do not hang below the lowest foot
    for hand, pull in zip(hands, pulls):
        if pull:
            slack = np.where(_pull_ok(shoulders, hand, pull), slack, -np.inf)
    return slack


def _rest(cores: np.ndarray, hands: np.ndarray, feet: np.ndarray, body: Body, pulls: Sequence[str] = ()) -> tuple[float, np.ndarray, float]:
    """The least strained position that is within reach: (strain, torso center, lean). Strain is infinite when nothing is in reach."""
    best, where, lean = np.inf, cores[0], 0.0
    for angle in TORSO_ANGLES:
        up = np.array([np.sin(angle), -np.cos(angle)]) * 0.5
        shoulders, hips = cores + up, cores - up
        strain = np.where(_slack(shoulders, hips, hands, feet, body, pulls) >= MIN_FEASIBLE_MARGIN_L, _strain(shoulders, hips, hands, feet, body, angle), np.inf)
        index = int(np.argmin(strain))
        if strain[index] < best:
            best, where, lean = float(strain[index]), cores[index], float(angle)
    return best, where, lean


def _best_slack(cores: np.ndarray, hands: np.ndarray, feet: np.ndarray, body: Body, pulls: Sequence[str] = (),
                rest: list | None = None) -> tuple[float, np.ndarray, float, float]:
    """Largest worst-limb slack over torso centers and leans: (slack, center, lean, slack with the feet kept low).

    With `rest`, a list, the least strained position in reach is appended to it as (strain, center) from the same pass.

    The last value only counts positions where every foot is well below the hips, so a negative
    value means the placement needs a high foot. y grows downward, as in images.
    """
    best, where, lean, best_low = -np.inf, cores[0], 0.0, -np.inf
    relaxed, relaxed_at = np.inf, cores[0]
    for angle in TORSO_ANGLES:
        up = np.array([np.sin(angle), -np.cos(angle)]) * 0.5
        shoulders, hips = cores + up, cores - up
        slack = _slack(shoulders, hips, hands, feet, body, pulls)
        if rest is not None and slack.max() >= MIN_FEASIBLE_MARGIN_L:
            strain = np.where(slack >= MIN_FEASIBLE_MARGIN_L, _strain(shoulders, hips, hands, feet, body, angle), np.inf)
            if strain.min() < relaxed:
                relaxed, relaxed_at = float(strain.min()), cores[int(np.argmin(strain))]
        index = int(np.argmax(slack))
        if slack[index] > best:
            best, where, lean = float(slack[index]), cores[index], float(angle)
        low = slack if not len(feet) else np.where((feet[None, :, 1] - hips[:, None, 1] >= LOW_FOOT_BELOW_HIP_L).all(axis=1), slack, -np.inf)
        best_low = max(best_low, float(low.max()))
    if rest is not None:
        rest.append((relaxed, relaxed_at))
    return best, where, lean, best_low


def solve_pose(hands: Sequence[Sequence[float]], feet: Sequence[Sequence[float]], body: Body, pulls: Sequence[str] = (),
               refine: bool = True, rest: list | None = None) -> tuple[float, np.ndarray, float, float]:
    """The stick-figure position with the most 2D slack: (slack, torso center, lean in radians, slack with low feet)."""
    hand_points = np.asarray(hands, float).reshape(-1, 2)
    foot_points = np.asarray(feet, float).reshape(-1, 2)
    center = np.vstack([hand_points, foot_points]).mean(axis=0)
    best, where, lean, low = _best_slack(_grid(center, 2.5, 0.25), hand_points, foot_points, body, pulls, rest)
    if refine and np.isfinite(best):
        fine, fine_where, fine_lean, fine_low = _best_slack(_grid(where, 0.3, 0.05), hand_points, foot_points, body, pulls)
        if fine >= best:
            best, where, lean = fine, fine_where, fine_lean
        low = max(low, fine_low)
    return best, where, lean, low


def natural_pose(hands: Sequence[Sequence[float]], feet: Sequence[Sequence[float]], body: Body, pulls: Sequence[str] = ()) -> tuple[np.ndarray, float]:
    """A position for drawing: within reach and as relaxed as the holds allow. Returns (torso center, lean)."""
    hand_points = np.asarray(hands, float).reshape(-1, 2)
    foot_points = np.asarray(feet, float).reshape(-1, 2)
    _, where, lean, _ = solve_pose(hand_points, foot_points, body, pulls)
    strain, rest, rest_lean = _rest(_grid(where, 1.5, 0.1), hand_points, foot_points, body, pulls)
    return (rest, rest_lean) if np.isfinite(strain) else (where, lean)


def reach_margin(hands: Sequence[Sequence[float]], feet: Sequence[Sequence[float]], body: Body, refine: bool = True, pulls: Sequence[str] = ()) -> float:
    """2D slack in torso lengths for the given contacts, in torso-length coordinates. Negative means out of reach."""
    return solve_pose(hands, feet, body, pulls, refine)[0]


def hold_points(holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float) -> np.ndarray:
    return np.array([[h["x"] * width / length_px, h["y"] * height / length_px] for h in holds], float)


def _start_limb(hold: dict[str, Any]) -> str:
    return (hold.get("start_limb") or "") if hold.get("role") == "start" else ""


def _hand_start(hold: dict[str, Any]) -> bool:
    return hold.get("role") == "start" and hold.get("use", "") in HAND_USES and not _start_limb(hold).endswith("foot")


def is_volume(hold: dict[str, Any]) -> bool:
    return (hold.get("hold_type") or "").strip().lower() == VOLUME_TYPE


def expand_volumes(holds: Sequence[dict[str, Any]], points: np.ndarray, radii: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray, list[int]]:
    """A volume becomes several usable spots on its marked circle. Returns the spots, their points, and each spot's original hold."""
    spots, where, source = [], [], []
    for index, hold in enumerate(holds):
        offsets = VOLUME_SPOTS if is_volume(hold) else ((0.0, 0.0),)
        for dx, dy in offsets:
            spots.append({**hold, "use": hold.get("use") or "both"} if is_volume(hold) else hold)
            where.append(points[index] + radii[index] * np.array([dx, dy]))
            source.append(index)
    return spots, np.array(where, float).reshape(-1, 2), source


def setup_needed(holds: Sequence[dict[str, Any]]) -> list[str]:
    """What the climber still has to mark before any sequence can be proposed."""
    needs: list[str] = []
    if not any(_hand_start(h) for h in holds):
        needs.append("Mark at least one start hold for the hands.")
    if not any(h.get("role") == "finish" and h.get("use", "") in HAND_USES for h in holds):
        needs.append("Mark the finish hold. If the problem tops out, mark the point on the lip you grab last and choose Top out.")
    if not any(h.get("use", "") in FOOT_USES and h.get("role") != "finish" for h in holds):
        needs.append("Mark at least one hold your feet could use.")
    return needs


PROFILES = {
    "balanced": {"label": "Balanced", "move": 1.0, "distance": 0.5, "tight": 2.0, "high_foot": 1.5, "one_foot": 1.5, "strain": 3.0, "shift": 1.5},
    "fewer_moves": {"label": "Fewer moves", "move": 2.5, "distance": 0.3, "tight": 0.5, "high_foot": 0.5, "one_foot": 0.75, "strain": 1.0, "shift": 0.5},
    "low_feet": {"label": "Low feet, small steps", "move": 0.4, "distance": 1.0, "tight": 1.0, "high_foot": 5.0, "one_foot": 2.0, "strain": 6.0, "shift": 3.0},
}
State = tuple[int, int, int, int]


class _Problem:
    """One marked route in torso-length coordinates, with the solved position of every limb placement tried so far."""

    def __init__(self, holds: Sequence[dict[str, Any]], points: np.ndarray, body: Body):
        self.holds, self.points, self.body = holds, points, body
        self.pulls = [h.get("pull", "") or "" for h in holds]
        self.cache: dict[State, tuple[float, float]] = {}
        self.rests: dict[State, tuple[float, np.ndarray]] = {}

    def feet(self, state: State) -> np.ndarray:
        return self.points[[f for f in state[2:] if f != OFF_WALL]]

    def solve(self, state: State, refine: bool = False, rest: list | None = None) -> tuple[float, np.ndarray, float, float]:
        return solve_pose(self.points[list(state[:2])], self.feet(state), self.body, [self.pulls[i] for i in state[:2]], refine, rest)

    def margins(self, state: State) -> tuple[float, float]:
        """(slack, slack with low feet), from the coarse grid."""
        if state not in self.cache:
            rest: list = []
            margin, _, _, low = self.solve(state, rest=rest)
            self.rests[state] = rest[0]
            if abs(margin) < REFINE_BAND_L or abs(low) < REFINE_BAND_L:      # the coarse grid can miss a narrow feasible position
                margin, _, _, low = self.solve(state, refine=True)
            self.cache[state] = (margin, low)
        return self.cache[state]

    def rest(self, state: State) -> tuple[float, np.ndarray]:
        """(strain, torso center) of the most relaxed position in this placement."""
        self.margins(state)
        return self.rests[state]

    def humanly(self, state: State) -> bool:
        """Rules a reach circle cannot express: no foot above both hands, no deep cross of feet or hands, no splits."""
        points = self.points
        top_hand = min(points[state[0]][1], points[state[1]][1])
        if any(points[foot][1] <= top_hand for foot in state[2:] if foot != OFF_WALL):
            return False            # a heel hook might use this, but a plain model should not suggest it
        if points[state[0]][0] - points[state[1]][0] > MAX_HAND_CROSS_L:
            return False
        if state[2] != OFF_WALL and state[3] != OFF_WALL:
            if points[state[2]][0] - points[state[3]][0] > MAX_FOOT_CROSS_L:
                return False
            if float(np.linalg.norm(points[state[2]] - points[state[3]])) > MAX_FOOT_SPREAD_OF_LEG * self.body.leg_L:
                return False
        return True

    def allowed(self, state: State) -> bool:
        return self.humanly(state) and self.margins(state)[0] >= MIN_FEASIBLE_MARGIN_L

    def start_states(self) -> list[State]:
        """Limb placements to start from. A start hold the climber gave to one limb is used by that limb; the rest are tried."""
        holds, points = self.holds, self.points
        limb = [_start_limb(h) for h in holds]
        starts = sorted((i for i, h in enumerate(holds) if _hand_start(h)), key=lambda i: holds[i]["x"])
        free = [i for i in starts if not limb[i]]
        given = {side: next((i for i in starts if limb[i] in (f"{side}_hand", "both_hands")), None) for side in ("left", "right")}
        left = given["left"] if given["left"] is not None else (free[0] if free else given["right"])
        right = given["right"] if given["right"] is not None else (free[-1] if free else given["left"])
        fixed = {side: next((i for i in range(len(holds)) if limb[i] == f"{side}_foot"), None) for side in ("left", "right")}
        named = [i for i, h in enumerate(holds) if h.get("role") == "start" and h.get("use", "") in {"foot", "both"} and not limb[i] and i not in (left, right)]
        top = min(points[left][1], points[right][1])
        below = [i for i, h in enumerate(holds) if h.get("use", "") in FOOT_USES and h.get("role") != "finish" and points[i][1] > top and i not in (left, right) and not limb[i].endswith("foot")]
        # Start footholds with no limb given are alternatives, not a set that must all be used: try every pair, and each one alone with the other foot off the marks.
        pool = named or below
        lefts = pool if fixed["left"] is None else [fixed["left"]]
        rights = pool if fixed["right"] is None else [fixed["right"]]
        any_fixed = fixed["left"] is not None or fixed["right"] is not None
        tried: list[State] = [(left, right, a, b) for a in lefts for b in rights if a != b and (any_fixed or holds[a]["x"] <= holds[b]["x"])]
        if named or any_fixed:
            tried += [(left, right, a, OFF_WALL) for a in lefts if fixed["right"] is None] + [(left, right, OFF_WALL, b) for b in rights if fixed["left"] is None]
        options = sorted(((self.margins(state)[0], state) for state in tried if self.allowed(state)), reverse=True)
        both = [state for _, state in options if OFF_WALL not in state][:4]
        single = [state for _, state in options if OFF_WALL in state][:2 if both else 4]
        return [*both, *single] + ([] if any_fixed else [(left, right, OFF_WALL, OFF_WALL)])


def _search(problem: _Problem, profile: dict[str, float]) -> tuple[list[State] | None, dict[str, Any]]:
    """Lowest-cost feasible sequence for this profile, by shortest-path search over limb placements.

    The second value says how far the search got, for explaining a failure.
    """
    holds, points = problem.holds, problem.points
    finish = {i for i, h in enumerate(holds) if h.get("role") == "finish" and h.get("use", "") in HAND_USES}
    hand_ok = [i for i, h in enumerate(holds) if h.get("use", "") in HAND_USES]
    foot_ok = [i for i, h in enumerate(holds) if h.get("use", "") in FOOT_USES and h.get("role") != "finish"]
    costs: dict[State, float] = {}
    parents: dict[State, State | None] = {}
    moves_used: dict[State, int] = {}
    queue: list[tuple[float, State]] = []
    for state in problem.start_states():
        costs[state], parents[state], moves_used[state] = 0.0, None, 0
        heapq.heappush(queue, (0.0, state))
    expanded, highest = 0, None
    while queue and expanded < MAX_STATES:
        cost, state = heapq.heappop(queue)
        if cost > costs[state]:
            continue
        expanded += 1
        if highest is None or min(points[state[0]][1], points[state[1]][1]) < min(points[highest[0]][1], points[highest[1]][1]):
            highest = state
        if state[0] in finish and state[1] in finish:          # a problem is finished with both hands on the finish
            path = [state]
            while parents[path[-1]] is not None:
                path.append(parents[path[-1]])
            return path[::-1], {}
        if moves_used[state] >= MAX_MOVES:
            continue
        for limb in range(4):
            if limb < 2 and state[2] == OFF_WALL and state[3] == OFF_WALL:
                continue                    # a hand may not leave until at least one foot is on a marked hold
            for target in (hand_ok if limb < 2 else foot_ok):
                if target == state[limb]:
                    continue
                next_state = tuple(target if i == limb else v for i, v in enumerate(state))
                if not problem.allowed(next_state):
                    continue
                margin, low = problem.margins(next_state)
                distance = 0.0 if state[limb] == OFF_WALL else float(np.linalg.norm(points[target] - points[state[limb]]))
                if distance > (MAX_HAND_MOVE_OF_ARM * problem.body.arm_L if limb < 2 else MAX_FOOT_MOVE_OF_LEG * problem.body.leg_L):
                    continue
                strain, center = problem.rest(next_state)
                shift = float(np.linalg.norm(center - problem.rest(state)[1]))
                total = (cost + profile["move"] + profile["distance"] * distance + profile["tight"] * max(0.0, COMFORT_MARGIN_L - margin)
                         + profile["strain"] * strain + profile["shift"] * shift ** 2
                         + (profile["high_foot"] if limb >= 2 and low < MIN_FEASIBLE_MARGIN_L else 0.0)
                         + (profile["one_foot"] if limb < 2 and OFF_WALL in state[2:] else 0.0))
                if total < costs.get(next_state, np.inf):
                    costs[next_state], parents[next_state], moves_used[next_state] = total, state, moves_used[state] + 1
                    heapq.heappush(queue, (total, next_state))
    return None, {"hands_reached": sorted({highest[0], highest[1]}) if highest else [], "search_limit_reached": expanded >= MAX_STATES}


def _two_bone(root: np.ndarray, tip: np.ndarray, length: float, away_from: np.ndarray, prefer_up: bool) -> np.ndarray:
    """The middle joint of a two-part limb of the given total length, bent away from the body."""
    span = tip - root
    distance = float(np.linalg.norm(span))
    if distance < 1e-6:
        return root.copy()
    half = length / 2
    rise = float(np.sqrt(max(0.0, half ** 2 - min(distance, length) ** 2 / 4)))
    normal = np.array([-span[1], span[0]]) / distance
    middle = root + span / 2
    options = [middle + rise * normal, middle - rise * normal]
    # Knees bend upward and elbows hang downward; pointing away from the torso only breaks a tie.
    natural = lambda p: (-p[1] if prefer_up else p[1]) + 0.3 * float(np.linalg.norm(p - away_from))
    return max(options, key=natural)


def _figure(problem: _Problem, state: State) -> dict[str, list[float]]:
    """Joint positions of a stick figure in this placement, in torso-length coordinates. A sketch of one possible position."""
    body, points = problem.body, problem.points
    core, lean = natural_pose(points[list(state[:2])], problem.feet(state), body, [problem.pulls[i] for i in state[:2]])
    up = np.array([np.sin(lean), -np.cos(lean)])
    side = np.array([np.cos(lean), np.sin(lean)])           # toward the climber's right, seen from behind
    shoulders, hips = core + up * 0.5, core - up * 0.5
    joints = {"head": shoulders + up * 0.38, "neck": shoulders, "pelvis": hips,
              "left_shoulder": shoulders - side * SHOULDER_HALF_L, "right_shoulder": shoulders + side * SHOULDER_HALF_L,
              "left_hip": hips - side * HIP_HALF_L, "right_hip": hips + side * HIP_HALF_L}
    for index, name in enumerate(("left", "right")):
        hand = points[state[index]]
        joints[f"{name}_hand"] = hand
        joints[f"{name}_elbow"] = _two_bone(joints[f"{name}_shoulder"], hand, body.arm_L, core, prefer_up=False)
        foot = state[2 + index]
        target = joints[f"{name}_hip"] - up * body.leg_L * 0.95 if foot == OFF_WALL else points[foot]
        joints[f"{name}_foot"] = target
        joints[f"{name}_knee"] = _two_bone(joints[f"{name}_hip"], target, body.leg_L, core, prefer_up=True)
    return {name: [float(value[0]), float(value[1])] for name, value in joints.items()}


def _describe(path: list[State], problem: _Problem, profile_key: str, to_image, source: Sequence[int]) -> dict[str, Any]:
    """`source` gives the marked hold behind each planning spot, so a volume's spots are reported as that one hold."""
    holds, points = problem.holds, problem.points
    steps, margins = [], []
    first = problem.solve(path[0], refine=True)[0]
    hold_of = lambda spot: OFF_WALL if spot == OFF_WALL else source[spot]
    for before, after in zip(path, path[1:]):
        limb = next(i for i in range(4) if before[i] != after[i])
        margin, _, _, low = problem.solve(after, refine=True)
        distance = 0.0 if before[limb] == OFF_WALL else float(np.linalg.norm(points[after[limb]] - points[before[limb]]))
        partner = after[1 - limb] if limb < 2 else after[5 - limb]
        strain, center = problem.rest(after)
        shift = float(np.linalg.norm(center - problem.rest(before)[1]))
        margins.append(margin)
        steps.append({"limb": LIMBS[limb], "from_hold": hold_of(before[limb]), "to_hold": hold_of(after[limb]), "distance_L": round(distance, 2),
                      "margin_L": round(margin, 2), "tight": bool(margin < COMFORT_MARGIN_L),
                      "match": bool(partner == after[limb]), "crossed": bool(limb < 2 and points[after[0]][0] - points[after[1]][0] > CROSS_NOTE_L),
                      "high_foot": bool(limb >= 2 and low < MIN_FEASIBLE_MARGIN_L),
                      "strain": round(strain, 2), "strenuous": bool(strain >= HARD_STRAIN), "body_shift_L": round(shift, 2), "big_shift": bool(shift >= BIG_SHIFT_L),
                      "on_volume": bool(is_volume(holds[after[limb]])), "to_point": None if to_image is None else to_image(points[after[limb]])})
    last = holds[next(h for h in path[-1][:2] if holds[h].get("role") == "finish")]
    output = {"profile": profile_key, "label": PROFILES[profile_key]["label"],
              "start": {limb: hold_of(path[0][i]) for i, limb in enumerate(LIMBS)}, "feet_start_off_wall": path[0][2] == OFF_WALL and path[0][3] == OFF_WALL,
              "start_margin_L": round(first, 2), "steps": steps,
              "move_count": len(steps), "total_distance_L": round(sum(s["distance_L"] for s in steps), 2),
              "largest_move_L": max((s["distance_L"] for s in steps), default=0.0), "tightest_margin_L": round(min(margins, default=first), 2),
              "tight_moves": int(sum(s["tight"] for s in steps)), "high_foot_moves": int(sum(s["high_foot"] for s in steps)),
              "strenuous_moves": int(sum(s["strenuous"] for s in steps)), "big_shifts": int(sum(s["big_shift"] for s in steps)),
              "effort": round(sum(s["strain"] for s in steps) + sum(s["body_shift_L"] ** 2 for s in steps), 2),
              "matches": int(sum(s["match"] for s in steps)), "tops_out": (last.get("hold_type") or "").strip().lower() == TOP_OUT_TYPE}
    if to_image is not None:
        output["figures"] = [{name: to_image(point) for name, point in _figure(problem, state).items()} for state in path]
    return output


def plane_radii(plane, holds: Sequence[dict[str, Any]], width: int, height: int, torso_units: float) -> np.ndarray:
    """Each mark's radius on the wall plane, in torso lengths, for placing the usable spots of a volume."""
    centers = plane.plane([[h["x"] * width, h["y"] * height] for h in holds])
    edges = plane.plane([[(h["x"] + h["radius"]) * width, h["y"] * height] for h in holds])
    return np.linalg.norm(edges - centers, axis=1) / torso_units


def plane_to_image(plane, torso_units: float, width: int, height: int):
    """For planning on the wall plane: turns a planning point back into a fraction of the picture."""
    def convert(point) -> list[float]:
        x, y = plane.image([[float(point[0]) * torso_units, float(point[1]) * torso_units]])[0]
        return [round(float(x) / width, 4), round(float(y) / height, 4)]
    return convert


def _stuck_note(reached: dict[str, Any]) -> str:
    where = " and ".join(f"H{i + 1}" for i in reached.get("hands_reached", []))
    if reached.get("search_limit_reached"):
        return ("The search stopped at its size limit before reaching the finish" + (f", with the hands as far as {where}" if where else "") +
                ". Marking only the holds of this problem, with their hand and foot use, makes it smaller.")
    return ((f"The search got the hands as far as {where} and found no way on. " if where else "No sequence was found. ") +
            "From there, no marked hold is within reach without a foot above both hands, crossed feet, or a body position that does not fit a marked pull direction. "
            "Check that every hold you would use is marked, footholds included, that hand and foot uses are right, and that the picture's scale is right. "
            "This does not mean the problem is impossible: dynamic moves, smears, heel hooks, and unmarked holds are not modeled.")


def candidate_sequences(holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float, body: Body | None,
                        points: np.ndarray | None = None, to_image=None, radii: np.ndarray | None = None) -> dict[str, Any]:
    """Up to three different feasible sequences, each with its tradeoffs. Refuses instead of guessing when marks are missing.

    `to_image` maps a point in planning coordinates back to a fraction of the picture, for drawing the stick figure.
    `radii` are the marks' radii in planning coordinates; without them they are taken from the picture.
    """
    base = {"method": BETA_VERSION, "assumptions": ASSUMPTIONS, "candidates": [], "comfort_margin_L": COMFORT_MARGIN_L,
            "note": "These are untested ideas from 2D geometry. Try them on the wall; none is the best or easiest beta."}
    needs = setup_needed(holds)
    if body is None:
        needs.append("This attempt does not show the arms and legs often enough to estimate reach lengths.")
    if needs:
        return {**base, "status": "setup_needed", "needs": needs}
    if points is None:                      # picture coordinates; pass `points` to plan on the wall plane instead
        points = hold_points(holds, width, height, length_px)
        to_image = lambda p: [round(float(p[0]) * length_px / width, 4), round(float(p[1]) * length_px / height, 4)]
    if radii is None:
        radii = np.array([h.get("radius", 0.0) * width / length_px for h in holds], float)
    marked = holds
    holds, points, source = expand_volumes(marked, np.asarray(points, float), np.asarray(radii, float))
    problem = _Problem(holds, points, body)
    unspecified = sum(1 for h in marked if not h.get("use") and not is_volume(h))
    extra = ([] if len(marked) < 1 else ["If the feet start off the wall, the sequence assumes you can step from the ground onto the first marked foothold."]) + ([f"{unspecified} marked holds have no hand or foot use set, so they were treated as possible for both. Mark them to refine this."]
             if unspecified else [])
    if any(problem.pulls):
        extra.append("Pull directions you marked limit where the body can be while a hand is on that hold. Holds with no direction set can be pulled from anywhere.")
    if any(is_volume(h) for h in marked):
        extra.append("A volume is planned as three usable spots, on the top, left, and right of its circle, for hands or feet. Its real surface and angle are not known.")
    if any(_start_limb(h) for h in marked):
        extra.append("Start holds you gave to a hand or foot are used by that limb. The other limbs start where the reach geometry fits best.")
    seen, found, stuck = set(), [], {}
    for key, profile in PROFILES.items():
        path, reached = _search(problem, profile)
        if path is None:
            stuck = stuck or {**reached, "hands_reached": sorted({source[i] for i in reached.get("hands_reached", [])})}
            continue
        if tuple(path) in seen:
            continue
        seen.add(tuple(path))
        found.append(_describe(path, problem, key, to_image, source))
        if OFF_WALL in path[-1][2:]:
            extra.append(f"The {PROFILES[key]['label'].lower()} candidate ends with a foot off the marked holds, so check where that foot would really go.")
    if not found:
        return {**base, "status": "no_candidate", "needs": [], "assumptions": [*ASSUMPTIONS, *extra], "stuck": stuck, "note": _stuck_note(stuck)}
    return {**base, "status": "ready", "needs": [], "assumptions": [*ASSUMPTIONS, *extra], "body": body.public(), "candidates": found}


# ---- reach lengths from the climber's own height and wingspan, for planning without a tracked video

TORSO_OF_HEIGHT = 0.288           # shoulder joint to hip joint
LEG_OF_HEIGHT = 0.491             # hip joint to ankle, matching the tracked hip-knee-ankle length
ARM_OF_WINGSPAN = 0.339           # shoulder joint to the middle of the palm
HEIGHT_RANGE_CM = (100.0, 230.0)
WINGSPAN_RANGE_CM = (100.0, 250.0)
MEASURED_ASSUMPTIONS = [
    "Arm, leg, and torso lengths are estimated from your height and wingspan using average body proportions, so yours may differ by several centimeters.",
    "One scale is used for the whole picture. Unless the wall-angle correction below was applied, a photo taken from below shrinks the upper wall, so reaches near the top are really longer than they look.",
]


@dataclass(frozen=True)
class MeasuredBody:
    body: Body
    torso_cm: float
    arm_cm: float
    leg_cm: float

    def public(self) -> dict[str, Any]:
        return {"torso_cm": round(self.torso_cm, 1), "arm_cm": round(self.arm_cm, 1), "leg_cm": round(self.leg_cm, 1),
                "arm_L": round(self.body.arm_L, 3), "leg_L": round(self.body.leg_L, 3),
                "method": "average body proportions (Drillis and Contini segment ratios) applied to entered height and wingspan"}


def body_from_measurements(height_cm: float, wingspan_cm: float) -> MeasuredBody:
    torso = TORSO_OF_HEIGHT * height_cm
    arm, leg = ARM_OF_WINGSPAN * wingspan_cm, LEG_OF_HEIGHT * height_cm
    return MeasuredBody(Body(arm / torso, leg / torso, 0, 0), torso, arm, leg)


def torso_px(scale: dict[str, float], width: int, height: int, torso_cm: float) -> float:
    """Pixels per torso length from a user-marked line of known real length. Uses pixel distance, so aspect ratio is kept."""
    line_px = float(np.hypot((scale["x2"] - scale["x1"]) * width, (scale["y2"] - scale["y1"]) * height))
    return line_px / scale["cm"] * torso_cm
