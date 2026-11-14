#!/usr/bin/env bash
# Start ClimbReview and open it in your browser. Close this window or press Ctrl+C to stop it.
#   bash start.command
cd "$(dirname "$0")" || exit 1
PORT="${CLIMBREVIEW_PORT:-8317}"
URL="http://127.0.0.1:$PORT"
open_browser() { if [ -z "${CLIMBREVIEW_NO_BROWSER:-}" ]; then (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true; fi; }

if [ ! -x .venv/bin/python ]; then
  echo "ClimbReview is not installed yet. Run:  bash install.sh"
  exit 1
fi
if curl -fs -m 2 "$URL/api/attempts" >/dev/null 2>&1; then
  echo "ClimbReview is already running at $URL"
  open_browser
  exit 0
fi
( for _ in $(seq 1 60); do
    if curl -fs -m 2 "$URL/api/attempts" >/dev/null 2>&1; then open_browser; exit 0; fi
    sleep 1
  done
  echo "ClimbReview did not answer at $URL within a minute. Read the messages above." ) &
echo "Starting ClimbReview at $URL  (your videos stay on this computer; press Ctrl+C to stop)"
exec env CLIMBREVIEW_PORT="$PORT" .venv/bin/python scripts/run_app.py
