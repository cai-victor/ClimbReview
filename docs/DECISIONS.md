# Decision log

Format: decision, then reason. All numeric settings are provisional engineering choices. The required-landmark sets below come directly from `docs/PROJECT_SPEC.md` §6. Detector and eligibility semantics are recorded in D26-D31.

## Environment

**D1. Project-local conda-forge prefix at `.venv/` with Python 3.12.16 and FFmpeg 9.0.2.** FFmpeg was not installed, and the instructions keep work inside the project, so a system-wide Homebrew install was avoided. The system default was Python 3.13 and Homebrew's was 3.14. MediaPipe's setup page lists 3.9-3.14, and 3.12 is a mature choice within that range. The spec's 3.11 is a recommendation that allows "another tested compatible interpreter".

**D2. GPL FFmpeg build.** It includes `libx264`, the encoder selected for canonical video. The tool runs locally and is not redistributed with the project.

**D3. MediaPipe 1.2.2.** This was the current release and has an official macOS arm64 wheel. It was six days old when chosen, so compatibility was tested here, not assumed. `requirements.lock.txt` pins it. The Tasks API (`mp.tasks.vision.PoseLandmarker`) is used, not the legacy `mp.solutions` API.

**D4. `pose_landmarker_full` float16, verified by SHA-256 on every run.** The spec says to test the full model first. The official URL path says `latest`, so the checksum in `config/model_manifest.json` is what makes runs reproducible. A changed upstream file fails loudly instead of silently changing results.

## Video and time

**D5. FFmpeg's autorotate applies rotation once, and the result is verified.** Autorotate handles the display matrix before our filters. The pipeline then requires zero rotation metadata and the expected dimensions; tests check pixel content. Non-right-angle rotations are rejected.

**D6. Filter order: `setpts=PTS-STARTPTS`, `fps=30:round=near`, scale, `setsar=1`, `yuv420p`.** Resetting start time makes the clip begin at zero. The `fps` filter uses presentation time, so variable-rate sources keep real timing instead of being retimed by frame count.

**D7. H.264, CRF 18, no B-frames, GOP 15, timescale 30000, audio and metadata removed.** No B-frames keeps presentation order equal to decode order. The timescale makes each 30 fps frame exactly 1000 ticks. Short keyframe spacing supports later browser seeking. Removing metadata drops device and location tags from derived files.

**D8. Canonical dimensions are even, uniformly downscaled, never upscaled.** Longest side at most 1280. H.264 with 4:2:0 chroma needs even sizes, so per-axis scale and the very small aspect error are recorded.

**D9. Timestamps come from canonical packet presentation times, not from inference time or an assumed frame rate.** Frame count and strict monotonicity are enforced before MediaPipe receives a frame.

**D10. Inference runs on the global grid 0, 3, 6... restricted to the half-open interval `[start, end)`.** Keeping one global grid makes sample times independent of bounds. Inference is limited to the attempt so walk-up frames cannot seed the tracker on the wrong person. Changing bounds requires a new run, as the spec already says.

**D11. Frames are decoded through an FFmpeg raw RGB pipe, not OpenCV capture.** One decoder and one timing authority are used throughout. OpenCV is used only for drawing.

**D12. Limits use decimal megabytes.** 250 MB means 250,000,000 bytes, resolving the question in `docs/DATA_CONTRACTS.md`.

**D13 (superseded by D28, D29). HDR and sparse frames warn instead of failing.** The build cannot tone-map HDR (`zscale` is absent). Geometry and time remain valid, so the run proceeds with a recorded warning. Frame gaps longer than the sample period are likewise flagged because repeated frames could later resemble stillness.

## Data and coverage

**D14. Raw landmarks and validity are separated.** `poses.jsonl` stores what the model returned, including out-of-frame and low-visibility values. Validity is derived, so thresholds can change without re-running inference. No pose is `landmarks: null`; non-finite values are `null`; JSON is written with NaN disallowed.

**D15. Validity reasons in fixed priority: `no_pose`, `non_finite`, `out_of_frame`, `visibility_missing`, `low_visibility`, `low_presence`.** Thresholds are 0.6, from `docs/DATA_CONTRACTS.md`. Visibility is required, while presence is checked only when available, as that contract specifies. Off-image coordinates are treated as unavailable because the model is extrapolating there.

**D16. Required landmarks per detector.** Low movement: both wrists, ankles, and hips. Wrist motion: that side's shoulder, elbow, and wrist. All also need a valid attempt scale.

**D17. Eligible time is credited to intervals between consecutive samples, only when both endpoints are valid and at most 150 ms apart.** This matches how speed will be computed later, since a speed needs two valid observations. An isolated valid sample earns nothing and nothing crosses a gap. The trade-off is that the final sub-sample remainder is never credited, so perfect tracking of a 10 s attempt reports 99%.

**D18. An unavailable detector reports `insufficient_tracking` with `eligible_ms: null` and `fraction: null`.** A zero would look like a measured quantity. `landmarks_contiguously_valid_ms` remains available for diagnosis.

**D19. Attempt scale is the median shoulder-midpoint to hip-midpoint distance in pixels.** It needs at least 10 reliable samples, and lengths under 2% of the image diagonal are excluded. Pixels are used because normalized axes differ in scale. The median resists single-frame errors. It is not a physical calibration.

**D20. World landmarks are not stored.** The MVP is explicitly 2D image-space, and leaving them out avoids tempting 3D claims.

**D21. Overlay video is 10 fps and uses the exact frames that were analyzed.** At 30 fps, poses would have to be held or interpolated. Timestamps are burned in using canonical milliseconds. Joints and bones are hidden when unavailable.

**D22. Automatic identity-swap and jump detection was deferred (partly addressed by D26).** Without real data, any threshold would be invented. Human review of overlays handles this for Milestone 0.

**D23. The official MediaPipe photo is an integration-test fixture labeled `synthetic_test_media`.** It lets tests exercise the path where landmarks are actually returned. It is not climbing footage and cannot satisfy real-video acceptance criteria.

**D24. Output directories appear only after complete success.** Work happens in a temporary sibling directory, and `--overwrite` replaces only an earlier run directory.

## Overnight run (2026-11-09): real footage, detectors, and application

**D25. Public clips use a `public_development_sample` provenance.** They are development stress cases only: not the user's footage, not a test set, and not human evaluation. Sources, hashes, and licenses are in `config/public_samples.json`.

**D26. Whole-pose implausibility rule, from observed failures.** On a public clip showing only legs, MediaPipe returned a collapsed skeleton with both wrists marked visible (torso 0.42 of the attempt scale). Visibility cannot catch this, so a pose whose torso is under 0.5 L or over 2.0 L is unavailable. This tightens eligibility. It catches only gross collapses; a hallucinated pose at 0.69 L still passed.

**D27. Camera motion breaks eligibility (changes coverage semantics).** Eligibility now also requires that the estimated background shift between samples stays at or below 0.15 L/s, the same scale as the stillness threshold, when phase-correlation response is at least 0.3. A camera following a climber can make real movement look still, and vice versa. Consequence: handheld clips lose much coverage. The fixed-camera excerpt lost about 4% of intervals, whereas handheld clips lost 23-37%. Rotation and zoom are not modeled, and this estimator has no independent accuracy measurement.

**D28. Repeated source frames break eligibility.** A sample that shows the same source frame as the previous sample carries no new observation, so that interval is excluded instead of looking still. This replaces the earlier warning-only behavior for detectors. No current clip triggered it.

**D29. HLG HDR is converted, not relabeled.** The FFmpeg build lacks `zscale`, and `libplacebo` needs a GPU path. A generated 3D LUT applies BT.2100 HLG, a 1000-nit OOTF, scaling reference white near SDR white, a highlight knee, BT.2020 to BT.709 primaries, and BT.1886 encoding. Tests check known operating points through the real FFmpeg path. It is a documented approximation; PQ HDR still only warns. A three-clip comparison of relabeled versus tone-mapped input showed no consistent tracking difference, so correct color was kept.

**D30. IMG_1314 excerpt uses stream copy.** The attempt window is snapped back to the preceding keyframe, avoiding re-encoding HDR. `original_ms = canonical_ms + 57,940`. The excerpt's first frame was compared with the original at that offset (mean absolute difference 0.0). Limits were not raised.

**D31. Detector discrete-time rules (`detectors-v1`).** Smoothing is a centered 0.3 s time-window mean inside a segment. Speed is finite difference across samples within +/-150 ms, using actual elapsed time, which is 200 ms at 10 Hz; a span under 100 ms gives no speed. Low movement: all six joints valid, maximum joint speed strictly below 0.15 L/s, at least 2.0 s; runs merge only across interruptions of at most 200 ms inside the same fully observed segment. Wrist episodes: start above 0.35 L/s, end at the first sample of a below-0.20 L/s run lasting 0.25 s, at least 0.3 s and 0.2 L displacement from start. Episodes cut by the segment or attempt end stay but are marked truncated with a cause. All thresholds remain unvalidated.

**D32. Single job table plus a file-locked worker.** Imports and analyses share lifecycle, claiming, and restart handling. A file lock gives one worker; an atomic `UPDATE ... RETURNING` claims each job. Running rows found at worker start become `interrupted`.

**D33. Import normalizes before bounds are set.** The user previews the exact canonical video the analysis will use. Changing bounds requires a new analysis run; old reviews stay with their run.

**D34. Tracking-quality label.** Median of the lowest required-joint visibility across the event: at least 0.85 good, at least 0.70 fair, otherwise weak. Descriptive only and marked not calibrated.

**D35. Unscorable overlap rule for evaluation.** A prediction is excluded when at least half of it falls in a human-unscorable interval for that detector. Matching is greedy by descending tIoU at 0.30. Both are fixed before any labels exist.

**D36. Not implemented tonight: camera-motion compensation.** Subtracting estimated background motion might make handheld clips usable, but it adds an unvalidated step that could create false stillness. A tripod is the safer next step.

**D37. Baseline comparison reuses the stored run's poses and configuration.** Only smoothing and hysteresis change, and the final variant must reproduce the stored events, otherwise the runner exits non-zero. It reports differences between variants and writes no accuracy fields. Scoring the baseline against labels uses `scripts/evaluate.py --events-file events_baseline_raw.json`.

**D38. Import cancellation shares the job mechanism.** A queued import is cancelled immediately. A running one sets `cancel_requested`, and the normalization poll kills FFmpeg. The uploaded source is kept so the import can be retried.

## Phase 2 (2026-11-09): public clips, forecast, labeling, holds, camera experiment

**D39. Grouping is by climber when known, otherwise by recording.** Same-climber clips stay together across events (for example two clips of Anna Stöhr). Clips with unknown climbers are separate groups, which means an unknown climber could in principle appear in two groups.

**D40. The forecast is causal by construction.** `features_from_history` receives only samples up to prediction time. Scale is the history median torso length; no smoothing is used. Future samples decide only target value and availability. Camera steadiness over the horizon classifies an example for reporting and is never an input.

**D41. Histories must be fully valid and contiguous (11 samples).** Validity enters as visibility summaries. Filling missing inputs would conflict with the project's rule against substituted coordinates, at the cost of coverage.

**D42. The model trains on all reliable windows, and results are reported by camera condition.** The steady-camera filter left 187 training windows and none in the held-out groups, because public climbing video almost always moves. The target is wrist position minus hip position, so pure camera translation cancels, while zoom and rotation do not. This deviates from a steady-camera-only predictor and was fixed before any test evaluation. Results for all-window, steady, and moving strata are separate.

**D43. Baseline constant-velocity window is chosen on training groups** from 100, 200, 300, and 500 ms, matching the treatment of the Ridge alpha. Test groups are not used. A ledger records each held-out evaluation and refuses a changed model without an explicit flag, which is then written into the results.

**D44. Earlier public development clips train only**, since they were inspected during earlier work. The user's five development clips are a separate stress evaluation, not training data. The two reserved clips are refused by name.

**D45. Reference annotation is a separate blind page.** It loads only the video and the rater's own set. The set list shows counts but no intervals. Synthetic fixtures are flagged and excluded from the attempt-level export.

**D46. Holds live on a reference frame.** Marks are stored with frame index and the canonical video's SHA-256, and drawn only on that frame. An SVG in canonical pixel coordinates handles letterboxing. No tracking, detection, or wrist linkage exists.

**D47. Camera compensation stays experimental and off by default.** The time-boxed development study (`scripts/experiment_handheld.py`) accepted 86-100% of intervals on the phone clips with about 0.2 px median background residual, and blended frames showed less ghosting. Coverage rose, and wrist-event counts rose, but no event's validity is known. Low-movement events remained zero. Using it for detection needs human labels first.

**D48. Ridge alpha grid extended once on training cross-validation.** The first grid's best value sat at its edge. The test groups had not been read. After extension the optimum was interior at 100,000.

**D49. Test split was re-frozen once, before any test evaluation,** to add four sources from one bounded search. The earlier group assignments did not change.

## Footwork phase (2026-11-09)

**D50. Camera motion is measured from the background around the climber.** Whole-frame phase correlation flagged 191 intervals on two tripod clips where the masked background moved at most 0.255 px; it was following the climber. The new measure is the farthest image-corner motion of a background similarity transform, so rotation and zoom count, and it runs on every clip regardless of how the camera was described. It abstains when features are too few or no pose can mask the climber, and then the earlier estimate is used.

**D51. The default pose model is now the official heavy model.** A bounded comparison on the two development tripod clips showed fewer misplaced left-foot landmarks on IMG_7238 by AI-assisted spot check, and more abstention on hidden feet. This is not an accuracy result. Stored runs keep their own model record. The forecast stays tied to the full model and was not retrained.

**D52. Foot uncertainty is a caution, not a gate.** Shin-length and foot-length limits and an ankle-overlap rule flagged nothing useful, and overlapping feet or strongly bent knees are normal climbing. Knee-to-ankle length swinging by more than 0.07 torso lengths over about 0.9 s with ankle visibility below 0.9 flagged the unreliable IMG_7238 left-foot spans, but also some real fast steps. Such episodes stay visible, are labeled, and are excluded from context claims and digest highlights.

**D53. Foot episodes use each side's ankle only.** Each side works when the other is hidden. Heel and toe are support and never create an event. Thresholds are starting values (onset 0.40, offset 0.20 L/s, 0.25 s dwell, 0.3 s, 0.25 L), set larger than wrist minimum displacement to reduce heel-drop pivots, and were checked only against two development clips. Detector version is `detectors-v2-footwork`. The event field `hand` holds the body side for foot events, so stored data and label files stay compatible.

**D54. Quiet requires measurement, not the absence of an event.** A limb is "nearly still" only with every sample, including both window boundaries, in one continuous tracked run and at most 0.15 L of measured excursion. Motion without an episode is "shifted slowly". A tracking break is "unknown", even when samples on both sides are valid. Support wording names only the points compared, and neighbors cut off by tracking are described as last or first observed.

**D55. The evaluator keeps one reference per clip.** Overlapping unscorable rows are merged before the 50% test. When a clip has several raters, scoring stops until `--reference-annotator` chooses one rater or an adjudicated set. Original per-rater rows are unchanged.

**D56. Older runs are preserved.** Reanalysis creates a new run. The attempt page lets either be chosen, each keeps its own notes, and runs without foot data show a notice. A run predating a detector cannot produce misses for it in evaluation.


**D57. Final review fixes are versioned as 0.2.1-footwork / limb-context-v2.** Null plot samples and blocked run transitions break and shade charts; event-distance origins cannot cross tracking runs. Missing boundary samples keep whole-window foot context unknown. Filtering hides selected events by clearing their trail and loop. Fresh runs preserve earlier results and notes. These are correctness fixes, not new validation of climbing technique.

## Performance phase (2026-11-09)

**D58. Coaching is computed on request from stored files.** Cards use `events.json`, `movement.json` and `overlay.json`, so 0.2.0 and later runs gain coaching without reprocessing, and rule version `coaching-v1` can change without touching analyses. A run with no foot data is told to reanalyze.

**D59. A card is a conditional hypothesis with explicit counterexamples.** The rules were first written only for hand-first reaches and produced no cards on real clips. Rather than loosening those, hand-and-foot overlap, large steps, and long stops were added as separate, measurable situations. Reaches that fail a rule are shown as "Checked and not flagged", and ones without evidence as "Could not be judged".

**D60. Overextension is never inferred from a straight arm.** A straight arm is often good climbing. The arm card needs a qualifying upward reach, no foot setup, a near-straight projected arm, and near this arm's own tracked length, and it says 2D length cannot show strain.

**D61. Contact and smears are user-confirmed.** Proximity to a marked hold is reported as proximity. A missing marked hold is reported as unknown, including possibly an intentional smear. Automation never writes a placement status.

**D62. Marks are compared with movement only after measuring alignment.** Twelve frames are compared with the reference frame using the background around the climber, and every frame must stay within 8 canonical pixels, with at least 80% measurable. This runs per analysis and ignores any tripod label. It runs synchronously because it is about a second of work on cached frames, which is an exception to the rule that heavy work goes to the worker.

**D63. Candidate beta is a labeled 2D search, not a route solver.** An exact shortest-path search replaced an initial beam search, which missed feasible sequences on the real route. Feet may start off the wall, a hand may not move until a foot is placed, and a foot is never proposed above both hands. A stick figure scaled to the climber's tracked limbs gives a reach margin. Unknown hold use is treated as possible and disclosed.

**D64. Attempts are comparable only through explicit labels.** The same problem and climber text must both be entered. Outcome stays the user's own text, tracking proxies need 60% foot coverage, and no success model is trained without outcome data.

**D65. Input limits raised to 5 minutes and 2.5 GB.** The earlier 120 s and 250 MB limits rejected real climbing footage, and 4K HDR phone video runs at about 400 MB per minute. Size does not affect analysis, which always uses a copy of at most 1280 pixels on the long side at 30 fps. The cost is disk space, because each original is kept so an import can be retried. Earlier runs keep their recorded configuration.

## Route tools (2026-11-11)

**D66. Hold suggestion is color grouping that the user confirms.** A tapped seed color, a Lab distance with lightness at half weight, and connected regions give outlines. Nothing is stored until accepted. A region over 4% of the picture is refused as wall. No trained hold detector is used, because no labeled wall images exist to train or evaluate one.

**D67. Video suggestions use a median wall picture only when the camera is measured as still.** Frames must fit the reference frame within 8 pixels of corner motion, and at least 5 must qualify. Otherwise the reference frame is used and the result says so.

**D68. A photo is imported as a one-second still clip.** This reuses normalization, frames, hold maps, and deletion without a parallel data model. Photo attempts refuse analysis.

**D69. Planning without a video uses entered height and wingspan plus a user-marked scale line.** Lengths use average segment proportions and are disclosed as estimates. One scale applies to the whole picture and perspective is not corrected, which is stated with each plan. Measurements are kept in the browser, not the database.

**D70. The hold editor shows a pose-masked wall composite when the camera is still.** Each pixel is the median of frames where it lay outside a box around the tracked joints (20% margin), needing 3 clear views; otherwise the plain median is used and the uncovered share is reported. It supersedes the plain 15-frame median of D67 for analyzed videos. Marks stay valid because only frames aligned with the reference frame are combined.

**D71. Wall frames are registered to the reference frame before combining.** A real clip shifted about 35 pixels after its first frame, which made every later frame fail the still-camera test. Each frame now gets a RANSAC homography from tracked background features (at least 60 inliers, 50% inlier share, 1.5 px median residual, corner shift at most 15% of width) and is warped into reference coordinates. Unseen areas keep the reference frame and are reported. The separate check that decides whether marks may be compared with tracked movement is unchanged and still requires a still camera.
