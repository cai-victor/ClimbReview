"""Propose each hold's start, finish, and hand or foot use from where tracked limbs came to rest.

Everything here is a proposal for the climber to confirm. A limb resting near a mark does
not show that it touched that hold. Nothing is stored by this module.

Choosing the route's color automatically was tried and dropped: against four hand-marked
routes it matched 5 of 11, 3 of 3, 7 of 17 (the wrong color), and 0 of 10 holds. The climber
therefore still taps one hold to choose the color.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np


AUTO_VERSION = "role-proposal-v1"
REST_MAX_SPEED_L_PER_S = 0.2
REST_MIN_MS = 500
HAND_EXTENSION = 0.35              # the palm is taken to lie this share of the forearm beyond the wrist
HAND_NEAR_L = 0.5                  # beyond a hold's edge
FOOT_NEAR_L = 0.35
MAX_REGISTRATION_GAP_MS = 3000       # a rest farther than this from any lined-up frame cannot be placed on the wall picture
HANDS, FEET = ("left_wrist", "right_wrist"), ("left_foot", "right_foot")


def rest_points(series: dict[str, Any], samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Intervals where a limb was tracked continuously and nearly still, with the best available contact point.

    Feet use the toe point when it was tracked for at least half the interval, otherwise the ankle. Hands use
    a point just beyond the wrist along the forearm when the elbow was tracked, otherwise the wrist.
    """
    times = series["t"]
    by_time = {s["t"]: s for s in samples}
    found: list[dict[str, Any]] = []
    for limb, data in series["limbs"].items():
        side, begin = limb.split("_")[0], None
        for index in range(len(times) + 1):
            slow = index < len(times) and data["speed_L_per_s"][index] is not None and data["speed_L_per_s"][index] < REST_MAX_SPEED_L_PER_S
            still = slow and (begin is None or data["run"][index] == data["run"][begin])
            if still and begin is None:
                begin = index
            if not still and begin is not None:
                last = index - 1
                if times[last] - times[begin] >= REST_MIN_MS:
                    span = range(begin, last + 1)
                    x, y = float(np.mean([data["x"][i] for i in span])), float(np.mean([data["y"][i] for i in span]))
                    anchor = "wrist" if limb in HANDS else "ankle"
                    joints = [by_time[times[i]]["joints"] for i in span if times[i] in by_time]
                    if limb in FEET:
                        toes = [j[f"{side}_foot_index"] for j in joints if f"{side}_foot_index" in j]
                        if len(toes) >= 0.5 * len(span):
                            (x, y), anchor = np.mean(toes, axis=0).tolist(), "toe"
                    else:
                        pairs = [(j[f"{side}_wrist"], j[f"{side}_elbow"]) for j in joints if f"{side}_wrist" in j and f"{side}_elbow" in j]
                        if len(pairs) >= 0.5 * len(span):
                            wrist, elbow = np.mean([p[0] for p in pairs], axis=0), np.mean([p[1] for p in pairs], axis=0)
                            (x, y), anchor = (wrist + HAND_EXTENSION * (wrist - elbow)).tolist(), "palm_estimate"
                    found.append({"limb": limb, "start_ms": int(times[begin]), "end_ms": int(times[last]), "x": float(np.clip(x, 0, 1)), "y": float(np.clip(y, 0, 1)), "anchor": anchor})
                begin = index if slow else None          # a new tracked run can start its own rest at this sample
    return sorted(found, key=lambda r: r["start_ms"])


def _nearest(point: np.ndarray, holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float, limit_L: float) -> int | None:
    best, best_edge = None, limit_L
    for index, hold in enumerate(holds):
        edge = max(0.0, float(np.hypot(point[0] - hold["x"] * width, point[1] - hold["y"] * height)) - hold["radius"] * width) / length_px
        if edge <= best_edge:
            best, best_edge = index, edge
    return best


def visits(rests: Sequence[dict[str, Any]], holds: Sequence[dict[str, Any]], width: int, height: int, length_px: float) -> list[dict[str, Any]]:
    """Which marked hold, if any, each rest was near. Nearness is geometry in the picture, never contact."""
    found = []
    for rest in rests:
        hand = rest["limb"] in HANDS
        allowed = [i for i, h in enumerate(holds) if h.get("use", "") in ({"", "hand", "both"} if hand else {"", "foot", "both"})]
        index = _nearest(np.array([rest["x"] * width, rest["y"] * height]), [holds[i] for i in allowed], width, height, length_px, HAND_NEAR_L if hand else FOOT_NEAR_L)
        hold = None if index is None else allowed[index]
        if found and found[-1]["limb"] == rest["limb"] and found[-1]["hold_index"] == hold and hold is not None:
            found[-1]["end_ms"] = rest["end_ms"]
            continue
        found.append({"limb": rest["limb"], "start_ms": rest["start_ms"], "end_ms": rest["end_ms"], "hold_index": hold, "anchor": rest["anchor"]})
    return found


def to_reference(rests: Sequence[dict[str, Any]], registered: Sequence[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    """Move rest points into the wall picture's coordinates, using the nearest frame that was lined up with it.

    A rest with no lined-up frame within a few seconds is dropped, because where it lay on the wall picture is unknown.
    """
    if not registered:
        return []
    times = np.array([item["t"] for item in registered], float)
    moved = []
    for rest in rests:
        middle = (rest["start_ms"] + rest["end_ms"]) / 2
        index = int(np.argmin(np.abs(times - middle)))
        if abs(times[index] - middle) > MAX_REGISTRATION_GAP_MS:
            continue
        point = np.array(registered[index]["matrix"]) @ np.array([rest["x"] * width, rest["y"] * height, 1.0])
        x, y = point[0] / point[2] / width, point[1] / point[2] / height
        if 0 <= x <= 1 and 0 <= y <= 1:
            moved.append({**rest, "x": float(x), "y": float(y)})
    return moved


def assign_roles(holds: Sequence[dict[str, Any]], rests: Sequence[dict[str, Any]], width: int, height: int, length_px: float) -> dict[str, Any]:
    """Proposed start, finish, and hand or foot use for each hold, from which limbs rested near it.

    `rests` must already be in the holds' picture coordinates. The result is a proposal to confirm, not a record of contact.
    A hold a hand rested near is proposed for hands and feet, since feet often follow hands onto the same hold.
    """
    proposed = [{"role": "", "use": "", "visited_by": []} for _ in holds]
    for rest in rests:
        hand = rest["limb"] in HANDS
        index = _nearest(np.array([rest["x"] * width, rest["y"] * height]), holds, width, height, length_px, HAND_NEAR_L if hand else FOOT_NEAR_L)
        if index is not None and rest["limb"] not in proposed[index]["visited_by"]:
            proposed[index]["visited_by"].append(rest["limb"])
    for item in proposed:
        by_hand = any(limb in HANDS for limb in item["visited_by"])
        item["use"] = "both" if by_hand else "foot" if item["visited_by"] else ""
    hand_rests = [r for r in rests if r["limb"] in HANDS]
    # Finish: the highest hold in the picture. A start is not proposed: on the two routes with a marked start, rules based on
    # tracked hands picked a neighboring hold both times, so the climber taps the start instead.
    if len(holds) >= 2:
        top = min(range(len(holds)), key=lambda i: holds[i]["y"])
        proposed[top]["role"], proposed[top]["use"] = "finish", "hand"
    notes = []
    if not any(p["role"] == "start" for p in proposed):
        notes.append("Choose your start hold or holds. They are not proposed automatically.")
    if not any(p["role"] == "finish" for p in proposed):
        notes.append("No finish hold could be proposed. Set it yourself.")
    unvisited = sum(not p["visited_by"] for p in proposed)
    if unvisited:
        notes.append(f"No tracked limb rested near {unvisited} of the holds, so their use is left unset. A hidden hand or foot may still have used them.")
    return {"method": AUTO_VERSION, "holds": proposed, "notes": notes, "rests_used": len(rests), "hand_rests": len(hand_rests),
            "disclaimer": "Proposed from where tracked hands and feet rested. Resting near a mark does not show the hold was touched, so check each one."}
