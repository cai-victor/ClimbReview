#!/usr/bin/env bash
# Build what a tester needs. No course material, footage, tests, or notes.
#   dist/ClimbReview-<version>-macOS.dmg   the Mac app: open it and drag ClimbReview to Applications (Apple Silicon)
#   dist/ClimbReview-<version>.zip         the folder for install.sh, for other Macs and Linux
#   bash scripts/make_release.sh [version] [--no-dmg]
set -euo pipefail
cd "$(dirname "$0")/.."
DMG=1
if [ "${1:-}" = "--no-dmg" ]; then DMG=""; shift; fi
if [ "${2:-}" = "--no-dmg" ]; then DMG=""; fi
VERSION="${1:-$(git describe --tags --always --dirty 2>/dev/null || date +%Y%m%d)}"
NAME="ClimbReview-$VERSION"
STAGE="$(mktemp -d)/$NAME"
(cd frontend && npm ci --no-audit --no-fund >/dev/null && npm run build >/dev/null)
mkdir -p "$STAGE/backend" "$STAGE/frontend" "$STAGE/scripts" dist
rsync -a --exclude '__pycache__' --exclude 'forecast' backend/app "$STAGE/backend/"
rsync -a frontend/dist "$STAGE/frontend/"
rsync -a config "$STAGE/"
cp scripts/_bootstrap.py scripts/run_app.py scripts/download_model.py scripts/import_folder.py "$STAGE/scripts/"
cp environment.yml install.sh start.command "$STAGE/"
mkdir -p "$STAGE/desktop/dmg"
cp desktop/launcher.py desktop/ClimbReview.spec desktop/add_ffmpeg.py desktop/build_macos.sh desktop/requirements-desktop.txt "$STAGE/desktop/"
cp desktop/dmg/*.txt "$STAGE/desktop/dmg/"
# Testers need only what the running app imports. Tests, the HTTP test client, and the forecast experiment's
# packages (scikit-learn and SciPy, about 150 MB) are left out of their install.
grep -viE '^(scikit-learn|scipy|joblib|threadpoolctl|pytest|pluggy|iniconfig|Pygments|httpx|httpcore)==' requirements.lock.txt > "$STAGE/requirements.lock.txt"
cp TESTER_README.md "$STAGE/README.md"
chmod +x "$STAGE/install.sh" "$STAGE/start.command" "$STAGE/desktop/build_macos.sh"
rm -f "dist/$NAME.zip"
(cd "$(dirname "$STAGE")" && zip -qry "$OLDPWD/dist/$NAME.zip" "$NAME")
rm -rf "$(dirname "$STAGE")"
echo "dist/$NAME.zip  ($(du -h "dist/$NAME.zip" | cut -f1))"
unzip -l "dist/$NAME.zip" | grep -ciE '\.(mov|mp4|sqlite)$|/docs/|/inputs/|/data/|/tests/' | sed "s/^/private or dev files in the zip: /" || true
if [ -n "$DMG" ] && [ "$(uname -s)" = Darwin ]; then
  bash desktop/build_macos.sh --dmg-name "$NAME-macOS.dmg" >/dev/null
  echo "dist/$NAME-macOS.dmg  ($(du -h "dist/$NAME-macOS.dmg" | cut -f1), for $(uname -m) Macs)"
fi
