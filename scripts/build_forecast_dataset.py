#!/usr/bin/env python3
"""Build causal forecast examples from stored pose runs. No inference and no model fitting.

Earlier public development clips may only train. The user's development clips form a
separate stress set. Reserved clips are refused.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from _bootstrap import PROJECT_ROOT
from app.analysis.config import PipelineConfig
from app.analysis.pose import read_jsonl, sha256_file
from app.forecast.config import load_forecast_config
from app.forecast.dataset import ELIGIBLE_PRIMARY, ELIGIBLE_STRESS, build_clip_examples, feature_names

ROOT = PROJECT_ROOT / "data" / "public_training"
EARLIER_PUBLIC = {"public_khazanov_v3": "alex_khazanov", "public_caulier": "chloe_caulier", "public_rockspot_v3": "cryptic_c62"}
PERSONAL = ("phone01", "phone02", "phone03_a1", "phone04", "phone05")


def reserved_filenames() -> set[str]:
    path = PROJECT_ROOT / "data" / "raw" / "phone_import_inventory.json"
    if not path.exists():
        return set()
    return {Path(f["filename"]).name for f in json.loads(path.read_text())["files"] if f["role"] != "development"}


def clip_plan() -> list[dict[str, str]]:
    split = json.loads((PROJECT_ROOT / "config" / "public_training_split.json").read_text())
    plan = [{"clip_id": c, "group_id": v["group_id"], "split": v["split"], "run_dir": str(ROOT / "runs" / c)}
            for c, v in split["clips"].items()]
    plan += [{"clip_id": c, "group_id": g, "split": "train", "run_dir": str(PROJECT_ROOT / "data" / "public_feasibility" / c)}
             for c, g in EARLIER_PUBLIC.items()]
    plan += [{"clip_id": c, "group_id": c, "split": "personal_stress", "run_dir": str(PROJECT_ROOT / "data" / "feasibility" / c)}
             for c in PERSONAL]
    return plan


def main() -> int:
    config = load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")
    reserved = reserved_filenames()
    arrays: dict[str, list] = {k: [] for k in ("features", "targets", "side", "clip", "group", "split", "t_ms", "status", "scale")}
    sample_rows, clip_counts, inputs = [], [], {}
    for item in clip_plan():
        run_dir = Path(item["run_dir"])
        if not (run_dir / "poses.jsonl").exists():
            print(f"skip {item['clip_id']}: no stored run")
            continue
        run = json.loads((run_dir / "run.json").read_text())
        if run["source"]["filename"] in reserved:
            print(f"error: {item['clip_id']} is reserved.", file=sys.stderr)
            return 2
        quality = PipelineConfig.model_validate(run["config"]).quality
        records = read_jsonl(run_dir / "poses.jsonl")
        inputs[item["clip_id"]] = sha256_file(run_dir / "poses.jsonl")
        tally: dict[str, dict[str, int]] = {"left": {}, "right": {}}
        for example in build_clip_examples(records, run["canonical"]["width"], run["canonical"]["height"], quality, config):
            key = example.reason or example.status
            tally[example.side][key] = tally[example.side].get(key, 0) + 1
            sample_rows.append({"clip_id": item["clip_id"], "group_id": item["group_id"], "split": item["split"], "side": example.side,
                                "t_ms": example.t_ms, "status": example.status, "reason": example.reason or ""})
            if example.features is not None:
                arrays["features"].append(example.features); arrays["targets"].append(example.target)
                arrays["side"].append(example.side); arrays["clip"].append(item["clip_id"]); arrays["group"].append(item["group_id"])
                arrays["split"].append(item["split"]); arrays["t_ms"].append(example.t_ms); arrays["status"].append(example.status)
                arrays["scale"].append(example.scale_px)
        clip_counts.append({"clip_id": item["clip_id"], "group_id": item["group_id"], "split": item["split"], "samples": len(records),
                            "attempt_ms": run["attempt_bounds_ms"]["end"] - run["attempt_bounds_ms"]["start"], "tally": tally})
    output = ROOT / "dataset"
    output.mkdir(parents=True, exist_ok=True)
    stored = {k: np.array(v) for k, v in arrays.items()}
    np.savez(output / f"{config.version}.npz", **stored)
    digest = hashlib.sha256(np.array2string(stored["features"], threshold=10**9, precision=8).encode()
                            + np.array2string(stored["targets"], threshold=10**9, precision=8).encode()).hexdigest()
    with (output / f"{config.version}_samples.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sample_rows[0]))
        writer.writeheader()
        writer.writerows(sample_rows)
    manifest = {"version": config.version, "config": config.model_dump(), "feature_names_left": feature_names("left"),
                "content_sha256": digest, "input_pose_sha256": inputs, "clips": clip_counts,
                "note": "Windows overlap and are correlated. Report counts by clip and group."}
    (output / f"{config.version}_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    primary = stored["status"] == ELIGIBLE_PRIMARY
    for split in ("train", "test", "personal_stress"):
        mask = stored["split"] == split
        print(f"{split}: primary {int((mask & primary).sum())}, camera-moving {int((mask & (stored['status'] == ELIGIBLE_STRESS)).sum())}, "
              f"clips with primary {len(set(stored['clip'][mask & primary]))}, groups with primary {len(set(stored['group'][mask & primary]))}")
    print(f"content sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
