#!/usr/bin/env python3
"""Run the feasibility CLI on every clip in data/raw/manifest.csv and tabulate results."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from _bootstrap import PROJECT_ROOT
from app.analysis import ClimbReviewError
from app.analysis.config import load_config
from app.analysis.pipeline import PROVENANCE_CHOICES, run_analysis

REQUIRED_COLUMNS = {"clip_id", "filename", "attempt_start_ms", "attempt_end_ms"}
SUMMARY_COLUMNS = [
    "clip_id", "camera_view", "conditions", "result", "pose_detected_fraction", "attempt_scale",
    "low_movement_fraction", "wrist_left_fraction", "wrist_right_fraction", "provisional_target_met",
    "inference_samples_per_s", "manual_alignment_review", "error",
]


def _optional_int(text: str | None) -> int | None:
    return int(text) if text and text.strip() else None


def _row_result(row: dict[str, str], run: dict | None, error: str) -> dict[str, object]:
    base = {"clip_id": row["clip_id"], "camera_view": row.get("camera_view", ""),
            "conditions": row.get("conditions", ""), "manual_alignment_review": "not_reviewed", "error": error}
    if run is None:
        return {**base, "result": "failed"}
    coverage = run["coverage"]
    detectors = coverage["detectors"]
    return {
        **base,
        "result": "completed",
        "pose_detected_fraction": coverage["pose_detected_fraction"],
        "attempt_scale": coverage["attempt_scale"]["status"],
        "low_movement_fraction": detectors["low_movement"]["fraction"],
        "wrist_left_fraction": detectors["wrist_motion_left"]["fraction"],
        "wrist_right_fraction": detectors["wrist_motion_right"]["fraction"],
        "provisional_target_met": coverage["provisional_coverage_target"]["met"],
        "inference_samples_per_s": round(run["runtime_s"]["inference_samples_per_s"], 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "data" / "raw" / "manifest.csv")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data" / "feasibility")
    parser.add_argument("--provenance", choices=PROVENANCE_CHOICES, default="user_supplied_unverified")
    parser.add_argument("--overwrite", action="store_true", help="Replace earlier runs of these clips")
    args = parser.parse_args()

    raw_dir = args.manifest.resolve().parent
    with args.manifest.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            print(f"error: manifest lacks columns: {sorted(missing)}", file=sys.stderr)
            return 2
        rows = [r for r in reader if (r.get("clip_id") or "").strip()]
    if not rows:
        print(f"error: {args.manifest} lists no clips. Add 3-5 clips; see data/raw/README.md.", file=sys.stderr)
        return 2
    if not 3 <= len(rows) <= 5:
        print(f"note: the feasibility plan asks for 3-5 clips; manifest has {len(rows)}.")

    config = load_config(PROJECT_ROOT / "config" / "detectors.yaml")
    results = []
    for row in rows:
        clip_id, filename = row["clip_id"].strip(), row["filename"].strip()
        print(f"\n=== {clip_id} ===", flush=True)
        run, error = None, ""
        try:
            source = (raw_dir / filename).resolve()
            if raw_dir not in source.parents:
                raise ClimbReviewError(f"{filename} is outside {raw_dir}")
            run = run_analysis(source, args.output_root.resolve() / clip_id, config, PROJECT_ROOT, clip_id,
                               _optional_int(row["attempt_start_ms"]), _optional_int(row["attempt_end_ms"]),
                               args.provenance, args.overwrite)
        except (ClimbReviewError, ValueError) as exc:
            error = str(exc)
            print(f"error: {error}", file=sys.stderr)
        results.append(_row_result(row, run, error))

    args.output_root.mkdir(parents=True, exist_ok=True)
    summary = args.output_root / "summary.csv"
    with summary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {summary}. Inspect each overlay; every clip stays 'not_reviewed' until a person checks it.")
    return 0 if all(r["result"] == "completed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
