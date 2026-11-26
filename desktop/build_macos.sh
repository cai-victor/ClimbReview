#!/usr/bin/env bash
# Build dist/ClimbReview.app and dist/ClimbReview-macOS.dmg on this Mac. Needs: bash install.sh (or setup_env.sh) first.
#   bash desktop/build_macos.sh
# The app is built for this Mac's processor (Apple Silicon or Intel) and is not signed with an Apple Developer ID.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || { echo "Run: bash install.sh  first."; exit 1; }
[ -f models/pose_landmarker_heavy.task ] || "$PY" scripts/download_model.py
"$PY" -m pip install -q -r desktop/requirements-desktop.txt
(cd frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/desktop desktop/ClimbReview.spec
"$PY" desktop/add_ffmpeg.py dist/ClimbReview.app
codesign --force --deep --sign - dist/ClimbReview.app   # ad-hoc signature, so macOS lets the edited bundle run
dist/ClimbReview.app/Contents/MacOS/ClimbReview --self-test
# The bundle must never carry private material.
if find dist/ClimbReview.app \( -iname '*.mov' -o -iname '*.mp4' -o -iname '*.sqlite' -o -path '*/Resources/data/*' -o -path '*/Frameworks/data/*' -o -iname '*.jsonl' \) | grep -q .; then
  echo "Refusing to package: footage or a database ended up in the bundle." >&2; exit 1
fi
rm -f dist/ClimbReview-macOS.dmg
STAGE="$(mktemp -d)"; cp -R dist/ClimbReview.app "$STAGE/"; ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname ClimbReview -srcfolder "$STAGE" -ov -format UDZO dist/ClimbReview-macOS.dmg
rm -rf "$STAGE"
echo "dist/ClimbReview.app  ($(du -sh dist/ClimbReview.app | cut -f1))"
echo "dist/ClimbReview-macOS.dmg  ($(du -h dist/ClimbReview-macOS.dmg | cut -f1))"
