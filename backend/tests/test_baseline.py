"""The baseline runner must really change only temporal logic and must not report accuracy."""
from __future__ import annotations

import json

from app.analysis import baseline as b
from app.analysis import detectors as d
from app.analysis import pose as pose_module
from app.analysis import quality as q
from conftest import no_pose_record
from test_detectors import HEIGHT, WIDTH, build


def slowdown_move(t):
    if t < 1.0:
        return 0.0, 0.0
    if t < 1.8:
        return 1.0 * (t - 1.0), 0.0
    if t < 2.0:
        return 0.8 + 0.1 * (t - 1.8), 0.0
    if t < 2.8:
        return 0.82 + 1.0 * (t - 2.0), 0.0
    return 1.62, 0.0


def make_run(root, config, records, clip="clip_x"):
    directory = root / clip
    directory.mkdir(parents=True)
    pose_module.write_jsonl(records, directory / "poses.jsonl")
    end = records[-1]["timestamp_ms"] + 100
    validity = q.derive_validity(records, WIDTH, HEIGHT, config.quality, 100.0)
    coverage = q.compute_coverage(records, WIDTH, HEIGHT, 0, end, config.quality, 100.0, 0.7, validity)
    stored = d.run_detectors(records, validity, WIDTH, HEIGHT, coverage, config)
    (directory / "events.json").write_text(json.dumps(stored))
    (directory / "run.json").write_text(json.dumps({
        "clip_id": clip, "data_provenance": "synthetic_test_media", "config": config.model_dump(),
        "canonical": {"width": WIDTH, "height": HEIGHT}, "attempt_bounds_ms": {"start": 0, "end": end},
    }))
    return directory


def test_baseline_differs_only_in_temporal_logic(tmp_path, config):
    run = make_run(tmp_path, config, build(50, {"left_wrist": slowdown_move}))
    comparison, baseline = b.compare_run(run)
    left = comparison["detectors"]["wrist_motion_left"]
    assert left["final"]["event_count"] == 1
    assert left["baseline_raw"]["event_count"] >= 2
    assert comparison["stored_events_reproduced"] is True
    assert baseline["flags"] == {"smoothing": False, "hysteresis": False}
    assert left["agreement"]["final_only"] + left["agreement"]["matched"] == 1


def test_output_is_versioned_deterministic_and_has_no_accuracy_fields(tmp_path, config):
    run = make_run(tmp_path, config, build(50, {"left_wrist": slowdown_move}))
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    report = b.write_comparison([run], first)
    b.write_comparison([run], second)
    assert first.read_bytes() == second.read_bytes()
    assert report["comparison_version"] == b.COMPARISON_VERSION and report["detector_version"]
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    assert not {"precision", "recall", "f1", "accuracy"} & set(keys(json.loads(first.read_text())))
    saved = json.loads((run / b.BASELINE_EVENTS_FILE).read_text())
    assert saved["variant"] == "baseline_raw" and "detectors" in saved


def test_unavailable_detector_stays_null(tmp_path, config):
    records = [no_pose_record(i * 3, i * 100) for i in range(30)]
    comparison, _ = b.compare_run(make_run(tmp_path, config, records))
    item = comparison["detectors"]["low_movement"]
    assert item["final"]["event_count"] is None and item["baseline_raw"]["event_count"] is None
    assert item["agreement"] is None


def test_changed_stored_events_are_flagged(tmp_path, config):
    run = make_run(tmp_path, config, build(40))
    stored = json.loads((run / "events.json").read_text())
    stored["events"][0]["end_ms"] += 500
    (run / "events.json").write_text(json.dumps(stored))
    assert b.compare_run(run)[0]["stored_events_reproduced"] is False
