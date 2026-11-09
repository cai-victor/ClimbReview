#!/usr/bin/env python3
"""Download the official pose model and verify it against the tracked manifest."""
from __future__ import annotations

import hashlib
import json
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

import certifi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "config" / "model_manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    target = PROJECT_ROOT / manifest["local_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context(cafile=certifi.where())
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
        try:
            with urllib.request.urlopen(manifest["source_url"], context=context, timeout=120) as response:
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    digest.update(chunk)
                    temporary.write(chunk)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    if digest.hexdigest() != manifest["sha256"]:
        temp_path.unlink(missing_ok=True)
        print(f"error: downloaded SHA-256 {digest.hexdigest()} does not match manifest {manifest['sha256']}.\n"
              "The official 'latest' model may have changed; review it and update the manifest deliberately.",
              file=sys.stderr)
        return 2
    temp_path.replace(target)
    print(f"Verified {target} ({manifest['sha256']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
