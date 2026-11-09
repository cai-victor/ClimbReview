#!/usr/bin/env python3
"""Create the development manifest for the user's phone clips and the over-limit excerpt.

Only the five development clips are touched; phone06 and phone07 stay reserved.
Originals are read-only inputs. Private paths and footage stay in ignored data/raw/.
Bounds below were chosen by viewing frames of each clip.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys

import numpy as np

from _bootstrap import PROJECT_ROOT
from app.analysis.pose import sha256_file
from app.analysis.video import probe, tool_path

RAW = PROJECT_ROOT / "data" / "raw"
COMMON = {"camera_motion": "handheld, small drift", "assistant_may_inspect_frames": "yes",
          "allowed_dev_use": "local development; no public distribution"}
CLIPS = [
    {"clip_id": "phone01", "filename": "originals/IMG_1123.MOV", "camera_view": "back, oblique from below",
     "conditions": "portrait; foreground arm at frame edge", "attempt_start_ms": 5000, "attempt_end_ms": 48000},
    {"clip_id": "phone02", "filename": "originals/IMG_1129.MOV", "camera_view": "side/oblique on arete, panned",
     "conditions": "portrait; large pan; other person passes behind", "attempt_start_ms": 4000, "attempt_end_ms": 58000},
    {"clip_id": "phone04", "filename": "originals/IMG_2154.MOV", "camera_view": "back, oblique from below",
     "conditions": "portrait; ends with fall", "attempt_start_ms": 2000, "attempt_end_ms": 57000},
    {"clip_id": "phone05", "filename": "originals/IMG_2531.MOV", "camera_view": "back, oblique from below",
     "conditions": "portrait; dark clothing on dark wall section", "attempt_start_ms": 2000, "attempt_end_ms": 23800},
]
EXCERPT = {"clip_id": "phone03_a1", "original": "originals/IMG_1314.MOV", "requested_start_s": 58.0, "requested_end_s": 168.0,
           "camera_view": "wide landscape from below, apparently fixed", "conditions":
           "landscape; small climber; bystanders cross foreground; ends with fall",
           "attempt_end_in_source_s": 163.5}


def keyframe_at_or_before(path, second: float) -> float:
    out = subprocess.run([tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "packet=pts_time,flags", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    packets = json.loads(out.stdout)["packets"]
    return max(float(p["pts_time"]) for p in packets if "K" in p["flags"] and float(p["pts_time"]) <= second)


def frame_at(path, second: float) -> np.ndarray:
    data = subprocess.run([tool_path("ffmpeg"), "-nostdin", "-v", "error", "-ss", f"{second:.6f}", "-i", str(path),
                           "-frames:v", "1", "-vf", "scale=96:54", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, check=True).stdout
    return np.frombuffer(data[:96 * 54], np.uint8).astype(float)


def main() -> int:
    source = RAW / EXCERPT["original"]
    output = RAW / "derived" / f"{EXCERPT['clip_id']}.mov"
    output.parent.mkdir(exist_ok=True)
    offset_s = keyframe_at_or_before(source, EXCERPT["requested_start_s"])
    duration = EXCERPT["requested_end_s"] - offset_s
    subprocess.run([tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-ss", f"{offset_s:.6f}", "-t", f"{duration:.6f}",
                    "-i", str(source), "-map", "0:v:0", "-c", "copy", "-map_metadata", "0", str(output)], check=True)
    info = probe(output)
    difference = float(np.mean(np.abs(frame_at(output, 0.0) - frame_at(source, offset_s))))
    if difference > 6:
        print(f"error: excerpt start does not match the original at the recorded offset (MAD {difference:.1f})", file=sys.stderr)
        return 2
    attempt_end_ms = round((EXCERPT["attempt_end_in_source_s"] - offset_s) * 1000)
    record = {
        "clip_id": EXCERPT["clip_id"], "original": EXCERPT["original"], "original_sha256": sha256_file(source),
        "derivative": f"derived/{output.name}", "derivative_sha256": sha256_file(output),
        "method": "ffmpeg stream copy (no re-encode), start snapped to preceding keyframe",
        "source_offset_ms": round(offset_s * 1000), "duration_ms": info.duration_ms,
        "mapping": "original_ms = derivative_or_canonical_ms + source_offset_ms",
        "first_frame_mean_abs_difference_vs_original": round(difference, 2),
        "size_bytes": info.size_bytes,
    }
    (RAW / "phone_derivatives.json").write_text(json.dumps([record], indent=2) + "\n")
    rows = [{**clip, **COMMON} for clip in CLIPS]
    rows.append({"clip_id": EXCERPT["clip_id"], "filename": record["derivative"], "camera_view": EXCERPT["camera_view"],
                 "conditions": EXCERPT["conditions"], "attempt_start_ms": 500, "attempt_end_ms": attempt_end_ms, **COMMON,
                 "camera_motion": "apparently fixed"})
    columns = ["clip_id", "filename", "camera_view", "camera_motion", "conditions", "attempt_start_ms", "attempt_end_ms",
               "allowed_dev_use", "assistant_may_inspect_frames"]
    with (RAW / "manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
