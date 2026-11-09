#!/usr/bin/env python3
"""Feasibility CLI: normalize a video, extract pose, render overlay, report coverage."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _bootstrap import PROJECT_ROOT
from app.analysis import ClimbReviewError
from app.analysis.config import load_config
from app.analysis.pipeline import PROVENANCE_CHOICES, run_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Local MP4/MOV file; it is never modified")
    parser.add_argument("--output", type=Path, required=True, help="Run directory to create")
    parser.add_argument("--clip-id", help="Anonymous clip ID (default: output folder name)")
    parser.add_argument("--attempt-start-ms", type=int, help="Attempt start in canonical media ms (default 0)")
    parser.add_argument("--attempt-end-ms", type=int, help="Attempt end in canonical media ms (default: video end)")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "detectors.yaml")
    parser.add_argument("--provenance", choices=PROVENANCE_CHOICES, default="user_supplied_unverified")
    parser.add_argument("--overwrite", action="store_true", help="Replace an earlier run directory")
    args = parser.parse_args()
    try:
        run = run_analysis(
            args.video.resolve(), args.output.resolve(), load_config(args.config), PROJECT_ROOT,
            args.clip_id or args.output.name, args.attempt_start_ms, args.attempt_end_ms,
            args.provenance, args.overwrite,
        )
    except ClimbReviewError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"\nWrote {args.output}")
    for name, item in run["coverage"]["detectors"].items():
        fraction = "unavailable" if item["fraction"] is None else f"{item['fraction'] * 100:.1f}%"
        print(f"  {name}: {item['status']}, eligible {fraction}")
    for warning in run["warnings"]:
        print(f"  warning: {warning}")
    print("Tracking quality is UNVERIFIED until a person inspects overlay.mp4 and contact_sheet.jpg.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
