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

Also added after the first report: import cancellation (`POST /api/attempts/{id}/cancel-import`, with a Cancel button during import) and a reproducible baseline comparison (`scripts/compare_baseline.py`).

Not implemented: manual holds, attempt comparison, automatic hold types, slip diagnosis, real-time coaching, accounts, hosting.

## Phase 2 additions (2026-11-09)

Added and tested: blind reference-annotation workflow, manual reference-frame hold editor, time-boxed camera-compensation study (development only, off by default), experimental wrist-motion forecast with grouped train/test evaluation, public clip collection, class demo script, next-steps list. Details: `docs/TRAINING_REPORT.md`, `docs/DEMO_SCRIPT.md`, `docs/NEXT_STEPS.md`.

Forecast result, held-out 5 groups: Ridge MAE 0.3228 L, persistence 0.3282 L, constant velocity 0.4747 L. The learned model is only marginally better than doing nothing, and it tied persistence on the user's clips.

Latest verification: `pytest` 172 passed. Playwright, 5 specs, passed: blind labeling, import Cancel, hold alignment on portrait and landscape, full review smoke with continuous playback (at most 49.7 ms from media time). Clean copy from `git archive`, zero media files: `scripts/setup_env.sh` exit 0, `pytest` 172 passed, type-check OK, API 200 and page served, `pip freeze` identical to the lock. The existing `data/app` database opened with all 5 attempts and the new annotation and hold endpoints.

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

```bash
.venv/bin/python scripts/compare_baseline.py
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright install chromium
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test --headed --repeat-each=2 --timeout=120000 --global-timeout=170000
```

## Baseline comparison (variants only, not accuracy)

Output: `data/baseline_comparison/baseline-comparison-v1.json`; each run also gets `events_baseline_raw.json`. Baseline means raw landmarks and no onset/offset hysteresis. Wrist event counts, final vs baseline:

| Clip | Left | Right |
| --- | --- | --- |
| phone01 | 3 vs 5 | 1 vs 1 |
| phone02 | 0 vs 0 | 6 vs 7 |
| phone03_a1 | 4 vs 4 | 3 vs 7 |
| phone04 | 2 vs 2 | 4 vs 8 |
| phone05 | 0 vs 0 | 2 vs 0 |
| public_khazanov_v3 | 1 vs 2 | 1 vs 1 |
| public_caulier | 0 vs 0 | 0 vs 0 |
| public_rockspot_v3 | 1 vs 1 | 7 vs 6 |

Low movement: 0 vs 0 where available; unavailable on public_caulier. The baseline usually splits movement into more episodes, but not always. Which variant is better cannot be known without human labels.

## Verification

| Check | Result |
| --- | --- |
| `pytest` (detectors, media, quality, overlay, API/worker, evaluation, baseline, real-model CLI) | 118 passed, 1 deprecation warning from the test client |
| Frontend `tsc --noEmit` and production build | passed |
| Real browser run in the built-in pane: UI upload, real worker import and analysis, playback, canvas overlay, event selection, gap explanation, judgments, tags, autosaved note, reflection, reload persistence, three exports, loop, phone width, delete | passed on a public sample; details below |
| Same production path on five personal development clips | all completed |
| Playwright `frontend/tests/smoke.spec.ts`, bundled Chromium 158, headless | 1 passed (12.5 s) |
| Same spec, `--headed` (visible window, throwaway profile), `--repeat-each=2`, serial | 2 passed |
| Clean copy from `git archive` of commit 8336a2a, zero media or model files, `./scripts/setup_env.sh` | exit 0, including `npm ci` and frontend build; `pip freeze` identical to the lock |
| In that clean copy: `pytest`, frontend type-check, `run_app.py` serving API and page | 118 passed; type-check OK; API 200 and page served. Copy deleted afterward |
| `scripts/compare_baseline.py` on all 8 stored runs | all stored events reproduced exactly; results below |

Continuous playback (headed, 4 s of real playback, measured every display frame): 462 and 480 frames rendered, 40-41 distinct poses drawn, 40-41 distinct canvas images, video advanced 4.0 s, largest gap between drawn pose time and media time 49.6 ms (the drawing rule allows 60 ms). Headless runs gave 241 frames and at most 48.2 ms. Context loop wrapped back in every run. Frames captured during playback (`frontend/test-results/playing_strip.png`, public clip) show the skeleton following the climber.

Playwright diagnosis: the first run hung for 4 minutes in "setting up page". A bounded launch probe then started Chromium in 300 ms, and the spec passed on every serial run. **The original hang did not recur and its cause is unknown.** An intermediate `--repeat-each=3` run had 2 failures caused by the test design: copies ran in parallel and saw each other's same-titled clip. The config now forces one worker. Chromium logs `CVDisplayLinkCreateWithCGDisplay failed` warnings headless, without effect on the run.

Browser details: note persistence and escaping in the HTML report were confirmed on the final build; reflection and judgment persistence were confirmed by page reload on an earlier build; only the note-saving, loop, and cache code changed afterward. Loop wrap was seen at 12.8 s for an event ending at 11.7 s with 1 s of context. No horizontal overflow at 375 px. The manual pane session had a hidden pane; continuous playback was verified later by the headed Playwright run above.

Defects found and fixed during verification: stale cached `index.html` could leave a blank page after a rebuild; notes saved only on blur; context looping depended on animation frames.

Not exercised in a browser: the import Cancel button (the endpoint and worker behavior are covered by API tests, including stopping a running FFmpeg).

## Remaining work

1. Record tripod footage and rerun feasibility (see `docs/MORNING_REPORT.md`).
2. Human annotation and a fixed split; then tune on dev data and freeze.
3. Run `scripts/evaluate.py` on both `events.json` and `events_baseline_raw.json` once labels exist.
4. Usability study with real beginners.

## Next exact action

Record new clips, add them to `data/raw/manifest.csv`, then run:

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility_tripod
```
