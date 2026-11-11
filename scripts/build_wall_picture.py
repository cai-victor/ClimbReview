#!/usr/bin/env python3
"""Write the combined wall picture for an attempt to a file, without touching the app's database or caches."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import cv2

from _bootstrap import PROJECT_ROOT  # noqa: F401
from app.route_tools import build_wall_image
from app.settings import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--reference-ms", type=int, default=200)
    parser.add_argument("--untracked", action="store_true", help="Ignore body tracking, to compare")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = load_settings()
    connection = sqlite3.connect(f"file:{settings.database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    attempt = dict(connection.execute("SELECT * FROM attempts WHERE id=?", (args.attempt,)).fetchone())
    run = connection.execute("SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (args.attempt,)).fetchone()
    image, info = build_wall_image(settings, attempt, args.reference_ms, None, None if args.untracked or run is None else run["id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), image)
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
