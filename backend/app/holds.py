"""Manual route-hold marking on one reference frame of the canonical video.

Coordinates are valid for that reference frame only. They are not tracked through the
video, nothing here detects holds, and nothing links a wrist to a hold.
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .analysis import beta
from .analysis.pose import sha256_file
from .analysis.video import tool_path
from .settings import Settings, require_id

SCOPE_NOTE = ("Hold coordinates apply to this reference frame only. Showing them on other frames needs a verified fixed "
              "camera. These are user-marked regions, not detected holds or verified contacts.")
RADIUS_MAX = 0.5


class MapCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    reference_frame_ms: int = Field(ge=0)


class Hold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    radius: float = Field(gt=0, le=RADIUS_MAX, description="Fraction of image width")
    route: str = Field(default="", max_length=60)
    hold_type: str = Field(default="", max_length=40)
    role: Literal["", "start", "finish"] = ""
    use: Literal["", "hand", "foot", "both"] = ""
    pull: Literal["", "down", "left", "right", "up"] = Field(default="", description="Direction the hand pulls on the hold, as marked by the climber")
    start_limb: Literal["", "left_hand", "right_hand", "both_hands", "left_foot", "right_foot"] = Field(default="", description="For a start hold: the limb the climber starts with on it")


def _extract_frame(canonical: Path, output: Path, seconds: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.stem}.{uuid.uuid4().hex}.jpg")
    result = subprocess.run(
        [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-ss", f"{seconds:.6f}", "-i", str(canonical),
         "-frames:v", "1", "-q:v", "3", str(temporary)], capture_output=True)
    if result.returncode != 0 or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise HTTPException(500, "The reference frame could not be extracted.")
    temporary.replace(output)


def frame_path(settings: Settings, attempt: dict[str, Any], ms: int) -> Path:
    """The cached still image for this canonical time, extracted on first use."""
    index = int(ms * attempt["fps"] / 1000)
    directory = settings.attempt_dir(attempt["id"])
    output = directory / "frames" / f"{index:06d}.jpg"
    if not output.exists():
        _extract_frame(directory / "canonical.mp4", output, index / attempt["fps"])
    return output


def register_holds(app: FastAPI, get_settings) -> None:
    router = APIRouter()

    def attempt(connection, attempt_id: str) -> dict[str, Any]:
        row = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (require_id(attempt_id),)).fetchone())
        if row is None:
            raise HTTPException(404, "Attempt not found.")
        if row["status"] != "ready":
            raise HTTPException(409, "The video has not finished importing.")
        return row

    def get_map(connection, map_id: str) -> dict[str, Any]:
        row = db.row(connection.execute("SELECT * FROM hold_maps WHERE id=?", (require_id(map_id),)).fetchone())
        if row is None:
            raise HTTPException(404, "Hold map not found.")
        return row

    def tracked_torso_px(settings, connection, attempt_id: str) -> float | None:
        """The climber's median shoulder-to-hip length in the newest finished analysis, in picture pixels."""
        run = db.row(connection.execute(
            "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt_id,)).fetchone())
        movement = None if run is None else settings.run_dir(attempt_id, run["id"]) / "movement.json"
        if movement is None or not movement.exists():
            return None
        return json.loads(movement.read_text()).get("L_px")

    def public_map(settings, connection, row: dict[str, Any]) -> dict[str, Any]:
        holds = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (row["id"],))]
        scale = json.loads(row["scale"]) if row.get("scale") else None
        check = beta.scale_check(scale, row["width"], row["height"], tracked_torso_px(settings, connection, row["attempt_id"])) if scale else None
        return {**row, "scale": scale, "scale_check": check, "holds": holds, "coordinate_system": "normalized canonical frame; radius is a fraction of width",
                "scope_note": SCOPE_NOTE, "frame_url": f"/api/attempts/{row['attempt_id']}/frame?ms={row['reference_frame_ms']}"}

    @router.get("/api/attempts/{attempt_id}/frame")
    def frame(attempt_id: str, ms: int = Query(ge=0), settings: Settings = Depends(get_settings)) -> FileResponse:
        with db.session(settings.database) as connection:
            target = attempt(connection, attempt_id)
        if ms >= target["duration_ms"]:
            raise HTTPException(422, "That time is outside the video.")
        return FileResponse(frame_path(settings, target, ms), media_type="image/jpeg")

    @router.post("/api/attempts/{attempt_id}/hold-maps", status_code=201)
    def create_map(attempt_id: str, body: MapCreate, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            target = attempt(connection, attempt_id)
            if body.reference_frame_ms >= target["duration_ms"]:
                raise HTTPException(422, "The reference frame is outside the video.")
            index = int(body.reference_frame_ms * target["fps"] / 1000)
            digest = sha256_file(settings.attempt_dir(attempt_id) / "canonical.mp4")
            map_id = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO hold_maps(id, attempt_id, name, reference_frame_ms, frame_index, canonical_sha256, width, height, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (map_id, attempt_id, body.name, round(index * 1000 / target["fps"]), index, digest, target["width"], target["height"], db.now(), db.now()))
            return public_map(settings, connection, get_map(connection, map_id))

    @router.get("/api/attempts/{attempt_id}/hold-maps")
    def list_maps(attempt_id: str, settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
        with db.session(settings.database) as connection:
            attempt(connection, attempt_id)
            rows = [dict(r) for r in connection.execute("SELECT * FROM hold_maps WHERE attempt_id=? ORDER BY created_at", (attempt_id,))]
            return [public_map(settings, connection, r) for r in rows]

    @router.get("/api/hold-maps/{map_id}")
    def read_map(map_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            return public_map(settings, connection, get_map(connection, map_id))

    @router.delete("/api/hold-maps/{map_id}", status_code=204)
    def delete_map(map_id: str, settings: Settings = Depends(get_settings)) -> None:
        with db.session(settings.database) as connection:
            get_map(connection, map_id)
            connection.execute("DELETE FROM hold_maps WHERE id=?", (map_id,))

    @router.post("/api/hold-maps/{map_id}/holds", status_code=201)
    def add_hold(map_id: str, body: Hold, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_map(connection, map_id)
            connection.execute("""INSERT INTO holds(id, map_id, x, y, radius, route, hold_type, role, "use", pull, start_limb, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                               (uuid.uuid4().hex, map_id, body.x, body.y, body.radius, body.route, body.hold_type, body.role, body.use, body.pull, body.start_limb if body.role == "start" else "", db.now()))
            connection.execute("UPDATE hold_maps SET updated_at=? WHERE id=?", (db.now(), map_id))
            return public_map(settings, connection, row)

    @router.put("/api/hold-maps/{map_id}/holds/{hold_id}")
    def edit_hold(map_id: str, hold_id: str, body: Hold, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_map(connection, map_id)
            updated = connection.execute("""UPDATE holds SET x=?, y=?, radius=?, route=?, hold_type=?, role=?, "use"=?, pull=?, start_limb=? WHERE id=? AND map_id=?""",
                                         (body.x, body.y, body.radius, body.route, body.hold_type, body.role, body.use, body.pull, body.start_limb if body.role == "start" else "", require_id(hold_id), map_id))
            if updated.rowcount == 0:
                raise HTTPException(404, "Hold not found.")
            return public_map(settings, connection, row)

    @router.delete("/api/hold-maps/{map_id}/holds/{hold_id}")
    def delete_hold(map_id: str, hold_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row = get_map(connection, map_id)
            removed = connection.execute("DELETE FROM holds WHERE id=? AND map_id=?", (require_id(hold_id), map_id))
            if removed.rowcount == 0:
                raise HTTPException(404, "Hold not found.")
            return public_map(settings, connection, row)

    @router.get("/api/hold-maps/{map_id}/export")
    def export_map(map_id: str, settings: Settings = Depends(get_settings)) -> JSONResponse:
        with db.session(settings.database) as connection:
            item = public_map(settings, connection, get_map(connection, map_id))
        return JSONResponse(item, headers={"Content-Disposition": f'attachment; filename="hold_map_{map_id[:8]}.json"'})

    app.include_router(router)
