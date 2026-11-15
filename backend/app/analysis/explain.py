"""Specific, time-linked descriptions built only from stored measurements.

Everything here reports what the tracked points did in the picture. A limb is "quiet"
only when it was tracked through the window and no episode overlapped it. Missing
tracking is "unknown", never "quiet". Quiet does not mean supported, weighted, or
in contact with a hold.
"""
from __future__ import annotations

from typing import Any, Sequence

CONTEXT_VERSION = "limb-context-v2"
LIMBS = ("left_wrist", "right_wrist", "left_foot", "right_foot")
NAMES = {"left_wrist": "left hand", "right_wrist": "right hand", "left_foot": "left foot", "right_foot": "right foot"}
DETECTOR_OF = {"left_wrist": "wrist_motion_left", "right_wrist": "wrist_motion_right",
               "left_foot": "foot_motion_left", "right_foot": "foot_motion_right"}
MIN_OBSERVED_FOR_QUIET = 1.0      # a whole-window quiet claim requires every sample, including both boundaries
QUIET_MAX_EXCURSION_L = 0.15      # a limb is quiet only if measured motion stayed within this; no episode alone is not enough
SEQUENCE_WINDOW_MS = 1500         # how far before or after an event a neighboring limb's episode is mentioned
PHASE_GAP_MS = 750                # episodes closer than this are listed together
REPEAT_GAP_MS = 2000              # same-limb episodes closer than this are listed as repeated
LOW_COVERAGE_FRACTION = 0.6
DIRECTION_TEXT = {
    "up": "up", "down": "down", "image_left": "toward the left of the picture", "image_right": "toward the right of the picture",
    "up_and_image_left": "up and toward the left of the picture", "up_and_image_right": "up and toward the right of the picture",
    "down_and_image_left": "down and toward the left of the picture", "down_and_image_right": "down and toward the right of the picture",
}
SHORT_DIRECTION = {"up": "up", "down": "down", "image_left": "left in picture", "image_right": "right in picture",
                   "up_and_image_left": "up-left in picture", "up_and_image_right": "up-right in picture",
                   "down_and_image_left": "down-left in picture", "down_and_image_right": "down-right in picture",
                   "no_clear_net_direction": "out and back"}
REASON_TEXT = {
    "no_pose": "no body was detected", "non_finite": "no usable coordinate was returned", "out_of_frame": "the joint was outside the picture",
    "visibility_missing": "no visibility value was returned", "low_visibility": "the joint was probably hidden or poorly seen",
    "low_presence": "the model was unsure the joint was there", "implausible_torso_scale": "the detected body shape was implausibly sized",
    "camera_motion": "the camera appeared to move", "repeated_source_frame": "the video repeated a frame",
}


def clock(milliseconds: int | float) -> str:
    minutes, seconds = divmod(milliseconds / 1000, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


def limb_of(event: dict[str, Any]) -> str | None:
    if event["type"] == "wrist_motion":
        return f"{event['hand']}_wrist"
    if event["type"] == "foot_motion":
        return f"{event['hand']}_foot"
    return None


def is_uncertain(event: dict[str, Any]) -> bool:
    return (event["evidence"].get("foot_support") or {}).get("anchor_state") == "uncertain"


def _limb_events(events: Sequence[dict[str, Any]], limb: str) -> list[dict[str, Any]]:
    return [e for e in events if limb_of(e) == limb]


def _window_observation(series: dict[str, Any], limb: str, start_ms: int, end_ms: int) -> tuple[float, float | None]:
    """Share of samples in the window with a usable position, and the farthest excursion if one continuous run covers it."""
    times, data = series["t"], series["limbs"][limb]
    indices = [i for i, t in enumerate(times) if start_ms <= t <= end_ms]
    if not indices:
        return 0.0, None
    usable = [i for i in indices if data["x"][i] is not None]
    observed = len(usable) / len(indices)
    if not usable or len({data["run"][i] for i in usable}) != 1 or not series["L_px"]:
        return observed, None
    x0, y0 = data["x"][usable[0]] * series["width"], data["y"][usable[0]] * series["height"]
    farthest = max(((data["x"][i] * series["width"] - x0) ** 2 + (data["y"][i] * series["height"] - y0) ** 2) ** 0.5 for i in usable)
    return observed, round(farthest / series["L_px"], 3)


def limb_state(event: dict[str, Any], events: Sequence[dict[str, Any]], series: dict[str, Any], limb: str) -> dict[str, Any]:
    start, end = event["start_ms"], event["end_ms"]
    every = [e for e in _limb_events(events, limb) if e["id"] != event["id"] and e["start_ms"] <= end and e["end_ms"] >= start]
    overlapping = [e for e in every if not is_uncertain(e)]
    observed, excursion = _window_observation(series, limb, start, end)
    if overlapping:
        state, why = "moved", None
    elif every:
        state, why = "unknown", "uncertain_episode"
    elif observed < MIN_OBSERVED_FOR_QUIET:
        state, why = "unknown", "low_coverage"
    elif excursion is None:
        state, why = "unknown", "tracking_break"       # samples may be valid, but the path between them was not observed
    elif excursion <= QUIET_MAX_EXCURSION_L:
        state, why = "quiet", None
    else:
        state, why = "drifted", None                   # real measured motion that did not meet the episode rule
    return {"state": state, "unknown_reason": why, "observed_fraction": round(observed, 3),
            "max_excursion_L": excursion if state in {"quiet", "drifted"} else None,
            "overlapping": [{"event_id": e["id"], "start_ms": e["start_ms"], "end_ms": e["end_ms"]} for e in overlapping]}


def _neighbors(event: dict[str, Any], events: Sequence[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    own = limb_of(event)
    others = [e for e in events if limb_of(e) is not None and limb_of(e) != own and not is_uncertain(e)]
    before = [e for e in others if e["end_ms"] < event["start_ms"] and event["start_ms"] - e["end_ms"] <= SEQUENCE_WINDOW_MS]
    after = [e for e in others if e["start_ms"] > event["end_ms"] and e["start_ms"] - event["end_ms"] <= SEQUENCE_WINDOW_MS]
    previous = max(before, key=lambda e: e["end_ms"], default=None)
    following = min(after, key=lambda e: e["start_ms"], default=None)
    return (None if previous is None else {"limb": limb_of(previous), "event_id": previous["id"], "gap_ms": event["start_ms"] - previous["end_ms"],
                                           "truncated": bool(previous["evidence"].get("truncated_end"))},
            None if following is None else {"limb": limb_of(following), "event_id": following["id"], "gap_ms": following["start_ms"] - event["end_ms"],
                                            "truncated": bool(following["evidence"].get("truncated_start"))})


def build_context(event: dict[str, Any], events: Sequence[dict[str, Any]], series: dict[str, Any]) -> dict[str, Any]:
    own = limb_of(event)
    previous, following = _neighbors(event, events)
    return {"method": CONTEXT_VERSION, "limbs": {limb: limb_state(event, events, series, limb) for limb in LIMBS if limb != own},
            "previous": previous, "next": following}


def _context_sentences(event: dict[str, Any], context: dict[str, Any]) -> str:
    limbs = context["limbs"]
    parts: list[str] = []
    feet = [limb for limb in ("left_foot", "right_foot") if limb in limbs]
    quiet_feet = [limb for limb in feet if limbs[limb]["state"] == "quiet"]
    if len(feet) == 2 and len(quiet_feet) == 2:
        parts.append("Both feet stayed nearly still in the picture and were tracked continuously. That does not show they were on holds or bearing weight.")
    else:
        for limb in quiet_feet:
            parts.append(f"The {NAMES[limb]} stayed nearly still in the picture and was tracked continuously. That does not show it was on a hold.")
    for limb in LIMBS:
        if limb not in limbs:
            continue
        item = limbs[limb]
        if item["state"] == "moved":
            when = item["overlapping"][0]
            parts.append(f"The {NAMES[limb]} also moved during this time ({clock(when['start_ms'])} to {clock(when['end_ms'])}).")
        elif item["state"] == "drifted":
            parts.append(f"The {NAMES[limb]} shifted slowly by about {item['max_excursion_L']:.2f} torso lengths, without meeting the movement-episode rule.")
        elif item["state"] == "unknown" and limb in feet:
            parts.append(f"Whether the {NAMES[limb]} moved is unknown here: " + {
                "low_coverage": f"it was tracked for only {item['observed_fraction'] * 100:.0f}% of this time.",
                "tracking_break": "its tracking was interrupted during this time, so the path between samples was not observed.",
                "uncertain_episode": "its tracked point was unstable during this time.",
            }[item["unknown_reason"]])
    if context["previous"]:
        before = context["previous"]
        parts.append(f"The {NAMES[before['limb']]} was last observed moving {before['gap_ms'] / 1000:.1f}s before this began, when its tracking was cut off."
                     if before["truncated"] else f"Just before, the {NAMES[before['limb']]} finished moving {before['gap_ms'] / 1000:.1f}s before this began.")
    if context["next"]:
        after = context["next"]
        parts.append(f"The {NAMES[after['limb']]} was first observed already moving {after['gap_ms'] / 1000:.1f}s after this ended, when its tracking began."
                     if after["truncated"] else f"Next, the {NAMES[after['limb']]} started moving {after['gap_ms'] / 1000:.1f}s after this ended.")
    return " ".join(parts)


def _movement_sentence(event: dict[str, Any]) -> str:
    evidence = event["evidence"]
    limb = NAMES[limb_of(event)]
    tracked = "wrist" if event["type"] == "wrist_motion" else "ankle"
    span = f"from {clock(event['start_ms'])} to {clock(event['end_ms'])} ({evidence['duration_ms'] / 1000:.1f}s)"
    if evidence["direction"] == "no_clear_net_direction":
        moved = (f"The {limb} ({tracked} point) moved out and came back near where it started {span}, "
                 f"reaching about {evidence['max_displacement_L']:.2f} torso lengths away at most.")
    else:
        moved = (f"The {limb} ({tracked} point) moved {DIRECTION_TEXT[evidence['direction']]} {span}, "
                 f"ending {evidence['net_displacement_L']:.2f} torso lengths from where it began.")
    moved += f" Its fastest moment was {evidence['peak_speed_L_per_s']:.1f} torso lengths per second at {clock(evidence['peak_speed_ms'])}."
    if event["truncated"]:
        cause = "the attempt bounds" if evidence.get("truncation_cause") == "attempt_boundary" else "a tracking gap"
        moved += f" The movement was cut off by {cause}, so its true start or end was not observed."
    support = evidence.get("foot_support")
    if support:
        compared = " and ".join(support["points_compared"])
        points = f"{compared} point{'s' if len(support['points_compared']) > 1 else ''}"
        moved += {"agrees": f" The {points} moved the same way as the ankle.",
                  "differs": f" Compared with the ankle, the {points} did not all move the same way, so the foot may have rotated or the tracking may be unsure.",
                  "unavailable": " The heel and toe points were not tracked well enough to compare with the ankle."}[support["state"]]
    if is_uncertain(event):
        moved += (" Caution: the ankle point was unstable here, as can happen when the model guesses a hidden foot. "
                  "This may not be a real foot movement, so no conclusion is drawn from it.")
    return moved


def _reflection_question(event: dict[str, Any], context: dict[str, Any]) -> str:
    limbs, kind = context["limbs"], event["type"]
    if is_uncertain(event):
        return "Can you see this foot in the video here, and did it actually move?"
    previous = context["previous"]
    following = context["next"]
    if kind == "wrist_motion":
        feet = [limbs[f]["state"] for f in ("left_foot", "right_foot")]
        if previous and previous["limb"].endswith("foot"):
            return f"Your {NAMES[previous['limb']]} moved just before this reach. Was that step setting up this hand move?"
        if all(state == "quiet" for state in feet):
            return "Both feet stayed nearly still during this hand move. Were they already where you wanted them before you moved?"
        if any(state == "unknown" for state in feet):
            return "Foot tracking is incomplete here. Rewatch this moment: what were your feet doing as this hand moved?"
        if "drifted" in feet and "moved" not in feet:
            return "A foot shifted slowly during this hand move, without a distinct step. Was that shift intended?"
        return "A foot and this hand moved together here. Was that intentional, or did one follow the other?"
    if following and following["limb"].endswith("wrist"):
        return f"Your {NAMES[following['limb']]} moved next. Was this foot move preparing for that reach?"
    if event["evidence"]["direction"] == "no_clear_net_direction":
        return "This foot went out and came back to about the same place. What were you trying to find or adjust?"
    return "Where was this foot headed, and had you chosen the spot before it started moving?"


def describe_event(event: dict[str, Any], events: Sequence[dict[str, Any]], series: dict[str, Any]) -> dict[str, str]:
    evidence = event["evidence"]
    if event["type"] == "low_movement":
        context = {"method": CONTEXT_VERSION, "limbs": {}, "previous": None, "next": _neighbors(event, events)[1]}
        event["context"] = context
        following = (f" The first movement observed afterward was the {NAMES[context['next']['limb']]}, "
                     f"{context['next']['gap_ms'] / 1000:.1f}s later." if context["next"] else "")
        return {
            "template_version": "low-movement-v2",
            "observation": f"The tracked wrists, ankles, and hips moved little from {clock(event['start_ms'])} to {clock(event['end_ms'])} "
                           f"({evidence['duration_ms'] / 1000:.1f}s). The fastest required joint stayed at or below "
                           f"{evidence['max_required_joint_speed_L_per_s']:.2f} torso lengths per second.{following}",
            "context": "All required joints were tracked for this whole interval. Low movement does not show which holds or feet carried weight.",
            "interpretation": "This could be a planned rest, a moment of route planning, or something else. The video alone cannot say which.",
            "reflection_question": "Was this pause intentional, and what were you deciding here?",
        }
    context = build_context(event, events, series)
    event["context"] = context
    if event["type"] == "wrist_motion":
        interpretation = "This may be a reach, a repositioning, or another arm movement. Wrist motion alone does not show a hold was gripped or released."
        template = "wrist-motion-v2"
    else:
        interpretation = ("This may be a step to a new foothold, an adjustment on the same one, or a foot leaving the wall. "
                          "Ankle motion alone does not show that the foot touched, slipped, or carried weight.")
        template = "foot-motion-v1"
    return {"template_version": template, "observation": _movement_sentence(event), "context": _context_sentences(event, context),
            "interpretation": interpretation, "reflection_question": _reflection_question(event, context)}


def describe_events(events: list[dict[str, Any]], series: dict[str, Any]) -> None:
    for event in events:
        event["feedback"] = describe_event(event, events, series)


# ---- attempt-level digest, computed from stored events and coverage

def _phrase(event: dict[str, Any]) -> str:
    return f"{NAMES[limb_of(event)]} {SHORT_DIRECTION[event['evidence']['direction']]} {event['evidence']['max_displacement_L']:.2f} L"


def _phases(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    moving = sorted((e for e in events if limb_of(e) and not is_uncertain(e)), key=lambda e: e["start_ms"])
    groups: list[list[dict[str, Any]]] = []
    for event in moving:
        if groups and event["start_ms"] - max(e["end_ms"] for e in groups[-1]) <= PHASE_GAP_MS:
            groups[-1].append(event)
        else:
            groups.append([event])
    return [{"start_ms": g[0]["start_ms"], "end_ms": max(e["end_ms"] for e in g), "event_ids": [e["id"] for e in g],
             "text": ", then ".join(_phrase(e) for e in g)} for g in groups]


def _repeated(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for limb in LIMBS:
        cluster: list[dict[str, Any]] = []
        for event in [*sorted((e for e in _limb_events(events, limb) if not is_uncertain(e)), key=lambda e: e["start_ms"]), None]:
            if event is not None and (not cluster or event["start_ms"] - cluster[-1]["end_ms"] <= REPEAT_GAP_MS):
                cluster.append(event)
                continue
            if len(cluster) >= 2:
                right = sum(e["evidence"]["net_image_right_L"] for e in cluster)
                up = sum(e["evidence"]["net_up_L"] for e in cluster)
                found.append({"limb": limb, "start_ms": cluster[0]["start_ms"], "end_ms": cluster[-1]["end_ms"], "count": len(cluster),
                              "event_ids": [e["id"] for e in cluster], "net_displacement_L": round((right ** 2 + up ** 2) ** 0.5, 3),
                              "text": f"The {NAMES[limb]} moved {len(cluster)} times between {clock(cluster[0]['start_ms'])} and {clock(cluster[-1]['end_ms'])}, "
                                      f"ending {(right ** 2 + up ** 2) ** 0.5:.2f} torso lengths from where the first move began. "
                                      "This is an observation of repeated movement, not a mistake."})
            cluster = [event] if event is not None else []
    return sorted(found, key=lambda r: r["start_ms"])


def _rewatch(events: Sequence[dict[str, Any]], repeated: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {e["id"]: e for e in events}
    chosen: dict[str, str] = {}

    def offer(event: dict[str, Any] | None, reason: str) -> None:
        if event is not None and event["id"] not in chosen:
            chosen[event["id"]] = reason

    size = lambda e: e["evidence"]["max_displacement_L"]
    for limb in ("left_foot", "right_foot"):
        offer(max((e for e in _limb_events(events, limb) if not is_uncertain(e)), key=size, default=None),
              f"The largest {NAMES[limb]} movement in this attempt.")
    for item in repeated[:2]:
        offer(by_id[item["event_ids"][0]], f"Start of {item['count']} nearby {NAMES[item['limb']]} movements.")
    hands = [e for e in events if e["type"] == "wrist_motion" and e.get("context")]
    quiet = [e for e in hands if all(e["context"]["limbs"][f]["state"] == "quiet" for f in ("left_foot", "right_foot"))]
    offer(max(quiet, key=size, default=None), "The largest hand movement while both feet were tracked continuously and stayed nearly still.")
    unknown = [e for e in hands if any(e["context"]["limbs"][f]["state"] == "unknown" for f in ("left_foot", "right_foot"))]
    offer(max(unknown, key=size, default=None), "A large hand movement where foot tracking is incomplete, so watch the feet yourself.")
    offer(next((e for e in events if is_uncertain(e)), None), "An uncertain foot episode: check in the video whether this foot really moved.")
    offer(max((e for e in events if e["type"] == "low_movement"), key=lambda e: e["end_ms"] - e["start_ms"], default=None),
          "The longest interval with little visible movement.")
    return sorted(({"event_id": k, "start_ms": by_id[k]["start_ms"], "reason": r} for k, r in chosen.items()), key=lambda r: r["start_ms"])[:6]


def _limits(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for limb in LIMBS:
        item = coverage[DETECTOR_OF[limb]]
        if item["status"] != "available":
            notes.append({"limb": limb, "fraction": None, "text": f"The {NAMES[limb]} could not be analyzed in this attempt."})
            continue
        if item["fraction"] >= LOW_COVERAGE_FRACTION:
            continue
        tally: dict[str, int] = {}
        for gap in item["gaps"]:
            for key, count in gap.get("reasons", {}).items():
                tally[key] = tally.get(key, 0) + count
        why = f", mostly because {REASON_TEXT.get(max(tally, key=tally.get), 'tracking was not continuous')}" if tally else ""
        notes.append({"limb": limb, "fraction": item["fraction"],
                      "text": f"The {NAMES[limb]} was analyzable for {item['fraction'] * 100:.0f}% of the attempt{why}. "
                              "Movement in the remaining time is unknown, not absent."})
    return notes


def _prompts(events: Sequence[dict[str, Any]], repeated: Sequence[dict[str, Any]], rewatch: Sequence[dict[str, Any]]) -> list[str]:
    by_id = {e["id"]: e for e in events}
    prompts: list[str] = []
    for item in rewatch:
        event = by_id[item["event_id"]]
        if limb_of(event):
            prompts.append(f"At {clock(event['start_ms'])}: {event['feedback']['reflection_question']}")
        if len(prompts) == 2:
            break
    if repeated:
        first = repeated[0]
        prompts.append(f"From {clock(first['start_ms'])} to {clock(first['end_ms'])} your {NAMES[first['limb']]} moved {first['count']} times. What were you adjusting?")
    return prompts


def attempt_digest(result: dict[str, Any], events: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """What moved and when, what to rewatch, and where tracking prevents a conclusion. None for runs without foot analysis."""
    coverage = result["coverage"]["detectors"]
    detection = result["detection"]["detectors"]
    if "foot_motion_left" not in detection or detection["foot_motion_left"]["status"] == "not_run":
        return None
    limbs: dict[str, Any] = {}
    for limb in LIMBS:
        found = _limb_events(events, limb)
        count = detection[DETECTOR_OF[limb]]["event_count"]
        largest = max((e for e in found if not is_uncertain(e)), key=lambda e: e["evidence"]["max_displacement_L"], default=None)
        limbs[limb] = {
            "label": NAMES[limb], "episodes": count, "uncertain_episodes": sum(is_uncertain(e) for e in found), "analyzable_fraction": coverage[DETECTOR_OF[limb]]["fraction"],
            "moving_ms": None if count is None else sum(e["end_ms"] - e["start_ms"] for e in found),
            "largest": None if largest is None else {"event_id": largest["id"], "start_ms": largest["start_ms"], "text": _phrase(largest)},
        }
    repeated = _repeated(events)
    rewatch = _rewatch(events, repeated)
    return {"method": CONTEXT_VERSION, "limbs": limbs, "phases": _phases(events), "repeated": repeated, "rewatch": rewatch,
            "limits": _limits(coverage), "prompts": _prompts(events, repeated, rewatch),
            "meaning": "Counts describe tracked image motion. They are not a score, and more or fewer movements do not mean better climbing."}
