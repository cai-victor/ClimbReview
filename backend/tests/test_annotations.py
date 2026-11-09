"""Reference annotations, using deliberately labeled synthetic fixture intervals only."""
from __future__ import annotations

import csv
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analysis import evaluation as ev
from app.main import create_app
from app.settings import Settings, load_pipeline_config
from app.worker import Worker
from conftest import encode_frames


@pytest.fixture()
def env(tmp_path):
    settings = Settings(tmp_path / "appdata")
    client = TestClient(create_app(settings))
    rng = np.random.default_rng(1)
    clip = encode_frames([rng.integers(0, 40, (240, 320, 3), np.uint8) for _ in range(300)], tmp_path / "n.mp4")
    with clip.open("rb") as handle:
        attempt = client.post("/api/attempts", files={"file": ("c.mp4", handle, "video/mp4")}).json()
    Worker(settings, load_pipeline_config()).process_one()
    return settings, client, attempt["id"]


LOW = {"event_type": "low_movement", "start_ms": 1000, "end_ms": 4000, "notes": "fixture"}
WRIST = {"event_type": "wrist_motion", "hand": "left", "start_ms": 5000, "end_ms": 5400}
UNSCORABLE = {"event_type": "unscorable", "start_ms": 6000, "end_ms": 7000, "applies_to": ["low_movement", "wrist_motion_left"]}


def new_set(client, attempt_id, alias="fixture_rater", **extra):
    return client.post(f"/api/attempts/{attempt_id}/annotation-sets",
                       json={"rater_alias": alias, "clip_id": "clip_a", "climber_id": "c1", "route_id": "r1", "split": "dev",
                             "synthetic_test_fixture": True, **extra})


def test_create_edit_delete_reload_and_export_matches_evaluation_schema(env, tmp_path):
    settings, client, attempt_id = env
    created = new_set(client, attempt_id).json()
    assert created["kind"] == "synthetic_test_fixture" and created["timebase"] == "canonical_video_ms"
    sid = created["id"]
    for body in (LOW, WRIST, UNSCORABLE):
        assert client.post(f"/api/annotation-sets/{sid}/intervals", json=body).status_code == 201
    state = client.get(f"/api/annotation-sets/{sid}").json()
    first = state["intervals"][0]
    assert client.put(f"/api/annotation-sets/{sid}/intervals/{first['id']}", json={**LOW, "end_ms": 4500}).status_code == 200
    added = client.post(f"/api/annotation-sets/{sid}/intervals", json={**WRIST, "hand": "right"}).json()["intervals"]
    extra = next(i for i in added if i["hand"] == "right")
    assert client.delete(f"/api/annotation-sets/{sid}/intervals/{extra['id']}").status_code == 200

    restarted = TestClient(create_app(settings))
    saved = restarted.get(f"/api/annotation-sets/{sid}").json()["intervals"]
    assert [(i["event_type"], i["hand"], i["start_ms"], i["end_ms"]) for i in saved] == [
        ("low_movement", None, 1000, 4500), ("wrist_motion", "left", 5000, 5400), ("unscorable", None, 6000, 7000)]

    text = restarted.get(f"/api/annotation-sets/{sid}/export?format=csv").text
    path = tmp_path / "exported.csv"
    path.write_text(text)
    labels = ev.load_annotations(path, {"clip_a": 10_000})  # the real evaluation schema validator
    assert len(labels) == 3 and labels[0]["annotator_id"] == "fixture_rater"
    assert labels[2]["applies_to"] == "low_movement;wrist_motion_left"
    exported = restarted.get(f"/api/annotation-sets/{sid}/export?format=json").json()
    assert exported["kind"] == "synthetic_test_fixture" and exported["intervals"]


@pytest.mark.parametrize("body,fragment", [
    ({"event_type": "wrist_motion", "start_ms": 0, "end_ms": 500}, "left or right"),
    ({"event_type": "low_movement", "hand": "left", "start_ms": 0, "end_ms": 3000}, "Only wrist"),
    ({"event_type": "low_movement", "start_ms": 0, "end_ms": 1000}, "at least 2"),
    ({"event_type": "wrist_motion", "hand": "left", "start_ms": 0, "end_ms": 200}, "at least 0.3"),
    ({"event_type": "low_movement", "start_ms": 0, "end_ms": 99_000}, "video duration"),
    ({"event_type": "unscorable", "start_ms": 0, "end_ms": 500}, "detectors"),
    ({"event_type": "unscorable", "start_ms": 0, "end_ms": 500, "applies_to": ["all", "low_movement"]}, "detectors"),
    ({"event_type": "low_movement", "start_ms": 0, "end_ms": 3000, "applies_to": ["all"]}, "Only unscorable"),
])
def test_class_side_and_bounds_constraints(env, body, fragment):
    _, client, attempt_id = env
    sid = new_set(client, attempt_id).json()["id"]
    response = client.post(f"/api/annotation-sets/{sid}/intervals", json=body)
    assert response.status_code == 422 and fragment in response.json()["detail"]


def test_raters_stay_separate_and_list_hides_intervals(env):
    _, client, attempt_id = env
    a = new_set(client, attempt_id, "rater_a").json()["id"]
    b = new_set(client, attempt_id, "rater_b").json()["id"]
    client.post(f"/api/annotation-sets/{a}/intervals", json=LOW)
    assert client.get(f"/api/annotation-sets/{b}").json()["intervals"] == []
    listing = client.get(f"/api/attempts/{attempt_id}/annotation-sets").json()
    assert {r["rater_alias"]: r["interval_count"] for r in listing} == {"rater_a": 1, "rater_b": 0}
    assert all("intervals" not in r for r in listing)
    assert new_set(client, attempt_id, "rater_a").status_code == 409


def test_synthetic_sets_are_excluded_from_the_attempt_export(env):
    _, client, attempt_id = env
    fixture = new_set(client, attempt_id, "fixture").json()["id"]
    real = new_set(client, attempt_id, "person_a", synthetic_test_fixture=False).json()["id"]
    client.post(f"/api/annotation-sets/{fixture}/intervals", json=LOW)
    client.post(f"/api/annotation-sets/{real}/intervals", json=WRIST)
    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/attempts/{attempt_id}/annotations/export").text)))
    assert [r["annotator_id"] for r in rows] == ["person_a"]


@pytest.mark.parametrize("alias", ["Jane Smith", "", "a" * 33, "a/b"])
def test_identifying_or_unsafe_aliases_rejected(env, alias):
    _, client, attempt_id = env
    assert new_set(client, attempt_id, alias).status_code == 422


def test_deleting_attempt_removes_annotations(env):
    settings, client, attempt_id = env
    sid = new_set(client, attempt_id).json()["id"]
    client.post(f"/api/annotation-sets/{sid}/intervals", json=LOW)
    assert client.delete(f"/api/attempts/{attempt_id}").status_code == 204
    assert client.get(f"/api/annotation-sets/{sid}").status_code == 404
