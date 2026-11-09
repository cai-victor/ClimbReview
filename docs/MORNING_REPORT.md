# Morning report: November 9, 2026 overnight run

**The app works end to end on your real clips, but it cannot yet support the stillness analysis on handheld video, and event accuracy is unmeasured.** No human labels or user study exist. The provisional feasibility gate is not met.

## Phase 2 results (added after the first report)

**Forecast finding, plainly:** on held-out public clips the learned model was only slightly better than predicting no movement (0.3228 vs 0.3282 torso lengths), and it clearly beat constant velocity (0.4747). On your steady-camera clips it tied the do-nothing baseline. It mostly predicts little motion. Full report: `docs/TRAINING_REPORT.md`, with charts in `docs/training_report_forecast-v1.html`. Errors are against later pose estimates, not people.

**Added:**
- **Blind reference labeling:** per attempt, the Reference labeling button. It loads no skeletons, events, or forecasts, and exports to the evaluation format.
- **Manual holds:** the Mark holds button. Marks apply to one reference frame only.
- **Handheld camera experiment:** `scripts/experiment_handheld.py`, results in `data/experiments/handheld/summary.json`. Background transforms were accepted on 86-100% of phone-clip intervals. Coverage rose, but low-movement events stayed at zero and no accuracy is known. It stays off by default.
- **Demo and next steps:** `docs/DEMO_SCRIPT.md`, `docs/NEXT_STEPS.md`.

**Data notes:** 22 licensed public clips were added (249.8 MB). Public climbing video almost always has a moving camera, so only 48 steady-camera held-out windows exist. Wikimedia rate-limited the downloads. An early run retried after 180 s when asked to wait 600 s; the script now honors the full wait. The reserved clips stayed untouched for training, tuning, and testing.

**Verification:** 172 backend tests and 5 browser specs passed. The import Cancel button is now verified in a real browser. A clean copy of tracked files (no media) passed full setup, frontend build, 172 tests, and app start, with packages identical to the lock. Your existing local app data opened correctly with the new features.

The queue is complete. Everything remaining needs tripod footage, independent human labels, a user study, or the course documents (`docs/NEXT_STEPS.md`).

## 1. What works, what is experimental, what is unverified

**Works and was tested:** importing MP4/MOV, HDR conversion, upright normalization, attempt bounds, pose analysis in a separate worker, retry and cancel handling, synchronized skeleton playback, timeline, tracking-gap explanations, event cards, separate correctness and usefulness judgments, notes, reflection, JSON/CSV/HTML export, deletion, phone-width layout.

**Experimental:** every detector threshold, the camera-motion estimate, the implausible-pose rule, and the HDR conversion (a documented approximation).

**Unverified:** detector accuracy, pose accuracy beyond sampled frames, and left/right consistency across whole clips.

## 2. Start the app

```bash
.venv/bin/python scripts/run_app.py
```

Then open http://127.0.0.1:8317. It runs on this computer only. Your five development clips are already loaded, in `data/app/` (751 MB, ignored by Git). The server is currently stopped.

## 3. Tests and sample findings

Follow-up checks, all run after this report was first written:

| Check | Result |
| --- | --- |
| Backend tests | 118 passed |
| Clean copy of tracked files only (no media), full setup with frontend build, tests, app start | passed; packages identical to the lock |
| Real browser smoke spec, headless | passed |
| Same spec in a visible window, twice | passed |
| Continuous playback | about 40 distinct poses drawn in 4 s; drawn pose stayed within 49.6 ms of the video time |
| Event context looping | wrapped back in every run |
| Baseline comparison on 8 stored runs | ran; stored events reproduced exactly |

The original 4-minute Playwright hang did not recur, and its cause is unknown. Commands and details are in `docs/STATUS.md`.

**Baseline comparison:** raw landmarks without hysteresis usually produced more wrist episodes, for example phone04 right wrist 8 versus 4, but not always (phone05 right wrist 0 versus 2). This compares methods with each other. It says nothing about accuracy until human labels exist.

### Your phone clips (development only)

IMG_2532 and IMG_2748 were not viewed, analyzed, or used for tuning. IMG_2532 was only checksummed at the end, and its SHA-256 still matches your inventory. These are full-attempt results with the final rules.

| Clip | View | Pose returned | Low-movement coverage | Left / right wrist coverage | Camera-moved intervals | Low-movement events | Wrist events (L/R) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| phone01 (IMG_1123) | back, handheld | 100% | 21.4% | 58.4% / 16.1% | 37% | 0 | 3 / 1 |
| phone02 (IMG_1129) | side, panning | 100% | 2.8% | 0.7% / 62.6% | 35% | 0 | 0 / 6 |
| phone03_a1 (IMG_1314 excerpt) | wide, apparently fixed | 100% | 19.9% | 20.2% / 41.7% | 4% | 0 | 4 / 3 |
| phone04 (IMG_2154) | back, handheld | 100% | 30.0% | 13.5% / 74.0% | 23% | 0 | 2 / 4 |
| phone05 (IMG_2531) | back, handheld | 94.0% | 20.6% | 16.1% / 48.2% | 35% | 0 | 0 / 2 |

Coverage is not accuracy. Findings from inspecting 12 sampled overlay frames per clip:

- **Orientation:** correct on all five.
- **Alignment:** on the four portrait clips, joints sat on the body through reaches and high steps in the sampled frames. Hidden hands were usually reported unavailable, which is the intended behavior. This is sampled evidence only.
- **Wide clip (phone03_a1):** the climber is small, so wrists were often unavailable, but the camera was steady.
- **Why coverage is low:** handheld camera drift excludes many intervals, and the far wrist is often poorly visible in back views. Low movement needs 2 s of continuous valid video, so none was detected. "0 events" here means little was analyzable, not that you never paused.
- **HDR:** all clips are HLG and now converted. Comparing relabeled and tone-mapped input on three clips showed no consistent tracking difference.
- **IMG_1314 excerpt:** original time = canonical time + 57,940 ms. Excerpt at `data/raw/derived/phone03_a1.mov`, mapping in `data/raw/phone_derivatives.json`.

Artifacts: `data/feasibility/<clip_id>/overlay.mp4`, `contact_sheet.jpg`, `report.md`, plus `data/feasibility/summary.csv`.

### Public samples (stress cases only)

| Clip | Author, license | Low-movement coverage | Note |
| --- | --- | --- | --- |
| Alex Khazanov, IFSC Euros 2020 | Voltmetro, CC0 | 20.5% | Competition camera pans and zooms |
| Chloé Caulier, IFSC Euros 2020 | Voltmetro, CC0 | insufficient tracking | Tight framing; produced a collapsed skeleton, which led to the plausibility rule |
| Indoor Bouldering V3, Rock Spot | Cryptic C62, CC BY-SA 3.0 | 49.9% | 204×360, handheld |

Source links and hashes: `config/public_samples.json`, `data/public_samples/ATTRIBUTION.md`. Results: `data/public_feasibility/`.

## 4. Known defects and current state

- No low-movement events on any handheld clip, by design.
- Left/right labels can be wrong in back views; check overlays.
- A second person is not excluded automatically.
- Colors in converted HDR are approximate and can look bright.
- Git: local commits on `main` in this project only, nothing pushed. Private media is ignored.

## 5. What to record at your next gym session

1. **Use a tripod or a fixed mount.** This is the most important change.
2. Stand far enough back that the whole body, hands, and feet stay in frame through the top of the problem. Aim for the climber to fill about a third or more of the frame height.
3. Film at a slight angle rather than straight from behind, so both arms are visible more often.
4. Turn HDR video off. Don't use slow motion or zoom.
5. Keep bystanders out of frame if possible.
6. Record 3-5 attempts of 30-90 seconds, ideally on two routes and with a second climber.

Add the clips to `data/raw/`, add rows to `data/raw/manifest.csv`, then run:

```bash
.venv/bin/python scripts/run_feasibility.py --output-root data/feasibility_tripod
```

Watch each `overlay.mp4` and complete its `report.md` checklist.

## 6. Questions for you, and the next action

1. Please add the full rubric, submission instructions, due dates, team size, and any AI-use rules to `inputs/`. Does rule-based event modeling satisfy "model or predict"?
2. Who can independently label clips? `docs/ANNOTATION_GUIDE.md` has the protocol.
3. If tripod footage isn't possible, should camera compensation be enabled once labels exist? The experiment looks plausible but is unvalidated (`docs/DECISIONS.md` D47).

No technical verification remains blocked. What's left needs you: tripod footage, independent labels, a user study, and the course documents.

**Next action:** record tripod clips and run the command above. If coverage and alignment hold up, freeze the thresholds after labeling development clips.
