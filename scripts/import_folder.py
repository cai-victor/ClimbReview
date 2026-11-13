#!/usr/bin/env python3
"""Add every video in a folder to the running local app and analyze each one. Files stay on this computer.

    .venv/bin/python scripts/run_app.py            # in another terminal
    .venv/bin/python scripts/import_folder.py data/new_vids
"""
from __future__ import annotations

import json
import mimetypes
import sys
import urllib.request
import uuid
from pathlib import Path

PORT = 8317
RESERVED = ("IMG_2532", "IMG_2748")          # held-out personal clips: never imported for development
VIDEO = {".mov", ".mp4"}


def post(path: Path, title: str) -> dict:
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n{title}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"auto_analyze\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}\r\n\r\n").encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/attempts", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def main() -> int:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(__doc__)
        return 2
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/attempts") as response:
        have = {a["original_filename"] for a in json.load(response)}
    for path in sorted(Path(sys.argv[1]).rglob("*")):
        if path.suffix.lower() not in VIDEO:
            continue
        if any(name in path.name for name in RESERVED):
            print(f"skipped (reserved clip): {path.name}")
        elif path.name in have:
            print(f"skipped (already in the app): {path.name}")
        else:
            try:
                attempt = post(path, path.stem)
                print(f"added {path.name} -> http://127.0.0.1:{PORT}/#/attempt/{attempt['id']}")
            except Exception as error:      # one bad file should not stop the rest
                print(f"could not add {path.name}: {error}")
    print("Analysis runs one clip at a time in the app. Then: .venv/bin/python scripts/check_climb_story.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
