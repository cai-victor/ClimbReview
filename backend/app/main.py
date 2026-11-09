"""FastAPI application: metadata, media, and review state. No heavy computation here."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import db, report
from .annotations import register_annotations
from .coaching_api import register_coaching
from .holds import register_holds
from .worker import IMPORT_CANCELLED_MESSAGE
from .settings import PROJECT_ROOT, InvalidIdError, Settings, load_pipeline_config, load_settings, require_id

ALLOWED_EXTENSIONS = {".mp4", ".mov"}
CHUNK_BYTES = 1 << 20


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttemptPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    route_name: str | None = Field(default=None, max_length=200)
    grade: str | None = Field(default=None, max_length=50)
    outcome: str | None = Field(default=None, max_length=200)
    focus: str | None = Field(default=None, max_length=500)
    problem_label: str | None = Field(default=None, max_length=120)
    climber_label: str | None = Field(default=None, max_length=60)
    single_climber_confirmed: bool | None = None
    fixed_camera_confirmed: bool | None = None
    attempt_start_ms: int | None = Field(default=None, ge=0)
    attempt_end_ms: int | None = Field(default=None, gt=0)


class EventReview(StrictModel):
    detection_judgment: Literal["unreviewed", "confirmed", "incorrect", "cannot_tell"] = "unreviewed"
    usefulness: Literal["unrated", "useful", "not_useful"] = "unrated"
    context_tags: list[Literal["planned_rest", "planning_next_move", "intentional_dynamic_movement", "other"]] = []
    note: str = Field(default="", max_length=2000)


class Reflection(StrictModel):
    observation: str = Field(default="", max_length=2000)
    next_focus: str = Field(default="", max_length=2000)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    active_settings.prepare()
    db.initialize(active_settings.database)
    max_upload_bytes = int(load_pipeline_config().analysis.max_upload_mb * 1_000_000)
    app = FastAPI(title="ClimbReview", version="0.2.0")

    @app.exception_handler(InvalidIdError)
    async def _invalid_id(_: Request, __: InvalidIdError) -> JSONResponse:
        return JSONResponse({"detail": "Not found."}, status_code=404)

    def get_settings() -> Settings:
        return active_settings

    # ---- helpers
    def attempt_row(connection, attempt_id: str) -> dict[str, Any]:
        found = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (require_id(attempt_id),)).fetchone())
        if found is None:
            raise HTTPException(404, "Attempt not found.")
        return found

    def job_row(connection, job_id: str) -> dict[str, Any]:
        found = db.row(connection.execute("SELECT * FROM jobs WHERE id=? AND kind='analysis'", (require_id(job_id),)).fetchone())
        if found is None:
            raise HTTPException(404, "Analysis not found.")
        return found

    def public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": job["id"], "attempt_id": job["attempt_id"], "kind": job["kind"], "status": job["status"],
            "stage": job["stage"], "progress": {"done": job["progress_done"], "total": job["progress_total"]},
            "cancel_requested": bool(job["cancel_requested"]), "error": job["error"], "has_error_detail": bool(job["error_detail"]),
            "attempt_bounds_ms": {"start": job["attempt_start_ms"], "end": job["attempt_end_ms"]},
            "config_hash": job["config_hash"], "pipeline_version": job["pipeline_version"],
            "detector_version": job["detector_version"], "summary": json.loads(job["summary"]) if job["summary"] else None,
            "created_at": job["created_at"], "started_at": job["started_at"], "finished_at": job["finished_at"],
        }

    def public_attempt(connection, attempt: dict[str, Any]) -> dict[str, Any]:
        jobs = [dict(r) for r in connection.execute(
            "SELECT * FROM jobs WHERE attempt_id=? ORDER BY created_at DESC", (attempt["id"],))]
        import_job = next((j for j in jobs if j["kind"] == "import"), None)
        return {
            **{k: attempt[k] for k in ("id", "title", "route_name", "grade", "outcome", "focus", "problem_label", "climber_label", "status", "error",
                                       "width", "height", "fps", "frame_count", "duration_ms", "attempt_start_ms",
                                       "attempt_end_ms", "created_at", "original_filename")},
            "single_climber_confirmed": bool(attempt["single_climber_confirmed"]),
            "fixed_camera_confirmed": bool(attempt["fixed_camera_confirmed"]),
            "warnings": json.loads(attempt["warnings"]),
            "import_job": public_job(import_job) if import_job else None,
            "analyses": [public_job(j) for j in jobs if j["kind"] == "analysis"],
            "video_url": f"/api/attempts/{attempt['id']}/video" if attempt["status"] == "ready" else None,
        }

    def new_job(connection, attempt_id: str, kind: str, stage: str, start: int | None = None, end: int | None = None) -> str:
        job_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO jobs(id, attempt_id, kind, status, stage, attempt_start_ms, attempt_end_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (job_id, attempt_id, kind, "queued", stage, start, end, db.now()))
        return job_id

    def load_json(path: Path) -> Any:
        if not path.exists():
            raise HTTPException(409, "This analysis has no completed results.")
        return json.loads(path.read_text())

    def completed_run(connection, run_id: str, settings: Settings) -> tuple[dict[str, Any], Path]:
        job = job_row(connection, run_id)
        if job["status"] != "complete":
            raise HTTPException(409, "This analysis has no completed results.")
        return job, settings.run_dir(job["attempt_id"], job["id"])

    def events_with_reviews(connection, job_id: str, directory: Path) -> list[dict[str, Any]]:
        events = load_json(directory / "events.json")["events"]
        reviews = {r["event_id"]: dict(r) for r in connection.execute("SELECT * FROM event_reviews WHERE run_id=?", (job_id,))}
        for event in events:
            stored = reviews.get(event["id"])
            event["review"] = {
                "detection_judgment": stored["detection_judgment"] if stored else "unreviewed",
                "usefulness": stored["usefulness"] if stored else "unrated",
                "context_tags": json.loads(stored["context_tags"]) if stored else [],
                "note": stored["note"] if stored else "",
            }
        return events

    def reflection_of(connection, attempt_id: str) -> dict[str, str]:
        found = connection.execute("SELECT observation, next_focus FROM reflections WHERE attempt_id=?", (attempt_id,)).fetchone()
        return dict(found) if found else {"observation": "", "next_focus": ""}

    # ---- attempts
    @app.post("/api/attempts", status_code=201)
    async def import_attempt(file: UploadFile = File(...), title: str = Form(default=""),
                             settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        filename = Path(file.filename or "video").name
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(415, "Choose an MP4 or MOV file.")
        attempt_id = uuid.uuid4().hex
        directory = settings.attempt_dir(attempt_id)
        directory.mkdir(parents=True)
        target = directory / f"source{extension}"
        written = 0
        try:
            with target.open("wb") as handle:
                while chunk := await file.read(CHUNK_BYTES):
                    written += len(chunk)
                    if written > max_upload_bytes:
                        raise HTTPException(413, f"File is larger than the {max_upload_bytes / 1e6:.0f} MB limit. Trim it first.")
                    handle.write(chunk)
            if written == 0:
                raise HTTPException(400, "The selected file is empty.")
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        with db.session(settings.database) as connection:
            connection.execute(
                "INSERT INTO attempts(id, title, original_filename, source_ext, status, created_at) VALUES (?,?,?,?,?,?)",
                (attempt_id, title.strip()[:200] or Path(filename).stem[:200], filename[:255], extension, "importing", db.now()))
            new_job(connection, attempt_id, "import", "queued")
            return public_attempt(connection, attempt_row(connection, attempt_id))

    @app.get("/api/attempts")
    def list_attempts(settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
        with db.session(settings.database) as connection:
            rows = [dict(r) for r in connection.execute("SELECT * FROM attempts ORDER BY created_at DESC")]
            return [public_attempt(connection, r) for r in rows]

    @app.get("/api/attempts/{attempt_id}")
    def get_attempt(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            return public_attempt(connection, attempt_row(connection, attempt_id))

    @app.patch("/api/attempts/{attempt_id}")
    def patch_attempt(attempt_id: str, body: AttemptPatch, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        changes = body.model_dump(exclude_unset=True)
        with db.session(settings.database) as connection:
            attempt = attempt_row(connection, attempt_id)
            if ("attempt_start_ms" in changes or "attempt_end_ms" in changes):
                if db.active_job(connection, attempt_id):
                    raise HTTPException(409, "Bounds cannot change while a job is active.")
                start = changes.get("attempt_start_ms", attempt["attempt_start_ms"])
                end = changes.get("attempt_end_ms", attempt["attempt_end_ms"])
                if attempt["duration_ms"] is None or start is None or end is None or not 0 <= start < end <= attempt["duration_ms"]:
                    raise HTTPException(422, "Attempt bounds must satisfy 0 <= start < end <= video duration.")
            if changes:
                columns = ", ".join(f"{key}=?" for key in changes)
                connection.execute(f"UPDATE attempts SET {columns} WHERE id=?", (*changes.values(), attempt_id))
            return public_attempt(connection, attempt_row(connection, attempt_id))

    @app.delete("/api/attempts/{attempt_id}", status_code=204)
    def delete_attempt(attempt_id: str, settings: Settings = Depends(get_settings)) -> None:
        with db.session(settings.database) as connection:
            attempt_row(connection, attempt_id)
            if db.active_job(connection, attempt_id):
                raise HTTPException(409, "Cancel the active job before deleting this attempt.")
            directory = settings.attempt_dir(attempt_id)
            connection.execute("DELETE FROM attempts WHERE id=?", (attempt_id,))
        shutil.rmtree(directory, ignore_errors=True)

    @app.post("/api/attempts/{attempt_id}/retry-import")
    def retry_import(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            attempt = attempt_row(connection, attempt_id)
            if attempt["status"] != "failed" or db.active_job(connection, attempt_id):
                raise HTTPException(409, "Only a failed import can be retried.")
            connection.execute("UPDATE attempts SET status='importing', error=NULL WHERE id=?", (attempt_id,))
            new_job(connection, attempt_id, "import", "queued")
            return public_attempt(connection, attempt_row(connection, attempt_id))

    @app.post("/api/attempts/{attempt_id}/cancel-import")
    def cancel_import(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            attempt_row(connection, attempt_id)
            job = db.row(connection.execute(
                "SELECT * FROM jobs WHERE attempt_id=? AND kind='import' AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
                (attempt_id,)).fetchone())
            if job is None:
                raise HTTPException(409, "No import is active for this attempt.")
            if job["status"] == "queued":
                connection.execute("UPDATE jobs SET status='cancelled', error='Cancelled.', finished_at=? WHERE id=? AND status='queued'",
                                   (db.now(), job["id"]))
                connection.execute("UPDATE attempts SET status='failed', error=? WHERE id=?", (IMPORT_CANCELLED_MESSAGE, attempt_id))
            else:
                connection.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job["id"],))
            return public_attempt(connection, attempt_row(connection, attempt_id))

    @app.get("/api/attempts/{attempt_id}/video")
    def get_video(attempt_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
        path = settings.attempt_dir(attempt_id) / "canonical.mp4"
        if not path.exists():
            raise HTTPException(404, "Canonical video is not available.")
        return FileResponse(path, media_type="video/mp4")

    @app.put("/api/attempts/{attempt_id}/reflection")
    def put_reflection(attempt_id: str, body: Reflection, settings: Settings = Depends(get_settings)) -> dict[str, str]:
        with db.session(settings.database) as connection:
            attempt_row(connection, attempt_id)
            connection.execute(
                """INSERT INTO reflections(attempt_id, observation, next_focus, updated_at) VALUES (?,?,?,?)
                   ON CONFLICT(attempt_id) DO UPDATE SET observation=excluded.observation, next_focus=excluded.next_focus, updated_at=excluded.updated_at""",
                (attempt_id, body.observation, body.next_focus, db.now()))
            return reflection_of(connection, attempt_id)

    @app.get("/api/attempts/{attempt_id}/reflection")
    def get_reflection(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, str]:
        with db.session(settings.database) as connection:
            attempt_row(connection, attempt_id)
            return reflection_of(connection, attempt_id)

    # ---- analyses
    @app.post("/api/attempts/{attempt_id}/analyses", status_code=201)
    def queue_analysis(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            attempt = attempt_row(connection, attempt_id)
            if attempt["status"] != "ready":
                raise HTTPException(409, "The video has not finished importing.")
            if db.active_job(connection, attempt_id):
                raise HTTPException(409, "A job is already active for this attempt.")
            job_id = new_job(connection, attempt_id, "analysis", "queued", attempt["attempt_start_ms"], attempt["attempt_end_ms"])
            return public_job(job_row(connection, job_id))

    @app.get("/api/analyses/{run_id}")
    def get_analysis(run_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job = job_row(connection, run_id)
            payload = public_job(job)
        directory = settings.run_dir(job["attempt_id"], job["id"])
        if job["status"] == "complete":
            payload["result"] = load_json(directory / "result.json")
        return payload

    @app.post("/api/analyses/{run_id}/cancel")
    def cancel_analysis(run_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job = job_row(connection, run_id)
            if job["status"] == "queued":
                connection.execute("UPDATE jobs SET status='cancelled', error='Cancelled.', finished_at=? WHERE id=? AND status='queued'",
                                   (db.now(), run_id))
            elif job["status"] == "running":
                connection.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (run_id,))
            else:
                raise HTTPException(409, "This analysis is not active.")
            return public_job(job_row(connection, run_id))

    @app.get("/api/analyses/{run_id}/poses")
    def get_poses(run_id: str, settings: Settings = Depends(get_settings)) -> Any:
        with db.session(settings.database) as connection:
            _, directory = completed_run(connection, run_id, settings)
        return load_json(directory / "overlay.json")

    @app.get("/api/analyses/{run_id}/movement")
    def get_movement(run_id: str, settings: Settings = Depends(get_settings)) -> Any:
        """Per-limb series for charts. Older runs have none, and say so instead of failing."""
        with db.session(settings.database) as connection:
            _, directory = completed_run(connection, run_id, settings)
        path = directory / "movement.json"
        return {"available": True, **json.loads(path.read_text())} if path.exists() else {"available": False}

    @app.get("/api/analyses/{run_id}/events")
    def get_events(run_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, directory = completed_run(connection, run_id, settings)
            events = events_with_reviews(connection, job["id"], directory)
        result = load_json(directory / "result.json")
        return {"events": events, "detection": result["detection"], "summary": report.summarize(result, events)}

    @app.put("/api/analyses/{run_id}/events/{event_id}/review")
    def put_review(run_id: str, event_id: str, body: EventReview, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, directory = completed_run(connection, run_id, settings)
            known = {e["id"] for e in load_json(directory / "events.json")["events"]}
            if event_id not in known:
                raise HTTPException(404, "Event not found in this analysis.")
            connection.execute(
                """INSERT INTO event_reviews(run_id, event_id, detection_judgment, usefulness, context_tags, note, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(run_id, event_id) DO UPDATE SET detection_judgment=excluded.detection_judgment,
                     usefulness=excluded.usefulness, context_tags=excluded.context_tags, note=excluded.note, updated_at=excluded.updated_at""",
                (job["id"], event_id, body.detection_judgment, body.usefulness, json.dumps(body.context_tags), body.note, db.now()))
            return body.model_dump()

    @app.get("/api/analyses/{run_id}/export")
    def export(run_id: str, format: Literal["json", "csv", "html"] = Query(...), settings: Settings = Depends(get_settings)) -> Any:
        with db.session(settings.database) as connection:
            job, directory = completed_run(connection, run_id, settings)
            events = events_with_reviews(connection, job["id"], directory)
            attempt = public_attempt(connection, attempt_row(connection, job["attempt_id"]))
            reflection = reflection_of(connection, job["attempt_id"])
        result = load_json(directory / "result.json")
        short = run_id[:8]
        if format == "csv":
            return PlainTextResponse(report.events_csv(events), media_type="text/csv",
                                     headers={"Content-Disposition": f'attachment; filename="climbreview_events_{short}.csv"'})
        bundle = report.full_export(attempt, public_job(job), result, events, reflection)
        if format == "json":
            return JSONResponse(bundle, headers={"Content-Disposition": f'attachment; filename="climbreview_analysis_{short}.json"'})
        return HTMLResponse(report.html_report(bundle),
                            headers={"Content-Disposition": f'attachment; filename="climbreview_report_{short}.html"'})

    register_annotations(app, get_settings)
    register_holds(app, get_settings)
    register_coaching(app, get_settings)

    @app.middleware("http")
    async def _reject_oversized_uploads(request: Request, call_next):
        # Refuse before the multipart body is buffered; the streaming check below still applies.
        declared = request.headers.get("content-length")
        if request.method == "POST" and request.url.path == "/api/attempts" and declared and declared.isdigit() \
                and int(declared) > max_upload_bytes + 1_000_000:
            return JSONResponse({"detail": f"File is larger than the {max_upload_bytes / 1e6:.0f} MB limit. Trim it first."},
                                status_code=413)
        return await call_next(request)

    @app.middleware("http")
    async def _no_stale_shell(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    dist = PROJECT_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
