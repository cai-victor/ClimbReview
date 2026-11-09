# ClimbReview status

Last updated 2026-11-09 (overnight run). Start with `docs/MORNING_REPORT.md` for the short version.

## Bottom line

The local app, analysis pipeline, two detectors, review flow, exports, and evaluation tooling are implemented and tested. **The provisional feasibility gate is not met** on the user's phone clips, mainly because the recordings are handheld. No independent human labels or user study exist, so **event accuracy is unknown**.

## Implemented

- Probing, validation, canonical normalization, HLG tone mapping, repeated-frame detection.
- MediaPipe Tasks pose extraction with per-landmark validity, a whole-pose plausibility rule, and camera-motion exclusion.
- Detector-specific coverage, attempt scale, low-movement and per-wrist detectors (`detectors-v1`), deterministic feedback.
- FastAPI + SQLite + one dedicated worker: import, bounds, persisted jobs, cancel, retry, interruption handling, deletion.
- React/TypeScript/Vite UI: library, setup, progress, review with synchronized canvas overlay, timeline, tracking-gap explanations, separate judgments, tags, notes, reflection, summary, responsive layout.
- JSON, CSV, standalone HTML exports. Evaluation tool, annotation guide, manifest template.

Not implemented: manual holds, attempt comparison, automatic hold types, slip diagnosis, real-time coaching, accounts, hosting. Cancelling an in-progress import has no UI or API; imports can be retried.

## Environment and versions

Apple M4 Pro, arm64, macOS 15.7.4. Python 3.12.16 and FFmpeg 9.0.2 (conda-forge GPL build) in `./.venv`. MediaPipe 1.2.2, OpenCV 5.0.0, NumPy 2.5.4, FastAPI 0.162.2, Starlette 1.10.0, Uvicorn 0.54.0. Node 24.16.0, React 18.3.1, Vite 8.3.6, TypeScript ~5.9.3. Pose model `pose_landmarker_full`, SHA-256 `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`, CPU delegate. Exact sets: `requirements.lock.txt`, `conda.lock.txt`, `frontend/package-lock.json`.

## Commands actually run

```bash
.venv/bin/python scripts/fetch_public_samples.py
```

```bash
.venv/bin/python scripts/prepare_phone_clips.py
```

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility --overwrite
```

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/public_samples/manifest.csv --output-root data/public_feasibility --provenance public_development_sample --overwrite
```

```bash
.venv/bin/python -m pytest
```

```bash
cd frontend && npm run build
```

```bash
.venv/bin/python scripts/load_manifest_into_app.py --url http://127.0.0.1:8318
```

## Verification

| Check | Result |
| --- | --- |
| `pytest` (detectors, media, quality, overlay, API/worker, evaluation, real-model CLI) | 112 passed, 1 deprecation warning from the test client |
| Frontend `tsc --noEmit` and production build | passed |
| Real browser run in the built-in pane: UI upload, real worker import and analysis, playback, canvas overlay, event selection, gap explanation, judgments, tags, autosaved note, reflection, reload persistence, three exports, loop, phone width, delete | passed on a public sample; details below |
| Same production path on five personal development clips | all completed |
| `frontend/tests/smoke.spec.ts` (Playwright) | **not passing here:** headless Chromium hung during setup in this environment before reaching the app. The spec is unverified; the browser checks above were done manually in the pane |
| Clean-copy `scripts/setup_env.sh` | last run before the app was added; not rerun with the frontend build step |

Browser details: note persistence and escaping in the HTML report were confirmed on the final build; reflection and judgment persistence were confirmed by page reload on an earlier build; only the note-saving, loop, and cache code changed afterward. Loop wrap was seen at 12.8 s for an event ending at 11.7 s with 1 s of context. No horizontal overflow at 375 px. The pane was hidden, which pauses animation frames, so continuous live overlay during playback was not observed; overlay placement was checked after seeks and in screenshots.

Defects found and fixed during verification: stale cached `index.html` could leave a blank page after a rebuild; notes saved only on blur; context looping depended on animation frames.

## Remaining work

1. Record tripod footage and rerun feasibility (see `docs/MORNING_REPORT.md`).
2. Human annotation and a fixed split; then tune on dev data and freeze.
3. Run `scripts/evaluate.py`; implement the raw-landmark baseline comparison run (detector flags exist: `smoothing=False`, `hysteresis=False`).
4. Usability study with real beginners.
5. Rerun `scripts/setup_env.sh` from a clean copy, and run the Playwright spec outside this restricted environment.

## Next exact action

Record new clips, add them to `data/raw/manifest.csv`, then run:

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility_tripod
```
