# Footwork phase report, November 9, 2026

**ClimbReview now analyzes left and right feet on real tripod footage, and explains each movement with times, direction, distance, and what the other limbs did. Event accuracy is still unmeasured, because no independent human labels or user study exist.** Every visual check below was an AI-assisted spot check of sampled frames, not a human review.

## Start it

```bash
.venv/bin/python scripts/run_app.py
```

Open http://127.0.0.1:8317. It runs on this computer only.

| In the library | Analyses |
| --- | --- |
| IMG_4301 (teammate tripod) | Latest 0.2.1 analysis: 25 events; earlier phase run preserved |
| IMG_7238 | Latest 0.2.1 analysis: 14 events, shown by default. Earlier v2 and original v1 analyses remain selectable under "Analysis shown" |
| Five phone clips | Unchanged v1 analyses. Each shows a notice and a Reanalyze button |

## What was wrong (baseline, before any change)

Baseline is commit b1b9cbf with `detectors-v1`, run on the whole of both clips. Results are in `data/tripod_nov09/baseline_detectors_v1/`.

**1. False camera-motion exclusions, the largest defect.** The old check used whole-frame phase correlation, which followed the moving climber. On these two clips it excluded 136 of 531 intervals (IMG_4301) and 55 of 326 (IMG_7238). With the climber masked out, background motion never exceeded 0.115 px and 0.255 px per interval. The background check did not support any of those 191 camera-motion flags on these two development videos; this is a diagnostic comparison, not an independent accuracy measurement.

**2. The tracked left foot on IMG_7238 could be wrong while reporting high visibility.** With the default model, spot-checked frames showed it on blank wall at 2.4 s and on a hold at 25.1 s.

**3. Hands are often hidden, and that is real.** The left wrist was usable in only 40% (IMG_4301) and 15% (IMG_7238) of samples. Low-movement analysis needs both wrists, so it remains limited.

Not found on these clips: ankle left/right swaps, or a rendering offset. Feet usually sit on the shoes on IMG_4301.

## What changed

**Camera check.** Camera motion is now measured from background features around the climber, as the farthest any image corner moves, so rotation and zoom count. It runs on every clip and trusts no "tripod" label. If it cannot measure, it falls back to the old check.

**Pose model.** A bounded comparison on these two development clips led to the official free heavy model. It looked better on IMG_7238's hard left-foot moments and abstained more on hidden feet, at a similar speed here (about 47 samples/s). It also gives lower availability for some points, so results are not uniformly better. Old runs keep their recorded model.

**Foot episodes.** Left and right are separate detectors, each needing only that side's ankle. The ankle is the tracked point and stands in for the foot; it does not locate the sole or show contact. Heel and toe are reported as support only. Episodes use onset 0.40 and offset 0.20 torso lengths/s, 0.25 s dwell, at least 0.3 s, and at least 0.25 torso lengths of displacement. These are unvalidated starting values, and they stop at any tracking gap, repeated frame, or measured camera motion.

**Geometry rules that were rejected.** Limits on shin or foot length, and on overlapping ankles, flagged nothing useful. Overlapping feet and strongly bent knees are normal climbing positions, so neither is treated as an error.

**Uncertain episodes.** Rapid swings in knee-to-ankle length while ankle visibility is reduced mark an episode "uncertain". The episode stays visible with a caution, and no conclusion is drawn from it: it is left out of sequences and the "largest movement" lists.

**Explanations.** Each event now states its time, duration, image-plane direction, distance in torso lengths, peak speed, and what other limbs did. A limb is "nearly still" only if every sample in its window was tracked in one continuous run and measurably stayed within 0.15 torso lengths. Otherwise it is "shifted slowly", or "unknown" with the reason. Attempt-level panels cover what moved and when, what to rewatch, repeated movement, where tracking prevents a conclusion, and specific questions.

**Interface.** Added left and right foot timeline rows, filters (Everything, Feet only, Hands only, per limb, hide uncertain), a legs-and-feet overlay, the selected movement's tracked path, a per-limb speed chart that seeks when clicked, and a per-event distance chart. Foot data is in the JSON, CSV and HTML exports. Blind labeling and the evaluator now accept foot episodes.

**Evaluation fixes from independent review.** Overlapping unscorable rows now count once. The evaluator refuses to pool several raters on one clip and asks for `--reference-annotator`, so duplicate labels cannot count as misses. Older CSV files and per-rater sets still work.

## Before and after on the two tripod clips

Time analyzable, as a share of the attempt. This measures availability, not accuracy.

| | IMG_4301 before | IMG_4301 after | IMG_7238 before | IMG_7238 after |
| --- | --- | --- | --- | --- |
| Camera-motion exclusions | 26% | 0% | 17% | 0% |
| Left foot | none | 87.1% | none | 86.7% |
| Right foot | none | 89.0% | none | 99.9% |
| Left wrist | 20.7% | 14.3% | 4.6% | 7.4% |
| Right wrist | 57.4% | 79.0% | 40.8% | 59.1% |
| Low movement | 23.7% | 19.4% | 8.0% | 15.6% |

| Episodes after (left / right) | IMG_4301 | IMG_7238 |
| --- | --- | --- |
| Foot | 9 / 7 | 4 / 6 |
| Wrist | 2 / 7 | 0 / 4 |
| Low movement | 0 | 0 |
| Foot episodes marked uncertain | 3 | 4 |

Left-wrist and low-movement coverage on IMG_4301 fell, because the heavy model reported fewer visible wrists there. No low-movement event was found on either clip, and that does not mean no pause occurred. The provisional 70% low-movement coverage target is not met on tripod footage either.

## AI-assisted spot checks of real footage

- **IMG_4301:** the six foot episodes sampled showed the anchor on the shoe and following a real change of foot position.
- **IMG_7238, left foot:** three long episodes (1.0, 7.7, and 23.9 s) are unreliable. The foot was mostly hidden behind the other leg while the anchor drifted to the wall, shin, or a hold. All three are marked uncertain.
- **Uncertainty over-flags.** Of the 7 uncertain episodes, 4 looked like real steps in the sampled frames (IMG_4301 at 14.8, 16.9, and 47.7 s; IMG_7238 at 31.4 s). The rule rests on two clips. Treat "uncertain" as "please check", not as "wrong".
- These samples are not a representative measurement, and other errors may exist.

## Verification actually run

| Check | Result |
| --- | --- |
| Backend tests, including foot semantics, occlusion, jitter, irregular time, side separation, direction, camera pan/rotation/zoom/moving foreground, quiet and drift rules, evaluation regressions, and old-data compatibility | 216 passed |
| Browser specs on the final build, including real IMG_4301 import to review, filters, seek, loop, charts, persistence, exports, phone width, and a run rewritten to the old format in the test data folder | 6 passed |
| Real v1 run of IMG_7238 in the live app | Opened with the notice and its 2 events. JSON, CSV and HTML exports returned. Reanalysis added a new run and left it in place |
| Pipeline on both clips, by CLI and through the live worker | Completed with matching event counts |
| Clean copy of tracked files (no media), full setup including the heavy model download | Setup exit 0, 216 backend tests passed, type-check OK, app started with API 200. Installed packages match the project environment |

Numerical trajectory fixtures and fixture reference labels are synthetic; the browser workflow also uses actual teammate footage. Software tests and AI-assisted spot checks do not establish pose accuracy.

## Limits and what remains

- Both clips are development footage from one teammate group. They are not independent evaluation.
- Feet are tracked in the 2D picture. Nothing here shows contact, weight, slips, flagging, or optimal movement.
- "Left foot" uses the model's label. Direction words such as "left of the picture" are the viewer's.
- The next useful step is independent human labels of foot episodes, using Reference labeling, followed by threshold tuning on development clips and a freeze before any held-out test.
- IMG_2532 and IMG_2748 remain reserved and were not used. The locked forecast test groups were not used, and the forecast was not retrained. It remains tied to the earlier full model.

## Independent review corrections (0.2.1)

The final source and live-browser review found and fixed four additional issues:

- Plot paths now stop at every null speed/coordinate, and blocked intervals are shaded even when both endpoint landmarks exist.
- An event-distance chart uses only the continuous tracking run containing the event origin; it does not measure a displacement across camera/tracking gaps.
- A whole-window quiet claim needs 100% of its samples in the same continuous run, including both boundaries. The former 90% rule could hide a short boundary gap. Context method is now limb-context-v2.
- Filtering away a selected hand/foot event clears its selection, path and loop. A real live-app test reproduced the hidden hand loop before the correction and confirmed the loop unchecked/disabled after Feet only.

Validation after these corrections: production build/type-check passed; full backend suite **218 passed**; **4 targeted Playwright checks passed**, comprising three chart geometry/SSR regressions and the real IMG_4301 import/analysis/review/filter/loop/persistence/export/legacy workflow. The full six-spec browser run and clean-copy check above preceded these last corrections and were not represented as new runs.

Both live tripod attempts were regenerated under pipeline 0.2.1-footwork, with earlier runs preserved. Final live checks confirmed left-foot selection at 5.4 s seeks video to 4.4 s with context, shows its event chart and specific hand/foot explanation, and keeps the original v1 IMG_7238 run selectable with its two wrist cards. Existing event review, hold map, hold, annotation and reflection tables match their pre-review SHA-256 fingerprints. The private database backup and comparison snapshot are under data/backups/.

A phone-width screenshot from the passing real-video test is at frontend/test-results/footwork-left-and-right-fe-60cba-ersistence-exports-old-runs/phone.png (private local artifact).
