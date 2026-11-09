#!/usr/bin/env python3
"""Download the licensed public samples, verify them, and convert them to MP4.

Originals stay untouched in data/public_samples/originals/. The conversion only
changes the container and codec (timestamps pass through unchanged, no audio).
"""
from __future__ import annotations

import csv
import hashlib
import json
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import certifi

from _bootstrap import PROJECT_ROOT
from app.analysis.video import tool_path

SAMPLES = json.loads((PROJECT_ROOT / "config" / "public_samples.json").read_text())["samples"]
ROOT = PROJECT_ROOT / "data" / "public_samples"
USER_AGENT = "ClimbReview-student-project/0.1 (local research tool)"
CONVERSION_ARGS = ["-map", "0:v:0", "-an", "-map_metadata", "-1", "-fps_mode", "passthrough",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"]


def download(sample: dict, target: Path) -> None:
    if not target.exists():
        request = urllib.request.Request(sample["download_url"], headers={"User-Agent": USER_AGENT})
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, context=context, timeout=180) as response:
            target.write_bytes(response.read())
    digest = hashlib.sha1(target.read_bytes()).hexdigest()
    if digest != sample["sha1"]:
        target.unlink()
        raise SystemExit(f"SHA-1 mismatch for {sample['clip_id']}: {digest}")


def main() -> int:
    originals, converted = ROOT / "originals", ROOT / "converted"
    originals.mkdir(parents=True, exist_ok=True)
    converted.mkdir(parents=True, exist_ok=True)
    rows, attribution = [], ["# Public sample attributions", ""]
    for sample in SAMPLES:
        suffix = Path(sample["commons_file"]).suffix
        original = originals / f"{sample['clip_id']}{suffix}"
        download(sample, original)
        output = converted / f"{sample['clip_id']}.mp4"
        subprocess.run([tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(original), *CONVERSION_ARGS,
                        str(output)], check=True)
        print(f"{sample['clip_id']}: verified and converted")
        rows.append({"clip_id": sample["clip_id"], "filename": f"converted/{output.name}",
                     "camera_view": sample["camera_view"], "conditions": sample["conditions"],
                     "attempt_start_ms": "", "attempt_end_ms": ""})
        attribution += [f"- **{sample['clip_id']}**: \"{sample['commons_file']}\" by {sample['author']}, "
                        f"{sample['license']} ({sample['license_url']}). Source: {sample['page_url']}. "
                        "Transformed: re-encoded to H.264 MP4, audio removed, timing unchanged."]
    manifest = ROOT / "manifest.csv"
    if not manifest.exists():
        with manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (ROOT / "ATTRIBUTION.md").write_text("\n".join(attribution) + "\n")
    (ROOT / "CONVERSION.json").write_text(json.dumps({"ffmpeg_args": ["-i", "<original>", *CONVERSION_ARGS, "<output>"]}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
