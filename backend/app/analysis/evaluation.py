"""Reproducible comparison of detector output with independent human labels.

Matching (docs/EVALUATION.md section 5): within a clip, event class, and hand, candidate
pairs are sorted by descending tIoU and greedily accepted one-to-one at or above the
threshold. Unmatched predictions are false positives; unmatched references are false
negatives. Undefined quantities are None, never a substituted value.

A human-visible event missed because the pose model abstained remains a false negative.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import ClimbReviewError

EVENT_KEYS = ("low_movement", "wrist_motion_left", "wrist_motion_right", "foot_motion_left", "foot_motion_right")
SIDED_TYPES = {"wrist_motion", "foot_motion"}
ANNOTATION_TYPES = {"low_movement", "wrist_motion", "foot_motion", "unscorable"}
VALID_SPLITS = {"dev", "test"}
UNSCORABLE_OVERLAP_FRACTION = 0.5


@dataclass(frozen=True)
class Interval:
    clip_id: str
    key: str
    start_ms: int
    end_ms: int

    @property
    def duration(self) -> int:
        return self.end_ms - self.start_ms


def tiou(a: Interval, b: Interval) -> float:
    overlap = max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))
    union = a.duration + b.duration - overlap
    return overlap / union if union else 0.0


def match_events(
    predictions: Sequence[Interval], references: Sequence[Interval], threshold: float,
) -> list[tuple[Interval, Interval, float]]:
    """One-to-one greedy matching by descending tIoU; ties resolve by start times."""
    candidates = [(tiou(p, r), i, j) for i, p in enumerate(predictions) for j, r in enumerate(references)]
    candidates = [c for c in candidates if c[0] >= threshold and c[0] > 0]
    candidates.sort(key=lambda c: (-c[0], predictions[c[1]].start_ms, references[c[2]].start_ms, c[1], c[2]))
    used_predictions, used_references, matches = set(), set(), []
    for score, i, j in candidates:
        if i not in used_predictions and j not in used_references:
            used_predictions.add(i)
            used_references.add(j)
            matches.append((predictions[i], references[j], score))
    return matches


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def f1_score(precision: float | None, recall: float | None) -> float | None:
    """Undefined if either input is undefined; 0 only when both are defined and sum to 0."""
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _key(kind: str, hand: str | None) -> str:
    return "low_movement" if kind == "low_movement" else f"{kind}_{hand}"


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"clip_id", "climber_id", "route_id", "view", "split", "run_dir", "video_duration_ms"}
    if rows and required - set(rows[0]):
        raise ClimbReviewError(f"Manifest lacks columns: {sorted(required - set(rows[0]))}")
    seen: set[str] = set()
    climbers: dict[str, str] = {}
    for row in rows:
        if row["split"] not in VALID_SPLITS:
            raise ClimbReviewError(f"{row['clip_id']}: split must be one of {sorted(VALID_SPLITS)}")
        if row["clip_id"] in seen:
            raise ClimbReviewError(f"Duplicate clip_id: {row['clip_id']}")
        seen.add(row["clip_id"])
        if climbers.setdefault(row["climber_id"], row["split"]) != row["split"]:
            raise ClimbReviewError(f"Climber {row['climber_id']} appears in both splits.")
    return rows


def load_annotations(path: Path, durations: dict[str, int]) -> list[dict[str, Any]]:
    """Validate human labels. Any invalid row stops the evaluation rather than being dropped."""
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"clip_id", "event_type", "hand", "start_ms", "end_ms", "annotator_id"}
    if rows and required - set(rows[0]):
        raise ClimbReviewError(f"Annotations lack columns: {sorted(required - set(rows[0]))}")
    labels: list[dict[str, Any]] = []
    for number, row in enumerate(rows, start=2):
        where = f"annotations line {number}"
        if row["clip_id"] not in durations:
            raise ClimbReviewError(f"{where}: unknown clip_id {row['clip_id']}")
        if row["event_type"] not in ANNOTATION_TYPES:
            raise ClimbReviewError(f"{where}: unknown event_type {row['event_type']}")
        hand = (row.get("hand") or "").strip().lower() or None
        if row["event_type"] in SIDED_TYPES and hand not in {"left", "right"}:
            raise ClimbReviewError(f"{where}: {row['event_type']} needs hand left or right (the body side)")
        try:
            start, end = int(row["start_ms"]), int(row["end_ms"])
        except ValueError as error:
            raise ClimbReviewError(f"{where}: start_ms and end_ms must be integers") from error
        if not 0 <= start < end <= durations[row["clip_id"]]:
            raise ClimbReviewError(f"{where}: need 0 <= start_ms < end_ms <= clip duration")
        applies = (row.get("applies_to") or "").strip()
        if row["event_type"] == "unscorable" and not applies:
            raise ClimbReviewError(f"{where}: unscorable rows need applies_to (detector keys separated by ';' or 'all')")
        labels.append({"clip_id": row["clip_id"], "event_type": row["event_type"], "hand": hand, "start_ms": start,
                       "end_ms": end, "annotator_id": row["annotator_id"], "applies_to": applies})
    return labels


def _excluded(prediction: Interval, unscorable: Iterable[dict[str, Any]]) -> bool:
    """A prediction is excluded when at least half of it lies in a human-unscorable interval."""
    spans = sorted((max(prediction.start_ms, label["start_ms"]), min(prediction.end_ms, label["end_ms"])) for label in unscorable
                   if label["clip_id"] == prediction.clip_id
                   and ({"all", prediction.key} & {k.strip() for k in label["applies_to"].split(";")}))
    overlap, cursor = 0, prediction.start_ms
    for start, end in spans:                 # a union: overlapping rows count once
        start = max(start, cursor)
        if end > start:
            overlap += end - start
            cursor = end
    return overlap >= UNSCORABLE_OVERLAP_FRACTION * prediction.duration


def _scorable_ms(clip_id: str, key: str, duration: int, unscorable: Iterable[dict[str, Any]]) -> int:
    spans = sorted((u["start_ms"], u["end_ms"]) for u in unscorable if u["clip_id"] == clip_id and
                   ({"all", key} & {k.strip() for k in u["applies_to"].split(";")}))
    excluded, cursor = 0, 0
    for start, end in spans:
        start = max(start, cursor)
        if end > start:
            excluded += end - start
            cursor = end
    return duration - excluded


def score_group(
    predictions: Sequence[Interval], references: Sequence[Interval], threshold: float, scorable_ms: int,
    excluded: int,
) -> dict[str, Any]:
    matches = match_events(predictions, references, threshold)
    tp, fp, fn = len(matches), len(predictions) - len(matches), len(references) - len(matches)
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    start_errors = [abs(p.start_ms - r.start_ms) for p, r, _ in matches]
    end_errors = [abs(p.end_ms - r.end_ms) for p, r, _ in matches]
    return {
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "predicted": len(predictions), "reference": len(references),
        "precision": precision, "recall": recall, "f1": f1_score(precision, recall),
        "mean_start_error_ms": safe_ratio(sum(start_errors), len(start_errors)),
        "mean_end_error_ms": safe_ratio(sum(end_errors), len(end_errors)),
        "false_positives_per_scorable_min": safe_ratio(fp, scorable_ms / 60_000),
        "scorable_ms": scorable_ms, "predictions_excluded_by_unscorable": excluded,
        "predicted_total_ms": sum(p.duration for p in predictions),
        "reference_total_ms": sum(r.duration for r in references),
    }


def load_predictions(run_dir: Path, events_file: str = "events.json") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events = json.loads((run_dir / events_file).read_text())
    return events["events"], events["detectors"]


def select_reference(
    annotations: list[dict[str, Any]], clip_ids: Sequence[str], reference_annotator: str | None,
) -> list[dict[str, Any]]:
    """One reference per clip. Several raters' rows are never pooled, since duplicates would count as misses.

    The original rows are not changed; this only chooses which ones to score against.
    """
    raters: dict[str, set[str]] = {clip: set() for clip in clip_ids}
    for label in annotations:
        if label["clip_id"] in raters:
            raters[label["clip_id"]].add(label["annotator_id"])
    if reference_annotator is None:
        ambiguous = {clip: sorted(names) for clip, names in raters.items() if len(names) > 1}
        if ambiguous:
            listing = "; ".join(f"{clip}: {', '.join(names)}" for clip, names in sorted(ambiguous.items()))
            raise ClimbReviewError(
                f"More than one rater labeled the same clip ({listing}). Pooling them would count duplicate labels as misses. "
                "Pass --reference-annotator with one rater, or with an adjudicated annotator_id such as 'adjudicated' whose rows "
                "are one agreed reference. Keep each rater's original rows.")
        return annotations
    missing = sorted(clip for clip, names in raters.items() if names and reference_annotator not in names)
    if missing:
        raise ClimbReviewError(f"Reference annotator '{reference_annotator}' has no rows for clips labeled by others: {', '.join(missing)}.")
    return [label for label in annotations if label["annotator_id"] == reference_annotator or label["clip_id"] not in raters]


def evaluate(
    manifest: list[dict[str, str]], annotations: list[dict[str, Any]], split: str, threshold: float, root: Path,
    events_file: str = "events.json", reference_annotator: str | None = None,
) -> dict[str, Any]:
    """Pooled and per-clip metrics for one split. Refuses a split with no clips or an ambiguous reference."""
    clips = [row for row in manifest if row["split"] == split]
    if not clips:
        raise ClimbReviewError(f"No clips in split '{split}'.")
    annotations = select_reference(annotations, [c["clip_id"] for c in clips], reference_annotator)
    unscorable = [a for a in annotations if a["event_type"] == "unscorable"]
    per_clip: list[dict[str, Any]] = []
    pooled: dict[str, dict[str, Any]] = {
        k: {"predictions": [], "references": [], "scorable": 0, "excluded": 0, "unavailable_clips": 0, "not_in_run_clips": 0}
        for k in EVENT_KEYS
    }
    for clip in clips:
        clip_id = clip["clip_id"]
        duration = int(clip["video_duration_ms"])
        events, detector_state = load_predictions(root / clip["run_dir"], events_file)
        references = [a for a in annotations if a["clip_id"] == clip_id and a["event_type"] != "unscorable"]
        for key in EVENT_KEYS:
            if key not in detector_state or detector_state[key]["status"] == "not_run":
                # A run made before this detector existed cannot miss anything; its references must not count as misses.
                pooled[key]["not_in_run_clips"] += 1
                per_clip.append({"clip_id": clip_id, "detector": key, "detector_status": "not_in_this_run"})
                continue
            all_predictions = [Interval(clip_id, key, e["start_ms"], e["end_ms"]) for e in events
                               if _key(e["type"], e["hand"]) == key]
            kept = [p for p in all_predictions if not _excluded(p, unscorable)]
            refs = [Interval(clip_id, key, a["start_ms"], a["end_ms"]) for a in references
                    if _key(a["event_type"], a["hand"]) == key]
            scorable = _scorable_ms(clip_id, key, duration, unscorable)
            excluded = len(all_predictions) - len(kept)
            status = detector_state[key]["status"]
            pooled[key]["predictions"] += kept
            pooled[key]["references"] += refs
            pooled[key]["scorable"] += scorable
            pooled[key]["excluded"] += excluded
            pooled[key]["unavailable_clips"] += status != "available"
            per_clip.append({"clip_id": clip_id, "detector": key, "detector_status": status,
                             **score_group(kept, refs, threshold, scorable, excluded)})
    results = {}
    for key, group in pooled.items():
        score = score_group(group["predictions"], group["references"], threshold, group["scorable"], group["excluded"])
        results[key] = {**score, "clips_with_detector_unavailable": group["unavailable_clips"],
                        "clips_analyzed_before_detector_existed": group["not_in_run_clips"]}
    return {
        "split": split, "tiou_threshold": threshold, "events_file": events_file, "clips": [c["clip_id"] for c in clips],
        "annotators": sorted({a["annotator_id"] for a in annotations if a["clip_id"] in {c["clip_id"] for c in clips}}),
        "reference_annotator": reference_annotator,
        "pooled": results, "per_clip": per_clip,
        "note": "Human labels are a reference standard. Coverage and F1 are not probabilities for individual events.",
    }
