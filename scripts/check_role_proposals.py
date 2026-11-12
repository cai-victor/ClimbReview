#!/usr/bin/env python3
"""Development check: compare proposed start, finish, and uses with the roles and uses the climber marked. Read-only."""
from __future__ import annotations

import json
import sqlite3

from _bootstrap import PROJECT_ROOT  # noqa: F401
from app.analysis import route_auto
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
        if not holds or run is None:
            continue
        directory = settings.run_dir(attempt["id"], run["id"])
        series, samples = json.loads((directory / "movement.json").read_text()), json.loads((directory / "overlay.json").read_text())["samples"]
        _, info = build_wall_image(settings, attempt, row["reference_frame_ms"], None, run["id"])
        rests = route_auto.to_reference(route_auto.rest_points(series, samples), info.get("registered", []), attempt["width"], attempt["height"])
        proposal = route_auto.assign_roles(holds, rests, attempt["width"], attempt["height"], series["L_px"])["holds"]
        with_use = [(h, p) for h, p in zip(holds, proposal) if h["use"]]
        compatible = lambda mine, theirs: theirs == "" or mine == theirs or "both" in (mine, theirs)
        print({"clip": row["title"], "holds": len(holds), "rests": len(rests), "near_any_limb": sum(bool(p["visited_by"]) for p in proposal),
               "marked_start": [i + 1 for i, h in enumerate(holds) if h["role"] == "start"], "proposed_start": [i + 1 for i, p in enumerate(proposal) if p["role"] == "start"],
               "marked_finish": [i + 1 for i, h in enumerate(holds) if h["role"] == "finish"], "proposed_finish": [i + 1 for i, p in enumerate(proposal) if p["role"] == "finish"],
               "uses_marked": len(with_use), "uses_proposed_and_compatible": sum(bool(p["use"]) and compatible(h["use"], p["use"]) for h, p in with_use),
               "uses_proposed_and_conflicting": sum(bool(p["use"]) and not compatible(h["use"], p["use"]) for h, p in with_use),
               "uses_left_unset": sum(not p["use"] for h, p in with_use)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
