# Evaluation and evidence plan

Everything in this document is a proposed method. Sample sizes, thresholds, and targets are planning choices; no results have been collected.

## 1. Questions the project can answer

1. Can the pose pipeline track the landmarks required by each detector under the declared recording conditions?
2. How accurately do the two event detectors locate independently annotated visible events?
3. Can beginner climbers find a highlighted moment, understand its explanation, and record a useful reflection?

These questions evaluate tracking, event modeling, and interaction separately. A useful interface does not establish detection accuracy. Accurate event detection does not establish that the event is a mistake. Neither establishes improved climbing performance without a separate longitudinal study.

## 2. Feasibility dataset before interface work

Supply 3–5 short, representative recordings of the intended climbing setting. Include ordinary views as well as at least one difficult view, such as occlusion, an overhang, a side-on body position, or an incomplete body frame. Use clips you are permitted to analyze and show for the project.

For each, record: clip ID, climber ID, route ID, camera view, approximate camera motion, source resolution/frame timing, attempt boundaries, and which development/debugging uses are allowed. Keep identifiers separate from participant names.

The feasibility script outputs:

- Probe metadata and canonical-video metadata.
- Required-joint availability over time, separately for each detector.
- An overlay video or frame sequence for visual checking.
- Processing duration and environment/model versions.
- Notes on identity swaps, implausible positions, missing hands/feet, rotation, and synchronization.

Proposed decision gate: most ordinary test clips should have enough visually plausible landmarks to analyze meaningful stretches of the attempt. As an initial engineering target, aim for at least 70% eligible time for the stricter low-movement detector in at least 3 clips; this target is provisional and must not be presented as a validated scientific cutoff. High model visibility alone is insufficient: manually inspect alignment.

If the gate fails, document the failure and change framing/crop, supported conditions, or model before polishing the UI. Keep a difficult failure example for the final report. If no tested pipeline supports the intended setting, revise the research question and report the limitation instead of displaying invented events.

## 3. Evaluation dataset

A useful exploratory target is 15–30 short attempts across roughly 5–10 climbers and multiple routes. A smaller dataset may be appropriate for a solo project or short deadline; describe it as a pilot and avoid broad generalization. A larger team should contribute more independent labels and broader evaluation.

Keep a tracked manifest of clip IDs, anonymous climber IDs, route IDs, view conditions, and split. Keep private footage in ignored media folders. Document provenance and permission to include demonstration frames.

Create development and test groups before threshold tuning. Prefer splitting by climber so one person's attempts do not appear in both groups. Repeated attempts from the same original recording stay together. With very few climbers, report the limitation explicitly. If the same routes appear in both groups, do not claim unseen-route generalization. Do not treat individual video frames as independent participants or independent test examples.

Use development clips to choose smoothing and event thresholds. Freeze configuration, model version, event definitions, and matching rules before running the held-out test. Save the split and hashes so the result can be reproduced.

If the test set informs a revision, mark it as used for development and obtain a fresh test set or clearly label later results as exploratory.

## 4. Human annotation protocol

Annotate canonical videos, not originals, so timestamps match the app. The supplied `evaluation/annotations_template.csv` is empty by design. Store intervals in milliseconds with `0 <= start_ms < end_ms <= video_duration_ms`.

First write a one-page coding guide and annotate two development examples to settle ambiguous cases. Annotators should not see the detector's event predictions while producing reference labels. Human labels are a reference standard with possible disagreement, not infallible ground truth.

### Event A: low visible movement

Mark an interval lasting at least 2 seconds during which both wrists, both ankles, and hips appear approximately stationary in the camera view, allowing small postural sway. Mark the observed interval boundaries, not an assumed mental hesitation. Do not label a rest as an error. Exclude setup and walk-away using the attempt bounds.

### Event B: visible wrist-movement episode

Label left and right separately. Mark a clearly visible wrist movement from the departure from relative stillness to its return to relative stillness. The minimum intended duration is 0.3 seconds; movement should exceed tiny jitter. Use example clips in the annotation guide to align what counts as substantial movement. Do not require a new hold contact or label a motion as a regrip merely because it moves near a hold.

Human perception and numerical thresholds will not align perfectly. Report disagreements and refine definitions only on development data. This evaluation tests correspondence with visibly reviewable events; synthetic trajectories separately test exact numerical detector logic.

### Unscorable intervals

Mark intervals where a human cannot judge the required event because the body is occluded or off-screen. Store `event_type=unscorable` and describe the affected detector in notes or a dedicated schema field once implemented. For detector-specific exclusions, the implemented schema should explicitly include `applies_to`; do not rely on free text in the evaluation script.

Crucially, a human-visible event missed because the pose model abstained remains a false negative in the main evaluation. Do not exclude every interval that the model could not track. Report human-unscorable time and model-unavailable time separately.

### Independent review

Where feasible, have a second annotator independently label at least a subset, preferably 20–30% of clips and a mix of easy and hard examples. Report event agreement and boundary differences before adjudication. Resolve disagreements for the final reference labels and keep the original labels. If only one annotator is available, disclose that limitation and have an experienced climber review representative cases.

## 5. Matching and quantitative metrics

Match predictions and reference events within the same clip, event class, and hand side. Use one-to-one interval matches with temporal intersection-over-union (tIoU). An initial proposed threshold is 0.30; freeze it before test evaluation. Sort candidate pairs by descending tIoU and greedily accept unmatched qualifying pairs, or use a documented maximum-weight assignment. Fix the choice for reproducibility.

`tIoU = overlap_duration / union_duration`.

Unmatched predictions are false positives; unmatched reference events are false negatives. Handle human-unscorable intervals with a fixed documented overlap rule and report how many predictions were excluded. Do not quietly remove hard, human-scorable events.

Report for each detector, and separately for left/right where useful:

- Precision = true positives / all predicted positives.
- Recall = true positives / all reference positives.
- F1, with a documented convention for empty denominators.
- Start/end boundary error for matched events.
- False positives per human-scorable minute.
- Human-scorable time, model-eligible time, and abstention rate.
- Per-clip and pooled counts; results by view condition when sample size permits.

For low movement, also report predicted/reference total durations and their difference. Do not average a clip with no predictions as if its precision were proven perfect. Use `null` for undefined quantities and display the denominator.

Include a simple baseline or ablation: compare the final detector against the same feature logic with raw, unsmoothed landmarks and no onset/offset hysteresis. Keep data and event definitions fixed. This helps show what the project's cleaning and temporal logic contribute. Report if the baseline performs similarly or better.

A pose-quality percentage is not event precision. Measured F1 is not a probability assigned to an individual event. Avoid combining different metrics into an unexplained “technique score.”

## 6. Small usability and reflection study

Aim for approximately 5–8 beginner climbers if practical. This is an exploratory study rather than proof of learning gains. Record participant experience and whether they are reviewing their own footage.

Suggested tasks:

1. Import or open an attempt and set meaningful boundaries.
2. Find one low-movement event and replay its context.
3. Explain in their own words what the app measured and what remains uncertain.
4. Judge whether the detection is correct, separately from whether it is useful.
5. Dismiss or tag an intentional movement.
6. Save one reflection and a next-attempt focus.
7. Export the review.

Record task completion, confusing controls, time to locate a moment, usefulness rating, and comments on false positives. Ask “Did any wording imply the system knew more than it could observe?” Have an experienced climber review a small set of feedback cards for unsupported interpretations.

For a comparison, use plain video and assisted review with counterbalanced task order and two comparable clips, documenting differences between clips. A simple baseline-first walkthrough is also useful for design feedback, but repeated viewing can explain apparent improvement in review performance. Do not make a causal learning claim from it.

A real climbing-improvement study would need additional attempts, defined performance outcomes, and a design addressing practice effects and route difficulty. Treat that as an extension, not a promised MVP result.

## 7. Reproducibility artifacts

Keep the following under version control, excluding private media:

- Dataset manifest and fixed split using anonymous IDs.
- Annotation guide and independent/adjudicated labels where permitted.
- Model source/checksum, dependency locks, and detector configuration.
- Evaluation script and metric definitions.
- Machine-generated metrics tables and plots linked to run IDs.
- A list of exclusions and reasons.
- A failure-case gallery with permitted images or diagrams.

Save exact commands and random seeds, if any. An analysis run records the pipeline version and configuration hash. Never invent an accuracy number to fill a report template.

## 8. Suggested final figures and report

Useful figures: one video frame with a correctly aligned skeleton; one timeline with reference versus predicted events; a tracking-coverage plot; a precision/recall table with counts; and two representative failure cases.

The report should cover problem and assignment fit, related technical components, your own feature/detector design, dataset and methods, actual results, interface feedback, limitations, and next steps. Explain how user feedback changed the implementation. Include a short demonstration on an unseen supported clip when practical.
