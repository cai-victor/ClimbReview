#!/usr/bin/env python3
"""Fit the experimental Ridge forecast on training groups only. Test groups are not read."""
from __future__ import annotations

import json

import numpy as np
import sklearn

from _bootstrap import PROJECT_ROOT
from app.forecast import model as md
from app.forecast.config import load_forecast_config
from app.forecast.dataset import ELIGIBLE_PRIMARY, SIDES

ROOT = PROJECT_ROOT / "data" / "public_training"


def main() -> int:
    config = load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")
    data = np.load(ROOT / "dataset" / f"{config.version}.npz")
    manifest = json.loads((ROOT / "dataset" / f"{config.version}_manifest.json").read_text())
    train = (data["split"] == "train") & (data["status"] == ELIGIBLE_PRIMARY)
    artifact: dict = {"version": config.version, "kind": "experimental_wrist_motion_forecast",
                      "not": ["pose inference", "event detection", "technique feedback"],
                      "config": config.model_dump(), "dataset_content_sha256": manifest["content_sha256"],
                      "library": {"scikit_learn": sklearn.__version__, "numpy": np.__version__}, "sides": {}}
    selection = {}
    for side in SIDES:
        mask = train & (data["side"] == side)
        features, targets, groups = data["features"][mask], data["targets"][mask], data["group"][mask]
        chosen = md.select_hyperparameters(features, targets, groups, side, config)
        artifact["sides"][side] = md.fit_side_model(features, targets, side, chosen["alpha"], chosen["constant_velocity_window_ms"])
        artifact["sides"][side]["n_training_groups"] = int(len(np.unique(groups)))
        selection[side] = {**chosen, "n_examples": int(mask.sum()), "n_groups": int(len(np.unique(groups))),
                           "n_clips": int(len(np.unique(data["clip"][mask])))}
        print(side, json.dumps(selection[side]))
    output = ROOT / "models"
    output.mkdir(parents=True, exist_ok=True)
    text = md.canonical_json(artifact)
    (output / f"{config.version}.json").write_text(text + "\n")
    (output / f"{config.version}_selection.json").write_text(md.canonical_json(selection) + "\n")
    print(f"model sha256 {md.sha256_text(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
