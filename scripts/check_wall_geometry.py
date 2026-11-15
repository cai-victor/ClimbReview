#!/usr/bin/env python3
"""Development check: fit the bolt grid on each marked route and compare picture distances with wall-plane distances. Read-only."""
from __future__ import annotations

import json
import sqlite3

import numpy as np

from _bootstrap import PROJECT_ROOT  # noqa: F401
from app.analysis import beta, wall_grid
from app.route_tools import build_wall_image
from app.settings import load_settings


def main() -> int:
    settings = load_settings()
    connection = sqlite3.connect(f"file:{settings.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    for row in map(dict, connection.execute("SELECT m.*, a.title FROM hold_maps m JOIN attempts a ON a.id=m.attempt_id")):
        holds = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (row["id"],))]
        attempt = dict(connection.execute("SELECT * FROM attempts WHERE id=?", (row["attempt_id"],)).fetchone())
        run = connection.execute("SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone()
        if len(holds) < 3 or run is None:
            continue
        width, height = attempt["width"], attempt["height"]
        image, _ = build_wall_image(settings, attempt, row["reference_frame_ms"], None, run["id"])
        focus = (float(np.mean([h["x"] for h in holds])) * width, float(np.mean([h["y"] for h in holds])) * height)
        fit = wall_grid.fit_image(image, width, height, focus)
        plane, summary = wall_grid.correction_for(fit, holds, width, height)
        entry = {"clip": row["title"], "holds": len(holds), "fit": fit["status"], "bolts": fit.get("inliers"), "applied": summary["applied"],
                 "on_fitted_face": summary.get("holds_on_fitted_face"), "tilt": summary.get("tilt"), "reason": summary.get("reason")}
        if plane is not None:
            directory = settings.run_dir(attempt["id"], run["id"])
            samples = json.loads((directory / "overlay.json").read_text())["samples"]
            length = json.loads((directory / "movement.json").read_text())["L_px"]
            torso = beta.plane_torso(samples, width, height, plane)
            order = sorted(range(len(holds)), key=lambda i: -holds[i]["y"])
            px = np.array([[holds[i]["x"] * width, holds[i]["y"] * height] for i in order])
            picture = np.linalg.norm(np.diff(px, axis=0), axis=1) / length
            wall = np.linalg.norm(np.diff(plane.plane(px), axis=0), axis=1) / torso
            ratio = wall / np.maximum(picture, 1e-6)
            third = max(1, len(ratio) // 3)
            entry.update(scale_change=summary["scale_change"], torso_grid_steps=round(torso, 2),
                         bottom_third_wall_over_picture=round(float(np.median(ratio[:third])), 2), top_third_wall_over_picture=round(float(np.median(ratio[-third:])), 2),
                         largest_gap_picture_L=round(float(picture.max()), 2), largest_gap_wall_L=round(float(wall.max()), 2))
            if any(h["role"] == "start" for h in holds) and any(h["role"] == "finish" for h in holds):
                body = beta.body_model(samples, width, height, length)
                on_plane = beta.body_model(samples, width, height, length, plane)
                plane_body = beta.Body(on_plane.arm_L * length / torso, on_plane.leg_L * length / torso, 0, 0)
                points = plane.plane([[h["x"] * width, h["y"] * height] for h in holds]) / torso
                flat, corrected = beta.candidate_sequences(holds, width, height, length, body), beta.candidate_sequences(holds, width, height, length, plane_body, points)
                describe = lambda r: r["status"] if r["status"] != "ready" else [(c["label"], c["move_count"], c["largest_move_L"], c["tightest_margin_L"]) for c in r["candidates"]]
                entry.update(candidates_picture=describe(flat), candidates_wall=describe(corrected),
                             arm_leg_picture=(round(body.arm_L, 2), round(body.leg_L, 2)), arm_leg_wall=(round(plane_body.arm_L, 2), round(plane_body.leg_L, 2)))
        print(json.dumps(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
