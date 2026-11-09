#!/usr/bin/env python3
"""Development demonstration of candidate sequences on a real marked route.

Reads a hold map and an analysis read-only. Roles are NOT in the user's map, so this applies
explicit assumed roles to an in-memory copy: start holds are the two marked holds nearest the
wrists in the first tracked frames, and the finish is the topmost hold. Nothing is written to the database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

from _bootstrap import PROJECT_ROOT
from app.analysis import beta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = PROJECT_ROOT / "data" / "app"
    connection = sqlite3.connect(f"file:{data / 'climbreview.sqlite'}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    attempt = dict(connection.execute("SELECT * FROM attempts WHERE id=?", (args.attempt,)).fetchone())
    run = connection.execute("SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (args.attempt,)).fetchone()["id"]
    map_row = connection.execute("SELECT * FROM hold_maps WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1", (args.attempt,)).fetchone()
    holds = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (map_row["id"],))]
    directory = data / "attempts" / args.attempt / "runs" / run
    samples = json.loads((directory / "overlay.json").read_text())["samples"]
    length = json.loads((directory / "movement.json").read_text())["L_px"]
    width, height = attempt["width"], attempt["height"]
    points = np.array([[h["x"] * width, h["y"] * height] for h in holds])
    wrists = [np.array(s["joints"][n]) * [width, height] for s in samples[:30] for n in ("left_wrist", "right_wrist") if n in s["joints"]]
    center = np.mean(wrists, axis=0)
    start = sorted(np.argsort(np.linalg.norm(points - center, axis=1))[:2].tolist())
    finish = int(np.argmin(points[:, 1]))
    assumed = [{**h, "role": "start" if i in start else "finish" if i == finish else "", "use": ""} for i, h in enumerate(holds)]
    body = beta.body_model(samples, width, height, length)
    result = beta.candidate_sequences(assumed, width, height, length, body)
    report = {"demonstration_only": True, "assumed_roles": {"start_holds": [i + 1 for i in start], "finish_hold": finish + 1,
              "basis": "Assumed for this demonstration. The climber has not marked start, finish, or hand and foot use on this map."},
              "attempt": attempt["title"], "run": run, "hold_count": len(holds), **result}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("assumed_roles", "status", "note")}, indent=1))
    for candidate in report["candidates"]:
        print(candidate["label"], candidate["move_count"], "moves", candidate["total_distance_L"], "L, tightest", candidate["tightest_margin_L"],
              [f"{s['limb']}->H{s['to_hold'] + 1}" for s in candidate["steps"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
