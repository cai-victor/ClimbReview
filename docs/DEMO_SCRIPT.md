# Class demo script

About 6-8 minutes. Runs live on your laptop with real analysis, offline.

**Use this clip:** `data/public_samples/converted/public_rockspot_v3.mp4` ("Indoor Bouldering V3 Rock Spot" by Cryptic C62, CC BY-SA 3.0, https://commons.wikimedia.org/wiki/File:Indoor_Bouldering_V3_Rock_Spot.webm, re-encoded to MP4, audio removed). Credit it on screen. **Do not show private phone footage in anything you share or post.**

The clip is 204×360 and handheld, so it is a limited example. Say so.

## Before you present

```bash
.venv/bin/python scripts/run_app.py
```

Open http://127.0.0.1:8317. Do one rehearsal so the page and video load quickly.

## Walkthrough

1. **Problem (30 s).** Beginners struggle to know which parts of an attempt to rewatch. ClimbReview points to observable moments and leaves judgment to the climber.
2. **Import (1 min).** Choose the clip. Point out the Cancel button and that the app creates an upright copy. Everything runs on this computer.
3. **Set bounds (30 s).** Mark start 3 s and end 30 s. Note the checkboxes: this clip is not on a fixed camera, so say the warning is correct.
4. **Quality feedback (1 min).** Run the analysis and show real progress. Open the warnings and the timeline's hatched gaps. Click one gap and read the reason.
5. **Review (1.5 min).** Play at 0.5× with the skeleton on. Select a wrist event, loop it, and read Observed / Could be / Reflect.
6. **Judgments and reflection (1 min).** Show that "was it visible" and "was it useful" are separate. Add a note and a next-attempt focus, refresh, and show they persist.
7. **Export (30 s).** Open the HTML report.
8. **Reference labeling (30 s).** Click Reference labeling and show the blind mode. Explain that real accuracy needs labels from people.
9. **Learned forecast (1 min).** Show the results table in `docs/TRAINING_REPORT.md`. Be clear what it is: predicting tracked wrist motion, not judging technique.

## Say plainly

- Pose landmarks come from a pretrained model.
- Events come from rules I wrote, with unvalidated thresholds.
- Event accuracy has not been measured yet, because independent labels are pending.
- The forecast is a separate experiment, and its error is against later pose estimates.
- No claim is made about technique, injury, or climbing improvement.
