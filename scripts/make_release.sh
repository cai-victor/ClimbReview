#!/usr/bin/env bash
# Build dist/ClimbReview-<version>.zip: only what a tester needs to run the app. No course material, footage, tests, or notes.
set -euo pipefail
cd "$(dirname "$0")/.."
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
# Testers need only what the running app imports. Tests, the HTTP test client, and the forecast experiment's
# packages (scikit-learn and SciPy, about 150 MB) are left out of their install.
grep -viE '^(scikit-learn|scipy|joblib|threadpoolctl|pytest|pluggy|iniconfig|Pygments|httpx|httpcore)==' requirements.lock.txt > "$STAGE/requirements.lock.txt"
cp TESTER_README.md "$STAGE/README.md"
chmod +x "$STAGE/install.sh" "$STAGE/start.command"
rm -f "dist/$NAME.zip"
(cd "$(dirname "$STAGE")" && zip -qry "$OLDPWD/dist/$NAME.zip" "$NAME")
rm -rf "$(dirname "$STAGE")"
echo "dist/$NAME.zip  ($(du -h "dist/$NAME.zip" | cut -f1))"
unzip -l "dist/$NAME.zip" | grep -ciE '\.(mov|mp4|sqlite)$|/docs/|/inputs/|/data/|/tests/' | sed "s/^/private or dev files in the zip: /" || true
