#!/usr/bin/env python3
"""Development check: compare color suggestions with one hand-marked route. Read-only; not an accuracy study.

Each marked hold is used once as the tapped seed, with all marks hidden from the suggester. A mark counts as found
when a suggestion's center lies within 1.5 radii of it. Suggestions matching no mark are not necessarily wrong,
because the climber may have marked only part of what is on the wall.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from _bootstrap import PROJECT_ROOT
from app.analysis import hold_suggest
from app.settings import load_settings
from app.holds import frame_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", default="normal")
    args = parser.parse_args()
    settings = load_settings()
    connection = sqlite3.connect(f"file:{settings.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    row = dict(connection.execute("SELECT * FROM hold_maps WHERE id=?", (args.map,)).fetchone())
    attempt = dict(connection.execute("SELECT * FROM attempts WHERE id=?", (row["attempt_id"],)).fetchone())
    holds = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (args.map,))]
    reference = cv2.imread(str(frame_path(settings, attempt, row["reference_frame_ms"])))
    frames = [cv2.imread(str(frame_path(settings, attempt, int(ms)))) for ms in np.linspace(0, attempt["duration_ms"] - 200, 25)]
    image, info = hold_suggest.clean_wall(reference, frames)
    width, height = row["width"], row["height"]
    per_seed = []
    for index, seed in enumerate(holds):
        try:
            result = hold_suggest.suggest(image, seed["x"], seed["y"], args.tolerance)
        except hold_suggest.SuggestionError as error:
            per_seed.append({"seed_hold": index + 1, "error": str(error)})
            continue
        found = [any(np.hypot((s["x"] - h["x"]) * width, (s["y"] - h["y"]) * height) <= 1.5 * h["radius"] * width for s in result["suggestions"]) for h in holds]
        extra = sum(not any(np.hypot((s["x"] - h["x"]) * width, (s["y"] - h["y"]) * height) <= 1.5 * h["radius"] * width for h in holds) for s in result["suggestions"])
        per_seed.append({"seed_hold": index + 1, "seed_color": result["seed_color"], "marks_found": int(sum(found)), "marks_total": len(holds),
                         "suggestions": len(result["suggestions"]), "suggestions_matching_no_mark": int(extra), "result": result["suggestions"]})
    usable = [p for p in per_seed if "error" not in p]
    best = max(usable, key=lambda p: p["marks_found"], default=None)
    canvas = image.copy()
    for hold in holds:
        cv2.circle(canvas, (int(hold["x"] * width), int(hold["y"] * height)), int(hold["radius"] * width), (0, 200, 255), 2)
    for s in (best or {}).get("result", []):
        cv2.circle(canvas, (int(s["x"] * width), int(s["y"] * height)), int(s["radius"] * width), (255, 0, 255), 2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output.with_suffix(".jpg")), canvas)
    report = {"development_check_only": True, "map": args.map, "tolerance": args.tolerance, "image": info,
              "per_seed": [{k: v for k, v in p.items() if k != "result"} for p in per_seed]}
    args.output.write_text(json.dumps(report, indent=1) + "\n")
    print(info["detail"])
    for p in report["per_seed"]:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
