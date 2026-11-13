#!/usr/bin/env python3
"""Print the climb story (on-wall window, stops, takeaways) for every current analysis in the local app. Read-only."""
from __future__ import annotations

import glob
import json
import os
import sqlite3
import sys

from _bootstrap import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from app.analysis.explain import clock  # noqa: E402
from app.analysis.story import build_story  # noqa: E402

RESERVED = ("IMG_2532", "IMG_2748")


def main() -> int:
    data = PROJECT_ROOT / "data" / "app"
    db = sqlite3.connect(f"file:{data / 'climbreview.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    for attempt in db.execute("select id, title, width, height, outcome, original_filename from attempts order by created_at"):
        if any(name in (attempt["original_filename"] or "") for name in RESERVED):
            continue
        runs = sorted(glob.glob(str(data / "attempts" / attempt["id"] / "runs" / "*" / "movement.json")), key=os.path.getmtime)
        if not runs:
            continue
        directory = os.path.dirname(runs[-1])
        read = lambda name: json.load(open(os.path.join(directory, name)))
        result, events, movement = read("result.json"), read("events.json")["events"], read("movement.json")
        story = build_story(result, events, read("overlay.json")["samples"], attempt["width"], attempt["height"], movement["L_px"])
        print(f"\n== {attempt['title']}  (your outcome: {attempt['outcome'] or 'not recorded'})")
        if not story["available"]:
            print("  unavailable:", story["reason"])
            continue
        wall, stats = story["on_wall"], story["stats"]
        print(f"  on wall {clock(wall['start_ms'])} ({wall['started_by']}) to {clock(wall['end_ms'])} ({wall['ended_by']}); stopped {stats['stopped_ms'] / 1000:.1f} s of {stats['on_wall_ms'] / 1000:.1f} s; "
              f"high point {clock(stats['high_point_ms'])}, {stats['height_gained_L']} L; hips tracked {stats['hips_tracked_fraction']:.0%}")
        for stop in story["stops"]:
            print(f"    stop {clock(stop['start_ms'])}-{clock(stop['end_ms'])} {stop['role']} h={stop['height_L']} {stop['counts']}")
        for item in story["takeaways"]:
            print(f"  * [{item['kind']}] {item['title']}\n      {item['observed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
