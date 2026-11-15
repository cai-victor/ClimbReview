"""User-authored reference annotations, kept apart from every model output.

These endpoints never read poses, events, or forecasts. Each rater's set is stored
separately. A set flagged as a synthetic fixture can be exported on its own but is
never included in the attempt-level export used for evaluation.
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .settings import PROJECT_ROOT, Settings, require_id

ALIAS = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{0,64}$")
DETECTOR_KEYS = {"low_movement", "wrist_motion_left", "wrist_motion_right", "foot_motion_left", "foot_motion_right"}
MIN_DURATION_MS = {"low_movement": 2000, "wrist_motion": 300, "foot_motion": 300}
CSV_COLUMNS = ["clip_id", "climber_id", "route_id", "split", "annotator_id", "event_type", "hand", "start_ms", "end_ms",
               "observability", "applies_to", "notes"]


class SetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rater_alias: str
    clip_id: str = ""
    climber_id: str = ""
    route_id: str = ""
    split: Literal["", "dev", "test"] = ""
    synthetic_test_fixture: bool = False


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["low_movement", "wrist_motion", "foot_motion", "unscorable"]
    hand: Literal["left", "right"] | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    applies_to: list[str] = []
    notes: str = Field(default="", max_length=1000)


def _reserved_names() -> set[str]:
    path = PROJECT_ROOT / "data" / "raw" / "phone_import_inventory.json"
    if not path.exists():
        return set()
    return {Path(f["filename"]).name for f in json.loads(path.read_text())["files"] if f["role"] != "development"}


def _validate_interval(body: Interval, duration_ms: int) -> None:
    if not 0 <= body.start_ms < body.end_ms <= duration_ms:
        raise HTTPException(422, "The interval must satisfy 0 <= start < end <= video duration.")
    if body.event_type == "wrist_motion" and body.hand is None:
        raise HTTPException(422, "Wrist motion needs a left or right hand.")
    if body.event_type == "foot_motion" and body.hand is None:
        raise HTTPException(422, "Foot motion needs a left or right foot.")
    if body.event_type not in {"wrist_motion", "foot_motion"} and body.hand is not None:
        raise HTTPException(422, "Only wrist or foot motion has a side.")
    if body.event_type == "unscorable":
        chosen = set(body.applies_to)
        if not chosen or not chosen <= {*DETECTOR_KEYS, "all"} or ("all" in chosen and len(chosen) > 1):
            raise HTTPException(422, "Unscorable time needs detectors, or 'all'.")
    else:
        if body.applies_to:
            raise HTTPException(422, "Only unscorable time uses applies_to.")
        minimum = MIN_DURATION_MS[body.event_type]
        if body.end_ms - body.start_ms < minimum:
            raise HTTPException(422, f"This event class must last at least {minimum / 1000:g}s (see the annotation guide).")


def register_annotations(app: FastAPI, get_settings) -> None:
    router = APIRouter()

    def attempt(connection, attempt_id: str) -> dict[str, Any]:
        row = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (require_id(attempt_id),)).fetchone())
        if row is None:
            raise HTTPException(404, "Attempt not found.")
        return row

    def get_set(connection, set_id: str) -> dict[str, Any]:
        row = db.row(connection.execute("SELECT * FROM annotation_sets WHERE id=?", (require_id(set_id),)).fetchone())
        if row is None:
            raise HTTPException(404, "Annotation set not found.")
        return row

    def intervals(connection, set_id: str) -> list[dict[str, Any]]:
        rows = [dict(r) for r in connection.execute(
            "SELECT * FROM annotation_intervals WHERE set_id=? ORDER BY start_ms, end_ms, id", (set_id,))]
        for row in rows:
            row["applies_to"] = row["applies_to"].split(";") if row["applies_to"] else []
        return rows

    def public_set(connection, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "synthetic_test_fixture": bool(row["synthetic_test_fixture"]), "kind":
                "synthetic_test_fixture" if row["synthetic_test_fixture"] else "user_authored_reference",
                "intervals": intervals(connection, row["id"]), "timebase": "canonical_video_ms"}

    def csv_rows(sets: list[dict[str, Any]]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in sets:
            for row in item["intervals"]:
                writer.writerow({
                    "clip_id": item["clip_id"], "climber_id": item["climber_id"], "route_id": item["route_id"], "split": item["split"],
                    "annotator_id": item["rater_alias"], "event_type": row["event_type"], "hand": row["hand"] or "",
                    "start_ms": row["start_ms"], "end_ms": row["end_ms"], "observability": "unscorable" if row["event_type"] == "unscorable" else "observed",
                    "applies_to": ";".join(row["applies_to"]), "notes": row["notes"],
                })
        return buffer.getvalue()

    @router.post("/api/attempts/{attempt_id}/annotation-sets", status_code=201)
    def create_set(attempt_id: str, body: SetCreate, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        if not ALIAS.match(body.rater_alias):
            raise HTTPException(422, "Use a short non-identifying alias: letters, numbers, - or _.")
        for field in (body.clip_id, body.climber_id, body.route_id):
            if not SAFE_ID.match(field):
                raise HTTPException(422, "IDs may use letters, numbers, dot, - or _.")
        with db.session(settings.database) as connection:
            target = attempt(connection, attempt_id)
            if target["status"] != "ready":
                raise HTTPException(409, "The video has not finished importing.")
            if target["original_filename"] in _reserved_names():
                raise HTTPException(403, "This clip is reserved and must not be annotated in this phase.")
            set_id = uuid.uuid4().hex
            try:
                connection.execute(
                    """INSERT INTO annotation_sets(id, attempt_id, rater_alias, clip_id, climber_id, route_id, split,
                       synthetic_test_fixture, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (set_id, attempt_id, body.rater_alias, body.clip_id or attempt_id[:8], body.climber_id, body.route_id, body.split,
                     int(body.synthetic_test_fixture), db.now(), db.now()))
            except db.sqlite3.IntegrityError as error:
                raise HTTPException(409, "That alias already has a set for this attempt.") from error
            return public_set(connection, get_set(connection, set_id))

    @router.get("/api/attempts/{attempt_id}/annotation-sets")
    def list_sets(attempt_id: str, settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
        """Metadata only, so choosing a set does not reveal other raters' intervals."""
        with db.session(settings.database) as connection:
            attempt(connection, attempt_id)
            rows = connection.execute(
                """SELECT s.id, s.rater_alias, s.synthetic_test_fixture, s.updated_at, COUNT(i.id) AS interval_count
                   FROM annotation_sets s LEFT JOIN annotation_intervals i ON i.set_id=s.id
                   WHERE s.attempt_id=? GROUP BY s.id ORDER BY s.created_at""", (attempt_id,)).fetchall()
            return [{**dict(r), "synthetic_test_fixture": bool(r["synthetic_test_fixture"])} for r in rows]

    @router.get("/api/annotation-sets/{set_id}")
    def read_set(set_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            return public_set(connection, get_set(connection, set_id))

    @router.delete("/api/annotation-sets/{set_id}", status_code=204)
    def delete_set(set_id: str, settings: Settings = Depends(get_settings)) -> None:
        with db.session(settings.database) as connection:
            get_set(connection, set_id)
            connection.execute("DELETE FROM annotation_sets WHERE id=?", (set_id,))

    def write_interval(connection, set_row: dict[str, Any], body: Interval, interval_id: str | None, settings) -> str:
        target = attempt(connection, set_row["attempt_id"])
        _validate_interval(body, target["duration_ms"])
        applies = ";".join(sorted(body.applies_to))
        if interval_id is None:
            interval_id = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO annotation_intervals(id, set_id, event_type, hand, start_ms, end_ms, applies_to, notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (interval_id, set_row["id"], body.event_type, body.hand, body.start_ms, body.end_ms, applies, body.notes, db.now()))
        else:
            updated = connection.execute(
                """UPDATE annotation_intervals SET event_type=?, hand=?, start_ms=?, end_ms=?, applies_to=?, notes=? WHERE id=? AND set_id=?""",
                (body.event_type, body.hand, body.start_ms, body.end_ms, applies, body.notes, require_id(interval_id), set_row["id"]))
            if updated.rowcount == 0:
                raise HTTPException(404, "Interval not found.")
        connection.execute("UPDATE annotation_sets SET updated_at=? WHERE id=?", (db.now(), set_row["id"]))
        return interval_id

    @router.post("/api/annotation-sets/{set_id}/intervals", status_code=201)
    def add_interval(set_id: str, body: Interval, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_set(connection, set_id)
            write_interval(connection, row, body, None, settings)
            return public_set(connection, row)

    @router.put("/api/annotation-sets/{set_id}/intervals/{interval_id}")
    def edit_interval(set_id: str, interval_id: str, body: Interval, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_set(connection, set_id)
            write_interval(connection, row, body, interval_id, settings)
            return public_set(connection, row)

    @router.delete("/api/annotation-sets/{set_id}/intervals/{interval_id}")
    def remove_interval(set_id: str, interval_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_set(connection, set_id)
            removed = connection.execute("DELETE FROM annotation_intervals WHERE id=? AND set_id=?", (require_id(interval_id), set_id))
            if removed.rowcount == 0:
                raise HTTPException(404, "Interval not found.")
            connection.execute("UPDATE annotation_sets SET updated_at=? WHERE id=?", (db.now(), set_id))
            return public_set(connection, row)

    @router.get("/api/annotation-sets/{set_id}/export")
    def export_set(set_id: str, format: Literal["csv", "json"] = Query(...), settings: Settings = Depends(get_settings)) -> Any:
        with db.session(settings.database) as connection:
            item = public_set(connection, get_set(connection, set_id))
        short = f"{item['clip_id']}_{item['rater_alias']}"
        if format == "csv":
            return PlainTextResponse(csv_rows([item]), media_type="text/csv",
                                     headers={"Content-Disposition": f'attachment; filename="annotations_{short}.csv"'})
        return JSONResponse(item, headers={"Content-Disposition": f'attachment; filename="annotations_{short}.json"'})

    @router.get("/api/attempts/{attempt_id}/annotations/export")
    def export_attempt(attempt_id: str, settings: Settings = Depends(get_settings)) -> PlainTextResponse:
        """All real raters' raw intervals. Synthetic fixtures are excluded; no agreement is computed."""
        with db.session(settings.database) as connection:
            attempt(connection, attempt_id)
            rows = [dict(r) for r in connection.execute(
                "SELECT * FROM annotation_sets WHERE attempt_id=? AND synthetic_test_fixture=0 ORDER BY created_at", (attempt_id,))]
            sets = [public_set(connection, row) for row in rows]
        return PlainTextResponse(csv_rows(sets), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="annotations_{attempt_id[:8]}_all_raters.csv"'})

    app.include_router(router)
