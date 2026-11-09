#!/usr/bin/env python3
"""Import each clip in a manifest into the running local app and analyze it.

Uses the same API as the browser, so results come from the production path. The two
reserved clips are not in data/raw/manifest.csv and are never loaded by this script.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import httpx

from _bootstrap import PROJECT_ROOT


def wait(client: httpx.Client, url: str, is_done, limit_s: float = 600):
    deadline = time.time() + limit_s
    while time.time() < deadline:
        body = client.get(url).json()
        if is_done(body):
            return body
        time.sleep(1)
    raise TimeoutError(url)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "data" / "raw" / "manifest.csv")
    parser.add_argument("--url", default="http://127.0.0.1:8317")
    args = parser.parse_args()
    root = args.manifest.parent
    with args.manifest.open(newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get("clip_id") or "").strip()]
    failures = 0
    with httpx.Client(base_url=args.url, timeout=120) as client:
        for row in rows:
            path = root / row["filename"]
            with path.open("rb") as video:
                created = client.post("/api/attempts", files={"file": (path.name, video, "video/quicktime")},
                                      data={"title": f"{row['clip_id']} (development clip)"})
            created.raise_for_status()
            attempt_id = created.json()["id"]
            attempt = wait(client, f"/api/attempts/{attempt_id}", lambda b: b["status"] != "importing")
            if attempt["status"] != "ready":
                print(f"{row['clip_id']}: import failed: {attempt['error']}", file=sys.stderr)
                failures += 1
                continue
            bounds = {"attempt_start_ms": int(row["attempt_start_ms"]), "attempt_end_ms": int(row["attempt_end_ms"])}
            client.patch(f"/api/attempts/{attempt_id}", json=bounds).raise_for_status()
            run = client.post(f"/api/attempts/{attempt_id}/analyses").json()
            done = wait(client, f"/api/analyses/{run['id']}", lambda b: b["status"] not in {"queued", "running"})
            print(f"{row['clip_id']}: {done['status']} {done['error'] or ''} events={done['summary'] and done['summary']['event_count']}", flush=True)
            failures += done["status"] != "complete"
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
