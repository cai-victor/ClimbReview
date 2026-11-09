# ClimbReview: detailed product and technical specification

## 1. Purpose and assignment fit

**Project category:** option 3, using data analytics to model sports behavior or performance.

**Primary research question:** How accurately can an explainable video-based pipeline identify selected movement events during beginner indoor bouldering, and how useful are those events for reviewing an attempt?

**Product promise:** Help a climber find, inspect, and reflect on observable moments in a recording.

**Academic contribution:** Define movement features; implement event detectors with explicit thresholds and missing-data behavior; collect and annotate a small dataset; evaluate detection performance; and connect evidence to an interactive review experience. A pretrained pose model supplies inputs to the student's analysis, rather than supplying the entire project.

Do not claim a new pose model, validated automatic coaching, or improved climbing performance unless the project actually produces evidence for those claims. Rule-based event modeling still fits the provided wording, which does not explicitly require a newly trained predictive model. Reconcile this interpretation with the full rubric when available.

## 2. Users and supported setting

The initial user is a beginner indoor boulderer who can record an attempt and wants help deciding what to review. An experienced climber can help interpret examples and label evaluation footage.

Support one climber, a stationary camera, a mostly visible body, and a single bounded attempt. A back or oblique view is acceptable only if the feasibility test demonstrates usable landmarks. No view is promised to work in advance. Require the recording to include the climber's hands and feet as much as practical.

Initial configurable limits: MP4/MOV containers, at most 120 seconds, at most 250 MB. Probe the actual codec rather than trusting the extension. Record these as project defaults, not inherent model limits. Show an actionable rejection when a codec or file cannot be decoded.

Exclude real-time coaching, multi-climber identity tracking, competition scoring, injury assessment, force or fatigue estimation, calibrated 3D biomechanics, and automatic assessment of an optimal climbing sequence.

## 3. Scope tiers

| Tier | Deliverables | Completion condition |
| --- | --- | --- |
| Feasibility proof | Video normalization, pose extraction, diagnostic overlay, quality report | Real climbing clips have been inspected; supported conditions and failures are documented |
| Required MVP | Import/trim, persisted analysis, two detectors, synchronized review, event annotations, reflection, export | A new real video works through the entire app without fabricated results |
| First extension | User-marked route holds and candidate wrist-near-hold events | Annotation and event accuracy are evaluated separately |
| Later extensions | Two-attempt comparison; alternative pose model; assisted hold detection | Added only after core validation |
| Research stretch | Hold types; foot-contact/slip classification; trained technique classification | Requires appropriate labels and separate accuracy evidence |

Do not begin with automatic jug/crimp/sloper/pinch classification. Those labels need a defined taxonomy and labeled examples; the model and labels must be demonstrated rather than assumed. A manually marked route preserves useful route context while reducing the first version's scope.

## 4. End-to-end user experience

### Screen A: attempts library

Show an empty state with “Add an attempt,” short recording guidance, and an optional clearly labeled demo. Each saved attempt shows a user-entered title, thumbnail, date, processing state, and analysis-quality summary. Route name and grade are optional user metadata, not model predictions.

The library supports opening, renaming, retrying analysis, and deleting an attempt. Deletion removes its videos, derived files, jobs, notes, and exports from application storage. Temporary working files must also be cleaned up.

### Screen B: import and setup

1. Choose a local file and show import progress.
2. Validate it and create a canonical playable copy.
3. Preview that exact canonical video.
4. Mark start and end of the climbing attempt, excluding walk-up, setup, and walk-away.
5. Enter optional route name, grade, attempt outcome, and one sentence about the intended focus.
6. Confirm that the intended climber is the only climber being analyzed and the camera stays fixed. If not, request a better recording or mark the clip as unsupported.
7. Start analysis.

Use a full-frame single-person recording or a simple fixed user-selected crop. A fixed crop is an optional aid, not a tracker. If implemented, persist its mapping to the canonical full frame so overlays remain aligned. Do not silently switch among people.

### Screen C: analysis progress

Show actual stages: queued, normalizing, extracting pose, computing features, detecting events, generating report, complete. Display processed frames or media seconds when measurable; do not invent a remaining-time estimate. Allow cancellation and retry. Refreshing the browser must preserve progress through persisted job state.

On failure, retain the source attempt and show a short message such as “Video could not be decoded,” “Pose model is missing,” or “Not enough trackable body landmarks.” Link to diagnostic details without dumping stack traces into the main interface.

### Screen D: review workspace

Use a large video player on the left and event cards on the right on desktop; stack them on narrow screens. The video supports play/pause, 0.5×/1× speed, seeking, and optional looping of a selected event with roughly one second of context on each side.

Overlay toggles: body skeleton, wrist trails, optional manual holds. Draw a joint only when its stored visibility/validity supports it. Hide unavailable segments instead of joining them across occlusion.

The timeline shows separate event tracks for low movement, left/right wrist movement, and tracking gaps. Use text and icons as well as colors. Selecting an event seeks to its beginning minus context, opens its card, and can loop it. Clicking an uncertain interval explains why analysis is missing.

Each event card includes:

- Type and start/end time.
- Plain-language observation based on recorded measurements.
- A short “why review this?” explanation with uncertainty.
- Tracking-quality category and an expandable evidence panel.
- A reflection question.
- Controls: useful / not useful, confirm observable event / incorrect detection / cannot tell, and optional note.
- Optional context tag: planned rest, planning next move, intentional dynamic movement, other user explanation.

Keep detection correctness, usefulness, and user interpretation as separate fields. “Not useful” must not automatically become “incorrect detection.” User responses do not silently retrain or rewrite the detector.

Illustrative card, not a measured result:

> 00:18.2–00:20.7 · Low visible movement
> The tracked wrists, ankles, and hips moved little for about 2.5 seconds.
> This could be a planned rest or a moment of route planning. Rewatch what you were deciding here.
> Reflection: Was this pause intentional, and did it help your next move?

If no events are found, say so. If tracking is weak, explain that detections are incomplete. Never convert “no events” into “excellent technique.”

### Screen E: summary and reflection

Display attempt duration, detector-specific analyzable time, low-movement time as a percentage of eligible time, and left/right wrist-episode counts. Provide a top-three review list ranked by event duration and tracking quality, explicitly labeled as review priority rather than mistake severity.

Ask the climber to write one observation and one focus for a future attempt. Save these alongside the review. Comparisons between attempts, if added later, show observable differences with a recording-quality caveat and do not equate fewer pauses or faster completion with better technique.

### Screen F: exports

Required: machine-readable analysis JSON, event CSV, and a standalone HTML review report that can be printed to PDF. Include metadata, detector versions, configuration, measured coverage, event evidence, and user notes. Do not embed the full video in every report by default. A burned-in annotated video is optional; the live canvas overlay meets the interactive annotated-video goal for the MVP.

## 5. Processing and coordinate pipeline

1. **Probe:** Use FFprobe to inspect stream, duration, dimensions, rotation, timebase, and codec. Reject unsupported input cleanly. FFprobe's machine-readable stream information is documented in the official [reference](https://www.ffmpeg.org/ffprobe.html).
2. **Normalize:** Transcode a canonical upright, square-pixel MP4 suitable for the target browser, with a project choice of constant 30 fps, at most 1280 px on the longest side, preserved aspect ratio, and no speed change. Remove audio from the analysis/playback derivative. Handle rotation once and verify it visually. Store the exact transform and output metadata.
3. **Timebase:** Keep the canonical full clip beginning at time zero; store attempt bounds in that timebase. The player, poses, events, annotations, and exports all use canonical-video milliseconds. The original file remains unchanged. Slow-motion source is analyzed at its encoded playback time; do not invent original capture timing.
4. **Sample:** Start at 10 pose-inference frames per second, sampling canonical frame indices 0, 3, 6, etc. Derive timestamps from the actual canonical stream/frame mapping. Store timestamps with each result; never use wall-clock inference time as video time.
5. **Extract:** Use the MediaPipe Tasks Pose Landmarker Python API in VIDEO mode with one pose. Test the full model first and compare the lite model only if runtime matters. Store model source, checksum, library version, and options.
6. **Validate:** Retain visibility and presence when available. Mark missing or implausible observations as unavailable. Never represent a missing coordinate as (0, 0).
7. **Clean and calculate:** Smooth within contiguous valid segments, calculate features with actual elapsed time, and detect events. Never bridge an unavailable interval in the core implementation.
8. **Persist:** Write raw landmarks, cleaned features, detector validity, events, configuration, and quality summary to versioned outputs. Generate templates from those outputs.

The official Pose Landmarker describes body landmarks in images/video, including 33 landmark locations; that capability does not establish climbing-specific accuracy. See the [official Pose Landmarker guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker). Its video API requires monotonically increasing frame timestamps; see the [Python API](https://developers.google.com/edge/api/mediapipe/python/mp/tasks/vision/PoseLandmarker).

Important geometry: convert normalized positions to image-space pixels before measuring Euclidean distances: `p = (x * width, y * height)`. Measuring raw normalized x/y distances would distort geometry when width and height differ. Use one robust per-attempt torso-length scale `L` from reliable shoulder-midpoint to hip-midpoint observations. Exclude degenerate estimates; if insufficient reliable scale exists, abstain. This scale reduces size dependence but is not a physical calibration.

Do not recenter every frame on the hips before computing global movement; that would erase the hip movement being measured. Use 2D image-space measures in the MVP. Do not present model-estimated depth as a measured wall distance or body center of mass.

## 6. Event detector definitions

All numerical settings below are initial engineering hypotheses. Tune on development clips, freeze for evaluation, and report the final configuration. They are not validated climbing standards.

### Detector 1: low visible movement

Required landmarks: both wrists, both ankles, and both hips. Reliable torso observations are also required to establish scale. A frame/derivative interval is eligible only if all event-required observations are valid; missing feet cannot be interpreted as stationary feet.

- Smooth each eligible coordinate over a short window, initially 0.3 seconds, without crossing gaps.
- Estimate joint speeds in torso lengths per second over an approximately 0.3-second finite-difference window.
- Define `movement(t)` as the maximum speed across required joints. This conservative choice avoids calling the whole body still while a visible limb moves substantially.
- Start a candidate when `movement(t)` remains below an initial 0.15 L/s threshold.
- Keep it only if the eligible low-movement interval lasts at least 2.0 seconds.
- Merge only small, fully observed interruptions under a documented rule; initially 0.2 seconds. Never merge through missing tracking.
- Clip event bounds to the user-selected attempt.

Output: an observable low-movement interval, not a diagnosis of hesitation, fatigue, inefficiency, or error. A user can mark it as a planned rest.

### Detector 2: wrist-movement episodes

Analyze each wrist separately. Require that wrist and the relevant arm landmarks to be reliable, plus a valid attempt scale. Treat left/right as model-anatomical labels and visually check for swapping in example clips.

- Start when the wrist's smoothed image-space speed rises above an initial 0.35 L/s.
- Continue until it remains below an initial 0.20 L/s for 0.25 seconds; this separate onset/offset rule reduces rapid toggling.
- Retain an episode only when its duration is at least 0.3 seconds and its displacement from initial position reaches at least 0.2 L.
- Terminate or discard a candidate at an invalid segment according to a documented rule; label incomplete episodes as truncated rather than complete moves.
- Record start/end, hand side, duration, displacement, and path length. Hand episodes may overlap each other or low-movement events near boundaries.

Output: visible wrist motion, not proven hand release, a new hold contact, a climbing move, or a grip adjustment. No efficiency score is inferred from the number of episodes.

### Quality and abstention

Store detector-specific eligible duration and fraction of the selected attempt. A descriptive tracking-quality label may combine landmark availability and continuity. It is not a calibrated probability that an event is correct. Do not display an invented “92% confidence.” Show the underlying fraction/criteria in the evidence panel.

If tracking is insufficient, return `insufficient_tracking` for the affected detector and retain the playable video for manual review. Do not make absence of wrist detections look like zero actual wrist motion.

### First extension: manual holds and candidate repositioning

Let a user mark hold centers and approximate outlines/radii on an unobstructed canonical frame. Save normalized image coordinates, route membership, and optional user-supplied type. These positions are only valid for the same fixed camera.

A separate experimental detector may associate a visible wrist with a marked region using proximity, dwell time, and entry/exit hysteresis. Repeated departures and returns near the same region can be flagged as “possible repeated repositioning near this hold.” Projected proximity is not evidence of grip or force. Evaluate these candidate events independently. Do not add a “feet cut” or “slip” detector based solely on 2D landmark overlap with the wall.

## 7. Feedback generation

Use deterministic, versioned templates in the MVP. Each card is generated from a structured event and its measurements. An example template is: “From {start} to {end}, {observed_measurement}. This may be {multiple plausible interpretations}. Rewatch and consider {reflection_question}.”

Keep observations, interpretations, and user reflections visibly distinct. Suggestions should be review questions or a focus to discuss with an experienced climber, rather than unsupported biomechanical instructions. Do not prescribe dropping a knee, changing grip, or shifting weight unless the feature and evidence support the statement.

An optional later LLM can rewrite already-grounded text from structured events. It must not invent observations, holds, causes, or measurements; its output is validated against the event schema. The app works fully without an LLM API key. The coding assistant and the application runtime are separate uses of AI.

## 8. Architecture and stack

Recommended baseline: React + TypeScript + Vite frontend; Python 3.11 or another tested compatible interpreter; FastAPI/Pydantic backend; MediaPipe Tasks, OpenCV, NumPy; FFmpeg/FFprobe; SQLite for metadata; filesystem for video/derived arrays. Use pytest for analysis and API behavior and Playwright for the browser's critical workflow.

Choose current mutually compatible versions during setup and record them in lockfiles. Check OS/architecture support first; do not assume the newest Python interpreter is compatible with every dependency. The current official MediaPipe setup page lists supported environments in its [setup guide](https://developers.google.com/edge/mediapipe/solutions/setup_python).

Run locally on loopback. In development Vite proxies API/media requests. For a reproducible demonstration, build the frontend and serve it with the backend from one origin. No authentication, public hosting, managed database, billing, or cloud storage is needed for this local prototype.

Heavy analysis runs in a separate local worker process, with one analysis job at a time and SQLite-backed state. The API remains available for playback and status. A simple dedicated worker polling queued rows is sufficient; atomically claim jobs and handle interruption. This is a project architecture choice, not a claim that a production distributed queue has been built. FastAPI's own documentation distinguishes heavy computation from ordinary [background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/).

Suggested structure:

```text
ClimbReview/
  README.md
  frontend/src/{components,pages,api,types}/
  backend/app/{api,schemas,storage,jobs}/
  backend/app/analysis/{video,pose,quality,features,detectors,feedback}/
  backend/tests/
  frontend/tests/
  scripts/{analyze_video,evaluate,download_model,dev}
  config/detectors.yaml
  docs/
  inputs/
  evaluation/
  data/raw/             # ignored originals
  data/attempts/        # ignored canonical videos and artifacts
  models/               # ignored weights plus tracked manifest elsewhere
```

## 9. Persistent records and API contract

Minimum records:

- **Attempt:** ID, title, optional route metadata, original/canonical asset paths, duration/dimensions, attempt bounds, creation time, user outcome.
- **AnalysisRun:** ID, attempt ID, status, stage, progress counts, detector configuration hash, model manifest, pipeline version, quality summary, result paths, error information.
- **PoseFrame:** timestamp, landmarks with validity/visibility, person state; store as JSONL or a compact documented format.
- **Event:** ID, run ID, type, hand side if applicable, start/end milliseconds, evidence values, tracking-quality category, template version.
- **EventReview:** event ID, observable-event judgment, usefulness, context tags, user note.
- **Reflection:** attempt ID, observation, next-attempt focus.

Reanalysis creates a new run. Preserve prior annotations on their original run and do not silently attach them to changed event IDs.

Suggested endpoints:

```text
POST   /api/attempts                       import multipart video
GET    /api/attempts                       list attempts
GET    /api/attempts/{id}                  metadata and available runs
PATCH  /api/attempts/{id}                  bounds/title/user metadata
DELETE /api/attempts/{id}                  delete assets and records
POST   /api/attempts/{id}/analyses          queue a run
GET    /api/analyses/{id}                  persisted job state/quality
POST   /api/analyses/{id}/cancel           request cancellation
GET    /api/analyses/{id}/poses            timestamped overlay data
GET    /api/analyses/{id}/events           structured events
PUT    /api/analyses/{id}/events/{event}/review
PUT    /api/attempts/{id}/reflection
GET    /api/analyses/{id}/export?format=json|csv|html
GET    /api/attempts/{id}/video            canonical media with seeking support
```

See `docs/DATA_CONTRACTS.md` for illustrative records and configuration. Keep frontend and backend types aligned with the API schema. Sanitize filenames, use generated IDs for storage, stream uploads with a size cap, and pass FFmpeg argument arrays rather than interpolated shell strings. These requirements prevent ordinary file-handling defects in this application.

On worker shutdown, cancellation, or failure, release resources and clean partial outputs. On restart, mark interrupted jobs as interrupted/failed with a retry action instead of leaving them “running” forever. Prevent deletion or reconfiguration from racing with active analysis.

## 10. Playback correctness

The player and overlay share canonical media timestamps. Use the media element's current playback time, not a separate timer. Scale positions into the displayed video's actual content rectangle, including letterboxing. Account for browser pixel density, resizing, portrait video, fullscreen, seeking, and playback speed.

For a 10 Hz pose track, draw a sufficiently close valid sample or interpolate only between adjacent valid samples under a small, configured gap limit. Never draw through an invalid interval or carry a skeleton indefinitely after tracking stops. Clip overlays and event loops to media duration and the selected attempt as appropriate.

## 11. Milestones and acceptance gates

**Milestone 0 — feasibility, approximately week 1.** Analyze 3–5 representative real clips through a CLI. Produce canonical videos, raw poses, coverage tables, runtime logs, and diagnostic overlays. Include at least one difficult clip. Inspect real joints visually; software tests cannot establish tracking accuracy. Decide which camera/view conditions are supportable. If tracking is weak, first improve framing or a fixed crop; then consider another model after documenting the failure. A manual-review mode remains useful but does not substitute for the promised evaluated analytics contribution.

**Milestone 1 — real import-to-overlay slice, approximately week 2.** Import, trim, queue analysis, persist results, and play synchronized overlays in the browser. Refresh/restart behavior works. Use actual output from the feasibility pipeline. A sample demo is explicitly labeled.

**Milestone 2 — detectors and review, approximately week 3.** Implement and test both detectors, evidence cards, event seeking/looping, uncertainty states, and saved annotations. Freeze event semantics before annotating the evaluation set.

**Milestone 3 — evaluation and revision, approximately week 4.** Create a predefined development/test split, label videos, tune only on development data, and evaluate the held-out data. Report failure cases and missing-data coverage. Address defects identified by climbers.

**Milestone 4 — final demonstration, approximately weeks 5–6.** Complete reflections, export, setup instructions, browser verification, and report/presentation. Add manual holds or comparison only when the core works. Map actual dates to the course schedule.

For one student, prioritize the core and a modest evaluation. For two, divide analytics/evaluation and application/interaction while integrating early. For three, add independent annotation, a stronger user study, and the manual-hold extension; have all members understand the shared method. The assignment expects scope proportional to team size and prior experience.

## 12. Meaningful verification and definition of done

- Synthetic tracks verify actual detector semantics: stillness, moving limb, short jitter, simultaneous hands, irregular timestamps, missing joints, threshold boundaries, and truncated episodes.
- One media test verifies upright portrait/landscape normalization and timestamp mapping; inspect a real phone clip with variable frame timing if available.
- API/worker tests cover import validation, persisted status, failure/retry/cancel, restart interruption, and deletion cleanup.
- A browser test exercises import → bounds → real analysis → overlay → select event → save note → refresh → export. It must not replace the production analytics with fake results.
- Manual visual inspection checks skeleton alignment while playing, seeking, resizing, and changing playback speed.
- The evaluation script produces actual metrics from independent annotations. Empty or small test sets are reported honestly.
- The final report distinguishes implemented, evaluated, experimental, and future features; no unmeasured effectiveness claim appears as a result.

The project is complete when a fresh setup can process a new supported video, present evidence and uncertainty correctly, retain a review, export reproducible results, and reproduce the reported evaluation.
