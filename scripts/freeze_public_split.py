#!/usr/bin/env python3
"""Freeze the grouped train/test split once. Uses only group metadata, never results."""
from __future__ import annotations

import json
import sys

from _bootstrap import PROJECT_ROOT
from app.forecast.config import load_forecast_config
from app.forecast.split import freeze_split

OUTPUT = PROJECT_ROOT / "config" / "public_training_split.json"


def main() -> int:
    if OUTPUT.exists():
        print(f"error: {OUTPUT} is frozen. Delete it deliberately to redo the split.", file=sys.stderr)
        return 2
    sources = json.loads((PROJECT_ROOT / "config" / "public_training_sources.json").read_text())["sources"]
    config = load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")
    split = freeze_split(sources, config.seed)
    OUTPUT.write_text(json.dumps(split, indent=1, sort_keys=True) + "\n")
    print(json.dumps(split["groups"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
