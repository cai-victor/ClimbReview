# Editable assignment proposal

## Title

ClimbReview: Explainable Video Analytics for Beginner Bouldering Reflection

## Overview

Beginner indoor boulderers may find it difficult to identify which moments of an attempt deserve closer review. We propose a video-based analytics application that tracks body movement and highlights selected observable events with timestamps, visual overlays, and reflection prompts.

The project aligns primarily with the final assignment's third pathway: using data analytics to model sports behavior or performance. Its central contribution will be the design and evaluation of an explainable movement-analysis pipeline, supported by an interactive review experience.

## Research question

How accurately can a video-based pipeline identify low-movement intervals and visible wrist-movement episodes during beginner indoor bouldering, and how useful are those events for reviewing an attempt?

## Proposed system

A climber will import a recording and mark the beginning and end of an attempt. A pretrained pose-estimation model will extract body landmarks. We will develop algorithms that clean and normalize those measurements, track missing data, and identify two defined classes of movement events. The application will display synchronized video and body overlays, an event timeline, evidence-based explanations, and a place for the climber to record interpretations and future practice goals.

The system will distinguish observations from interpretations. A period of low movement may reflect a planned rest or route planning; it will not automatically be labeled a mistake. Uncertain tracking will be visible, and the system will abstain when the required measurements are unavailable.

## Technical approach

The planned implementation uses a React/TypeScript interface and a Python analysis service, with a pretrained pose model, explicit temporal features, and rule-based event detectors. The first milestone will test the model on representative climbing recordings. The core version will run locally and will not require a paid language-model API.

Manual route-hold marking on a reference frame has been implemented as an extension; the core system still awaits independent validation. Automatic hold detection, hold-type classification, and technique diagnoses are stretch goals requiring additional data and evaluation.

## Data and evaluation

We will assemble a small dataset of recorded attempts, create independent timestamped reference labels, and divide the recordings into development and held-out test groups, preferably by climber. We will evaluate event precision, recall, timing error, and tracking coverage. A small user study will assess whether beginner climbers can understand and use the review interface. We will report limitations and will not claim improved climbing performance without measuring it.

## Expected deliverables

A working video-review prototype; an explainable and versioned analysis pipeline; an annotation guide and evaluation results; a documented demonstration; and a final report discussing design decisions, user feedback, and limitations.

## Current implementation status (November 2026)

| Component | Kind | State |
| --- | --- | --- |
| Pose landmarks | Pretrained MediaPipe model, weights frozen | Running on real clips; alignment inspected on samples only |
| Low-movement and wrist events | Rule-based, written for this project | Implemented; thresholds unvalidated; accuracy not yet measured |
| Wrist-motion forecast | Learned Ridge model on public clips, self-supervised | Experimental; only marginally better than predicting no movement. See `docs/TRAINING_REPORT.md` |
| Independent evaluation | Human reference labels | Tooling complete; labels and user study still pending |
| Manual holds | Extension | Implemented for one reference frame; no hold detection or contact claims |
| Camera compensation | Experimental study | Development clips only; off by default; unvalidated |
| Feasibility on recorded clips | Provisional gate | Not met on handheld phone clips; tripod footage needed |

## Team and experience

Fill in team members, relevant experience, available equipment, actual deadline, and scope. For one student, the two event detectors and a modest evaluation form the core. For a larger team, broaden independent annotation, user testing, or the evaluated manual-hold extension rather than only adding interface features.

## Suggested four-submission progression

The assignment excerpt mentions four submissions but does not give their individual instructions. The following is a proposed progression to reconcile with the actual rubrics, not a statement of course requirements.

| Submission | Proposed contents | Concrete evidence |
| --- | --- | --- |
| 1: proposal | Problem, users, pathway 3 alignment, research question, scope, roles | This revised proposal and initial recording examples |
| 2: design and feasibility | User flow, architecture, event definitions, pose feasibility, data/evaluation plan | Real diagnostic overlays, coverage notes, wireframes, documented failures |
| 3: prototype and preliminary evaluation | Functional end-to-end review, development-set results, feedback-driven revisions | Working import-to-review demo, independent labels, preliminary metrics, issue log |
| 4: final project | Final system, frozen method, held-out results, limitations, reflection | Reproducible code, report/presentation, demonstration, actual evaluation artifacts |

The youth-learning pathway is not the basis for this proposal: the current target users are beginner climbers of unspecified age. Reflection supports the design but does not by itself establish a youth learning experience.
