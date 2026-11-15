#!/usr/bin/env bash
# ClimbReview installer. Puts everything inside this folder (.venv, models, .tools) and nothing system-wide.
#   bash install.sh
# Tested on macOS with Apple Silicon. Needs about 1.5 GB of disk and an internet connection for the first run.
set -euo pipefail
cd "$(dirname "$0")"
STARTED=$(date +%s)
UV_VERSION=0.13.8
say() { printf '\n==> %s  (%s)\n' "$*" "$(( ($(date +%s) - STARTED) / 60 )) min $(( ($(date +%s) - STARTED) % 60 ))s so far"; }
fail() { printf '\nInstall stopped: %s\n' "$*" >&2; exit 1; }

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLATFORM=osx-arm64 ;; Darwin-x86_64) PLATFORM=osx-64 ;;
  Linux-x86_64) PLATFORM=linux-64 ;; Linux-aarch64) PLATFORM=linux-aarch64 ;;
  *) fail "this installer supports macOS and Linux. On Windows, run it inside WSL." ;;
esac

# 1. A package tool: an existing conda or mamba, else a private copy of micromamba in ./.tools.
TOOL=""
if [ -z "${CLIMBREVIEW_FORCE_MICROMAMBA:-}" ]; then
  for candidate in "${CONDA_EXE:-}" "$(command -v mamba || true)" "$(command -v conda || true)" \
      "$HOME/miniforge3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" /opt/miniconda3/bin/conda /opt/homebrew/Caskroom/miniconda/base/bin/conda; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then TOOL="$candidate"; break; fi
  done
fi
if [ -z "$TOOL" ]; then
  TOOL="$PWD/.tools/bin/micromamba"
  if [ ! -x "$TOOL" ]; then
    if [ -z "${CLIMBREVIEW_YES:-}" ]; then
      printf 'No conda was found. Download micromamba (about 10 MB, from micro.mamba.pm) into this folder to set up Python? [Y/n] '
      read -r answer
      case "$answer" in n*|N*) fail "install conda or Miniforge yourself (https://conda-forge.org/download/), then run this again." ;; esac
    fi
    say "Downloading micromamba for $PLATFORM"
    mkdir -p .tools
    curl -fsSL "https://micro.mamba.pm/api/micromamba/$PLATFORM/latest" | tar -xj -C .tools bin/micromamba || fail "could not download micromamba. Check your connection and run this again."
  fi
  export MAMBA_ROOT_PREFIX="$PWD/.tools/root"
fi
export CONDA_PKGS_DIRS="$PWD/.tools/pkgs" CONDA_REGISTER_ENVS=false

# 2. Python 3.12 and FFmpeg, in ./.venv.
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 12))' 2>/dev/null; then
  say "Python environment already present"
else
  say "Creating the Python environment (Python and FFmpeg, a few minutes)"
  rm -rf .venv
  case "$TOOL" in
    *micromamba) "$TOOL" create -y -p "$PWD/.venv" -f environment.yml ;;
    *) "$TOOL" env create -y -p "$PWD/.venv" -f environment.yml ;;
  esac
fi

# 3. Python packages at the exact versions the app was tested with.
say "Installing Python packages"
# uv downloads packages in parallel, which is several times faster than pip. pip remains the fallback.
if .venv/bin/python -m pip install --quiet --disable-pip-version-check "uv==$UV_VERSION" 2>/dev/null \
    && .venv/bin/python -m uv pip install --quiet --python .venv/bin/python --no-deps -r requirements.lock.txt; then
  :
else
  echo "The fast installer was not available, so this step uses pip and takes a few minutes longer."
  .venv/bin/python -m pip install --quiet --disable-pip-version-check --no-deps -r requirements.lock.txt
fi
.venv/bin/python -m pip check >/dev/null || fail "the installed packages do not fit together on this computer. Send the lines above to whoever gave you the app."

# 4. The pose model, checked against a known SHA-256.
if [ -f models/pose_landmarker_heavy.task ]; then
  say "Pose model already present"
else
  say "Downloading the pose model (31 MB)"
  .venv/bin/python scripts/download_model.py
fi

# 5. The web pages. A release zip ships them built; a source checkout builds them with Node.
if [ ! -f frontend/dist/index.html ]; then
  command -v npm >/dev/null || fail "the web pages are not built and Node.js is not installed. Use the release zip, or install Node.js and run this again."
  say "Building the web pages"
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

# 6. Check the parts that matter before saying it worked.
say "Checking the install"
.venv/bin/python -c 'import cv2, fastapi, mediapipe, numpy, yaml' || fail "a Python package failed to load."
.venv/bin/ffmpeg -hide_banner -version >/dev/null || fail "FFmpeg did not start."
rm -rf .tools/pkgs
printf '\nClimbReview is installed. Start it with:\n\n    bash start.command\n\n'
