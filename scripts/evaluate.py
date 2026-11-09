#!/usr/bin/env python3
"""Score detector output against independent human annotations.

No labels are generated here. If annotations are empty or a split has no clips, the
command stops with a message and writes no results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from _bootstrap import PROJECT_ROOT
from app.analysis import ClimbReviewError
from app.analysis.evaluation import evaluate, load_annotations, load_manifest


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "evaluation" / "dataset_manifest.csv")
    parser.add_argument("--annotations", type=Path, default=PROJECT_ROOT / "evaluation" / "annotations.csv")
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--tiou", type=float, default=0.30, help="Matching threshold; freeze before test evaluation")
    parser.add_argument("--events-file", default="events.json",
                        help="Events in each run directory; use events_baseline_raw.json for the baseline")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.manifest.exists() or not args.annotations.exists():
            raise ClimbReviewError("Manifest or annotations file not found. See docs/ANNOTATION_GUIDE.md.")
        manifest = load_manifest(args.manifest)
        durations = {row["clip_id"]: int(row["video_duration_ms"]) for row in manifest}
        annotations = load_annotations(args.annotations, durations)
        if not annotations:
            raise ClimbReviewError("Annotations are empty. Metrics require independent human labels.")
        result = evaluate(manifest, annotations, args.split, args.tiou, PROJECT_ROOT, args.events_file)
    except ClimbReviewError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    result["inputs"] = {"manifest_sha256": sha256(args.manifest), "annotations_sha256": sha256(args.annotations)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {args.output}")
    for key, score in result["pooled"].items():
        print(f"  {key}: TP {score['true_positives']} FP {score['false_positives']} FN {score['false_negatives']} "
              f"precision {score['precision']} recall {score['recall']} f1 {score['f1']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
