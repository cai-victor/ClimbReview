#!/usr/bin/env python3
"""Evaluate the frozen forecast and baselines on untouched test groups and stress sets.

A ledger records each held-out evaluation. A changed model cannot read the test split
again unless --acknowledge-repeat-test is given, and that fact is written to the results.
Errors are in torso-length units against later pose estimates, not human ground truth.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import numpy as np

from _bootstrap import PROJECT_ROOT
from app.forecast import model as md
from app.forecast.config import load_forecast_config
from app.forecast.dataset import ELIGIBLE_PRIMARY, ELIGIBLE_STRESS, SIDES, constant_velocity_prediction

ROOT = PROJECT_ROOT / "data" / "public_training"
METHODS = ("ridge", "persistence", "constant_velocity")


def predictions(artifact: dict, side: str, features: np.ndarray, horizon_ms: int) -> dict[str, np.ndarray]:
    window = artifact["sides"][side]["constant_velocity_window_ms"]
    return {"ridge": md.predict(artifact["sides"][side], features), "persistence": np.zeros((len(features), 2)),
            "constant_velocity": np.vstack([constant_velocity_prediction(r, side, window, horizon_ms) for r in features])}


def summarize(errors: np.ndarray) -> dict:
    return {"n": int(len(errors)), "mae_L": float(np.mean(errors)), "rmse_L": float(np.sqrt(np.mean(errors ** 2))),
            "median_L": float(np.median(errors))}


def score(mask: np.ndarray, data, artifact, config) -> dict:
    """Identical examples for every method; clip and group averages count each unit once."""
    if not mask.any():
        return {"n_examples": 0, "n_clips": 0, "n_groups": 0, "note": "No eligible examples."}
    errors = {m: [] for m in METHODS}
    clips, groups = [], []
    for side in SIDES:
        subset = mask & (data["side"] == side)
        if not subset.any():
            continue
        result = predictions(artifact, side, data["features"][subset], config.horizon_ms)
        for method in METHODS:
            errors[method].append(md.endpoint_errors(result[method], data["targets"][subset]))
        clips.append(data["clip"][subset]); groups.append(data["group"][subset])
    clip_array, group_array = np.concatenate(clips), np.concatenate(groups)
    pooled = {m: np.concatenate(errors[m]) for m in METHODS}
    report = {"n_examples": int(mask.sum()), "n_clips": int(len(np.unique(clip_array))), "n_groups": int(len(np.unique(group_array))),
              "pooled": {m: summarize(pooled[m]) for m in METHODS}}
    for unit, labels in (("per_clip", clip_array), ("per_group", group_array)):
        report[unit] = {label: {m: summarize(pooled[m][labels == label]) for m in METHODS} for label in sorted(set(labels))}
        report[f"macro_{unit[4:]}_mae_L"] = {m: float(np.mean([report[unit][l][m]["mae_L"] for l in report[unit]])) for m in METHODS}
    report["groups_where_ridge_beats"] = {
        baseline: int(sum(report["per_group"][g]["ridge"]["mae_L"] < report["per_group"][g][baseline]["mae_L"] for g in report["per_group"]))
        for baseline in ("persistence", "constant_velocity")}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-repeat-test", action="store_true")
    args = parser.parse_args()
    config = load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")
    model_text = (ROOT / "models" / f"{config.version}.json").read_text()
    artifact = json.loads(model_text)
    model_hash = md.sha256_text(model_text.strip())
    results_dir = ROOT / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    ledger = results_dir / "test_access_log.jsonl"
    previous = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    repeated = any(entry["model_sha256"] != model_hash for entry in previous)
    if repeated and not args.acknowledge_repeat_test:
        print("error: the test split was already used with a different model. Refusing to evaluate.", file=sys.stderr)
        return 2
    data = np.load(ROOT / "dataset" / f"{config.version}.npz")
    primary, stress = data["status"] == ELIGIBLE_PRIMARY, data["status"] == ELIGIBLE_STRESS
    splits = data["split"]
    report = {
        "version": config.version, "model_sha256": model_hash, "dataset_content_sha256": artifact["dataset_content_sha256"],
        "units": "Euclidean endpoint error in torso lengths of body-relative wrist displacement over 0.5 s",
        "caution": "Targets are later pose estimates, not human ground truth. Windows overlap and are correlated.",
        "repeat_test_use": repeated,
        "held_out_test_primary": score((splits == "test") & primary, data, artifact, config),
        "held_out_test_camera_moving_stress": score((splits == "test") & stress, data, artifact, config),
        "personal_dev_stress_primary": score((splits == "personal_stress") & primary, data, artifact, config),
        "personal_dev_stress_camera_moving": score((splits == "personal_stress") & stress, data, artifact, config),
    }
    with ledger.open("a") as handle:
        handle.write(json.dumps({"model_sha256": model_hash, "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
    tracked = PROJECT_ROOT / "evaluation" / "forecast"
    tracked.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=1, sort_keys=True, allow_nan=False) + "\n"
    (tracked / f"results_{config.version}.json").write_text(text)
    for name in ("held_out_test_primary", "held_out_test_camera_moving_stress", "personal_dev_stress_primary"):
        section = report[name]
        print(name, section["n_examples"], "examples", section["n_clips"], "clips", section["n_groups"], "groups")
        if section["n_examples"]:
            for method in METHODS:
                print(f"  {method}: pooled MAE {section['pooled'][method]['mae_L']:.4f} RMSE {section['pooled'][method]['rmse_L']:.4f} "
                      f"macro-group MAE {section['macro_group_mae_L'][method]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
