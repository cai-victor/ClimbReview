# How the feasibility pipeline works

A plain-language guide for explaining and defending this milestone. Reasons for each choice are in `docs/DECISIONS.md`.

## The question this milestone answers

Before building an app, can a pretrained pose model follow a climber well enough, in our recording conditions, to support later movement analysis? The software measures availability. A person must judge alignment.

## The five stages

**1. Probe and normalize (`video.py`).** FFprobe reports what the file actually contains. Phones often store sideways pixels plus a note saying "rotate on display", and may space frames unevenly. We create one canonical video: upright, square pixels, exactly 30 frames per second, starting at time zero. Each canonical frame shows whatever the source displayed at that moment, so time is preserved. The original is never changed.

**2. Extract pose (`pose.py`).** Every third frame (10 per second) goes to MediaPipe's Pose Landmarker in VIDEO mode, which uses earlier frames to help track. It returns 33 landmarks, each with x and y as fractions of the image, an estimated depth, a visibility score, and a presence score. We pass each frame's real media timestamp. If no pose is found, we store `null`. This matters because writing (0, 0) would look like a real position in the corner, and a stream of repeated zeros would look like perfect stillness.

**3. Decide what is usable and measure coverage (`quality.py`).** A landmark is unavailable if the pose is missing, the coordinate is not a real number, it lies outside the image, or its visibility or presence is below 0.6. Each planned detector has its own needs:

| Detector | Must be valid at a sample |
| --- | --- |
| Low movement | both wrists, both ankles, both hips |
| Left wrist motion | left shoulder, elbow, wrist |
| Right wrist motion | right shoulder, elbow, wrist |

Hidden feet therefore block the low-movement detector without blocking wrist analysis.

Coverage is counted between pairs of neighbouring samples. Time is credited only when both are valid, because a future speed measurement needs two valid observations. Worked example: in a 10.000 s attempt with samples every 100 ms, one bad sample at 5.000 s loses the intervals 4.900-5.000 and 5.000-5.100. Eligible time is 9,700 ms, or 97%. That gap is never bridged.

We also compute torso length `L`, the median distance in pixels from the shoulder midpoint to the hip midpoint, so later speeds can be expressed in body-lengths per second. Pixels matter because x and y fractions have different scales on a non-square frame. On a 720×1280 frame, a torso spanning 0.2 of the height is 256 px, while 0.2 of the width would be 144 px. If too few reliable torso samples exist, the detector reports `insufficient_tracking` with `null`, which is different from zero.

**4. Render diagnostics (`overlay.py`).** The skeleton is drawn on the exact frames analyzed. Left is orange and right is blue, as labeled by the model, so swaps are visible. A joint is drawn only when valid, and a bone only when both ends are valid. Burned-in text shows media time and each detector's status.

**5. Record the run (`pipeline.py`).** `run.json` stores the source hash, the exact transform and FFmpeg arguments, model checksum and options, library versions, configuration hash, runtimes, coverage, and warnings. Its `visual_alignment_review` field stays `not_reviewed`.

## Reading the output folder

| File | Use |
| --- | --- |
| `overlay.mp4`, `contact_sheet.jpg` | Watch these first; the real test of alignment |
| `report.md` | Coverage summary and manual checklist |
| `coverage.json`, `coverage_timeline.csv` | Per-detector and per-sample detail, with reasons |
| `poses.jsonl` | Raw landmarks, one sample per line |
| `canonical.mp4` | Timebase for everything else |
| `run.json` | Full provenance |

## Likely questions

**Did you build the pose model?** No. It is pretrained. The project's contribution is the explicit feature and event definitions, handling of missing data, and evaluation against human labels.

**Is 90% coverage 90% accuracy?** No. Coverage means the model reported usable landmarks for that share of time. It can be confidently wrong, so a person must inspect the overlay. Event accuracy is measured later against independent human labels.

**Why not fill small tracking gaps?** Interpolation invents observations. A gap in tracking could hide movement, and bridging it could create a false low-movement interval.

**Why these thresholds?** They are starting hypotheses from the project plan, not validated standards. They are to be tuned on development clips and frozen before held-out testing.

**How do you know the tests mean anything?** They check behavior such as pixel positions after rotation and brightness-coded timing. Eight deliberately injected defects each caused a failure. They still cannot establish pose accuracy on climbing footage.

**What is not known yet?** Whether this works on real climbing video. No real clip has been processed.
