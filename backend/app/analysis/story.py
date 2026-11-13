"""The shape of one attempt: when the climber was on the wall, where they moved, where they stayed put, and how it ended.

Everything here is read from the hip midpoint in the picture, one camera, no depth. It is a description of where time
went, not a measurement of effort, balance, or a physical center of mass. Thresholds are starting values that have not
been validated against human labels.
"""
from __future__ import annotations

import hashlib
from typing import Any, Sequence

import numpy as np

from .explain import clock, is_uncertain, limb_of

STORY_VERSION = "climb-story-v1"
C = {
    "gap_ms": 350,              # hips missing for longer than this break the track; nothing is bridged across it
    "smooth_ms": 500,           # rolling median inside one continuous run
    "stall_radius_L": 0.30,     # hips stay within this distance of where the stop began
    "stall_min_ms": 3000,
    "stall_bridge_ms": 1000,    # a stop may contain an untracked moment this short
    "area_join_ms": 5000,       # two stops this close in time...
    "area_join_L": 0.5,         # ...and this close in place are one stay in the same area
    "area_spread_L": 0.8,       # ...as long as the hips never left this radius in between
    "drop_L": 1.2,              # hips go down at least this far...
    "drop_window_ms": 1500,     # ...within this time: a fall or a jump down
    "min_tracked_fraction": 0.6,
    "ground_band_L": 0.25,      # an ankle this close to the lowest foot level seen in the clip may be on the ground
    "standing_leg": 0.8,        # ...if that leg is also nearly as long, top to bottom, as it ever appears
    "ground_bridge_ms": 1500,
    "ground_min_ms": 1000,
    "early_drop_fraction": 0.2, # a descent this early, with climbing after it, is getting into the start, not leaving the wall
    "small_foot_L": 0.4,
    "long_stall_ms": 8000,
    "stalled_share": 0.35,
}


def _id(*parts: Any) -> str:
    return "story-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def hip_track(samples: Sequence[dict[str, Any]], width: int, height: int, length_px: float, start: float, end: float) -> dict[str, np.ndarray]:
    """Hip midpoint in torso lengths, picture coordinates (y grows downward). NaN where either hip was not tracked."""
    rows = [s for s in samples if start <= s["t"] <= end]
    t = np.array([s["t"] for s in rows], dtype=float)
    xy = np.full((len(rows), 2), np.nan)
    for i, sample in enumerate(rows):
        joints = sample.get("joints", {})
        if "left_hip" in joints and "right_hip" in joints:
            left, right = joints["left_hip"], joints["right_hip"]
            xy[i] = ((left[0] + right[0]) / 2 * width / length_px, (left[1] + right[1]) / 2 * height / length_px)
    valid = ~np.isnan(xy[:, 0])
    run = np.full(len(rows), -1)
    current, last = -1, None
    for i in range(len(rows)):
        if not valid[i]:
            continue
        if last is None or t[i] - t[last] > C["gap_ms"]:
            current += 1
        run[i], last = current, i
    smooth = xy.copy()
    for r in range(current + 1):
        index = np.flatnonzero(run == r)
        for i in index:
            near = index[np.abs(t[index] - t[i]) <= C["smooth_ms"] / 2]
            smooth[i] = np.median(xy[near], axis=0)
    return {"t": t, "x": smooth[:, 0], "y": smooth[:, 1], "run": run, "valid": valid}


def find_lift_off(samples: Sequence[dict[str, Any]], height: int, length_px: float, start: float, end: float) -> dict[str, Any] | None:
    """When the climber last stood at the lowest foot level seen in the clip, at the beginning of the clip.

    Standing means an ankle at that level under a leg that is nearly as tall as it ever appears. A clip that starts with
    the climber already off the ground has no such phase. A straight leg on the lowest foothold looks the same, so the
    result is reported as the ground or the first foothold.
    """
    rows = [s for s in samples if start <= s["t"] <= end]
    legs: dict[str, list[tuple[float, float, float]]] = {"left": [], "right": []}
    for sample in rows:
        joints = sample.get("joints", {})
        for side in legs:
            if f"{side}_ankle" in joints and f"{side}_hip" in joints:
                ankle, hip = joints[f"{side}_ankle"][1] * height, joints[f"{side}_hip"][1] * height
                legs[side].append((sample["t"], ankle, ankle - hip))
    every = [a for side in legs.values() for _, a, _ in side]
    if len(every) < 10:
        return None
    ground = float(np.percentile(every, 98))
    tallest = max(float(np.percentile([leg for _, _, leg in side], 95)) for side in legs.values() if side)
    standing = sorted(t for side in legs.values() for t, ankle, leg in side
                      if ankle >= ground - C["ground_band_L"] * length_px and leg >= C["standing_leg"] * tallest)
    first_tracked = min(t for side in legs.values() for t, _, _ in side)
    if not standing or standing[0] - first_tracked > C["ground_bridge_ms"]:
        return None
    last = standing[0]
    for moment in standing[1:]:
        if moment - last > C["ground_bridge_ms"]:
            break
        last = moment
    if last - standing[0] < C["ground_min_ms"]:
        return None
    return {"start_ms": int(standing[0]), "end_ms": int(last), "ground_y_px": round(ground, 1)}


def find_drop(track: dict[str, np.ndarray], after: float = -np.inf) -> dict[str, Any] | None:
    """The first fast descent of the hips after `after`. The video cannot tell a fall from a jump down."""
    t, y, valid = track["t"], track["y"], track["valid"]
    index = np.flatnonzero(valid & (t >= after))
    for a in index:
        later = index[(t[index] > t[a]) & (t[index] <= t[a] + C["drop_window_ms"])]
        if len(later) and np.max(y[later]) - y[a] >= C["drop_L"]:
            # Walk back to where the descent began: the highest hip position just before it.
            before = index[(t[index] >= t[a] - 1000) & (t[index] <= t[a] + C["drop_window_ms"])]
            top = before[np.flatnonzero(y[before] <= np.min(y[before]) + 0.1)[-1]]      # the last moment still at the top
            landing = index[(t[index] > t[top]) & (t[index] <= t[top] + 2 * C["drop_window_ms"])]
            bottom = landing[np.argmax(y[landing])]
            return {"start_ms": int(t[top]), "end_ms": int(t[bottom]), "drop_L": round(float(y[bottom] - y[top]), 2)}
    return None


def find_stalls(track: dict[str, np.ndarray], until: float, since: float = -np.inf) -> list[dict[str, Any]]:
    """Stretches where the hips stayed within a small radius of where the stop began."""
    t, x, y, valid = track["t"], track["x"], track["y"], track["valid"]
    index = [i for i in np.flatnonzero(valid) if since <= t[i] <= until]
    stalls, k = [], 0
    while k < len(index):
        a = index[k]
        j = k
        while j + 1 < len(index):
            b = index[j + 1]
            if t[b] - t[index[j]] > C["stall_bridge_ms"] or np.hypot(x[b] - x[a], y[b] - y[a]) > C["stall_radius_L"]:
                break
            j += 1
        if t[index[j]] - t[a] >= C["stall_min_ms"]:
            inside = index[k:j + 1]
            stalls.append({"start_ms": int(t[a]), "end_ms": int(t[index[j]]), "tracked_fraction": round(len(inside) / max(1, np.sum((t >= t[a]) & (t <= t[index[j]]))), 2),
                           "x": float(np.median(x[inside])), "y": float(np.median(y[inside]))})
            k = j + 1
        else:
            k += 1
    # Slow drift splits one long stay into several short stops. Join neighbours that are the same area.
    merged: list[dict[str, Any]] = []
    for stall in stalls:
        previous = merged[-1] if merged else None
        if previous and stall["start_ms"] - previous["end_ms"] <= C["area_join_ms"] and np.hypot(stall["x"] - previous["x"], stall["y"] - previous["y"]) <= C["area_join_L"]:
            inside = [i for i in index if previous["start_ms"] <= t[i] <= stall["end_ms"]]
            cx, cy = float(np.median(x[inside])), float(np.median(y[inside]))
            if float(np.max(np.hypot(x[inside] - cx, y[inside] - cy))) <= C["area_spread_L"]:
                previous.update(end_ms=stall["end_ms"], x=cx, y=cy, parts=previous.get("parts", 1) + 1,
                                tracked_fraction=round(len(inside) / max(1, np.sum((t >= previous["start_ms"]) & (t <= stall["end_ms"]))), 2))
                continue
        merged.append(dict(stall))
    for stall in merged:
        inside = [i for i in index if stall["start_ms"] <= t[i] <= stall["end_ms"]]
        stall["spread_L"] = round(float(np.max(np.hypot(x[inside] - stall["x"], y[inside] - stall["y"]))), 2)
    return merged


def _activity(start: int, end: int, events: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"left_foot": 0, "right_foot": 0, "left_wrist": 0, "right_wrist": 0, "uncertain": 0}
    for event in events:
        limb = limb_of(event)
        if limb and event["start_ms"] < end and event["end_ms"] > start:
            if is_uncertain(event):
                counts["uncertain"] += 1
            else:
                counts[limb] += 1
    return counts


def _limb_text(counts: dict[str, int]) -> str:
    feet, hands = counts["left_foot"] + counts["right_foot"], counts["left_wrist"] + counts["right_wrist"]
    plural = lambda n, word: f"{n} {word} movement{'s' if n != 1 else ''}"
    if not feet and not hands:
        return "No tracked hand or foot made a movement during it."
    return f"During it the app tracked {plural(feet, 'foot')} and {plural(hands, 'hand')}."


def _stall_reading(counts: dict[str, int]) -> tuple[str, str, str]:
    """(pattern, what to try, when to keep). Counts describe tracked movement only; they never show grip or contact."""
    feet, hands = counts["left_foot"] + counts["right_foot"], counts["left_wrist"] + counts["right_wrist"]
    if feet >= 3 and feet >= 2 * max(hands, 1):
        return ("feet_busy", "Your feet kept moving while your hips stayed in one place. Before the next attempt, choose the footholds for this section from the ground, then place each foot once and move on. Compare how long you spend here.",
                "Trying several footholds is a fair way to learn a move on a first attempt. If that is what you were doing, keep going.")
    if hands >= 2 and hands > feet:
        return ("hands_busy", "Your hands moved several times while your hips stayed in one place. Before the next attempt, decide which hand goes where for this section, and try it with one deliberate reach. Compare how long you spend here.",
                "Adjusting a grip or chalking up is normal. If the hand movements were on purpose, keep them.")
    if not feet and not hands:
        return ("still", "If you were working out the next move, read this section from the ground first and decide the next two moves before you start. If you were resting, check that it was on your best hold and with a straight arm.",
                "A planned rest is not a mistake. If you chose to stop here, keep it.")
    return ("mixed", "Watch this stretch and name what you were waiting for. If it was a decision, make it from the ground before the next attempt. If it was a hard position to move from, try one different foot position and compare.",
            "A planned rest or a careful setup for a hard move is not a mistake.")


def build_story(result: dict[str, Any], events: Sequence[dict[str, Any]], samples: Sequence[dict[str, Any]], width: int, height: int, length_px: float | None) -> dict[str, Any]:
    """Phases, a height profile, and a few takeaways. Pure: the same inputs give the same output."""
    base = {"version": STORY_VERSION, "criteria": C,
            "note": "Read from the middle of the hips in the picture. One camera cannot see depth, effort, grip, or contact, and these thresholds are unvalidated."}
    bounds = result["attempt_bounds_ms"]
    if not length_px:
        return {**base, "available": False, "reason": "This attempt has no reliable body scale."}
    track = hip_track(samples, width, height, length_px, bounds["start"], bounds["end"])
    tracked = float(np.mean(track["valid"])) if len(track["t"]) else 0.0
    if tracked < C["min_tracked_fraction"]:
        return {**base, "available": False, "tracked_fraction": round(tracked, 2),
                "reason": f"The hips were tracked for only {tracked:.0%} of the attempt, which is too little to describe its shape."}

    t, x, y, valid = track["t"], track["x"], track["y"], track["valid"]
    index = np.flatnonzero(valid)
    wall_start, started_by = int(t[index[0]]), "start_of_clip"
    ground = find_lift_off(samples, height, length_px, bounds["start"], bounds["end"])
    if ground:
        wall_start, started_by = ground["end_ms"], "left_the_ground"
    drop = find_drop(track, wall_start)
    span = bounds["end"] - bounds["start"]
    while drop and drop["start_ms"] - bounds["start"] <= C["early_drop_fraction"] * span and int(t[index[-1]]) - drop["end_ms"] >= 10_000:
        # Going down early and then carrying on is sitting or lowering into the start position.
        wall_start, started_by = drop["end_ms"], "lowered_into_start"
        drop = find_drop(track, wall_start)
    wall_end = drop["start_ms"] if drop else int(t[index[-1]])
    on = index[(t[index] >= wall_start) & (t[index] <= wall_end)]
    if len(on) < 10:
        return {**base, "available": False, "reason": "Too little of this clip shows tracked climbing after the start."}
    floor = float(np.max(y[on]))                         # the lowest hip position while on the wall
    top = on[np.argmin(y[on])]
    stalls = find_stalls(track, wall_end, wall_start)
    for stall in stalls:
        stall["duration_ms"] = stall["end_ms"] - stall["start_ms"]
        stall["counts"] = _activity(stall["start_ms"], stall["end_ms"], events)
        stall["height_L"] = round(floor - stall["y"], 2)
        stall["role"] = "start" if stall["start_ms"] - wall_start <= 2000 else "before_leaving" if drop and wall_end - stall["end_ms"] <= 2000 else "middle"

    phases: list[dict[str, Any]] = []
    cursor = wall_start
    for stall in stalls:
        if stall["start_ms"] - cursor >= 500:
            phases.append({"kind": "moving", "start_ms": cursor, "end_ms": stall["start_ms"]})
        phases.append({"kind": "stopped", "start_ms": stall["start_ms"], "end_ms": stall["end_ms"], "role": stall["role"]})
        cursor = stall["end_ms"]
    if wall_end - cursor >= 500:
        phases.append({"kind": "moving", "start_ms": cursor, "end_ms": wall_end})
    if drop:
        phases.append({"kind": "off_wall", "start_ms": wall_end, "end_ms": bounds["end"]})

    wall_ms = wall_end - wall_start
    stopped_ms = sum(s["duration_ms"] for s in stalls)
    profile = [{"t": int(t[i]), "h": round(floor - float(y[i]), 2), "run": int(track["run"][i])} for i in index]
    if wall_start - bounds["start"] >= 500:
        phases.insert(0, {"kind": "before_start", "start_ms": bounds["start"], "end_ms": wall_start})
    stats = {"on_wall_ms": wall_ms, "stopped_ms": stopped_ms, "moving_ms": wall_ms - stopped_ms, "stops": len(stalls),
             "high_point_ms": int(t[top]), "height_gained_L": round(floor - float(y[top]), 2), "hips_tracked_fraction": round(tracked, 2)}

    takeaways: list[dict[str, Any]] = []
    measure = lambda label, value: {"label": label, "value": value}
    middle = [s for s in stalls if s["role"] != "start"]
    longest = max(middle, key=lambda s: s["duration_ms"], default=None)
    if longest and (longest["duration_ms"] >= C["long_stall_ms"] or stopped_ms / max(wall_ms, 1) >= C["stalled_share"]):
        seconds, share = longest["duration_ms"] / 1000, longest["duration_ms"] / max(wall_ms, 1)
        pattern, try_this, keep_if = _stall_reading(longest["counts"])
        takeaways.append({
            "id": _id("stall", longest["start_ms"]), "kind": "longest_stop", "pattern": pattern, "start_ms": longest["start_ms"], "end_ms": longest["end_ms"],
            "title": f"{seconds:.0f} s in one area, {share:.0%} of your time on the wall",
            "observed": f"From {clock(longest['start_ms'])} to {clock(longest['end_ms'])} your hips stayed within {max(longest['spread_L'], 0.1):.1f} torso lengths of one place, about {longest['height_L']:.1f} torso lengths above your lowest point. {_limb_text(longest['counts'])}",
            "why": "Time spent holding on in one place adds up over a boulder problem. It usually goes to a decision or to a rest, and the two call for different changes.",
            "limbs": [], "try_this": try_this, "keep_if": keep_if,
            "verify": "The video cannot tell a planned rest from hesitation, and a hidden hand or foot may have moved unseen.",
            "measurements": [measure("Time in one area", f"{seconds:.1f} s"), measure("How far the hips strayed", f"{longest['spread_L']:.1f} torso lengths"), measure("Share of time on the wall", f"{share:.0%}"),
                             measure("Foot movements during it, left / right", f"{longest['counts']['left_foot']} / {longest['counts']['right_foot']}"),
                             measure("Hand movements during it, left / right", f"{longest['counts']['left_wrist']} / {longest['counts']['right_wrist']}"),
                             measure("Hips tracked during it", f"{longest['tracked_fraction']:.0%}")]})
    if drop:
        last = next((s for s in stalls if s["role"] == "before_leaving"), None)
        reached = (floor - float(y[np.flatnonzero(t == drop["start_ms"])[0]])) / max(stats["height_gained_L"], 1e-6)
        waited = f" You had been in that spot for {last['duration_ms'] / 1000:.0f} s." if last else ""
        takeaways.append({
            "id": _id("drop", drop["start_ms"]), "kind": "left_wall", "start_ms": max(wall_start, drop["start_ms"] - 2000), "end_ms": drop["end_ms"],
            "title": f"You left the wall at {clock(drop['start_ms'])}",
            "observed": f"At {clock(drop['start_ms'])} your hips dropped {drop['drop_L']:.1f} torso lengths in {(drop['end_ms'] - drop['start_ms']) / 1000:.1f} s, from {reached:.0%} of the highest point you reached.{waited}",
            "try_this": ("If this was a fall, watch the two seconds before it and name the last thing that moved. On the next attempt, try the move sooner after you arrive at that position, or step back down to your last comfortable stance before trying it, and compare."
                         if last else "If this was a fall, watch the two seconds before it and name the last thing that moved. Set that limb more deliberately on the next attempt and compare."),
            "why": "The last seconds before leaving the wall show what the final move depended on, which is the most specific thing to practice.", "limbs": [],
            "keep_if": "If you had finished and jumped down on purpose, there is nothing to change here.",
            "verify": "The video cannot tell a fall from a jump down, or show why a hand or foot came off.",
            "measurements": [measure("Hip drop", f"{drop['drop_L']:.1f} torso lengths"), measure("Height when it began", f"{reached:.0%} of your high point"),
                             *([measure("Time in that spot before it", f"{last['duration_ms'] / 1000:.1f} s")] if last else [])]})
    feet = [e for e in events if e["type"] == "foot_motion" and not is_uncertain(e) and e["start_ms"] <= wall_end]
    small = [e for e in feet if e["evidence"].get("max_displacement_L", 9) < C["small_foot_L"]]
    if len(small) >= 3 and len(small) / len(feet) >= 0.4:
        first = small[0]
        takeaways.append({
            "id": _id("feet", len(small), len(feet)), "kind": "small_foot_moves", "start_ms": first["start_ms"], "end_ms": first["end_ms"],
            "title": f"{len(small)} of {len(feet)} foot movements were small adjustments",
            "observed": f"{len(small)} of the {len(feet)} tracked foot movements covered less than {C['small_foot_L']:g} torso lengths. The first was at {clock(first['start_ms'])}; others were at {', '.join(clock(e['start_ms']) for e in small[1:5])}.",
            "try_this": "On the next attempt, look at each foothold until your foot is on it, place the foot once, and count how many times you move a foot without going anywhere. Compare the count.",
            "why": "Each extra foot adjustment is more time holding on. Placing a foot once and trusting it is a common coaching goal, often called quiet feet.", "limbs": ["left_foot", "right_foot"],
            "keep_if": "Pivoting on a foothold, switching feet, and testing a hold on a first try are all deliberate small movements. Keep those.",
            "verify": "The ankle stands in for the foot, so a small ankle movement can also be the heel dropping or the knee turning.",
            "measurements": [measure("Small foot movements", f"{len(small)} of {len(feet)}"), measure("Counted as small below", f"{C['small_foot_L']:g} torso lengths")],
            "moments": [e["start_ms"] for e in small]})
    start = next((s for s in stalls if s["role"] == "start"), None)
    # Only a start that is followed by real movement; a clip where the hips never go anywhere is not a slow start.
    if start and start["duration_ms"] >= 5000 and wall_end - start["end_ms"] >= 2000 and stats["height_gained_L"] + float(np.ptp(x[on])) >= 1.0:
        takeaways.append({
            "id": _id("start", start["end_ms"]), "kind": "slow_start", "start_ms": start["start_ms"], "end_ms": start["end_ms"],
            "title": f"{start['duration_ms'] / 1000:.0f} s at the start before your hips moved away",
            "observed": f"The first {start['duration_ms'] / 1000:.0f} s of the clip show your hips in one place. {_limb_text(start['counts'])}",
            "try_this": "If you were already holding the start holds, read the first moves from the ground instead, then pull on and go. If you were still on the ground, trim the clip's start so this time is not counted.",
            "why": "Time on the start holds counts toward how long you hold on.", "limbs": [],
            "keep_if": "Settling into a sit start or a hard first position takes time. If that is what this was, keep it.",
            "verify": "The app cannot tell standing on the ground from hanging on the start holds here.",
            "measurements": [measure("Time before the hips moved away", f"{start['duration_ms'] / 1000:.1f} s")]})

    if not drop and wall_ms >= 8000 and stopped_ms / wall_ms < 0.15 and tracked >= 0.9:
        takeaways.append({
            "id": _id("steady", wall_start, wall_end), "kind": "steady", "start_ms": wall_start, "end_ms": min(wall_end, wall_start + 5000),
            "title": f"You kept moving: {('no stop' if not stalls else 'almost no time stopped')} in {wall_ms / 1000:.0f} s on the wall",
            "observed": f"From {clock(wall_start)} to {clock(wall_end)} your hips never stayed in one area for more than {max((s2['duration_ms'] for s2 in stalls), default=C['stall_min_ms']) / 1000:.0f} s"
                        + (", and no stop of 3 s or more was found." if not stalls else f"; {stopped_ms / 1000:.0f} s in total was spent stopped."),
            "why": "An attempt without long stops is a useful reference: it shows the pace you can hold when you know the moves.", "limbs": [],
            "try_this": "Nothing to change from the timing. Keep this attempt as your reference and compare harder attempts against it, using the same problem and climber name in the Compare tab.",
            "keep_if": "Moving steadily is not always the goal. On a harder problem a rest in the right place can be the better choice.",
            "verify": "Steady hips do not show whether each hold felt secure.",
            "measurements": [measure("Time on the wall", f"{wall_ms / 1000:.1f} s"), measure("Time stopped", f"{stopped_ms / 1000:.1f} s"), measure("Hips tracked", f"{tracked:.0%}")]})
    places = len(stalls)
    headline = (f"On the wall for {wall_ms / 1000:.0f} s: moving for {(wall_ms - stopped_ms) / 1000:.0f} s and staying put for {stopped_ms / 1000:.0f} s"
                + (f" in {places} place{'s' if places != 1 else ''}." if places else ".")
                + (f" You left the wall at {clock(wall_end)}." if drop else "")
                + ({"left_the_ground": f" Counted from {clock(wall_start)}, when your feet left the lowest level seen in the clip (the ground or your first foothold).",
                    "lowered_into_start": f" Counted from {clock(wall_start)}, after you lowered into the start position."}.get(started_by, "")))
    return {**base, "available": True, "headline": headline, "on_wall": {"start_ms": wall_start, "end_ms": wall_end, "started_by": started_by, "ended_by": "fast_descent" if drop else "end_of_clip"},
            "drop": drop, "stats": stats, "phases": phases, "stops": [{k: v for k, v in s.items() if k not in {"x", "y"}} for s in stalls],
            "profile": profile, "takeaways": takeaways}
