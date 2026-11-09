# ClimbReview status

Last updated 2026-11-09. Current milestone: **Milestone 0 (feasibility), tooling complete, real-footage validation outstanding.**

## Bottom line

The command-line pipeline is implemented and tested on generated media and one official non-climbing photo. **No real climbing clip has been processed. Tracking quality on climbing footage is unverified, and the Milestone 0 decision gate has not been evaluated.** There is no evidence yet for or against pose tracking working on our intended recordings. Do not start Prompt 2 until the real-clip step below is done.

## Implemented

- `scripts/analyze_video.py`: one clip, optional attempt bounds, output directory, configuration.
- `scripts/run_feasibility.py`: every clip in `data/raw/manifest.csv`, plus `data/feasibility/summary.csv`.
- `scripts/setup_env.sh`, `scripts/download_model.py`: project-local setup and checksum-verified model download.
- Probe and validation of the actual container, duration, and size; explicit errors for bad input.
- Canonical upright, square-pixel, 30 fps H.264 video starting at time zero, with no audio or source metadata. The transform is recorded.
- 10 Hz MediaPipe Tasks Pose Landmarker inference in VIDEO mode, with timestamps read from the canonical stream.
- Raw landmarks in JSONL, with `null` for missing data.
- Per-landmark validity, one attempt torso scale, and separate coverage for `low_movement`, `wrist_motion_left`, and `wrist_motion_right`.
- Diagnostic `overlay.mp4`, `contact_sheet.jpg`, `report.md` with a blank human-review checklist, `run.json` with versions, checksums, configuration hash, and runtimes.

Not implemented, by design: detectors, smoothing, speeds, API, database, worker, or user interface.

## Environment and versions

| Item | Value |
| --- | --- |
| Machine | Apple M4 Pro, arm64, 24 GB, macOS 15.7.4 (Darwin 24.6.0) |
| Python | 3.12.16, conda-forge, in `./.venv` |
| FFmpeg / FFprobe | 9.0.2, conda-forge GPL build, in `./.venv` |
| MediaPipe | 1.2.2 |
| OpenCV (contrib) | 5.0.0 (`5.0.0.93` wheel) |
| NumPy | 2.5.4 |
| Pose model | `pose_landmarker_full` float16, SHA-256 `4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad` |
| Inference | CPU delegate; GPU not tested |

Node 24.16.0 is present but unused in this milestone. Exact packages are in `requirements.lock.txt` and `conda.lock.txt`; the model source is in `config/model_manifest.json`.

## Reproduce

```bash
./scripts/setup_env.sh
```

```bash
.venv/bin/python -m pytest
```

`setup_env.sh` needs an existing conda and installs only into `.venv/`, `models/`, and `data/test_assets/`.

## Verification actually run (2026-11-09)

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest` in the project | 54 passed |
| `./scripts/setup_env.sh` in a separate clean copy, then pytest | exit 0; 53 passed (run before the 54th test, the HEVC case, was added); `pip freeze` identical to the lock |
| Eight deliberate code defects, one at a time, in a temporary copy | each made a test fail: autorotate off, frame-count retiming, normalized-distance geometry, gap bridging, zeros for missing data, ignored pixel aspect, drawing invalid joints, dropping required ankles. Run before the HEVC test was added |
| `scripts/analyze_video.py` on the official MediaPipe still photo, stored rotated with rotation metadata, labeled `synthetic_test_media` | completed; the contact sheet was viewed and showed an upright image with the skeleton on the person's joints |
| `scripts/run_feasibility.py` on the empty manifest | exit 2, clear message |
| `scripts/run_feasibility.py` on a temporary manifest with one good, one corrupt, and one path-escaping entry | good entry completed; other two recorded as failed; summary written |

What the tests cover: rotation by pixel content (±90°, 180°), portrait and landscape, 10-bit HEVC, variable frame timing by content, nonzero start time, 29.97 fps duration, non-square pixels, audio and metadata removal, input rejection, missing-data serialization, validity reasons, pixel-space scale, coverage with gaps, irregular timestamps, attempt bounds, overlay hiding of invalid joints, real-model abstention on a video with no person, and failure cleanup.

The photo is one static, unobstructed person in a yoga pose. It verifies software wiring only. Its 90% coverage and 10-17 samples/s (short runs dominated by model startup) must not be reported as climbing results.

## Assignment reconciliation

`inputs/` contains only the assignment excerpt. There is no full rubric, no instructions for the four submissions, no due dates, no AI-use rules, and no team size. The project fits pathway 3 (data analytics to model sports behavior). Whether rule-based event modeling satisfies "model or predict" needs checking against the actual rubric. The six-week schedule remains an assumption.

## Limitations and unverified items

- Real climbing tracking: unverified (wall contact, back views, occlusion, overhangs, chalk, gym lighting).
- Real phone files: rotation, HEVC, and variable timing were tested only on generated clips made to resemble them.
- HDR sources are not tone-mapped (this FFmpeg build lacks `zscale`); the run records a warning.
- Slow-motion speed ramps are not reconstructed; clips use encoded playback time.
- A source frame gap over 100 ms produces repeated samples that could later resemble stillness; the run records a warning, and this must be handled when the detectors are built.
- `num_poses=1` cannot select a person. A second person may capture the track; identity jumps and left/right swaps are found only by watching the overlay.
- Model visibility is not alignment. Coverage counts landmarks the model reports as usable.
- MediaPipe logs a `NORM_RECT without IMAGE_DIMENSIONS` warning on non-square frames. The one inspected overlay looked aligned, but this should be rechecked on real overlays.
- Only this Mac was tested. Not a Git repository; nothing was committed.

## Remaining work for Milestone 0

1. Add 3-5 real clips and complete `data/raw/manifest.csv` as described in `data/raw/README.md`.
2. Run the batch command below.
3. Watch every overlay, complete each `report.md` checklist, and record supported and unsupported conditions here.
4. Apply the provisional gate in `docs/EVALUATION.md` (at least 70% low-movement eligible time in at least 3 clips, plus visually plausible alignment).

## Next exact command

After adding the clips and manifest rows:

```bash
.venv/bin/python scripts/run_feasibility.py
```

