#!/usr/bin/env bash
# Reproducible project-local setup. Installs only into ./.venv and ./models.
# Requires an existing conda (tested with conda 25.11.1 at /opt/miniconda3).
set -euo pipefail
cd "$(dirname "$0")/.."
CONDA_BIN="${CONDA_EXE:-/opt/miniconda3/bin/conda}"
export CONDA_PKGS_DIRS="$PWD/.conda-pkgs" CONDA_REGISTER_ENVS=false
"$CONDA_BIN" env create -y -p "$PWD/.venv" -f environment.yml
.venv/bin/python -m pip install --no-deps -r requirements.lock.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/download_model.py
# Official MediaPipe still image of a person: integration-test fixture only.
mkdir -p data/test_assets
curl -sSfL -o data/test_assets/pose.jpg https://storage.googleapis.com/mediapipe-assets/pose.jpg
echo "c8a830ed683c0276d713dd5aeda28f415f10cd6291972084a40d0d8b934ed62b  data/test_assets/pose.jpg" | shasum -a 256 -c
rm -rf .conda-pkgs
# Frontend build (uses Node from PATH; tested with v24.16.0).
(cd frontend && npm ci --no-audit --no-fund && npm run build)
echo "Setup complete. Run: .venv/bin/python scripts/run_app.py"
