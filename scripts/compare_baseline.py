#!/usr/bin/env python3
"""Compare final detectors with the raw-landmark, no-hysteresis baseline on stored runs.

Re-reads each run's poses and configuration; no inference. Reports variant differences,
not accuracy. Runs of clips reserved in data/raw/phone_import_inventory.json are refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import PROJECT_ROOT
from app.analysis import ClimbReviewError
from app.analysis.baseline import COMPARISON_VERSION, write_comparison

INVENTORY = PROJECT_ROOT / "data" / "raw" / "phone_import_inventory.json"


def reserved_filenames() -> set[str]:
    if not INVENTORY.exists():
        return set()
    files = json.loads(INVENTORY.read_text())["files"]
    return {Path(f["filename"]).name for f in files if f["role"] != "development"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, action="append",
                        help="Folder of run directories; may repeat (default: data/feasibility and data/public_feasibility)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "baseline_comparison" / f"{COMPARISON_VERSION}.json")
    args = parser.parse_args()
    roots = args.runs_root or [PROJECT_ROOT / "data" / "feasibility", PROJECT_ROOT / "data" / "public_feasibility"]
    reserved = reserved_filenames()
    runs = []
    for root in roots:
        for candidate in sorted(root.iterdir()) if root.is_dir() else []:
            if (candidate / "run.json").exists() and (candidate / "poses.jsonl").exists():
                if json.loads((candidate / "run.json").read_text())["source"]["filename"] in reserved:
                    print(f"error: {candidate.name} is a reserved clip and must not be used here.", file=sys.stderr)
                    return 2
                runs.append(candidate)
    if not runs:
        print("error: no completed runs found.", file=sys.stderr)
        return 2
    try:
        report = write_comparison(runs, args.output)
    except ClimbReviewError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {args.output}\n{report['note']}")
    for clip in report["clips"]:
        cells = []
        for key, item in clip["detectors"].items():
            cells.append(f"{key}: final {item['final']['event_count']} vs raw {item['baseline_raw']['event_count']}")
        flag = "" if clip["stored_events_reproduced"] else "  [STORED EVENTS NOT REPRODUCED]"
        print(f"  {clip['clip_id']}: " + "; ".join(cells) + flag)
    return 0 if all(c["stored_events_reproduced"] for c in report["clips"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
