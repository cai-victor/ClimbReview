#!/usr/bin/env bash
# Build the ClimbReview Mac app on this Mac. Needs: bash install.sh (or scripts/setup_env.sh) first.
#   bash desktop/build_macos.sh             dist/ClimbReview.app and dist/ClimbReview-macOS.dmg
#   bash desktop/build_macos.sh --install   the same, then put ClimbReview.app in Applications (no disk image)
#   bash desktop/build_macos.sh --dmg-name ClimbReview-1.0-macOS.dmg
# The app is built for this Mac's processor (Apple Silicon or Intel) and is not signed with an Apple Developer ID.
set -euo pipefail
cd "$(dirname "$0")/.."
INSTALL=""; DMG_NAME="ClimbReview-macOS.dmg"
while [ $# -gt 0 ]; do
  case "$1" in
    --install) INSTALL=1 ;;
    --dmg-name) DMG_NAME="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
PY=.venv/bin/python
[ -x "$PY" ] || { echo "Run: bash install.sh  first."; exit 1; }
[ -f models/pose_landmarker_heavy.task ] || "$PY" scripts/download_model.py
"$PY" -m pip install -q --disable-pip-version-check -r desktop/requirements-desktop.txt
# A source checkout builds the web pages; a release folder already has them built and no Node.js is needed.
if [ -f frontend/package.json ] && command -v npm >/dev/null; then
  (cd frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
fi
[ -f frontend/dist/index.html ] || { echo "The web pages are not built. Install Node.js and run this again." >&2; exit 1; }

"$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath dist --workpath build/desktop desktop/ClimbReview.spec
rm -rf dist/ClimbReview     # PyInstaller's intermediate folder; everything is in ClimbReview.app
"$PY" desktop/add_ffmpeg.py dist/ClimbReview.app
codesign --force --deep --sign - dist/ClimbReview.app   # ad-hoc signature, so macOS lets the edited bundle run
dist/ClimbReview.app/Contents/MacOS/ClimbReview --self-test 2>/dev/null
# The bundle must never carry private material.
if find dist/ClimbReview.app \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.sqlite' -o -path '*/Resources/data/*' -o -path '*/Frameworks/data/*' -o -iname '*.jsonl' \) | grep -q .; then
  echo "Refusing to package: footage or a database ended up in the bundle." >&2; exit 1
fi
echo "dist/ClimbReview.app  ($(du -sh dist/ClimbReview.app | cut -f1))"

if [ -n "$INSTALL" ]; then
  if [ -n "${CLIMBREVIEW_APP_DIR:-}" ]; then TARGET="$CLIMBREVIEW_APP_DIR"      # for testing the installer
  elif [ -w /Applications ]; then TARGET=/Applications; else TARGET="$HOME/Applications"; fi
  mkdir -p "$TARGET"
  if pgrep -f "ClimbReview.app/Contents/MacOS/ClimbReview" >/dev/null; then
    echo "ClimbReview is open. Quit it, then run this again to replace it." >&2; exit 1
  fi
  rm -rf "$TARGET/ClimbReview.app"     # the app only; reviews live in ~/Library/Application Support/ClimbReview
  ditto dist/ClimbReview.app "$TARGET/ClimbReview.app"
  echo "Installed: $TARGET/ClimbReview.app"
  exit 0
fi

# A disk image to share: the app, a shortcut to Applications to drag it onto, and first-open instructions.
rm -f "dist/$DMG_NAME"
STAGE="$(mktemp -d)"
ditto dist/ClimbReview.app "$STAGE/ClimbReview.app"
ln -s /Applications "$STAGE/Applications"
cp desktop/dmg/*.txt "$STAGE/"
hdiutil create -quiet -volname ClimbReview -srcfolder "$STAGE" -ov -format UDZO "dist/$DMG_NAME"
rm -rf "$STAGE"
echo "dist/$DMG_NAME  ($(du -h "dist/$DMG_NAME" | cut -f1))"
