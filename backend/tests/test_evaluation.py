"""Metric and schema tests for the evaluation tool, on hand-computed cases."""
from __future__ import annotations

import csv
import json

import pytest

from app.analysis import ClimbReviewError
from app.analysis import evaluation as ev


def iv(start, end, clip="c1", key="low_movement"):
    return ev.Interval(clip, key, start, end)


def test_tiou_values():
    assert ev.tiou(iv(0, 100), iv(0, 100)) == 1
    assert ev.tiou(iv(0, 100), iv(50, 150)) == pytest.approx(50 / 150)
    assert ev.tiou(iv(0, 100), iv(100, 200)) == 0


def test_matching_is_one_to_one_and_prefers_highest_overlap():
    predictions = [iv(0, 100), iv(10, 110)]
    references = [iv(10, 110)]
    matches = ev.match_events(predictions, references, 0.3)
    assert len(matches) == 1 and matches[0][0] == predictions[1]


def test_threshold_is_inclusive():
    predictions, references = [iv(0, 130)], [iv(100, 200)]  # overlap 30, union 200 -> 0.15
    assert ev.match_events(predictions, references, 0.15) != []
    assert ev.match_events(predictions, references, 0.16) == []


def test_metrics_counts_and_undefined_values():
    score = ev.score_group([iv(0, 100), iv(500, 600)], [iv(0, 100), iv(900, 1000)], 0.3, 60_000, 0)
    assert (score["true_positives"], score["false_positives"], score["false_negatives"]) == (1, 1, 1)
    assert score["precision"] == 0.5 and score["recall"] == 0.5 and score["f1"] == 0.5
    assert score["false_positives_per_scorable_min"] == 1.0
    empty = ev.score_group([], [], 0.3, 60_000, 0)
    assert empty["precision"] is None and empty["recall"] is None and empty["f1"] is None
    no_predictions = ev.score_group([], [iv(0, 100)], 0.3, 60_000, 0)
    assert no_predictions["precision"] is None and no_predictions["recall"] == 0 and no_predictions["f1"] is None


def _write(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _manifest(path, climber2="c2"):
    _write(path, [
        {"clip_id": "a", "climber_id": "c1", "route_id": "r1", "view": "back", "split": "dev", "run_dir": "runs/a", "video_duration_ms": "60000"},
        {"clip_id": "b", "climber_id": climber2, "route_id": "r2", "view": "back", "split": "test", "run_dir": "runs/b", "video_duration_ms": "60000"},
    ])


ROW = {"clip_id": "a", "event_type": "low_movement", "hand": "", "start_ms": "1000", "end_ms": "4000", "annotator_id": "h1", "applies_to": ""}


def test_manifest_rejects_a_climber_in_both_splits(tmp_path):
    _manifest(tmp_path / "m.csv", climber2="c1")
    with pytest.raises(ClimbReviewError, match="both splits"):
        ev.load_manifest(tmp_path / "m.csv")


@pytest.mark.parametrize("change,message", [
    ({"clip_id": "zzz"}, "unknown clip_id"), ({"event_type": "fatigue"}, "unknown event_type"),
    ({"event_type": "wrist_motion"}, "needs hand"), ({"start_ms": "5000"}, "start_ms"),
    ({"end_ms": "70000"}, "start_ms"), ({"end_ms": "4x"}, "integers"),
    ({"event_type": "unscorable"}, "applies_to"),
])
def test_annotation_schema_rejects_bad_rows(tmp_path, change, message):
    path = tmp_path / "a.csv"
    _write(path, [{**ROW, **change}])
    with pytest.raises(ClimbReviewError, match=message):
        ev.load_annotations(path, {"a": 60_000})


def _run(tmp_path, clip, events, detectors=None):
    directory = tmp_path / "runs" / clip
    directory.mkdir(parents=True)
    states = detectors or {k: {"status": "available", "event_count": 0} for k in ev.EVENT_KEYS}
    (directory / "events.json").write_text(json.dumps({"events": events, "detectors": states}))


def event(start, end, kind="low_movement", hand=None):
    return {"type": kind, "hand": hand, "start_ms": start, "end_ms": end}


def test_evaluate_counts_abstention_as_a_miss_and_handles_unscorable(tmp_path):
    _manifest(tmp_path / "m.csv")
    manifest = ev.load_manifest(tmp_path / "m.csv")
    states = {k: {"status": "insufficient_tracking", "event_count": None} for k in ev.EVENT_KEYS}
    _run(tmp_path, "a", [event(50_000, 55_000)], states)
    _run(tmp_path, "b", [])
    labels = [
        {"clip_id": "a", "event_type": "low_movement", "hand": None, "start_ms": 1000, "end_ms": 4000, "annotator_id": "h1", "applies_to": ""},
        {"clip_id": "a", "event_type": "unscorable", "hand": None, "start_ms": 49_000, "end_ms": 56_000, "annotator_id": "h1", "applies_to": "all"},
    ]
    result = ev.evaluate(manifest, labels, "dev", 0.3, tmp_path)
    low = result["pooled"]["low_movement"]
    assert low["false_negatives"] == 1 and low["predicted"] == 0            # human event missed by abstention
    assert low["predictions_excluded_by_unscorable"] == 1 and low["false_positives"] == 0
    assert low["clips_with_detector_unavailable"] == 1
    assert low["scorable_ms"] == 60_000 - 7_000
    assert result["clips"] == ["a"]                                         # the test clip was not read


def test_empty_split_is_an_error(tmp_path):
    _manifest(tmp_path / "m.csv")
    manifest = [row for row in ev.load_manifest(tmp_path / "m.csv") if row["split"] == "dev"]
    with pytest.raises(ClimbReviewError, match="No clips"):
        ev.evaluate(manifest, [], "test", 0.3, tmp_path)
