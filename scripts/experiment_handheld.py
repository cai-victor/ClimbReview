#!/usr/bin/env python3
"""EXPERIMENTAL, development clips only: exclusion-only versus background compensation.

More coverage is not evidence of better accuracy. Reserved clips and the frozen forecast
test groups are never read.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from _bootstrap import PROJECT_ROOT
from app.analysis import camera_compensation as cc
from app.analysis import detectors, quality
from app.analysis.config import PipelineConfig
from app.analysis.pose import read_jsonl
from app.analysis.video import iter_rgb_frames

RUNS = [PROJECT_ROOT / "data" / "feasibility" / c for c in ("phone01", "phone02", "phone03_a1", "phone04", "phone05")] + \
       [PROJECT_ROOT / "data" / "public_feasibility" / c for c in ("public_khazanov_v3", "public_caulier", "public_rockspot_v3")]
OUTPUT = PROJECT_ROOT / "data" / "experiments" / "handheld"


def counts(result: dict) -> dict:
    return {k: result["detectors"][k]["event_count"] for k in result["detectors"]}


def coverage_summary(coverage: dict) -> dict:
    return {k: {"status": v["status"], "fraction": v["fraction"]} for k, v in coverage["detectors"].items()}


def strip(frames: dict[int, np.ndarray], records, intervals, path: Path) -> None:
    """Reference frame, raw later frame blended, and compensated later frame blended; background ghosting shows residual motion."""
    start = next((i for i, step in enumerate(intervals) if step["accepted"]), None)
    if start is None:
        return
    cumulative, end = np.eye(3), start
    for j in range(start, min(start + 20, len(intervals))):
        if not intervals[j]["accepted"]:
            break
        cumulative = np.vstack([np.array(intervals[j]["matrix"]), [0, 0, 1]]) @ cumulative
        end = j + 1
    reference, later = frames[records[start]["frame_index"]], frames[records[end]["frame_index"]]
    height, width = reference.shape[:2]
    warped = cv2.warpAffine(later, np.linalg.inv(cumulative)[:2], (width, height))
    raw_blend = cv2.addWeighted(reference, 0.5, later, 0.5, 0)
    comp_blend = cv2.addWeighted(reference, 0.5, warped, 0.5, 0)
    panel = np.hstack([cv2.resize(p, None, fx=360 / max(width, height), fy=360 / max(width, height)) for p in (raw_blend, comp_blend)])
    cv2.imwrite(str(path), cv2.cvtColor(panel, cv2.COLOR_RGB2BGR))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    limits = cc.TransformLimits()
    rows = []
    for run_dir in RUNS:
        run = json.loads((run_dir / "run.json").read_text())
        config = PipelineConfig.model_validate(run["config"])
        records = read_jsonl(run_dir / "poses.jsonl")
        width, height = run["canonical"]["width"], run["canonical"]["height"]
        bounds = run["attempt_bounds_ms"]
        wanted = {r["frame_index"] for r in records}
        frames = {}
        for index, rgb in iter_rgb_frames(run_dir / "canonical.mp4", width, height):
            if index in wanted:
                frames[index] = rgb.copy()
            if len(frames) == len(wanted):
                break
        intervals = cc.estimate_track(frames, records, limits)
        period = config.analysis.sample_period_ms

        def analyze(state, positions):
            validity = quality.derive_validity(state, width, height, config.quality, period)
            coverage = quality.compute_coverage(state, width, height, bounds["start"], bounds["end"], config.quality, period,
                                                config.feasibility.low_movement_target_fraction, validity)
            return coverage, detectors.run_detectors(positions, validity, width, height, coverage, config)

        base_coverage, base = analyze(records, records)
        state = cc.with_transform_camera_state(records, intervals)
        compensated = cc.compensated_records(records, intervals, width, height)
        comp_coverage, comp = analyze(state, compensated)

        accepted = [s for s in intervals if s["accepted"]]
        reasons: dict[str, int] = {}
        for step in intervals:
            if not step["accepted"]:
                reasons[step["reason"]] = reasons.get(step["reason"], 0) + 1
        # Residual after compensation, against the median shift it removed.
        shifts = [float(np.hypot(s["matrix"][0][2], s["matrix"][1][2])) for s in accepted]
        row = {
            "clip_id": run["clip_id"], "intervals": len(intervals), "accepted": len(accepted),
            "accepted_fraction": round(len(accepted) / len(intervals), 4) if intervals else None,
            "rejection_reasons": reasons,
            "median_background_residual_px": round(float(np.median([s["median_residual_px"] for s in accepted])), 3) if accepted else None,
            "median_camera_shift_px_per_interval": round(float(np.median(shifts)), 3) if shifts else None,
            "exclusion_only": {"coverage": coverage_summary(base_coverage), "events": counts(base)},
            "compensated": {"coverage": coverage_summary(comp_coverage), "events": counts(comp)},
        }
        rows.append(row)
        (OUTPUT / f"{run['clip_id']}_transforms.json").write_text(json.dumps({"method_version": cc.METHOD_VERSION, "limits": limits.__dict__, "intervals": intervals}))
        strip(frames, records, intervals, OUTPUT / f"{run['clip_id']}_alignment.jpg")
        print(run["clip_id"], json.dumps(row), flush=True)
    summary = {"method_version": cc.METHOD_VERSION, "status": "experimental, development clips only",
               "caution": "More coverage does not show better accuracy; event validity needs human labels.", "clips": rows}
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
