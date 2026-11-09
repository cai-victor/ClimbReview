"""Ablation: compare the final detectors with raw landmarks and no hysteresis.

Both variants read the same stored poses and validity, so only the temporal logic
differs. This module compares the variants with each other. It never produces an
accuracy figure; scoring against human labels is done by scripts/evaluate.py with
`--events-file events_baseline_raw.json`.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Sequence

from . import PIPELINE_VERSION
from . import detectors as detectors_module
from . import quality
from .config import PipelineConfig
from .evaluation import EVENT_KEYS, Interval, match_events
from .pose import read_jsonl, sha256_file

COMPARISON_VERSION = "baseline-comparison-v1"
BASELINE_EVENTS_FILE = "events_baseline_raw.json"
AGREEMENT_TIOU = 0.30
VARIANTS = {
    "final": {"smoothing": True, "hysteresis": True},
    "baseline_raw": {"smoothing": False, "hysteresis": False},
}
NOTE = ("Agreement compares the two variants with each other. It is not accuracy. "
        "Precision, recall, and F1 require independent human labels (scripts/evaluate.py).")


def _key(event: dict[str, Any]) -> str:
    return "low_movement" if event["type"] == "low_movement" else f"{event['type']}_{event['hand']}"


def _intervals(clip_id: str, events: Sequence[dict[str, Any]], key: str) -> list[Interval]:
    return [Interval(clip_id, key, e["start_ms"], e["end_ms"]) for e in events if _key(e) == key]


def _describe(intervals: Sequence[Interval], available: bool) -> dict[str, Any]:
    if not available:
        return {"status": "insufficient_tracking", "event_count": None, "total_ms": None, "median_duration_ms": None}
    durations = [i.duration for i in intervals]
    return {"status": "available", "event_count": len(durations), "total_ms": sum(durations),
            "median_duration_ms": statistics.median(durations) if durations else None}


def _signature(events: Sequence[dict[str, Any]]) -> list[tuple[str, str | None, int, int]]:
    return sorted((e["type"], e["hand"], e["start_ms"], e["end_ms"]) for e in events)


def compare_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the clip comparison and the baseline detection output for one run."""
    run = json.loads((run_dir / "run.json").read_text())
    config = PipelineConfig.model_validate(run["config"])
    records = read_jsonl(run_dir / "poses.jsonl")
    width, height = run["canonical"]["width"], run["canonical"]["height"]
    bounds = run["attempt_bounds_ms"]
    period = config.analysis.sample_period_ms
    validity = quality.derive_validity(records, width, height, config.quality, period)
    coverage = quality.compute_coverage(records, width, height, bounds["start"], bounds["end"], config.quality, period,
                                        config.feasibility.low_movement_target_fraction, validity)
    outputs = {name: detectors_module.run_detectors(records, validity, width, height, coverage, config, **flags)
               for name, flags in VARIANTS.items()}
    stored = json.loads((run_dir / "events.json").read_text())

    clip_id = run["clip_id"]
    detectors: dict[str, Any] = {}
    for key in EVENT_KEYS:
        available = outputs["final"]["detectors"][key]["status"] == "available"
        final = _intervals(clip_id, outputs["final"]["events"], key)
        baseline = _intervals(clip_id, outputs["baseline_raw"]["events"], key)
        matched = len(match_events(final, baseline, AGREEMENT_TIOU))
        detectors[key] = {
            "final": _describe(final, available),
            "baseline_raw": _describe(baseline, available),
            "agreement": None if not available else {
                "tiou_threshold": AGREEMENT_TIOU, "matched": matched,
                "final_only": len(final) - matched, "baseline_only": len(baseline) - matched,
            },
        }
    comparison = {
        "clip_id": clip_id,
        "data_provenance": run["data_provenance"],
        "poses_sha256": sha256_file(run_dir / "poses.jsonl"),
        "config_hash": config.content_hash(),
        "stored_events_reproduced": _signature(stored["events"]) == _signature(outputs["final"]["events"]),
        "detectors": detectors,
    }
    baseline_output = {**outputs["baseline_raw"], "variant": "baseline_raw", "flags": VARIANTS["baseline_raw"],
                       "comparison_version": COMPARISON_VERSION}
    return comparison, baseline_output


def write_comparison(run_dirs: Sequence[Path], output: Path) -> dict[str, Any]:
    clips = []
    for run_dir in run_dirs:
        comparison, baseline = compare_run(run_dir)
        (run_dir / BASELINE_EVENTS_FILE).write_text(json.dumps(baseline, indent=2, allow_nan=False) + "\n")
        clips.append(comparison)
    report = {
        "comparison_version": COMPARISON_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "detector_version": detectors_module.DETECTOR_VERSION,
        "variants": VARIANTS,
        "note": NOTE,
        "clips": clips,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report
