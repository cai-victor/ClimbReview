#!/usr/bin/env python3
"""Start the ClimbReview API and worker on this computer only (127.0.0.1)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from _bootstrap import PROJECT_ROOT

PORT = os.environ.get("CLIMBREVIEW_PORT", "8317")


def main() -> int:
    environment = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "backend")}
    if not (PROJECT_ROOT / "frontend" / "dist" / "index.html").exists():
        print("note: the frontend is not built. Run: cd frontend && npm ci && npm run build", file=sys.stderr)
    processes = [
        subprocess.Popen([sys.executable, "-m", "app.worker"], env=environment, cwd=PROJECT_ROOT),
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT,
                          "--log-level", "warning"], env=environment, cwd=PROJECT_ROOT),
    ]
    print(f"ClimbReview is running at http://127.0.0.1:{PORT}  (Ctrl+C to stop)", flush=True)

    def stop(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    finally:
        stop()
        for process in processes:
            process.wait(timeout=30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
