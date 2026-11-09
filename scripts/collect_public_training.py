#!/usr/bin/env python3
"""Download the public training clips after re-verifying license and hash at the source.

Stops if a file's license or checksum differs from config/public_training_sources.json,
or if the planned total exceeds the 500 MB phase cap. Originals are kept unchanged;
conversion changes only container/codec, with timestamps passed through.
"""
from __future__ import annotations

import csv
import hashlib
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi

from _bootstrap import PROJECT_ROOT
from app.analysis.video import tool_path

SOURCES = json.loads((PROJECT_ROOT / "config" / "public_training_sources.json").read_text())["sources"]
ROOT = PROJECT_ROOT / "data" / "public_training"
CAP_BYTES = 500_000_000
PAUSE_BETWEEN_DOWNLOADS_S = 8
MAX_ATTEMPTS = 5
UA = {"User-Agent": "ClimbReview-student-project/0.2 (local research tool)"}
CONTEXT = ssl.create_default_context(cafile=certifi.where())
CONVERSION_ARGS = ["-map", "0:v:0", "-an", "-map_metadata", "-1", "-fps_mode", "passthrough",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"]


def polite_download(url: str) -> bytes:
    """Back off on rate limiting, honoring Retry-After, with a bounded number of attempts."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), context=CONTEXT, timeout=300).read()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == MAX_ATTEMPTS - 1:
                raise
            wait = int(error.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
            print(f"rate limited; waiting {wait} s", flush=True)
            time.sleep(min(wait, 180))
    raise AssertionError("unreachable")


def verify_at_source(source: dict) -> None:
    query = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "sha1|extmetadata",
                                    "titles": source["commons_title"]})
    request = urllib.request.Request(f"https://commons.wikimedia.org/w/api.php?{query}", headers=UA)
    page = next(iter(json.load(urllib.request.urlopen(request, context=CONTEXT, timeout=60))["query"]["pages"].values()))
    info = page["imageinfo"][0]
    license_name = info["extmetadata"]["LicenseShortName"]["value"]
    if license_name != source["license"] or info["sha1"] != source["sha1"]:
        raise SystemExit(f"{source['clip_id']}: source changed (license {license_name}, sha1 {info['sha1']}). Stopping.")


def main() -> int:
    total = sum(s["size_bytes"] for s in SOURCES)
    if total > CAP_BYTES:
        raise SystemExit(f"Planned download {total / 1e6:.0f} MB exceeds the {CAP_BYTES / 1e6:.0f} MB cap.")
    originals, converted = ROOT / "originals", ROOT / "converted"
    originals.mkdir(parents=True, exist_ok=True)
    converted.mkdir(parents=True, exist_ok=True)
    rows, attribution = [], ["# Public training clip attributions", ""]
    for source in SOURCES:
        verify_at_source(source)
        suffix = "." + source["download_url"].rsplit(".", 1)[1]
        original = originals / f"{source['clip_id']}{suffix}"
        if not original.exists():
            original.write_bytes(polite_download(source["download_url"]))
            time.sleep(PAUSE_BETWEEN_DOWNLOADS_S)
        digest = hashlib.sha1(original.read_bytes()).hexdigest()
        if digest != source["sha1"]:
            original.unlink()
            raise SystemExit(f"{source['clip_id']}: SHA-1 mismatch {digest}")
        output = converted / f"{source['clip_id']}.mp4"
        subprocess.run([tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(original), *CONVERSION_ARGS, str(output)], check=True)
        print(f"{source['clip_id']}: verified and converted", flush=True)
        rows.append({"clip_id": source["clip_id"], "filename": f"converted/{output.name}", "camera_view": "see catalog",
                     "conditions": source["event_id"], "attempt_start_ms": "", "attempt_end_ms": ""})
        attribution.append(f"- **{source['clip_id']}**: \"{source['commons_title'][5:]}\" by {source['author']}, {source['license']}. "
                           f"{source['page_url']}. Transformed: re-encoded to H.264 MP4, audio removed, timing unchanged.")
    with (ROOT / "manifest.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (ROOT / "ATTRIBUTION.md").write_text("\n".join(attribution) + "\n")
    print(f"Originals total: {sum(p.stat().st_size for p in originals.iterdir()) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
