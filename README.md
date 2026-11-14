# ClimbReview

ClimbReview helps you review a video of your own bouldering attempt. You film one climb, drop the video into the app, and it shows you where you stopped, where your feet and hands moved, and a few specific things to try on your next go.

It runs entirely on your own computer. Your videos are never uploaded, and it needs no account and no internet connection once it is installed.

## What you get

- **A timeline of your climb**: how long you were on the wall, where you paused, and where you came off.
- **Moments worth a second look**: short cards such as a slow stand-up after a high step, each with what happened, why it might matter, and what to try. Clicking a card jumps the video to that moment and marks the body part it is about.
- **A plan for the next attempt**: the cards you chose to act on, in one list.
- **Route tools**: mark the holds on your route and compare two attempts side by side.
- **Your own notes**: say whether each card applies to you, write a reflection, and download a report.

The suggestions are things to test on the wall, not verdicts. See [What it can and cannot tell you](#what-it-can-and-cannot-tell-you).

## Install it

You need:

- A Mac. It has been tested on Apple Silicon Macs only. Intel Macs and Linux should work but have not been tested. On Windows, use WSL.
- About 2 GB of free disk space, and an internet connection for the install.

### 1. Get the folder

**If someone sent you a zip** (named like `ClimbReview-tester-1.zip`): unzip it somewhere you can find it, such as your Desktop.

**If you are getting it from GitHub**: you also need [Node.js](https://nodejs.org) installed, because the web pages are built during the install. Then download the code:

```bash
git clone https://github.com/cai-victor/ClimbReview.git
```

### 2. Open the folder in Terminal

Open the Terminal app, type `cd ` (with a space after it), drag the ClimbReview folder onto the Terminal window, and press Return.

### 3. Run the installer (once, about 5 to 10 minutes)

```bash
bash install.sh
```

Everything is installed inside the ClimbReview folder and nothing is installed system-wide. If your computer has no conda, the installer asks before downloading a small tool called micromamba into the same folder.

## Start it

```bash
bash start.command
```

Your browser opens the app at http://127.0.0.1:8317. Leave the Terminal window open while you use it, and press Ctrl+C in that window to stop.

## Review your first climb

1. **Film it.** Prop the phone up so the camera does not move. Keep your hands and feet in the frame for the whole climb, with one climber on the wall.
2. **Add the video.** Drag it onto the home page. MP4 and MOV files work, up to 5 minutes and 2.5 GB.
3. **Mark the attempt.** Set where the attempt starts and ends, then start the analysis. It takes roughly as long as the clip.
4. **Read the review.** The video is on the left with its timeline. The tabs on the right are:

   | Tab | What it shows |
   | --- | --- |
   | Opportunities | The shape of your climb and the moments worth a second look |
   | Next attempt | The suggestions you chose to try |
   | Route | The holds you marked and how your feet used them |
   | Compare | Two attempts on the same route, side by side |
   | Evidence | The measurements behind the cards, and where tracking was lost |

5. **Decide for yourself.** Mark each card "I'll try this", "Was intentional", "Doesn't apply", or "Can't tell". Your choices and notes are saved.

Keyboard shortcuts in the review: `N` and `P` step to the next and previous moment, `L` loops the selected moment, and `O` shows or hides the skeleton overlay.

## What it can and cannot tell you

- It describes movement it can see: stops, steps, reaches, and how your hips moved relative to your feet. It does not score your technique, and it does not measure force, grip, fatigue, or how far your hips are from the wall.
- The thresholds behind the suggestions are starting values that have not been validated, and no climbing coach has rated the feedback.
- A camera directly behind you hides your hands about half the time, so most feedback is about hips and feet. When a body part cannot be seen, the app says so and does not guess.
- Left and right follow the pose model's labels, so check them against the video.

## Your data

Videos, analysis results, and notes are stored in the `data` folder inside the ClimbReview folder. To remove the app, delete the ClimbReview folder; copy `data` out first if you want to keep your reviews.

## If something goes wrong

- **"ClimbReview is not installed yet"**: run `bash install.sh` first.
- **The install stops**: read the last line, which says what failed. Running `bash install.sh` again is safe and continues where it left off.
- **The browser does not open**: go to http://127.0.0.1:8317 yourself while the Terminal window is still running.
- **Anything else**: copy the last 20 lines from the Terminal window and send them to whoever gave you the app.

---

# Documentation

The rest of this page is for people who want to understand, change, or evaluate the app.

## How it works

1. **Normalize the video.** FFmpeg makes an upright, 30 frames-per-second copy. The original is never changed. All times in the app refer to this copy.
2. **Find the body.** A pretrained pose model (MediaPipe Pose Landmarker) locates 33 body landmarks ten times per second. Landmarks that are hidden or uncertain are recorded as unavailable, never as zero.
3. **Detect events.** Explicit rules turn the landmark tracks into events: low-movement intervals, wrist and foot movement episodes, high steps, stops, and leaving the wall. Distances are measured in torso lengths so they do not depend on how far away the camera is. Events are never joined across a tracking gap.
4. **Build the review.** The events become the climb profile and the coaching cards. Each card keeps the observation, the possible interpretation, and your own judgment separate.

The app does not train or modify the pose model. [docs/PIPELINE_EXPLAINED.md](docs/PIPELINE_EXPLAINED.md) explains each stage in plain language.

## What is in the folder

| Path | Contents |
| --- | --- |
| `backend/` | Python server, analysis pipeline, and tests |
| `frontend/` | The web interface (React and TypeScript) and browser tests |
| `config/` | Detector thresholds and limits |
| `scripts/` | Command-line tools for setup, analysis, evaluation, and releases |
| `evaluation/` | Templates for human reference labels |
| `models/` | The pose model, downloaded during install |
| `data/` | Your videos and results. Not tracked by git |
| `docs/` | Design, evaluation, and status documents |

## Developer setup

Requires conda (or mamba) and Node.js.

```bash
./scripts/setup_env.sh
```

Run the app from source, then open http://127.0.0.1:8317:

```bash
.venv/bin/python scripts/run_app.py
```

Run the Python tests:

```bash
.venv/bin/python -m pytest
```

Run the browser tests, from the `frontend` folder:

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" npx playwright test
```

Analyze one video from the command line, without the web interface:

```bash
.venv/bin/python scripts/analyze_video.py --help
```

The app serves on this computer only (the loopback address) and needs no API keys.

## Sharing it with a tester

```bash
bash scripts/make_release.sh
```

This writes a zip to `dist/` with the web pages already built, so the tester does not need Node.js. It contains no videos or personal data. [TESTER_README.md](TESTER_README.md) is the short guide that goes with it.

## Further reading

| Document | What it covers |
| --- | --- |
| [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) | Product, interface, analysis, and architecture specification |
| [docs/PIPELINE_EXPLAINED.md](docs/PIPELINE_EXPLAINED.md) | Plain-language walk through the analysis pipeline |
| [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) | Data structures, configuration, and the job lifecycle |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every change to event definitions and thresholds, with reasons |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Evaluation plan: dataset, labelling rules, and metrics |
| [docs/ANNOTATION_GUIDE.md](docs/ANNOTATION_GUIDE.md) | How to label reference events by hand |
| [docs/COACHING_EVALUATION.md](docs/COACHING_EVALUATION.md) | How the coaching cards are meant to be rated |
| [docs/STATUS.md](docs/STATUS.md) | What is implemented, what was tested, and what remains |
| [docs/SOURCES.md](docs/SOURCES.md) | External documentation the design relies on |

## Project context

ClimbReview is a course project in sports-behavior analytics. Its aim is an explainable pipeline: every suggestion traces back to a defined event and the measurements behind it. It has been tested on a small set of clips, and it has not yet been evaluated against human labels or rated by climbers.
