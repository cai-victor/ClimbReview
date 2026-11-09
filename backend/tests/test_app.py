"""API and worker behavior with real media, real storage, and the real pose model."""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.settings import InvalidIdError, Settings, load_pipeline_config
from app.worker import Worker
from conftest import PROJECT_ROOT, encode_frames

POSE_IMAGE = PROJECT_ROOT / "data" / "test_assets" / "pose.jpg"


@pytest.fixture()
def env(tmp_path):
    settings = Settings(tmp_path / "appdata")
    client = TestClient(create_app(settings))
    return settings, client, Worker(settings, load_pipeline_config())


def noise_clip(path: Path, frames: int = 45) -> Path:
    rng = np.random.default_rng(1)
    return encode_frames([rng.integers(0, 40, (240, 320, 3), np.uint8) for _ in range(frames)], path)


def person_clip(path: Path, frames: int = 60) -> Path:
    bgr = cv2.imread(str(POSE_IMAGE))
    rgb = cv2.cvtColor(bgr[: bgr.shape[0] // 2 * 2, : bgr.shape[1] // 2 * 2], cv2.COLOR_BGR2RGB)
    return encode_frames([rgb] * frames, path)


def upload(client, path: Path, name: str = "clip.mp4", title: str = "Test"):
    with path.open("rb") as handle:
        return client.post("/api/attempts", files={"file": (name, handle, "video/mp4")}, data={"title": title})


def imported(env, path: Path):
    _, client, worker = env
    attempt = upload(client, path).json()
    assert worker.process_one()
    return client.get(f"/api/attempts/{attempt['id']}").json()


def test_import_creates_canonical_video_with_range_support(env, tmp_path):
    settings, client, _ = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4"))
    assert attempt["status"] == "ready" and attempt["duration_ms"] == 1500
    assert attempt["attempt_start_ms"] == 0 and attempt["attempt_end_ms"] == 1500
    response = client.get(attempt["video_url"], headers={"Range": "bytes=0-99"})
    assert response.status_code == 206 and len(response.content) == 100
    assert (settings.attempt_dir(attempt["id"]) / "canonical.mp4").exists()


def test_corrupt_upload_fails_with_message_and_can_be_deleted(env, tmp_path):
    settings, client, worker = env
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    attempt = upload(client, bad).json()
    worker.process_one()
    state = client.get(f"/api/attempts/{attempt['id']}").json()
    assert state["status"] == "failed" and "could not be read" in state["error"]
    assert client.post(f"/api/attempts/{attempt['id']}/retry-import").status_code == 200
    worker.process_one()
    assert client.delete(f"/api/attempts/{attempt['id']}").status_code == 204
    assert not settings.attempt_dir(attempt["id"]).exists()
    assert client.get(f"/api/attempts/{attempt['id']}").status_code == 404


def test_oversized_upload_is_rejected_and_leaves_nothing(tmp_path, monkeypatch):
    import types
    from app import main as main_module

    real = load_pipeline_config()
    limited = types.SimpleNamespace(analysis=types.SimpleNamespace(max_upload_mb=0.001))  # 1000 bytes
    monkeypatch.setattr(main_module, "load_pipeline_config", lambda: limited)
    settings = Settings(tmp_path / "limited")
    client = TestClient(create_app(settings))
    big = tmp_path / "big.mp4"
    big.write_bytes(b"0" * 5000)
    response = upload(client, big)
    assert response.status_code == 413 and "limit" in response.json()["detail"]
    assert list(settings.attempts_dir.iterdir()) == []
    assert real.analysis.max_upload_mb == 2500 and real.analysis.max_duration_s == 300


def test_rejects_wrong_extension_and_empty_upload(env, tmp_path):
    settings, client, _ = env
    text = tmp_path / "x.txt"
    text.write_text("hello")
    assert upload(client, text, "x.txt").status_code == 415
    empty = tmp_path / "e.mp4"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 400
    assert list(settings.attempts_dir.iterdir()) == []


@pytest.mark.parametrize("bad", ["..", "..%2F..%2Fetc", "abc", "0" * 31 + "/", "A" * 32])
def test_bad_ids_cannot_reach_storage(env, bad):
    _, client, _ = env
    assert client.get(f"/api/attempts/{bad}/video").status_code in {404, 307}
    assert client.delete(f"/api/attempts/{bad}").status_code in {404, 405}


def test_storage_paths_reject_traversal(env):
    settings, _, _ = env
    for value in ("..", "../x", "a" * 31, "A" * 32):
        with pytest.raises(InvalidIdError):
            settings.attempt_dir(value)


def test_invalid_bounds_rejected(env, tmp_path):
    _, client, _ = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4"))
    for body in ({"attempt_start_ms": 1000, "attempt_end_ms": 500}, {"attempt_end_ms": 99_999}):
        assert client.patch(f"/api/attempts/{attempt['id']}", json=body).status_code == 422
    assert client.patch(f"/api/attempts/{attempt['id']}", json={"unknown": 1}).status_code == 422


@pytest.mark.mediapipe
def test_analysis_without_person_reports_unavailable_not_zero(env, tmp_path):
    _, client, worker = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4"))
    run = client.post(f"/api/attempts/{attempt['id']}/analyses").json()
    assert client.post(f"/api/attempts/{attempt['id']}/analyses").status_code == 409
    worker.process_one()
    done = client.get(f"/api/analyses/{run['id']}").json()
    assert done["status"] == "complete" and done["stage"] == "complete"
    events = client.get(f"/api/analyses/{run['id']}/events").json()
    assert events["events"] == []
    assert events["detection"]["detectors"]["low_movement"]["event_count"] is None
    assert events["summary"]["low_movement_fraction_of_eligible"] is None
    assert events["summary"]["wrist_episode_counts"] == {"left": None, "right": None}
    poses = client.get(f"/api/analyses/{run['id']}/poses").json()
    assert poses["samples"][0] == {"t": 0, "pose": False, "joints": {}}


@pytest.mark.mediapipe
def test_full_review_flow_persists_and_exports(env, tmp_path):
    settings, client, worker = env
    if not POSE_IMAGE.exists():
        pytest.skip("Missing official test image")
    attempt = imported(env, person_clip(tmp_path / "p.mp4", 120))
    aid = attempt["id"]
    client.patch(f"/api/attempts/{aid}", json={"attempt_start_ms": 200, "attempt_end_ms": 3800, "route_name": "<b>Blue</b>"})
    run = client.post(f"/api/attempts/{aid}/analyses").json()
    assert run["attempt_bounds_ms"] == {"start": 200, "end": 3800}
    worker.process_one()
    data = client.get(f"/api/analyses/{run['id']}/events").json()
    low = [e for e in data["events"] if e["type"] == "low_movement"]
    assert len(low) == 1 and low[0]["start_ms"] >= 200 and low[0]["end_ms"] < 3800
    assert "little" in low[0]["feedback"]["observation"]
    poses = client.get(f"/api/analyses/{run['id']}/poses").json()
    assert poses["samples"][0]["t"] == 200 and "left_wrist" in poses["samples"][0]["joints"]

    review = {"detection_judgment": "confirmed", "usefulness": "not_useful", "context_tags": ["planned_rest"], "note": "x<y"}
    assert client.put(f"/api/analyses/{run['id']}/events/{low[0]['id']}/review", json=review).status_code == 200
    assert client.put(f"/api/analyses/{run['id']}/events/{'e' * 16}/review", json=review).status_code == 404
    client.put(f"/api/attempts/{aid}/reflection", json={"observation": "Saw it", "next_focus": "Plan"})

    fresh = TestClient(create_app(settings))  # a restarted API sees the same state
    stored = fresh.get(f"/api/analyses/{run['id']}/events").json()["events"][0]
    assert stored["review"]["detection_judgment"] == "confirmed" and stored["review"]["usefulness"] == "not_useful"

    exported = fresh.get(f"/api/analyses/{run['id']}/export?format=json").json()
    assert exported["reflection"]["next_focus"] == "Plan"
    assert exported["result"]["config_hash"] and exported["events"][0]["review"]["note"] == "x<y"
    rows = list(csv.DictReader(io.StringIO(fresh.get(f"/api/analyses/{run['id']}/export?format=csv").text)))
    assert rows[0]["detection_judgment"] == "confirmed" and rows[0]["usefulness"] == "not_useful"
    page = fresh.get(f"/api/analyses/{run['id']}/export?format=html").text
    assert "<b>Blue</b>" not in page and "&lt;b&gt;Blue" in page and "x&lt;y" in page

    # Reanalysis is a new run; the old review stays with the old run.
    second = fresh.post(f"/api/attempts/{aid}/analyses").json()
    worker.process_one()
    assert fresh.get(f"/api/analyses/{second['id']}/events").json()["events"][0]["review"]["detection_judgment"] == "unreviewed"
    assert fresh.get(f"/api/analyses/{run['id']}/events").json()["events"][0]["review"]["detection_judgment"] == "confirmed"

    assert fresh.delete(f"/api/attempts/{aid}").status_code == 204
    assert not settings.attempt_dir(aid).exists()
    with db.session(settings.database) as connection:
        for table in ("jobs", "event_reviews", "reflections", "attempts"):
            assert connection.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0


def test_cancel_queued_job_and_block_delete_while_active(env, tmp_path):
    settings, client, worker = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4"))
    run = client.post(f"/api/attempts/{attempt['id']}/analyses").json()
    assert client.delete(f"/api/attempts/{attempt['id']}").status_code == 409
    assert client.patch(f"/api/attempts/{attempt['id']}", json={"attempt_start_ms": 100}).status_code == 409
    assert client.post(f"/api/analyses/{run['id']}/cancel").json()["status"] == "cancelled"
    assert worker.process_one() is False
    assert client.post(f"/api/analyses/{run['id']}/cancel").status_code == 409
    assert client.get(f"/api/analyses/{run['id']}/events").status_code == 409


@pytest.mark.mediapipe
def test_cancel_running_analysis_leaves_no_results(env, tmp_path, monkeypatch):
    settings, client, worker = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4", 120))
    run = client.post(f"/api/attempts/{attempt['id']}/analyses").json()
    original = worker._check
    calls = {"n": 0}

    def cancel_midway(job_id):
        calls["n"] += 1
        if calls["n"] == 5:
            client.post(f"/api/analyses/{run['id']}/cancel")
        original(job_id)

    monkeypatch.setattr(worker, "_check", cancel_midway)
    worker.process_one()
    state = client.get(f"/api/analyses/{run['id']}").json()
    assert state["status"] == "cancelled" and 0 < state["progress"]["done"] < state["progress"]["total"]
    run_dir = settings.run_dir(attempt["id"], run["id"])
    assert not run_dir.exists() and not run_dir.with_name(run_dir.name + ".partial").exists()
    assert client.post(f"/api/attempts/{attempt['id']}/analyses").status_code == 201


def test_cancel_queued_import_then_retry(env, tmp_path):
    settings, client, worker = env
    attempt = upload(client, noise_clip(tmp_path / "n.mp4")).json()
    state = client.post(f"/api/attempts/{attempt['id']}/cancel-import").json()
    assert state["status"] == "failed" and "cancelled" in state["error"]
    assert state["import_job"]["status"] == "cancelled"
    assert worker.process_one() is False
    assert client.post(f"/api/attempts/{attempt['id']}/cancel-import").status_code == 409
    assert client.post(f"/api/attempts/{attempt['id']}/retry-import").status_code == 200
    worker.process_one()
    assert client.get(f"/api/attempts/{attempt['id']}").json()["status"] == "ready"


def test_cancel_running_import_stops_ffmpeg_and_cleans_up(env, tmp_path, monkeypatch):
    settings, client, worker = env
    attempt = upload(client, noise_clip(tmp_path / "n.mp4", 300)).json()
    original = worker._check

    def cancel_first(job_id):
        client.post(f"/api/attempts/{attempt['id']}/cancel-import")
        original(job_id)

    monkeypatch.setattr(worker, "_check", cancel_first)
    worker.process_one()
    state = client.get(f"/api/attempts/{attempt['id']}").json()
    assert state["status"] == "failed" and "cancelled" in state["error"] and state["import_job"]["status"] == "cancelled"
    directory = settings.attempt_dir(attempt["id"])
    assert not (directory / "canonical.mp4").exists() and not (directory / "canonical.partial.mp4").exists()
    assert (directory / "source.mp4").exists()  # the uploaded video is kept for a retry


def test_worker_failure_keeps_attempt_and_records_error(env, tmp_path):
    settings, client, worker = env
    attempt = imported(env, noise_clip(tmp_path / "n.mp4"))
    (settings.attempt_dir(attempt["id"]) / "media.json").write_text("{broken")
    run = client.post(f"/api/attempts/{attempt['id']}/analyses").json()
    worker.process_one()
    state = client.get(f"/api/analyses/{run['id']}").json()
    assert state["status"] == "failed" and state["error"] and "Traceback" not in state["error"]
    assert state["has_error_detail"] is True
    assert client.get(attempt["video_url"]).status_code == 200


def test_claim_is_exclusive(env, tmp_path):
    settings, client, _ = env
    upload(client, noise_clip(tmp_path / "n.mp4"))
    with db.session(settings.database) as first:
        assert db.claim_next_job(first, 1) is not None
    with db.session(settings.database) as second:
        assert db.claim_next_job(second, 2) is None


def _worker_process(data_dir: Path) -> subprocess.Popen:
    environment = {**os.environ, "CLIMBREVIEW_DATA_DIR": str(data_dir), "PYTHONPATH": str(PROJECT_ROOT / "backend")}
    return subprocess.Popen([sys.executable, "-m", "app.worker"], env=environment, cwd=PROJECT_ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_restart_marks_stale_running_job_interrupted_and_single_worker(env, tmp_path):
    settings, client, _ = env
    attempt = upload(client, noise_clip(tmp_path / "n.mp4")).json()
    with db.session(settings.database) as connection:
        assert db.claim_next_job(connection, 999_999) is not None  # as if a worker died mid-job
    process = _worker_process(settings.data_dir)
    try:
        assert "Marked 1 job" in process.stdout.readline()
        assert "Worker ready" in process.stdout.readline()
        second = _worker_process(settings.data_dir)
        second.wait(timeout=30)
        assert second.returncode == 2
        deadline = time.time() + 20
        while time.time() < deadline:
            state = client.get(f"/api/attempts/{attempt['id']}").json()
            if state["import_job"]["status"] == "interrupted":
                break
            time.sleep(0.1)
        assert state["import_job"]["status"] == "interrupted" and state["status"] == "failed"
        assert client.post(f"/api/attempts/{attempt['id']}/retry-import").status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=30)
