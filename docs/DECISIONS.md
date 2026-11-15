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

## Automation (2026-11-12)

**D72. Analysis starts automatically after upload, on the whole clip.** It is a per-browser preference, on by default, and the upload flag defaults to off in the API. Bounds can still be narrowed and the attempt reanalyzed.

**D73. Route setup is two clicks plus confirmation, not zero.** Automatic route-color selection was built and measured against four hand-marked routes (5 of 11, 3 of 3, 7 of 17 in the wrong color, 0 of 10), then removed. The climber clicks one hold; color grouping finds the rest.

**D74. Roles are proposed from rest points and geometry, and only the finish and uses.** The finish is the highest hold, a rule fitted to the two routes that had a marked finish. A hold a hand rested near is proposed for hands and feet; one only feet rested near, for feet. Start is never proposed because both tracked-hand rules failed on both routes. For existing maps, proposals fill only fields the climber left empty.

**D75. The default review is a simple view.** Evidence panels move behind a Detailed switch that is remembered per browser. The first three suggestions shown are one per kind in a fixed order of specificity, which is presentation and not a ranking of importance.

**D76. The planner falls back to the tracked torso for scale** when a map has no scale line and the attempt has an analysis, and says so in its assumptions.

## Wall geometry (2026-11-12)

**D77. Route distances are measured on a wall plane fitted to the bolt grid.** Dots are detected, given grid positions by stepping outward from the holds, and fitted with a RANSAC homography (at least 30 inliers, median error at most 2 px). Holds and the climber's limb lengths are both measured on that plane. The grid is assumed square and the face flat; both are stated with every result.

**D78. The correction needs evidence that the holds are on the fitted face.** At least 80% of holds must lie in the fitted area, within 3 grid steps, or among holes following the same grid. A looser rule was tried and dropped: texture on holds produced stray dots, so a lack of agreement could not separate another face from the same face with hidden holes.

**D79. Wall angle is reported relative to the camera only.** A focal length is solved from the grid under square pixels and a centered lens, and rejected outside 0.4 to 6 times the picture size. No overhang relative to gravity is claimed, because the camera's own tilt is unknown.

**D80. Event detection is unchanged.** Episodes and card rules keep picture distances and one attempt scale, so stored analyses and earlier results stay valid. Cards show the wall-plane distance as an added measurement.

## Review workspace (2026-11-12)

**D81. The review is one workspace with tabs, replacing the Simple and Detailed switch (supersedes D75).** The video and timeline stay on the left; Opportunities, Next attempt, Route, Compare and Evidence are tabs on the right. Reason: on a phone the first coaching card was about 3,800 px below the video, and the switch hid the timeline that links a card to its moment. The first three cards are still one per kind, which is presentation and not a ranking.

**D82. A coaching card and its timeline marker are one selection.** Either one selects the card, highlights the marker, and seeks to 1 s before the card's start. The card's own time stays the measured start. Scrubbing out of a looped moment turns the loop off and keeps the selection; a filter that hides the selected card or movement clears it with its loop and drawn path.

**D83. Cards read in a fixed order: what happened, why it might matter, what to try, what to verify.** The text and measurements are unchanged from coaching-v1. The first two limits of each card are now shown open instead of inside a collapsed section. No numeric confidence is shown, because none of the stored values is a calibrated probability.

**D84. Timeline marks use one neutral color with row labels; the accent color means selection or a primary action only.** Left and right keep orange and blue on the video overlay and chart lines, always with a text label.

## Climb story (2026-11-13)

**D85. The shape of an attempt is read from the hip midpoint in the picture.** It is described as hip height and position in the picture, never as a center of mass, effort, or balance. A stop is 3 s or more within 0.3 torso lengths; stops within 5 s and 0.5 torso lengths are one stay if the hips never left a 0.8 torso-length radius. These are starting values, untuned.

**D86. A fast hip descent ends the time on the wall.** At least 1.2 torso lengths down within 1.5 s. It is reported as leaving the wall, with the statement that a fall and a jump down look the same. Cards and foot placements after it are removed and counted, because they describe walking on the mat. Detection of the start of climbing is not attempted: standing on the ground and hanging on the start holds were not separable on the clips available.

**D87. Whole-attempt takeaways are cards.** They share the card layout, decisions, and markers. Up to two lead the first view, followed by up to three moment cards as before. A stay reported at the attempt level replaces `long_pause` cards inside it. Limb counts during a stay describe tracked movement only and pick the wording of the suggestion; they are not evidence of grip or contact.

**D88. Coaching output is now `coaching-v2`.** Moment-card rules and ids are unchanged, so saved decisions still attach. A slow-start card requires real movement afterwards, so a clip in which the hips never move produces none.

**D89. Climbing is counted from lift-off when the clip shows the climber standing first.** Standing is an ankle within 0.25 torso lengths of the lowest foot level in the clip (98th percentile) under a leg at least 0.8 of its tallest appearance, starting within 1.5 s of the first tracked sample and lasting at least 1 s. It is reported as "the ground or your first foothold" because the two look the same. Stops, cards, and placements before it are not counted. Reason: IMG_7863 and IMG_7850.

**D90. An early fast descent followed by climbing is the start, not the end.** If it begins in the first 20% of the clip and at least 10 s of tracked hips follow, time on the wall starts when it ends. Reason: IMG_7853, a sit start.

**D91. A steady attempt gets a reference card.** No fast descent, at least 8 s on the wall, under 15% of it stopped, and hips tracked at least 90%. It suggests no change, so that an attempt with nothing flagged still says what was checked.

## Self-review (2026-11-14)

**D92. A high step is judged by the stand-up that follows it, not by its size.** Measured when the foot lands: sideways distance from the hip midpoint to that ankle, and the time for the hips to rise 0.5 torso lengths (watched for 6 s). Rising within 2 s is reported as a clean stand-up and not flagged. Not rising within 2.5 s, or leaving the wall first, is a card; hips 0.6 torso lengths or more to the side get the hips-over-foot suggestion. The kind stays `large_step` so saved decisions still attach. Reason: on IMG_7863 and IMG_7865 the old intermediate-foothold advice missed what the footage shows. The intermediate foothold is still offered when a marked foothold lies between the two heights.

**D93. The wrist visibility threshold stays at 0.6.** Frames from IMG_7850 and IMG_7238 show low-visibility wrists placed on the torso or head while the real hands are hidden, so accepting them would feed guessed positions to the reach rules.

**D94. Cards carry a highlight.** Fixed marks at positions measured for that card plus a caption, drawn only while the card is selected, and the card's limbs drawn heavier. Marks are measurements (where a foot landed, where the hips were) or the suggested direction, labelled as such; none marks contact.

**D95. A foot planted on the lowest foothold for more than half the clip is not a ground phase**, and a pause card is dropped when half or more of it lies inside a stay that is not the starting position.

## Changes after a climber's review (2026-11-15)

A more experienced climber tried the tester build and sent 22 written points. These decisions answer them.

**D96. The planner refuses positions a person cannot get into** (`candidate-beta-v2`). Added to the reach circles: the left foot may be at most 0.35 torso lengths right of the right foot and the reverse; hands may cross by at most 1.0; feet may be at most 1.5 leg lengths apart; one foot move is at most 1.1 leg lengths and one hand move at most 2 arm lengths; the hips may sit at most 0.2 torso lengths below the lowest foot. Reason: the review reported impossible leg crossovers, and on the marked IMG_7768 route the old planner proposed single moves of 3.84 torso lengths. These limits are stated assumptions, not measured human limits.

**D97. Profiles are Balanced, Fewer moves, and Low feet, small steps.** "More reach margin" and "Shorter individual moves" are gone. A placement counts as a high foot when no in-reach position keeps every foot 0.8 torso lengths below the hips; each profile charges a different cost for it, and Low feet charges the most. A hand move made while one foot is off the marked holds also costs extra. Reason: the review said the planner "really likes high feet" and asked for something "humanly achievable" instead of the old two extremes.

**D98. Tracked arm reach runs to the palm, and sequences may be up to 40 moves.** Tracked arm length adds 0.35 of the forearm, the same share already used to place a resting hand. Placements within 0.2 torso lengths of the limit are solved on the fine grid. Reason: with D96 in place, the 17-hold IMG_7768 route that the climber actually climbed came back as impossible; the reach stopped at the wrist and the 14-move cap was too short once giant moves were excluded. After the change it returns sequences of 20 and 15 moves with a longest move of 2.42 torso lengths.

**D99. Wall-plane coordinates are turned to match the picture.** The fitted bolt grid's axes can point any way, but the planner reads "below", "left of", and "upright" from coordinates. The plane is now rotated or mirrored (distances unchanged) so right and down in the picture are right and down on the plane. Reason: a test wall came out rotated a quarter turn, which made "a foot below the hands" a sideways comparison whenever the wall-angle correction was applied. This was a bug in every corrected plan.

**D100. Alternative start footholds are tried one at a time, and a blocked search says where it stopped.** Footholds marked Start are options: every pair is tried, and each alone with the other foot off the marks. When no sequence is found, the note names the highest holds the hands reached and lists what to check. Reason: the review reported "No sequence stayed within this 2D reach model" for a problem with two possible starting foot positions.

**D101. A hold can carry a pull direction, and a top out is a kind of finish.** Pull direction (down, left, right, up) is optional and set by the climber; it limits where the shoulders may be while a hand is on that hold. Holds without one are unrestricted. A top-out point is stored as a finish with the label `top-out`, so nothing else in the app changes. The app does not detect either.

**D102. The route sketch is a stick figure with hands blue and feet orange, and the video skeleton uses the same colors.** The figure shows one in-reach position per placement, chosen to hang on nearly straight arms; it is a sketch, not a required position. On the video, arms are blue and legs orange, and the tracker's left and right are shown as L and R letters at the wrists and ankles so a swapped side stays visible. Reason: the reviewer read orange and blue as feet and hands, not left and right.

**D103. HLG phone video is converted to look like the phone shows it.** The old conversion mapped HLG reference white to SDR white, which blew out bright walls and over-saturated colors. The new one uses scene light with a 1.2 gain, a highlight shoulder above 0.7, saturation 0.85, and a 2.2 gamma; the three numbers were set by matching static parts of one frame of IMG_7850 to macOS's own rendering of the same file (median gray 0.60 against 0.57). It applies to new imports only: existing attempts keep their converted video, so their saved analyses still match what is shown. Effect on pose tracking has not been measured.

**D104. The bolt grid is fitted under several detection settings** (`bolt-grid-v2`). The dot detector is run with its original automatic threshold and with three relative-darkness thresholds, and the accepted fit with the most bolt holes is kept. Acceptance rules are unchanged. Reason: the natural-looking conversion in D103 shows wall texture that the old conversion had washed out, and the original threshold then found too many stray dots to fit IMG_7238. On the four marked walls the result is 559, 517, and 231 bolt holes and one wall still not fitted, against 509, 514, 220, and not fitted before.

**D105. Seconds are written without a space ("52s"), and tester installs skip unused packages.** The release zip's package list leaves out the test tools and the forecast experiment's scikit-learn and SciPy, and the installer downloads with uv, falling back to pip.

