# Example data contracts and algorithm flow

These examples specify intended structures. Numbers and IDs are illustrative, not measured results. Implemented Pydantic and TypeScript schemas must agree; keep one documented source of truth.

## Analysis run

```json
{
  "schema_version": "1.0",
  "id": "run-example",
  "attempt_id": "attempt-example",
  "status": "complete",
  "stage": "complete",
  "pipeline_version": "record-actual-commit-or-version",
  "config_hash": "record-actual-hash",
  "timebase": "canonical_video_ms",
  "attempt_bounds_ms": {"start": 4500, "end": 46200},
  "model": {
    "name": "pose_landmarker_heavy",
    "source": "record-actual-official-source",
    "sha256": "record-actual-checksum",
    "library_version": "record-actual-version"
  },
  "coverage": {
    "low_movement": {
      "status": "available",
      "eligible_ms": 33700,
      "attempt_ms": 41700,
      "fraction": 0.8082
    },
    "wrist_motion_left": {
      "status": "available",
      "eligible_ms": 38100,
      "attempt_ms": 41700,
      "fraction": 0.9137
    }
  },
  "event_count": 8,
  "warnings": []
}
```

Coverage is an observed data-availability fraction, not event accuracy. If a detector cannot run, give it an explicit unavailable status and null derived metrics. A zero count and an unavailable count must display differently.

## Event and user review

```json
{
  "schema_version": "1.0",
  "id": "event-example",
  "analysis_run_id": "run-example",
  "type": "low_movement",
  "hand": null,
  "start_ms": 18200,
  "end_ms": 20700,
  "evidence": {
    "duration_ms": 2500,
    "max_required_joint_speed_L_per_s": 0.12,
    "configured_speed_limit_L_per_s": 0.15,
    "required_joints_valid_fraction": 1.0
  },
  "tracking_quality": {
    "label": "good",
    "method_version": "quality-rules-v1",
    "is_calibrated_event_probability": false
  },
  "feedback": {
    "template_version": "low-movement-v1",
    "observation": "Tracked wrists, ankles, and hips moved little for about 2.5 seconds.",
    "interpretation": "This may be a planned rest or a moment of route planning.",
    "reflection_question": "Was this pause intentional, and did it help the next move?"
  },
  "review": {
    "detection_judgment": "unreviewed",
    "usefulness": "unrated",
    "context_tags": [],
    "note": ""
  }
}
```

Store evidence in one place; generate the text from that evidence. Do not recalculate numbers independently in the frontend or feedback layer. Validate start/end bounds and units. Use milliseconds consistently and format human-readable timestamps only in display/report code.

## Initial configuration sketch

```yaml
analysis:
  canonical_fps: 30
  inference_fps: 10
  longest_side_px: 1280
  max_duration_s: 120
  max_upload_mb: 250
quality:
  min_visibility: 0.6
  min_presence_if_available: 0.6
  fill_missing_gaps: false
features:
  scale: robust_attempt_torso_length_pixels
  smoothing_window_s: 0.3
  speed_window_s: 0.3
low_movement:
  max_joint_speed_L_per_s: 0.15
  min_duration_s: 2.0
  max_fully_observed_interruption_s: 0.2
wrist_motion:
  onset_speed_L_per_s: 0.35
  offset_speed_L_per_s: 0.20
  offset_dwell_s: 0.25
  min_duration_s: 0.3
  min_displacement_L: 0.2
```

All values are provisional engineering settings. Decide the exact discrete-time rounding, filtering alignment, gap policy, and event boundary semantics in the implementation and tests. Do not imply these are established climbing thresholds. `max_upload_mb` should specify decimal MB or MiB in the actual validation code/UI.

## Processing flow

```text
validate/probe source
  -> canonical upright video + metadata
  -> selected attempt interval in canonical time
  -> timestamped pose observations
  -> per-landmark validity + attempt scale
  -> contiguous valid feature segments
  -> detector-specific eligible-time masks
  -> structured event intervals + evidence
  -> deterministic feedback templates
  -> synchronized review + separate user judgments
  -> reproducible export/evaluation
```

## Job lifecycle

```text
queued -> running -> complete
                  -> failed
                  -> cancelled
running + process interruption -> interrupted -> explicit retry as a new run
queued + cancel request -> cancelled
```

Detailed stage lives separately from lifecycle status, for example `status=running, stage=extracting_pose`. Progress reflects processed units, and stage changes do not pretend that inference runtime is predictable. Worker job claiming is atomic; only one process owns a job. Cleanup and state transitions run on error paths as well as success.

Changing attempt bounds or detector configuration creates a new analysis run. Review annotations remain associated with their original event IDs. A restart does not silently label a partially produced run complete.

## Hold-detection research extension

If core evaluation is complete and automatic holds remain a goal:

1. Separate hold localization, route membership, and hold-type classification as different tasks.
2. Build or obtain appropriately permitted wall images with the necessary box/mask and route/type labels. Unknown type is a legitimate label when an image does not establish it.
3. Verify the selected detector's supported labels. Do not assume a general pretrained object detector already recognizes climbing holds.
4. Fine-tune or adapt only with adequate labeled training examples; retain manual corrections in the interface.
5. Split evaluation by recording/wall/route as appropriate, not adjacent frames from one video.
6. Measure localization and classification separately, and report failure conditions. Route color can assist selection but is not a universal guarantee of route membership.
7. Keep this extension's metrics separate from the movement-event evaluation. A plausible-looking annotation is not a validated hold classifier.

This extension is intentionally outside the required MVP and should not delay the independently evaluated movement analysis.
