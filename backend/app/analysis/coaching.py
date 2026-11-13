"""Timestamped coaching hypotheses built from stored measurements.

Every card is a testable suggestion, not a diagnosis. Nothing here can see contact, grip,
sole angle, friction, force, fatigue, or depth from the wall. Reaches that cannot be
judged are listed as such, and reaches that look fine are listed as counterexamples, so
an empty card list is a valid result. All thresholds are unvalidated development values.
"""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

from . import beta, route_auto, story as story_module
from .explain import NAMES, clock, is_uncertain, limb_of, limb_state

COACHING_VERSION = "coaching-v2"
MAX_CARDS = 8
MAX_PER_KIND = 3
FOOTS = ("left_foot", "right_foot")
SOURCES = {
    "seifert2015": {"title": "Seifert, Boulanger, Orth, Davids (2015). Environmental design shapes perceptual-motor exploration, learning, and transfer in climbing. Frontiers in Psychology.",
                    "url": "https://www.frontiersin.org/articles/10.3389/fpsyg.2015.01819/full"},
    "straight_arms": {"title": "Philadelphia Rock Gyms. What is straight-arming and why every climber should do it (coaching article).", "url": "https://philarockgym.com/?p=25593"},
    "footwork_basics": {"title": "Sportrock Climbing Centers. Basics of footwork (coaching article, including the Silent Traverse drill).", "url": "https://www.sportrock.com/post/basics-of-footwork"},
    "smearing": {"title": "Philadelphia Rock Gyms. What is smearing? (coaching article).", "url": "https://philarockgym.com/?p=26439"},
    "feet_first": {"title": "Bouldering Boss. 10 bouldering habits to avoid, and what to do instead (coaching article).", "url": "https://boulderingboss.com/new-at-bouldering-10-habits-to-avoid/"},
    "mediapipe": {"title": "Google. MediaPipe Pose Landmarker documentation.", "url": "https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker"},
}
# Operational heuristics, reported with every result. They are not validated climbing standards.
CRITERIA = {
    "reach_min_rise_L": 0.5,                 # a hand must rise this far to count as a reach
    "setup_window_ms": 1500,                 # time before a reach examined for foot setup
    "follow_window_ms": 1500,                # time after a reach examined for a following step
    "follow_early_ms": 200,                  # a following step may begin this long before the reach ends
    "follow_foot_min_rise_L": 0.4,
    "arm_straightness_min": 0.97,            # shoulder-wrist distance over shoulder-elbow-wrist length, about 150 degrees or straighter
    "arm_extension_min": 0.88,               # shoulder-wrist distance over this attempt's own 95th percentile arm length
    "arm_min_samples": 30,                   # samples needed before an attempt-specific arm length means anything
    "arm_end_window_ms": 200,
    "repeat_gap_ms": 2000,                   # same-foot episodes closer than this form a cluster
    "repeat_net_ratio_max": 0.6,             # net travel over summed travel; higher means the foot was progressing
    "repeat_reach_window_ms": 2000,
    "shift_min_ankle_L": 0.25,
    "shift_min_toe_L": 0.2,
    "settle_window_ms": 600,
    "settle_max_excursion_L": 0.15,
    "near_hold_margin_L": 0.25,
    "alternative_min_gain_L": 0.15,
    "alternative_max_step_L": 1.5,
    "together_min_foot_rise_L": 0.4,
    "together_min_overlap": 0.4,             # share of the shorter episode during which both limbs moved
    "foot_led_ms": 300,                      # a foot starting this much earlier counts as setting up the reach
    "large_step_min_rise_L": 1.0,
    "ground_leave_ms": 1500,                 # steps this early are treated as leaving the ground
    "intermediate_min_step_L": 0.3,
    "pause_min_ms": 3500,
}
C = CRITERIA


def _id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12]


class Poses:
    """Valid joints from overlay.json, addressed by canonical time."""

    def __init__(self, samples: Sequence[dict[str, Any]], width: int, height: int, length_px: float):
        self.samples, self.width, self.height, self.length = samples, width, height, length_px
        self.times = np.array([s["t"] for s in samples], float)

    def between(self, start: float, end: float) -> list[dict[str, Any]]:
        return [s for s in self.samples if start <= s["t"] <= end]

    def nearest(self, ms: float, tolerance: float = 60) -> dict[str, Any] | None:
        if not len(self.times):
            return None
        index = int(np.argmin(np.abs(self.times - ms)))
        return self.samples[index] if abs(self.times[index] - ms) <= tolerance else None

    def point(self, sample: dict[str, Any], name: str) -> np.ndarray | None:
        joint = sample["joints"].get(name)
        return None if joint is None else np.array([joint[0] * self.width, joint[1] * self.height])

    def distance_L(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.linalg.norm(a - b)) / self.length


def arm_references(poses: Poses) -> dict[str, tuple[float, int] | None]:
    """Each arm's own 95th percentile projected length, or None when it was seldom seen."""
    found: dict[str, tuple[float, int] | None] = {}
    for side in ("left", "right"):
        lengths = []
        for sample in poses.samples:
            s, e, w = (poses.point(sample, f"{side}_{part}") for part in ("shoulder", "elbow", "wrist"))
            if s is not None and e is not None and w is not None:
                lengths.append(float(np.linalg.norm(s - e) + np.linalg.norm(e - w)))
        found[side] = (float(np.percentile(lengths, 95)), len(lengths)) if len(lengths) >= C["arm_min_samples"] else None
    return found


def arm_at_reach_end(event: dict[str, Any], poses: Poses, references: dict[str, Any]) -> dict[str, Any]:
    """Projected straightness and extension over the last samples. A foreshortened arm reads as shorter, never longer."""
    side = event["hand"]
    if references.get(side) is None:
        return {"status": "unavailable", "reason": "This arm was tracked too rarely to estimate its length."}
    straight, extended = [], []
    for sample in poses.between(event["end_ms"] - C["arm_end_window_ms"], event["end_ms"]):
        s, e, w = (poses.point(sample, f"{side}_{part}") for part in ("shoulder", "elbow", "wrist"))
        if s is None or e is None or w is None:
            continue
        chain = float(np.linalg.norm(s - e) + np.linalg.norm(e - w))
        straight.append(float(np.linalg.norm(s - w)) / chain if chain else 0.0)
        extended.append(float(np.linalg.norm(s - w)) / references[side][0])
    if len(straight) < 2:
        return {"status": "unavailable", "reason": "The shoulder, elbow, and wrist were not all tracked at the end of this reach."}
    straightness, extension = float(np.median(straight)), float(np.median(extended))
    return {"status": "available", "straightness": round(straightness, 3), "extension": round(extension, 3),
            "extended": straightness >= C["arm_straightness_min"] and extension >= C["arm_extension_min"], "samples": len(straight)}


def _window_states(start: int, end: int, events: Sequence[dict[str, Any]], series: dict[str, Any], limbs: Sequence[str]) -> dict[str, dict[str, Any]]:
    window = {"id": "__window__", "start_ms": start, "end_ms": end}
    return {limb: limb_state(window, events, series, limb) for limb in limbs}


def _following_step(event: dict[str, Any], events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    earliest, latest = event["end_ms"] - C["follow_early_ms"], event["end_ms"] + C["follow_window_ms"]
    options = [e for e in events if e["type"] == "foot_motion" and not is_uncertain(e) and earliest <= e["start_ms"] <= latest
               and e["evidence"]["net_up_L"] >= C["follow_foot_min_rise_L"] and e["start_ms"] > event["start_ms"]]
    return min(options, key=lambda e: e["start_ms"], default=None)


def _state_text(states: dict[str, dict[str, Any]]) -> str:
    words = {"quiet": "nearly still", "drifted": "shifted slowly", "moved": "moved", "unknown": "unknown"}
    return "; ".join(f"{NAMES[limb]}: {words[item['state']]}" for limb, item in states.items())


def _position(event: dict[str, Any], series: dict[str, Any], limb: str, ms: float) -> dict[str, float] | None:
    times, data = series["t"], series["limbs"][limb]
    usable = [i for i, t in enumerate(times) if abs(t - ms) <= 60 and data["x"][i] is not None]
    if not usable:
        return None
    index = min(usable, key=lambda i: abs(times[i] - ms))
    return {"x": data["x"][index], "y": data["y"][index]}


def _base_card(kind: str, title: str, event: dict[str, Any], start_ms: int, end_ms: int, limbs: Sequence[str], **fields: Any) -> dict[str, Any]:
    return {"id": _id("cue", kind, limb_of(event), start_ms, end_ms), "primary_event_id": None if kind in {"long_pause", "repeat_foot_adjust"} else event["id"], "kind": kind, "title": title, "start_ms": start_ms, "end_ms": end_ms,
            "status_label": "Hypothesis to test", "limbs": list(limbs), "alternatives": [], "map_action": None, **fields}


UNCERTAIN_ALWAYS = ("One camera cannot see contact, grip, force, or how far the hips are from the wall. "
                    "Thresholds are unvalidated development values.")


def _measurement(label: str, value: str, criterion: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "criterion": criterion}


def _sequence_card(event, step, setup, arm) -> dict[str, Any]:
    hand, foot = NAMES[limb_of(event)], NAMES[limb_of(step)]
    gap = (step["start_ms"] - event["end_ms"]) / 1000
    rise = step["evidence"]["net_up_L"]
    timing = f"{gap:.1f} s after the hand finished" if gap >= 0 else "just as the hand finished"
    arm_row = (_measurement("Arm at end of reach", f"{arm['straightness']:.2f} straightness, {arm['extension']:.2f} of this arm's tracked length")
               if arm["status"] == "available" else _measurement("Arm at end of reach", "not measurable here"))
    return _base_card(
        "step_after_reach", "Try the step before the reach", event, event["start_ms"], step["end_ms"], [limb_of(event), limb_of(step)],
        moment=f"At {clock(event['start_ms'])} your {hand} rose {event['evidence']['net_up_L']:.2f} torso lengths. "
               f"Your {foot} then rose {rise:.2f} torso lengths, starting {timing}.",
        measurements=[
            _measurement("Hand rise", f"{event['evidence']['net_up_L']:.2f} L", f"at least {C['reach_min_rise_L']} L"),
            _measurement("Foot rise after", f"{rise:.2f} L, {gap:+.1f} s from the end of the reach", f"at least {C['follow_foot_min_rise_L']} L within {C['follow_window_ms'] / 1000:g} s"),
            _measurement("Feet in the 1.5 s before", _state_text(setup), "no foot step"), arm_row],
        why="Moving the feet first can let the legs raise the body, so the hand arrives with more room. On this move the step came after the reach, so the reach had to be made from the lower foot position.",
        try_this=f"Next attempt, step your {foot} up first, toward where it ended at {clock(step['end_ms'])}, then reach with your {hand}. Compare how controlled the hand feels when it arrives.",
        keep_if="The first hand may have been needed to make the step possible, or this may be a deliberate dynamic move. If so, your order may be the right one.",
        uncertainty=[UNCERTAIN_ALWAYS, "The video cannot tell whether the foot could have reached that spot before the hand moved."],
        sources=["feet_first"], target={"limb": limb_of(step), "ms": step["end_ms"]})


def _extended_card(event, setup, arm, poses, series) -> dict[str, Any]:
    hand = NAMES[limb_of(event)]
    start_y = {foot: _position(event, series, foot, event["start_ms"]) for foot in FOOTS}
    known = {foot: p["y"] for foot, p in start_y.items() if p}
    lower = max(known, key=known.get) if len(known) == 2 else None
    foot_text = f"Try raising your {NAMES[lower]} a little first, if there is something to stand on, then reach." if lower else "Try moving a foot up first, if there is something to stand on, then reach."
    return _base_card(
        "extended_reach", "Reach ended with the arm near full length", event, event["start_ms"], event["end_ms"], [limb_of(event), *([lower] if lower else [])],
        moment=f"At {clock(event['end_ms'])} your {hand} finished a {event['evidence']['net_up_L']:.2f} torso-length rise with the arm close to its full tracked length, and neither foot stepped in the 1.5 s before.",
        measurements=[
            _measurement("Hand rise", f"{event['evidence']['net_up_L']:.2f} L", f"at least {C['reach_min_rise_L']} L"),
            _measurement("Arm straightness in the picture", f"{arm['straightness']:.2f}", f"at least {C['arm_straightness_min']}"),
            _measurement("Shoulder-to-wrist, of this arm's tracked length", f"{arm['extension']:.2f}", f"at least {C['arm_extension_min']}"),
            _measurement("Feet in the 1.5 s before", _state_text(setup), "no foot step")],
        why="Reaching near full arm length leaves little room to adjust at the end of the move. A higher foot can bring the hand to the hold with more room.",
        try_this=f"{foot_text} Compare whether you arrive with some bend left in the arm.",
        keep_if="A long straight arm is often good climbing, because it lets the skeleton hang the load. If you reached the hold under control, keep it.",
        uncertainty=[UNCERTAIN_ALWAYS, "This is 2D arm length in the picture, so it cannot show strain or that the arm was overextended."],
        sources=["straight_arms", "feet_first"], target=None)


def _together_card(event, foot_event, overlap, lead_ms, arm) -> dict[str, Any]:
    hand, foot = NAMES[limb_of(event)], NAMES[limb_of(foot_event)]
    first = f"The {hand} started {-lead_ms / 1000:.1f} s earlier." if lead_ms < -100 else "They started at about the same time."
    arm_row = (_measurement("Arm at end of reach", f"{arm['straightness']:.2f} straightness, {arm['extension']:.2f} of this arm's tracked length")
               if arm["status"] == "available" else _measurement("Arm at end of reach", "not measurable here"))
    return _base_card(
        "hand_foot_together", "Hand and foot moved up together", event, min(event["start_ms"], foot_event["start_ms"]), max(event["end_ms"], foot_event["end_ms"]),
        [limb_of(event), limb_of(foot_event)],
        moment=f"At {clock(event['start_ms'])} your {hand} rose {event['evidence']['net_up_L']:.2f} torso lengths while your {foot} rose {foot_event['evidence']['net_up_L']:.2f}. {first}",
        measurements=[
            _measurement("Time both were moving", f"{overlap * 100:.0f}% of the shorter movement", f"at least {C['together_min_overlap'] * 100:.0f}%"),
            _measurement("Foot start relative to hand", f"{lead_ms / 1000:+.1f} s (positive means the foot went first)", f"foot not more than {C['foot_led_ms'] / 1000:g} s ahead"),
            _measurement("Hand rise", f"{event['evidence']['net_up_L']:.2f} L", f"at least {C['reach_min_rise_L']} L"),
            _measurement("Foot rise", f"{foot_event['evidence']['net_up_L']:.2f} L", f"at least {C['together_min_foot_rise_L']} L"), arm_row],
        why="If a hand and a foot both leave at once, the body may be moving with two points of support during that time. Separating them gives a chance to settle the foot before committing the hand.",
        try_this=f"Try it in two stages: place your {foot} and let it settle, then move your {hand}. See whether the reach feels more controlled, or whether you lose momentum.",
        keep_if="Moving together can be efficient and is normal on dynamic or steep moves. If this one was deliberate and controlled, keep it.",
        uncertainty=[UNCERTAIN_ALWAYS, "The video shows that both tracked points moved. It cannot show which limbs were on holds."],
        sources=["feet_first"], target=None)


def _large_step_cards(events, series, poses, bounds, hold_context, not_flagged) -> list[dict[str, Any]]:
    cards = []
    for event in sorted((e for e in events if e["type"] == "foot_motion"), key=lambda e: e["start_ms"]):
        if is_uncertain(event) or event["truncated"] or event["evidence"]["net_up_L"] < C["large_step_min_rise_L"]:
            continue
        foot = NAMES[limb_of(event)]
        if event["start_ms"] - bounds["start"] < C["ground_leave_ms"]:
            not_flagged.append({"start_ms": event["start_ms"], "text": f"{foot.capitalize()} at {clock(event['start_ms'])}: this large step was at the very start, so it may simply be leaving the ground."})
            continue
        rise = event["evidence"]["net_up_L"]
        card = _base_card(
            "large_step", "Large single foot move", event, event["start_ms"], event["end_ms"], [limb_of(event)],
            moment=f"At {clock(event['start_ms'])} your {foot} rose {rise:.2f} torso lengths in one move lasting {event['evidence']['duration_ms'] / 1000:.1f} s.",
            measurements=[_measurement("Foot rise", f"{rise:.2f} L", f"at least {C['large_step_min_rise_L']} L"),
                          _measurement("Peak foot speed", f"{event['evidence']['peak_speed_L_per_s']:.1f} L/s")],
            why="A very high step is powerful when the hips can follow it, but it can be hard to stand up from. An intermediate foot, even a smear, may split the move into two easier parts.",
            try_this=f"Look for a spot about halfway up, roughly {rise / 2:.1f} torso lengths above where your {foot} started. Try one small intermediate step or a smear there, then step to the high foot.",
            keep_if="If you stood up smoothly from this foot, a high step may be the better choice. High steps are ordinary technique.",
            uncertainty=[UNCERTAIN_ALWAYS, "Whether a usable intermediate spot exists cannot be seen from the tracked points. Smearing depends on the wall surface and shoe, which the video cannot measure."],
            sources=["smearing"], target=None)
        if not hold_context:
            card["map_action"] = "Mark the holds on this route to see whether a marked foothold lies between these two heights."
        elif not hold_context["usable"]:
            card["map_action"] = hold_context["message"]
        else:
            begin, end = _position(event, series, limb_of(event), event["start_ms"]), _position(event, series, limb_of(event), event["end_ms"])
            if begin and end:
                options = []
                for index, hold in enumerate(hold_context["holds"]):
                    if hold.get("use", "") not in beta.FOOT_USES or not end["y"] < hold["y"] < begin["y"]:
                        continue
                    step = float(np.hypot((hold["x"] - begin["x"]) * poses.width, (hold["y"] - begin["y"]) * poses.height)) / poses.length
                    if step >= C["intermediate_min_step_L"]:
                        options.append({"limb": limb_of(event), "hold_index": index, "hold_id": hold["id"], "step_L": round(step, 2), "margin_L": None, "gain_L": None, "x": hold["x"], "y": hold["y"]})
                card["alternatives"] = sorted(options, key=lambda o: o["step_L"])[:2]
                if not options:
                    card["alternative_summary"] = "No marked foothold lies between these two foot heights. An unmarked spot or a smear might still work."
        cards.append(card)
    return cards


def _pause_cards(events, series, bounds, cannot) -> list[dict[str, Any]]:
    moving = sorted((e for e in events if limb_of(e)), key=lambda e: e["start_ms"])
    cards = []
    for before, after in zip(moving, moving[1:]):
        latest = max(e["end_ms"] for e in moving if e["start_ms"] <= before["start_ms"])
        if after["start_ms"] - latest < C["pause_min_ms"]:
            continue
        states = _window_states(latest + 100, after["start_ms"] - 100, events, series, FOOTS)
        label = f"Pause at {clock(latest)}"
        if any(item["state"] in {"unknown", "moved"} for item in states.values()):
            cannot.append({"start_ms": latest, "text": f"{label}: both feet were not tracked continuously, so this quiet time cannot be read as a pause."})
            continue
        seconds = (after["start_ms"] - latest) / 1000
        tracked = _window_states(latest + 100, after["start_ms"] - 100, events, series, ("left_wrist", "right_wrist"))
        hands = _state_text(tracked)
        cards.append(_base_card(
            "long_pause", "Long stop before the next move", after, latest, after["start_ms"], [*FOOTS, limb_of(after)],
            moment=f"From {clock(latest)} to {clock(after['start_ms'])} ({seconds:.1f} s) no tracked limb made a movement episode. The next one detected was your {NAMES[limb_of(after)]}."
                   + (" Hand tracking was incomplete here, so a hand may have moved unseen." if any(item["state"] == "unknown" for item in tracked.values()) else ""),
            measurements=[_measurement("Time without a movement episode", f"{seconds:.1f} s", f"at least {C['pause_min_ms'] / 1000:g} s"),
                          _measurement("Feet during it", _state_text(states), "tracked and not stepping"), _measurement("Hands during it", hands)],
            why="A long stop may be useful rest, or it may be working out the next move while holding on. Planning from the ground or from a better rest can save that time on the wall.",
            try_this="If you were working out the next move, plan it from the ground before your next attempt and decide your next two moves in advance. If you were resting, try hanging from a straighter arm so the rest costs less.",
            keep_if="A planned rest is not a mistake, and pausing to shake out or read the route is often the right choice.",
            uncertainty=[UNCERTAIN_ALWAYS, "The video cannot tell a planned rest from hesitation, and hand tracking may be partial here."],
            sources=["straight_arms", "seifert2015"], target=None))
    return cards


def _clusters(events: Sequence[dict[str, Any]], limb: str) -> list[list[dict[str, Any]]]:
    found = sorted((e for e in events if limb_of(e) == limb and not is_uncertain(e)), key=lambda e: e["start_ms"])
    groups: list[list[dict[str, Any]]] = []
    for event in found:
        if groups and event["start_ms"] - groups[-1][-1]["end_ms"] <= C["repeat_gap_ms"]:
            groups[-1].append(event)
        else:
            groups.append([event])
    return [g for g in groups if len(g) >= 2]


def _repeat_cards(events, not_flagged) -> list[dict[str, Any]]:
    cards = []
    reaches = [e for e in events if e["type"] == "wrist_motion"]
    for limb in FOOTS:
        for group in _clusters(events, limb):
            right = sum(e["evidence"]["net_image_right_L"] for e in group)
            up = sum(e["evidence"]["net_up_L"] for e in group)
            net = float(np.hypot(right, up))
            travel = sum(e["evidence"]["path_length_L"] for e in group)
            start, end = group[0]["start_ms"], group[-1]["end_ms"]
            ratio = net / travel if travel else 1.0
            label = f"{NAMES[limb]} at {clock(start)}"
            if ratio > C["repeat_net_ratio_max"]:
                not_flagged.append({"start_ms": start, "text": f"{label.capitalize()}: {len(group)} moves went steadily in one direction (net {ratio:.2f} of travel), which looks like progress, not adjustment."})
                continue
            reach = next((r for r in reaches if start - C["repeat_reach_window_ms"] <= r["start_ms"] <= end + C["repeat_reach_window_ms"]), None)
            if reach is None:
                not_flagged.append({"start_ms": start, "text": f"{label.capitalize()}: repeated moves with no hand reach nearby, so nothing suggests they delayed a move."})
                continue
            cards.append(_base_card(
                "repeat_foot_adjust", "Repeated foot adjustment near a reach", group[0], start, end, [limb, limb_of(reach)],
                moment=f"Between {clock(start)} and {clock(end)} your {NAMES[limb]} moved {len(group)} times but ended only {net:.2f} torso lengths from where it began. Your {NAMES[limb_of(reach)]} reached at {clock(reach['start_ms'])}.",
                measurements=[
                    _measurement("Foot moves", str(len(group)), f"at least 2, each within {C['repeat_gap_ms'] / 1000:g} s"),
                    _measurement("Net travel over summed travel", f"{ratio:.2f}", f"at most {C['repeat_net_ratio_max']}"),
                    _measurement("Summed travel", f"{travel:.2f} L")],
                why="Repeated resets can spend time and attention just before a move. Exploring is not always bad, though, and research links some exploratory movement to learning.",
                try_this=f"Pick the spot for your {NAMES[limb]} before it leaves, then place it once and quietly. Then make the reach without moving that foot again.",
                keep_if="Testing a foothold on a first try is reasonable exploration. If you were reading the problem, or the placement was hard to see, keep exploring.",
                uncertainty=[UNCERTAIN_ALWAYS, "The ankle point can shift when the foot pivots, without the foot leaving its hold."],
                sources=["seifert2015", "footwork_basics"], target=None))
    return cards


def _foot_part_travel(start: int, end: int, poses: Poses, name: str) -> float | None:
    points = [poses.point(s, name) for s in poses.between(start, end)]
    if not points or any(p is None for p in points):
        return None
    return max(poses.distance_L(p, points[0]) for p in points)


def _shift_cards(events, poses, not_flagged, cannot) -> list[dict[str, Any]]:
    cards = []
    for event in (e for e in events if e["type"] == "wrist_motion" and e.get("context")):
        for limb in FOOTS:
            item = event["context"]["limbs"][limb]
            if item["state"] != "drifted" or item["max_excursion_L"] < C["shift_min_ankle_L"]:
                continue
            side = limb.split("_")[0]
            toe = _foot_part_travel(event["start_ms"], event["end_ms"], poses, f"{side}_foot_index")
            label = f"{NAMES[limb]} during the {NAMES[limb_of(event)]} move at {clock(event['start_ms'])}"
            if toe is None:
                cannot.append({"start_ms": event["start_ms"], "text": f"{label.capitalize()}: the ankle shifted, but the toe was not tracked throughout, so foot movement cannot be separated from a heel change."})
            elif toe < C["shift_min_toe_L"]:
                not_flagged.append({"start_ms": event["start_ms"], "text": f"{label.capitalize()}: the ankle shifted {item['max_excursion_L']:.2f} L but the toe stayed within {toe:.2f} L, which fits a heel or ankle change on a planted foot."})
            else:
                cards.append(_base_card(
                    "foot_shift_during_reach", "Foot shifted while the hand moved", event, event["start_ms"], event["end_ms"], [limb, limb_of(event)],
                    moment=f"While your {NAMES[limb_of(event)]} moved at {clock(event['start_ms'])}, your {NAMES[limb]} shifted {item['max_excursion_L']:.2f} torso lengths without a distinct step.",
                    measurements=[
                        _measurement("Ankle excursion", f"{item['max_excursion_L']:.2f} L", f"at least {C['shift_min_ankle_L']} L"),
                        _measurement("Toe excursion", f"{toe:.2f} L", f"at least {C['shift_min_toe_L']} L, so the toe moved too")],
                    why="A foot that shifts during a reach may have been repositioned, turned, or lost its place. Each would change how you stand on it during the move.",
                    try_this=f"Before the next reach, settle your {NAMES[limb]} and press through the toe. Then see whether it stays put as the hand moves.",
                    keep_if="Pivoting or swapping the foot on purpose during a move is common technique.",
                    uncertainty=[UNCERTAIN_ALWAYS, "This cannot show a slip. Rewatch the foot to see what happened."],
                    sources=["footwork_basics"], target=None))
    return cards


def _evaluate_reaches(events, series, poses, references, bounds) -> tuple[list[dict], list[dict], list[dict], dict]:
    cards, not_flagged, cannot = [], [], []
    tally = {"reaches_evaluated": 0, "with_foot_setup_before": 0, "moved_with_feet": 0}
    for event in sorted((e for e in events if e["type"] == "wrist_motion"), key=lambda e: e["start_ms"]):
        evidence = event["evidence"]
        if evidence.get("net_up_L", 0) < C["reach_min_rise_L"]:
            continue
        label = f"{NAMES[limb_of(event)].capitalize()} reach at {clock(event['start_ms'])}"
        if event["tracking_quality"]["label"] == "weak" or event["truncated"]:
            why = "its tracking was weak" if event["tracking_quality"]["label"] == "weak" else "its start or end was cut off"
            cannot.append({"start_ms": event["start_ms"], "text": f"{label}: not judged because {why}."})
            continue
        if event["start_ms"] - C["setup_window_ms"] < bounds["start"]:
            cannot.append({"start_ms": event["start_ms"], "text": f"{label}: too close to the start of the attempt to see any setup."})
            continue
        setup = _window_states(event["start_ms"] - C["setup_window_ms"], event["start_ms"], events, series, FOOTS)
        tally["reaches_evaluated"] += 1
        if any(item["state"] == "moved" for item in setup.values()):
            tally["with_foot_setup_before"] += 1
            not_flagged.append({"start_ms": event["start_ms"], "text": f"{label}: a foot moved in the 1.5 s before, so the feet were being set up first."})
            continue
        companions = [f for f in events if f["type"] == "foot_motion" and not is_uncertain(f) and f["start_ms"] <= event["end_ms"] and f["end_ms"] >= event["start_ms"]]
        if companions:
            tally["moved_with_feet"] += 1
            foot_event = max(companions, key=lambda f: min(f["end_ms"], event["end_ms"]) - max(f["start_ms"], event["start_ms"]))
            shared = min(foot_event["end_ms"], event["end_ms"]) - max(foot_event["start_ms"], event["start_ms"])
            overlap = shared / max(1, min(foot_event["end_ms"] - foot_event["start_ms"], event["end_ms"] - event["start_ms"]))
            lead = event["start_ms"] - foot_event["start_ms"]
            if lead >= C["foot_led_ms"]:
                not_flagged.append({"start_ms": event["start_ms"], "text": f"{label}: the foot started {lead / 1000:.1f} s earlier, so the foot led this move."})
            elif foot_event["evidence"]["net_up_L"] < C["together_min_foot_rise_L"] or overlap < C["together_min_overlap"]:
                not_flagged.append({"start_ms": event["start_ms"], "text": f"{label}: a foot moved during it, but too little or too briefly to count as moving together."})
            else:
                cards.append((event, _together_card(event, foot_event, overlap, lead, arm_at_reach_end(event, poses, references))))
            continue
        if any(item["state"] == "unknown" for item in setup.values()):
            unknown = ", ".join(NAMES[f] for f, item in setup.items() if item["state"] == "unknown")
            cannot.append({"start_ms": event["start_ms"], "text": f"{label}: foot setup is unknown because the {unknown} was not tracked continuously or was unstable."})
            continue
        arm = arm_at_reach_end(event, poses, references)
        step = _following_step(event, events)
        if step is not None:
            cards.append((event, _sequence_card(event, step, setup, arm)))
        elif arm["status"] == "unavailable":
            cannot.append({"start_ms": event["start_ms"], "text": f"{label}: {arm['reason']}"})
        elif arm["extended"]:
            cards.append((event, _extended_card(event, setup, arm, poses, series)))
        else:
            not_flagged.append({"start_ms": event["start_ms"], "text": f"{label}: feet stayed put, but the arm still had room (straightness {arm['straightness']:.2f}, extension {arm['extension']:.2f}), so nothing suggests a change."})
    return cards, not_flagged, cannot, tally


def _contact_point(sample: dict[str, Any], side: str, poses: Poses) -> tuple[np.ndarray | None, str]:
    toe = poses.point(sample, f"{side}_foot_index")
    if toe is not None:
        return toe, "toe"
    return poses.point(sample, f"{side}_ankle"), "ankle"


def _nearest_marked(point: np.ndarray, holds: Sequence[dict[str, Any]], poses: Poses) -> dict[str, Any] | None:
    best = None
    for index, hold in enumerate(holds):
        if hold.get("use", "") not in beta.FOOT_USES:
            continue
        center = np.array([hold["x"] * poses.width, hold["y"] * poses.height])
        radius = hold["radius"] * poses.width
        distance = float(np.linalg.norm(point - center))
        edge_L = max(0.0, distance - radius) / poses.length
        if best is None or edge_L < best["edge_L"]:
            best = {"hold_index": index, "hold_id": hold["id"], "edge_L": round(edge_L, 3)}
    return best


def foot_placements(events, series, poses, hold_context) -> list[dict[str, Any]]:
    """Where a foot appeared to settle after moving. Proximity to a marked hold is never treated as contact."""
    found = []
    for event in sorted((e for e in events if e["type"] == "foot_motion"), key=lambda e: e["end_ms"]):
        limb, side = limb_of(event), event["hand"]
        if is_uncertain(event) or event["evidence"].get("truncated_end"):
            continue
        state = limb_state({"id": "__settle__", "start_ms": event["end_ms"] + 100, "end_ms": event["end_ms"] + 100 + C["settle_window_ms"]}, events, series, limb)
        if state["state"] != "quiet":
            continue
        sample = poses.nearest(event["end_ms"] + C["settle_window_ms"] / 2)
        if sample is None:
            continue
        point, anchor = _contact_point(sample, side, poses)
        if point is None:
            continue
        item = {"id": _id("foot", limb, event["end_ms"]), "limb": limb, "event_id": event["id"], "landing_ms": event["end_ms"], "review_ms": int(sample["t"]),
                "x": round(float(point[0]) / poses.width, 5), "y": round(float(point[1]) / poses.height, 5), "anchor": anchor,
                "settle_excursion_L": state["max_excursion_L"], "proximity": "map_unavailable", "nearest_hold": None}
        if hold_context and hold_context["usable"]:
            nearest = _nearest_marked(point, hold_context["holds"], poses)
            item["nearest_hold"] = nearest
            item["proximity"] = ("no_foot_hold_marked" if nearest is None else "within_marked_region" if nearest["edge_L"] == 0
                                 else "near_marked_region" if nearest["edge_L"] <= C["near_hold_margin_L"] else "no_marked_hold_nearby")
        found.append(item)
    return found


def _alternative_setups(event, series, poses, body, hold_context) -> dict[str, Any] | None:
    """Foot holds that would give this reach more 2D slack than the observed foot position."""
    if body is None or not hold_context or not hold_context["usable"]:
        return None
    side = event["hand"]
    other = "right" if side == "left" else "left"
    start, length = event["start_ms"], poses.length
    target = _position(event, series, limb_of(event), event["end_ms"])
    feet = {foot: _position(event, series, foot, start) for foot in FOOTS}
    if target is None or any(p is None for p in feet.values()):
        return None
    scale = np.array([poses.width / length, poses.height / length])
    to_L = lambda p: np.array([p["x"], p["y"]]) * scale
    sample = poses.nearest(start)
    other_joint = None if sample is None else sample["joints"].get(f"{other}_wrist")
    hands = [to_L(target)] + ([np.array(other_joint) * scale] if other_joint else [])
    observed = {foot: to_L(p) for foot, p in feet.items()}
    baseline = beta.reach_margin(hands, list(observed.values()), body)
    holds = hold_context["holds"]
    options = []
    for foot in FOOTS:
        partner = next(f for f in FOOTS if f != foot)
        for index, hold in enumerate(holds):
            if hold.get("use", "") not in beta.FOOT_USES:
                continue
            place = np.array([hold["x"], hold["y"]]) * scale
            step = float(np.linalg.norm(place - observed[foot]))
            if step < 0.2 or step > C["alternative_max_step_L"]:
                continue
            start_hand = _position(event, series, limb_of(event), start)
            if start_hand is None:
                continue
            before = beta.reach_margin([to_L(start_hand), *hands[1:]], [place, observed[partner]], body)
            if before < beta.MIN_FEASIBLE_MARGIN_L:
                continue
            margin = beta.reach_margin(hands, [place, observed[partner]], body)
            if margin - baseline >= C["alternative_min_gain_L"]:
                options.append({"limb": foot, "hold_index": index, "hold_id": hold["id"], "step_L": round(step, 2), "margin_L": round(margin, 2), "gain_L": round(margin - baseline, 2),
                                "x": hold["x"], "y": hold["y"]})
    options.sort(key=lambda o: (-o["gain_L"], o["step_L"]))
    return {"observed_margin_L": round(baseline, 2), "other_hand_used": bool(other_joint), "options": options[:2]}


def _attach_alternatives(pairs, series, poses, body, hold_context) -> None:
    for event, card in pairs:
        result = _alternative_setups(event, series, poses, body, hold_context)
        if not hold_context:
            card["map_action"] = "Mark the holds on this route to get a specific foot setup to try."
        elif not hold_context["usable"]:
            card["map_action"] = hold_context["message"]
        elif result is None:
            card["map_action"] = "The limbs were not all tracked at this moment, so no specific foot setup could be compared."
        elif not result["options"]:
            card["alternative_summary"] = (f"No marked foothold within reach gave at least {C['alternative_min_gain_L']} L more 2D margin than your observed feet "
                                           f"({result['observed_margin_L']:.2f} L).")
        else:
            card["alternatives"] = result["options"]
            card["observed_margin_L"] = result["observed_margin_L"]
            card["alternative_note"] = None if result["other_hand_used"] else "Your other hand was not tracked here, so it was left out of this comparison."


KIND_PRIORITY = ["step_after_reach", "extended_reach", "repeat_foot_adjust", "foot_shift_during_reach", "hand_foot_together", "large_step", "long_pause"]
TOP_COUNT = 3
STORY_TOP = 2      # whole-attempt cards lead, then the most specific moments


def top_card_ids(cards: Sequence[dict[str, Any]]) -> list[str]:
    """Cards to start with: up to two whole-attempt cards, then up to three moments, one per kind in a fixed order of how specific the suggestion is."""
    lead = [c["id"] for c in cards if c.get("scope") == "attempt"][:STORY_TOP]
    moments = [c for c in cards if c.get("scope") != "attempt"]
    chosen: list[str] = []
    for kind in KIND_PRIORITY:
        first = next((c for c in moments if c["kind"] == kind), None)
        if first is not None and len(chosen) < TOP_COUNT:
            chosen.append(first["id"])
    for card in moments:
        if len(chosen) < TOP_COUNT and card["id"] not in chosen:
            chosen.append(card["id"])
    return [*lead, *chosen]


def at_a_glance(result: dict[str, Any], events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """A few plain facts about the attempt. Counts cover tracked time only, so each comes with its coverage."""
    coverage = result["coverage"]["detectors"]
    bounds = result["attempt_bounds_ms"]
    moving = sorted((e for e in events if limb_of(e) and not is_uncertain(e)), key=lambda e: e["start_ms"])
    longest, at, latest = 0, None, None
    for event in moving:
        if latest is not None and event["start_ms"] - latest > longest:
            longest, at = event["start_ms"] - latest, latest
        latest = event["end_ms"] if latest is None else max(latest, event["end_ms"])
    tracked = lambda *keys: [coverage[k]["fraction"] for k in keys]
    hands, feet = tracked("wrist_motion_left", "wrist_motion_right"), tracked("foot_motion_left", "foot_motion_right")
    notes = []
    if any(f is None or f < 0.6 for f in hands):
        notes.append("A hand was hidden for much of the attempt, so hand moves are undercounted.")
    if any(f is None or f < 0.6 for f in feet):
        notes.append("A foot was hidden for much of the attempt, so foot moves are undercounted.")
    return {"attempt_ms": bounds["end"] - bounds["start"], "hand_moves": sum(e["type"] == "wrist_motion" for e in moving),
            "foot_moves": sum(e["type"] == "foot_motion" for e in moving), "longest_gap_ms": longest or None, "longest_gap_at_ms": at,
            "hand_tracked": hands, "foot_tracked": feet, "notes": notes}


def observed_route(series: dict[str, Any], samples: Sequence[dict[str, Any]], hold_context: dict[str, Any] | None, width: int, height: int) -> dict[str, Any] | None:
    """Which marked holds each limb rested near, in order, and which were never approached. Requires a verified map."""
    if not hold_context or not hold_context["usable"] or not hold_context["holds"]:
        return None
    holds = hold_context["holds"]
    found = [v for v in route_auto.visits(route_auto.rest_points(series, samples), holds, width, height, series["L_px"]) if v["hold_index"] is not None]
    seen = {v["hold_index"] for v in found}
    return {"visits": found, "unvisited": [i for i in range(len(holds)) if i not in seen],
            "note": "Near means the tracked point rested close to the mark in the picture. It does not show the hold was touched, and a hidden limb may have used a hold listed as not approached."}


def _add_wall_plane_distances(cards, events, series, samples, plane, width: int, height: int) -> None:
    """Add each card's main movement measured on the wall plane, next to the picture value. Skipped where the plane does not apply."""
    torso = beta.plane_torso(samples, width, height, plane)
    if not torso:
        return
    by_id = {e["id"]: e for e in events}
    for card in cards:
        event = by_id.get(card.get("primary_event_id"))
        if event is None or limb_of(event) is None:
            continue
        begin, end = _position(event, series, limb_of(event), event["start_ms"]), _position(event, series, limb_of(event), event["end_ms"])
        if begin is None or end is None:
            continue
        ends_px = [[begin["x"] * width, begin["y"] * height], [end["x"] * width, end["y"] * height]]
        if not all(plane.covers(p) for p in ends_px):
            continue
        on_wall = plane.plane(ends_px)
        corrected = float(np.linalg.norm(on_wall[1] - on_wall[0])) / torso
        card["measurements"].append(_measurement(
            f"Net {NAMES[limb_of(event)]} movement on the wall plane", f"{corrected:.2f} L ({event['evidence']['net_displacement_L']:.2f} L as it appears in the picture)",
            "corrected for the wall's angle using the bolt grid; rules above still use picture values"))


def _story_cards(story: dict[str, Any]) -> list[dict[str, Any]]:
    """Whole-attempt takeaways in the same shape as moment cards, so they can be opened, watched, and answered the same way."""
    return [{"id": item["id"], "kind": f"story_{item['kind']}", "scope": "attempt", "title": item["title"], "start_ms": item["start_ms"], "end_ms": item["end_ms"],
             "status_label": "Whole attempt", "limbs": item["limbs"], "moment": item["observed"], "why": item["why"], "try_this": item["try_this"], "keep_if": item["keep_if"],
             "measurements": [_measurement(m["label"], m["value"]) for m in item["measurements"]], "uncertainty": [item["verify"], story["note"]],
             "sources": [], "alternatives": [], "map_action": None, "target": None, "moments": item.get("moments", [])} for item in story.get("takeaways", [])]


def build_coaching(result: dict[str, Any], events: list[dict[str, Any]], series: dict[str, Any], samples: Sequence[dict[str, Any]],
                   width: int, height: int, hold_context: dict[str, Any] | None = None, plane=None) -> dict[str, Any]:
    """Cards, placements, counterexamples, and unknowns for one analysis. Pure: the same inputs give the same output."""
    length = series["L_px"]
    base = {"version": COACHING_VERSION, "criteria": CRITERIA, "sources": SOURCES,
            "disclaimer": "These are hypotheses to test on the wall, not diagnoses. Thresholds are unvalidated, and no accuracy has been measured."}
    if not length:
        return {**base, "available": False, "reason": "This attempt has no reliable body scale, so no coaching can be derived."}
    poses = Poses(samples, width, height, length)
    bounds = result["attempt_bounds_ms"]
    references = arm_references(poses)
    pairs, not_flagged, cannot, tally = _evaluate_reaches(events, series, poses, references, bounds)
    body = beta.body_model(samples, width, height, length)
    _attach_alternatives(pairs, series, poses, body, hold_context)
    cards = ([card for _, card in pairs] + _repeat_cards(events, not_flagged) + _shift_cards(events, poses, not_flagged, cannot)
             + _large_step_cards(events, series, poses, bounds, hold_context, not_flagged) + _pause_cards(events, series, bounds, cannot))
    order = {"step_after_reach": 0, "extended_reach": 1, "repeat_foot_adjust": 2, "foot_shift_during_reach": 3, "hand_foot_together": 4, "large_step": 5, "long_pause": 6}
    chosen: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda c: (order[c["kind"]], c["start_ms"])):
        if sum(c["kind"] == card["kind"] for c in chosen) < MAX_PER_KIND and len(chosen) < MAX_CARDS:
            chosen.append(card)
    story = story_module.build_story(result, events, samples, width, height, length)
    wall_end = story["on_wall"]["end_ms"] if story.get("available") and story["drop"] else None
    wall_start = story["on_wall"]["start_ms"] if story.get("available") and story["on_wall"]["started_by"] != "start_of_clip" else None
    # Nothing before the climber left the ground or after they left the wall is climbing.
    off_wall = lambda ms: (wall_end is not None and ms >= wall_end) or (wall_start is not None and ms < wall_start)
    after_wall = sum(off_wall(c["start_ms"]) for c in chosen)
    chosen = [c for c in chosen if not off_wall(c["start_ms"])]
    story_cards = _story_cards(story) if story.get("available") else []
    stops = [c for c in story_cards if c["kind"] in {"story_longest_stop", "story_slow_start"}]
    # A whole-attempt card about a stay replaces the pause cards inside it, so one stop is not reported twice.
    chosen = [c for c in chosen if not (c["kind"] == "long_pause" and any(s["start_ms"] - 500 <= c["start_ms"] and c["end_ms"] <= s["end_ms"] + 500 for s in stops))]
    chosen.sort(key=lambda c: c["start_ms"])
    chosen = [*story_cards, *chosen]
    if plane is not None:
        _add_wall_plane_distances(chosen, events, series, samples, plane, width, height)
    uncertain = [{"start_ms": e["start_ms"], "text": f"{NAMES[limb_of(e)].capitalize()} at {clock(e['start_ms'])}: the tracked point was unstable, so no advice uses it."}
                 for e in events if is_uncertain(e)]
    return {**base, "available": True, "cards": chosen, "cards_omitted": len(cards) - len(chosen),
            "not_flagged": sorted(not_flagged, key=lambda n: n["start_ms"]), "cannot_evaluate": sorted([*cannot, *uncertain], key=lambda n: n["start_ms"]),
            "placements": [p for p in foot_placements(events, series, poses, hold_context) if not off_wall(p["landing_ms"])],
            "story": {k: v for k, v in story.items() if k != "takeaways"}, "cards_after_leaving_wall": after_wall, "body": body.public() if body else None, "reach_tally": tally,
            "top_card_ids": top_card_ids(chosen), "glance": at_a_glance(result, events),
            "observed_route": observed_route(series, samples, hold_context, width, height)}
