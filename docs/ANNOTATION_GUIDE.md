# Annotation guide

Reference labels must come from people. Nothing in this repository creates them. No annotations exist yet.

## Before you begin

- Annotate the **canonical video** (`canonical.mp4` of the run), not the original phone file. Timestamps then match the app.
- Do not look at the detector's events or the skeleton overlay while labeling.
- Label only inside the attempt bounds.
- Labels are a reference standard with possible disagreement, not ground truth.
- Agree the rules on two development clips first and write down the decisions. Do this before any test clip.

## Event A: low visible movement (`low_movement`)

Mark an interval of at least 2 seconds in which both wrists, both ankles, and the hips look approximately stationary in the picture, allowing small postural sway.

- Mark what you see, not a guess at intent such as hesitation or rest.
- A rest is not a mistake.
- If a required joint cannot be seen, you cannot judge stillness. Use `unscorable` instead.

## Event B: visible wrist movement (`wrist_motion`)

Label left and right separately, using the climber's anatomical side. Mark from departure out of relative stillness to return to relative stillness, at least 0.3 seconds long and clearly larger than small jitter.

- Do not require a new hold contact.
- Do not call a movement a regrip because it happens near a hold.

## Unscorable intervals (`unscorable`)

Use these where a person cannot judge the event because the body is hidden or off screen. Fill `applies_to` with detector keys separated by `;`, or `all`. Keys: `low_movement`, `wrist_motion_left`, `wrist_motion_right`.

Mark human visibility only. Do not mark an interval unscorable because the model lost tracking. A human-visible event the model missed must stay in the labels so it counts as a miss.

## File format

Save rows in `evaluation/annotations.csv`. All times are integer milliseconds with `0 <= start_ms < end_ms <= video_duration_ms`.

| Column | Meaning |
| --- | --- |
| `clip_id` | Must match the dataset manifest |
| `event_type` | `low_movement`, `wrist_motion`, or `unscorable` |
| `hand` | `left` or `right` for wrist motion; otherwise blank |
| `start_ms`, `end_ms` | Observed interval in canonical time |
| `annotator_id` | Anonymous, such as `h1` |
| `applies_to` | For `unscorable` only |

The template's other columns (`climber_id`, `route_id`, `split`, `observability`, `notes`) are optional context. Keep each annotator's original file. If a second person labels the same clips, report their agreement before resolving differences.

## Dataset manifest

Copy `evaluation/dataset_manifest_template.csv` to `evaluation/dataset_manifest.csv`. Split by climber where possible, because the tool rejects a climber appearing in both splits. Fix the split before tuning any threshold.

## Commands

```bash
.venv/bin/python scripts/evaluate.py --split dev --output evaluation/results/dev.json
```

Run the test split only after thresholds, model, event definitions, and matching are frozen:

```bash
.venv/bin/python scripts/evaluate.py --split test --output evaluation/results/test.json
```

If a test result leads to a change, the test clips have become development clips. Label later results exploratory or collect a new test set.
