# Decision log

Format: decision, then reason. All numeric settings are provisional engineering choices. **No event semantics have been implemented yet**; the required-landmark sets below come directly from `docs/PROJECT_SPEC.md` §6.

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

**D13. HDR and sparse frames warn instead of failing.** The build cannot tone-map HDR (`zscale` is absent). Geometry and time remain valid, so the run proceeds with a recorded warning. Frame gaps longer than the sample period are likewise flagged because repeated frames could later resemble stillness.

## Data and coverage

**D14. Raw landmarks and validity are separated.** `poses.jsonl` stores what the model returned, including out-of-frame and low-visibility values. Validity is derived, so thresholds can change without re-running inference. No pose is `landmarks: null`; non-finite values are `null`; JSON is written with NaN disallowed.

**D15. Validity reasons in fixed priority: `no_pose`, `non_finite`, `out_of_frame`, `visibility_missing`, `low_visibility`, `low_presence`.** Thresholds are 0.6, from `docs/DATA_CONTRACTS.md`. Visibility is required, while presence is checked only when available, as that contract specifies. Off-image coordinates are treated as unavailable because the model is extrapolating there.

**D16. Required landmarks per detector.** Low movement: both wrists, ankles, and hips. Wrist motion: that side's shoulder, elbow, and wrist. All also need a valid attempt scale.

**D17. Eligible time is credited to intervals between consecutive samples, only when both endpoints are valid and at most 150 ms apart.** This matches how speed will be computed later, since a speed needs two valid observations. An isolated valid sample earns nothing and nothing crosses a gap. The trade-off is that the final sub-sample remainder is never credited, so perfect tracking of a 10 s attempt reports 99%.

**D18. An unavailable detector reports `insufficient_tracking` with `eligible_ms: null` and `fraction: null`.** A zero would look like a measured quantity. `landmarks_contiguously_valid_ms` remains available for diagnosis.

**D19. Attempt scale is the median shoulder-midpoint to hip-midpoint distance in pixels.** It needs at least 10 reliable samples, and lengths under 2% of the image diagonal are excluded. Pixels are used because normalized axes differ in scale. The median resists single-frame errors. It is not a physical calibration.

**D20. World landmarks are not stored.** The MVP is explicitly 2D image-space, and leaving them out avoids tempting 3D claims.

**D21. Overlay video is 10 fps and uses the exact frames that were analyzed.** At 30 fps, poses would have to be held or interpolated. Timestamps are burned in using canonical milliseconds. Joints and bones are hidden when unavailable.

**D22. Automatic identity-swap and jump detection was deferred.** Without real data, any threshold would be invented. Human review of overlays handles this for Milestone 0.

**D23. The official MediaPipe photo is an integration-test fixture labeled `synthetic_test_media`.** It lets tests exercise the path where landmarks are actually returned. It is not climbing footage and cannot satisfy real-video acceptance criteria.

**D24. Output directories appear only after complete success.** Work happens in a temporary sibling directory, and `--overwrite` replaces only an earlier run directory.
