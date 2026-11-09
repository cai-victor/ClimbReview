"""Deterministic grouped split. It reads only group metadata, never measured results."""
from __future__ import annotations

import hashlib
from typing import Any

TEST_FRACTION = 0.25


def freeze_split(sources: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    """Assign whole climber/recording groups, roughly 25% per event, ordered by a seeded hash."""
    group_event: dict[str, str] = {}
    for source in sorted(sources, key=lambda s: s["clip_id"]):
        group_event.setdefault(source["group_id"], source["event_id"])
    by_event: dict[str, list[str]] = {}
    for group, event in group_event.items():
        by_event.setdefault(event, []).append(group)
    assignments: dict[str, str] = {}
    for event, groups in sorted(by_event.items()):
        ordered = sorted(groups, key=lambda g: hashlib.sha256(f"{seed}|{g}".encode()).hexdigest())
        count = max(1, round(len(ordered) * TEST_FRACTION))
        for position, group in enumerate(ordered):
            assignments[group] = "test" if position < count else "train"
    return {
        "rule": "Within each primary event, groups ordered by sha256(seed|group_id); first round(25%) (min 1) are test.",
        "seed": seed,
        "groups": dict(sorted(assignments.items())),
        "clips": {s["clip_id"]: {"group_id": s["group_id"], "event_id": s["event_id"], "split": assignments[s["group_id"]]}
                  for s in sorted(sources, key=lambda s: s["clip_id"])},
    }
