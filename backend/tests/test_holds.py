"""Manual hold regions: identity, bounds, persistence, and reference-frame extraction."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings, load_pipeline_config
from app.worker import Worker
from conftest import assert_quadrants, encode_frames, quadrant_frame, tag_rotation


def setup_clip(tmp_path, source):
    settings = Settings(tmp_path / "appdata")
    client = TestClient(create_app(settings))
    with source.open("rb") as handle:
        attempt = client.post("/api/attempts", files={"file": ("c.mp4", handle, "video/mp4")}).json()
    Worker(settings, load_pipeline_config()).process_one()
    return settings, client, attempt["id"]


@pytest.fixture()
def env(tmp_path):
    return setup_clip(tmp_path, encode_frames([quadrant_frame(640, 360)] * 60, tmp_path / "landscape.mp4"))


def test_map_records_frame_and_video_identity_and_persists(env, tmp_path):
    settings, client, attempt_id = env
    created = client.post(f"/api/attempts/{attempt_id}/hold-maps", json={"name": "Blue", "reference_frame_ms": 510}).json()
    assert created["frame_index"] == 15 and created["reference_frame_ms"] == 500
    assert (created["width"], created["height"]) == (640, 360) and len(created["canonical_sha256"]) == 64
    assert "reference frame only" in created["scope_note"]
    mid = created["id"]
    added = client.post(f"/api/hold-maps/{mid}/holds", json={"x": 0.25, "y": 0.75, "radius": 0.05, "route": "blue", "hold_type": "user: jug"}).json()
    hold = added["holds"][0]
    edited = client.put(f"/api/hold-maps/{mid}/holds/{hold['id']}", json={"x": 0.3, "y": 0.75, "radius": 0.07, "route": "blue"}).json()
    assert edited["holds"][0]["x"] == 0.3 and edited["holds"][0]["hold_type"] == ""
    restarted = TestClient(create_app(settings))
    assert restarted.get(f"/api/hold-maps/{mid}").json()["holds"][0]["radius"] == 0.07
    exported = restarted.get(f"/api/hold-maps/{mid}/export").json()
    assert exported["canonical_sha256"] == created["canonical_sha256"] and exported["holds"]
    assert restarted.delete(f"/api/hold-maps/{mid}/holds/{hold['id']}").json()["holds"] == []


@pytest.mark.parametrize("body", [{"x": 1.2, "y": 0.5, "radius": 0.1}, {"x": 0.5, "y": -0.1, "radius": 0.1},
                                  {"x": 0.5, "y": 0.5, "radius": 0}, {"x": 0.5, "y": 0.5, "radius": 0.9}])
def test_invalid_regions_rejected(env, body):
    _, client, attempt_id = env
    mid = client.post(f"/api/attempts/{attempt_id}/hold-maps", json={"name": "A", "reference_frame_ms": 0}).json()["id"]
    assert client.post(f"/api/hold-maps/{mid}/holds", json=body).status_code == 422


def test_reference_outside_video_rejected(env):
    _, client, attempt_id = env
    assert client.post(f"/api/attempts/{attempt_id}/hold-maps", json={"name": "A", "reference_frame_ms": 99_999}).status_code == 422
    assert client.get(f"/api/attempts/{attempt_id}/frame?ms=99999").status_code == 422


def _decode(content):
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)


def test_reference_frame_is_upright_canonical_pixels(tmp_path):
    stored = np.rot90(quadrant_frame(360, 640), k=1).copy()
    tagged = tag_rotation(encode_frames([stored] * 30, tmp_path / "stored.mp4"), tmp_path / "portrait.mp4", -90)
    _, client, attempt_id = setup_clip(tmp_path, tagged)
    image = _decode(client.get(f"/api/attempts/{attempt_id}/frame?ms=500").content)
    assert image.shape[:2] == (640, 360)
    assert_quadrants(image, tolerance=45)


def test_deleting_attempt_removes_maps_and_frames(env):
    settings, client, attempt_id = env
    mid = client.post(f"/api/attempts/{attempt_id}/hold-maps", json={"name": "A", "reference_frame_ms": 0}).json()["id"]
    client.get(f"/api/attempts/{attempt_id}/frame?ms=0")
    assert client.delete(f"/api/attempts/{attempt_id}").status_code == 204
    assert client.get(f"/api/hold-maps/{mid}").status_code == 404
    assert not settings.attempt_dir(attempt_id).exists()
