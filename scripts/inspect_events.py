#!/usr/bin/env python3
"""Draw filmstrips of selected limb episodes from a stored run, for visual spot checks.

Strips show the pose-model anchor on real frames. They support inspection only and are not accuracy measurements.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from _bootstrap import PROJECT_ROOT  # noqa: F401
from app.analysis.pose import read_jsonl
from app.analysis.video import iter_rgb_frames

CELL = 220
COLORS = {"left": (0, 140, 255), "right": (255, 200, 0)}


def _point(record, name, width, height):
    landmark = next(lm for lm in record["landmarks"] if lm["name"] == name)
    return np.array([landmark["x"] * width, landmark["y"] * height]), landmark["visibility"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--events", nargs="+", required=True, help="side:kind:start_ms such as left:foot:1000")
    args = parser.parse_args()
    run = json.loads((args.run_dir / "run.json").read_text())
    width, height, length = run["canonical"]["width"], run["canonical"]["height"], run["coverage"]["attempt_scale"]["L_px"]
    records = read_jsonl(args.run_dir / "poses.jsonl")
    by_time = {r["timestamp_ms"]: r for r in records}
    events = json.loads((args.run_dir / "events.json").read_text())["events"]
    wanted = []
    for spec in args.events:
        side, kind, start = spec.split(":")
        match = next(e for e in events if e["hand"] == side and e["type"].startswith(kind) and e["start_ms"] == int(start))
        times = [t for t in by_time if match["start_ms"] <= t <= match["end_ms"]]
        picks = [min(times, key=lambda t: abs(t - v)) for v in np.linspace(match["start_ms"], match["end_ms"], 5)]
        wanted.append((match, picks))
    frames_needed = {by_time[t]["frame_index"]: t for _, picks in wanted for t in picks}
    frames = {}
    for index, rgb in iter_rgb_frames(args.run_dir / "canonical.mp4", width, height):
        if index in frames_needed:
            frames[frames_needed[index]] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        if len(frames) == len(frames_needed):
            break
    rows = []
    for event, picks in wanted:
        side = event["hand"]
        anchor = f"{side}_ankle" if event["type"] == "foot_motion" else f"{side}_wrist"
        cells = []
        path = [_point(by_time[t], anchor, width, height)[0] for t in picks]
        center = np.mean(path, axis=0)
        radius = int(max(1.2 * length, np.ptp(np.array(path), axis=0).max() * 0.75))
        x0, y0 = int(np.clip(center[0] - radius, 0, max(0, width - 2 * radius))), int(np.clip(center[1] - radius, 0, max(0, height - 2 * radius)))
        for t in picks:
            crop = frames[t][y0:y0 + 2 * radius, x0:x0 + 2 * radius]
            scale = CELL / max(crop.shape[:2])
            cell = np.zeros((CELL, CELL, 3), np.uint8)
            resized = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            cell[:resized.shape[0], :resized.shape[1]] = resized
            point, visibility = _point(by_time[t], anchor, width, height)
            mark = (int((point[0] - x0) * scale), int((point[1] - y0) * scale))
            cv2.drawMarker(cell, mark, COLORS[side] if visibility >= 0.6 else (0, 0, 255), cv2.MARKER_CROSS, 16, 2, cv2.LINE_AA)
            cv2.putText(cell, f"{t / 1000:.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
            cv2.putText(cell, f"{t / 1000:.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
            cells.append(cell)
        rows.append(np.hstack(cells))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.output), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
