#!/usr/bin/env python3
"""Write a blinded rating sheet of coaching cards for an experienced climber. See docs/COACHING_EVALUATION.md.

Cards are shuffled with a recorded seed and shown without rule names, measurements, or the app's decisions.
Rating columns are left empty: this tool never fills in a human judgment.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import urllib.request
from pathlib import Path

COLUMNS = ["rating_id", "clip", "start_s", "end_s", "what_happened", "suggestion", "rater_alias", "moment_is_real_0_2", "suggestion_is_reasonable_0_2", "would_coach_this_yes_no", "notes"]


def fetch(url: str):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8317")
    parser.add_argument("--attempts", nargs="+", required=True, help="Attempt ids to include")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Rating sheet path")
    parser.add_argument("--key", type=Path, required=True, help="Private key linking rating ids to card ids; keep it from the rater")
    args = parser.parse_args()
    rows, key = [], []
    for attempt_id in args.attempts:
        attempt = fetch(f"{args.url}/api/attempts/{attempt_id}")
        run = next(job for job in attempt["analyses"] if job["status"] == "complete")
        coaching = fetch(f"{args.url}/api/analyses/{run['id']}/coaching")
        if not coaching.get("available"):
            print(f"skipping {attempt['title']}: {coaching.get('reason')}")
            continue
        for card in coaching["cards"]:
            rows.append({"clip": attempt["title"], "start_s": round(card["start_ms"] / 1000, 1), "end_s": round(card["end_ms"] / 1000, 1), "what_happened": card["moment"], "suggestion": card["try_this"],
                         "_card": card["id"], "_kind": card["kind"], "_run": run["id"], "_version": coaching["version"]})
    random.Random(args.seed).shuffle(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for number, row in enumerate(rows, start=1):
            writer.writerow({"rating_id": number, **row})
            key.append({"rating_id": number, "card_id": row["_card"], "kind": row["_kind"], "run_id": row["_run"], "coaching_version": row["_version"]})
    args.key.parent.mkdir(parents=True, exist_ok=True)
    args.key.write_text(json.dumps({"seed": args.seed, "items": key}, indent=2) + "\n")
    print(f"Wrote {len(rows)} blank rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
