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
5. **Review (1.5 min).** Play at 0.5× with the overlay on. Open the **Evidence** tab, select a wrist movement on the timeline, loop it, and read Observed / Could be / Reflect.
   Then choose **Feet only**. Select a foot episode and read its time, direction, distance, and what the other limbs did. Show its path on the video and click the speed chart to jump. Open **What moved and when** and point out where tracking prevents a conclusion. If the licensed clip has too little foot tracking, describe this using `docs/FOOTWORK_REPORT.md` instead of showing private footage.
   Go back to the **Opportunities** tab. Open one card and choose **Watch this moment**. Read it aloud: what happened, why it might matter, what to try, what to verify. Point at its marker on the timeline. Open **Foot placements to check** and say that only the climber can confirm contact or a smear. On the **Route** tab, show that **Other sequences to test** asks for route setup instead of inventing a route.
6. **Decide what to try (1 min).** Choose **I'll try this** on a card and open the **Next attempt** tab to show the list. Add a note and a focus, refresh, and show they persist.
7. **Export (30 s).** Open **More**, then the HTML report.
8. **Reference labeling (30 s).** Open **More**, choose **Label reference events**, and show the blind mode. Explain that real accuracy needs labels from people.
9. **Learned forecast (1 min).** Show the results table in `docs/TRAINING_REPORT.md`. Be clear what it is: predicting tracked wrist motion, not judging technique. State that it was only slightly better than predicting no movement.
10. **Optional: holds (30 s).** Open **Mark route holds** and add one region. Say that marks apply to this one frame only.

## Say plainly

- Pose landmarks come from a pretrained model.
- Events come from rules I wrote, with unvalidated thresholds.
- Event accuracy has not been measured yet, because independent labels are pending.
- The forecast is a separate experiment, and its error is against later pose estimates.
- Coaching cards are untested hypotheses. No experienced climber has rated them, and nothing shows that they improve climbing.
- Candidate beta is 2D geometry on marks you made. It is not the best or easiest route.
- Foot movement uses the ankle as a stand-in. It does not show contact, weight, or a slip.
- "Uncertain" foot episodes need checking in the video, and that flag also catches some real steps.
- The feasibility gate is not met on handheld phone clips or on two tripod clips, because hands are often hidden.
- Hold marks are user-made and do not show contact.
- No claim is made about technique, injury, or climbing improvement.
