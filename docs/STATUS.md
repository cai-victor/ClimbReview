# ClimbReview status

Last updated 2026-11-13 after adding the climb story. Start with `docs/WALL_GEOMETRY_REPORT.md`, `docs/AUTOMATION_REPORT.md`, `docs/ROUTE_TOOLS_REPORT.md` and `docs/PERFORMANCE_REPORT.md` for the latest work, `docs/FOOTWORK_REPORT.md` for foot tracking, and `docs/MORNING_REPORT.md` for the earlier overnight run.

## Bottom line

The local app, analysis pipeline, two detectors, review flow, exports, evaluation tooling, blind reference labeling, and manual reference-frame hold marking are implemented and tested. An experimental wrist-motion forecast and a camera-compensation study also exist, separately from the default analysis. **The provisional feasibility gate is not met** on the user's phone clips, because of camera motion on earlier handheld recordings and hidden wrists even on the new tripod clips. No independent human labels or user study exist, so **event accuracy is unknown**.

## Climb story: on-wall time, stops, and how it ended (latest, 2026-11-13)

Added `backend/app/analysis/story.py` (`climb-story-v1`), read from the hip midpoint in the picture. It needs no reanalysis: it is computed from stored poses when a review opens.

- **On-wall detection:** a fast hip descent (at least 1.2 torso lengths within 1.5 s) ends the time on the wall. Suggestions and foot placements after it are dropped and counted. The video cannot tell a fall from a jump down, and the text says so.
- **Stops:** stretches of 3 s or more where the hips stay within 0.3 torso lengths, with neighbouring stops in the same area joined. Each lists the tracked hand and foot movements during it. Nothing is read across a tracking gap longer than 1 s.
- **Whole-attempt cards** lead the Opportunities list: the longest stay and its limb pattern, leaving the wall, small foot adjustments as a share of all foot movements, and a slow start. They use the same card layout, decisions, and timeline markers as moment cards. A whole-attempt stay replaces the older pause cards inside it.
- **Your climb panel:** time on the wall, moving, staying put, height gained, and a hip-height chart with stops shaded. Clicking it seeks.

**Results on the five tripod clips** (`scripts/check_climb_story.py`): hips tracked 96 to 100%. IMG_7549, recorded by the climber as a fall, is detected leaving the wall at 00:38.5; IMG_7547 at 00:35.9 after its finish. Stays of 7 to 12 s were found on every clip. I compared these with contact sheets of two clips by eye; that is an AI-assisted visual check, not a human label. No thresholds were tuned against labels, and no climber has rated the new cards.

**New Drive footage is not yet used.** The shared folder lists 16 clips that are not on this computer (IMG_7401, IMG_7732, IMG_7816, and 13 in "new vids 1"). The connector cannot download files of this size. After downloading the folder into `data/new_vids/`:

```bash
.venv/bin/python scripts/import_folder.py data/new_vids
.venv/bin/python scripts/check_climb_story.py
```

**Current verification:** `pytest` 311 passed (9 new in `test_story.py`). Playwright, 12 specs, passed, including the profile numbers, drawn stops, and chart seeking on real IMG_4301.

## Review workspace redesign (2026-11-12)

The interface was reorganized around one question: where to look, what was measured, how sure, what to try. No detector, coaching rule, API, or stored data changed. See D81 to D84.

- **Home:** upload with limits beside the button, three filming tips, a "pick up where you left off" card, and an attempt list with thumbnails, status in plain words, and route, grade and outcome when recorded. The list follows running jobs.
- **Attempt header:** title, which analysis is shown, Mark route holds, and a More menu (plan, reanalyze, downloads, reference labeling, delete). A newest analysis that failed no longer hides an older finished one.
- **Review:** video and timeline on the left, tabs on the right: Opportunities, Next attempt, Route, Compare, Evidence. Coaching cards have markers on the timeline; card and marker are one selection. Cards read what happened, why it might matter, what to try, what to verify. Feet and Hands filters, previous and next, keys O, L, N, P.
- **Fixes found on the way:** a failed save used to replace the whole review with an error; scrubbing out of a loop snapped back; shortcuts did nothing while a checkbox had focus; notes typed before the saved ones loaded could be overwritten.
- **Hold editor:** save state, undo last added hold, mode hint, start and finish counts.

**Current verification:** `npm run build` clean. Playwright, 12 specs, passed, with new checks for card and marker sync, loop exit on scrub, filter fallback, the overlay key, and hold undo. Backend unchanged, so `pytest` was not rerun (303 passed at 8a43c99). Looked at 1280, 768 and 390 px on IMG_7238 and an older hands-only analysis: no horizontal scroll, no console errors; keyboard-only path from the list to playing a card's moment works. On a 390 px phone the first card starts about 1,050 px down, was about 3,850. Not checked: a screen reader, Safari, a real phone, and a landscape clip by eye.

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test
```

## Wall angle from the bolt grid (2026-11-12)

Added and tested: bolt-hole detection, a grid fit that recovers the wall plane, route distances and reach measured on that plane, the wall's angle relative to the camera, a grid overlay in the hold editor, and corrected distances shown on suggestion cards. Details and real results: `docs/WALL_GEOMETRY_REPORT.md`.

**Current verification:** `pytest` 303 passed. Playwright, 12 specs, passed, including the correction on real IMG_7238. Accuracy against measured walls is untested.

```bash
.venv/bin/python scripts/check_wall_geometry.py
```

## Automation and hold-aware feedback (2026-11-12)

Added and tested: automatic analysis after upload, two-click route setup with proposed finish and uses, role fill-in for hand-marked maps, a tracked-route panel, at-a-glance counts, a simple default view, and a planner scale fallback. Details and measured results: `docs/AUTOMATION_REPORT.md`.

**Current verification:** `pytest` 290 passed. Playwright, 12 specs, passed, including the default flow on real IMG_7238. Role proposals were compared with two hand-marked routes only. No experienced climber has rated any suggestion.

```bash
.venv/bin/python scripts/check_role_proposals.py
```

## Route tools (2026-11-11)

Added and tested: color-based hold suggestions confirmed by the user, photo import for marking and planning, a scale line on hold maps, and candidate sequences from entered height and wingspan on a new Plan a route page. Input limits are 5 minutes and 2.5 GB. Details: `docs/ROUTE_TOOLS_REPORT.md`.

The hold editor and planner also show a clear wall picture combined from the video with the tracked climber cut out.

**Current verification:** `pytest` 276 passed. Playwright, 11 specs, passed. Suggestions were compared with one hand-marked route as a development check; no real photo and no real planned route were tried. Suggestion accuracy and plan usefulness are unmeasured.

```bash
.venv/bin/python scripts/check_hold_suggestions.py --map bdafbf1504724a5884a5d377d74c3b53 --tolerance normal --output data/tripod_nov09/hold_suggestion_check_normal.json
```

## Performance phase

Added and tested: timestamped coaching hypotheses with counterexamples and unknowns, foot placement review confirmed only by the user, hold roles and uses, background-measured hold-map alignment, candidate 2D sequences on marked holds, explicit same-problem comparison, decision and trial recording, and coaching in JSON and HTML exports. Coaching is computed from stored analysis files, so 0.2.0 and later runs did not need reprocessing. Details: `docs/PERFORMANCE_REPORT.md`. Human evaluation plan: `docs/COACHING_EVALUATION.md`.

**Current verification:** `pytest` 257 passed. Playwright, 10 specs, passed, including the real IMG_4301 import-to-coaching flow. The live database was backed up to `data/app/backups/climbreview_before_performance_phase.sqlite` before its additive migration; the 11 hold marks and existing notes are unchanged. The clean-copy setup was not rerun for this phase. **Coaching has not been rated by any experienced climber, its accuracy is unmeasured, and no performance improvement is shown.** Four of seven card types did not occur on the two real clips.

Performance commands actually run:

```bash
.venv/bin/python scripts/demo_candidate_beta.py --attempt febff1724e424bcbbf052abe569c2c08 --output data/tripod_nov09/candidate_beta_demo_img7238.json
```

```bash
.venv/bin/python scripts/export_coaching_rating_sheet.py --attempts febff1724e424bcbbf052abe569c2c08 cc5dde8e42d1490c90685fa554432603 --seed 317 --output data/tripod_nov09/coaching_rating_sheet_blank.csv --key data/tripod_nov09/coaching_rating_key.json
```

## Footwork phase

Added and tested: background-only camera measurement, the official heavy pose model, separately gated left and right foot episodes, per-limb series, specific event explanations with limb context, an attempt-level digest, filters, foot overlay and path, speed and distance charts, foot exports, foot reference labels and evaluation, and old-run compatibility. Details and before/after numbers: `docs/FOOTWORK_REPORT.md`.

**Current verification:** `pytest` 218 passed after the independent review corrections. Playwright, 6 specs, passed on the final build, including real IMG_4301 import to review. The real v1 run of IMG_7238 opened in the live app with its results and exports, and reanalysis added a new run beside it. A clean copy of tracked files (no media) passed full setup with the heavy model, 216 tests, type-check, and app start; its packages match the project environment. Event accuracy remains unmeasured. Tripod coverage also does not meet the provisional low-movement target (19.4% and 15.6% against 70%).

**Independent final review, pipeline 0.2.1-footwork:** fixed chart connections across nulls, event-distance origins across tracking runs, whole-window quiet claims with missing boundary samples, and hidden loops after filtering. The final build passed type-check/production build, 218 backend tests, and 4 targeted Playwright checks (3 synthetic chart checks and the real-video footwork workflow). The earlier full 6-spec browser suite and clean-copy 216-test check are retained above as stage results, not rerun claims. Both tripod attempts have fresh 0.2.1 runs. Existing review/hold/annotation/reflection table fingerprints match the pre-review backup. See docs/FOOTWORK_REPORT.md.

Footwork commands actually run:

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/tripod_nov09/manifest.csv --output-root data/tripod_nov09/baseline_detectors_v1
```

```bash
.venv/bin/python scripts/run_feasibility.py --manifest data/tripod_nov09/manifest.csv --output-root data/tripod_nov09/footwork_v2 --overwrite
```

```bash
cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test
```

## Implemented

- Probing, validation, canonical normalization, HLG tone mapping, repeated-frame detection.
- MediaPipe Tasks pose extraction with per-landmark validity, a whole-pose plausibility rule, and camera-motion exclusion.
- Detector-specific coverage, attempt scale, low-movement and per-wrist detectors (`detectors-v1`), deterministic feedback.
- FastAPI + SQLite + one dedicated worker: import, bounds, persisted jobs, cancel, retry, interruption handling, deletion.
- React/TypeScript/Vite UI: library, setup, progress, review with synchronized canvas overlay, timeline, tracking-gap explanations, separate judgments, tags, notes, reflection, summary, responsive layout.
- JSON, CSV, standalone HTML exports. Evaluation tool, annotation guide, manifest template.

Also added after the first report: import cancellation (`POST /api/attempts/{id}/cancel-import`, with a Cancel button during import) and a reproducible baseline comparison (`scripts/compare_baseline.py`).

Not implemented: attempt comparison, automatic hold detection or hold types, wrist-to-hold or foot-to-hold association, near-hold events, slip diagnosis, real-time coaching, accounts, hosting.

## Phase 2 additions (2026-11-09)

Added and tested: blind reference-annotation workflow, manual reference-frame hold editor, time-boxed camera-compensation study (development only, off by default), experimental wrist-motion forecast with grouped train/test evaluation, public clip collection, class demo script, next-steps list. Details: `docs/TRAINING_REPORT.md`, `docs/DEMO_SCRIPT.md`, `docs/NEXT_STEPS.md`.

Forecast result, held-out 5 groups: Ridge MAE 0.3228 L, persistence 0.3282 L, constant velocity 0.4747 L. The learned model is only marginally better than doing nothing, and it tied persistence on the user's clips.

**Historical Phase 2 verification:** `pytest` 172 passed. Playwright, 5 specs, passed: blind labeling, import Cancel, hold alignment on portrait and landscape, full review smoke with continuous playback (at most 49.7 ms from media time). Clean copy from `git archive`, zero media files: `scripts/setup_env.sh` exit 0, `pytest` 172 passed, type-check OK, API 200 and page served, `pip freeze` identical to the lock. The existing `data/app` database opened with all 5 attempts and the new annotation and hold endpoints.

## Environment and versions

Apple M4 Pro, arm64, macOS 15.7.4. Python 3.12.16 and FFmpeg 9.0.2 (conda-forge GPL build) in `./.venv`. MediaPipe 1.2.2, OpenCV 5.0.0, NumPy 2.5.4, FastAPI 0.162.2, Starlette 1.10.0, Uvicorn 0.54.0. Node 24.16.0, React 18.3.1, Vite 8.3.6, TypeScript ~5.9.3. Current pose model `pose_landmarker_heavy` float16, SHA-256 `64437af838a65d18e5ba7a0d39b465540069bc8aae8308de3e318aad31fcbc7b`, CPU delegate. Runs before the footwork phase and forecast-v1 used `pose_landmarker_full`, SHA-256 `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`. Exact sets: `requirements.lock.txt`, `conda.lock.txt`, `frontend/package-lock.json`.

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

## Earlier verification (historical, before Phase 2)

These results are from the first follow-up round. The 118-test counts are historical; the current count is the 172 above. Later features are covered by the current verification.

| Check | Result |
| --- | --- |
| `pytest` (detectors, media, quality, overlay, API/worker, evaluation, baseline, real-model CLI) | 118 passed at that time, 1 deprecation warning from the test client |
| Frontend `tsc --noEmit` and production build | passed |
| Real browser run in the built-in pane: UI upload, real worker import and analysis, playback, canvas overlay, event selection, gap explanation, judgments, tags, autosaved note, reflection, reload persistence, three exports, loop, phone width, delete | passed on a public sample; details below |
| Same production path on five personal development clips | all completed |
| Playwright `frontend/tests/smoke.spec.ts`, bundled Chromium 158, headless | 1 passed (12.5 s) |
| Same spec, `--headed` (visible window, throwaway profile), `--repeat-each=2`, serial | 2 passed |
| Clean copy from `git archive` of commit 3016e45, zero media or model files, `./scripts/setup_env.sh` | exit 0, including `npm ci` and frontend build; `pip freeze` identical to the lock |
| In that clean copy: `pytest`, frontend type-check, `run_app.py` serving API and page | 118 passed at that time; type-check OK; API 200 and page served. Copy deleted afterward |
| `scripts/compare_baseline.py` on all 8 stored runs | all stored events reproduced exactly; results below |

Continuous playback (headed, 4 s of real playback, measured every display frame): 462 and 480 frames rendered, 40-41 distinct poses drawn, 40-41 distinct canvas images, video advanced 4.0 s, largest gap between drawn pose time and media time 49.6 ms (the drawing rule allows 60 ms). Headless runs gave 241 frames and at most 48.2 ms. Context loop wrapped back in every run. Frames captured during playback (`frontend/test-results/playing_strip.png`, public clip) show the skeleton following the climber.

Playwright diagnosis: the first run hung for 4 minutes in "setting up page". A bounded launch probe then started Chromium in 300 ms, and the spec passed on every serial run. **The original hang did not recur and its cause is unknown.** An intermediate `--repeat-each=3` run had 2 failures caused by the test design: copies ran in parallel and saw each other's same-titled clip. The config now forces one worker. Chromium logs `CVDisplayLinkCreateWithCGDisplay failed` warnings headless, without effect on the run.

Browser details: note persistence and escaping in the HTML report were confirmed on the final build; reflection and judgment persistence were confirmed by page reload on an earlier build; only the note-saving, loop, and cache code changed afterward. Loop wrap was seen at 12.8 s for an event ending at 11.7 s with 1 s of context. No horizontal overflow at 375 px. The manual pane session had a hidden pane; continuous playback was verified later by the headed Playwright run above.

Defects found and fixed during verification: stale cached `index.html` could leave a blank page after a rebuild; notes saved only on blur; context looping depended on animation frames.

The import Cancel button was not exercised in a browser in this earlier round. It has since passed in `frontend/tests/annotate.spec.ts`, and API tests cover stopping a running FFmpeg.

## Remaining work

All remaining items depend on people or new footage; the tooling for them exists. See `docs/NEXT_STEPS.md`.

1. Add the full rubric, submission instructions, deadlines, team size, and AI-use rules to `inputs/`.
2. Independent human annotation of hand and foot episodes on the tripod clips and any new footage, with a fixed split; then tune on dev data and freeze.
3. More tripod footage from other climbers, so a held-out group exists.
4. Run `scripts/evaluate.py` on both `events.json` and `events_baseline_raw.json` once labels exist.
5. Usability study with real beginners.

Held-out caveat: the forecast test groups have been evaluated once, so any new forecast method needs a fresh test set. IMG_2532.MOV and IMG_2748.MOV remain reserved: they were not viewed, analyzed, or used for training, tuning, or testing, and IMG_2532.MOV was only checksummed to confirm it is unchanged.

## Next exact action

Open http://127.0.0.1:8317, open IMG_7238, and choose **Mark route holds**. Mark start, finish, and hand or foot use to get candidate sequences. Then have an experienced climber follow `docs/COACHING_EVALUATION.md`.

```bash
.venv/bin/python scripts/run_app.py
```
