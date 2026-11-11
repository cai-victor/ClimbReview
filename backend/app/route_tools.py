"""Hold suggestions, picture scale, and route planning from entered body measurements.

None of this needs an analysis run, so it also works for an imported photo.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

import cv2
import numpy as np
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .analysis import beta, hold_suggest
from .holds import frame_path
from .settings import Settings, require_id

CLEAN_WALL_FRAMES = 15
MIN_SCALE_LINE_PX = 20


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    tolerance: Literal["strict", "normal", "loose"] = "normal"


class Scale(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)
    cm: float = Field(ge=5, le=2000)


def register_route_tools(app: FastAPI, get_settings) -> None:
    router = APIRouter()

    def load(connection, map_id: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        row = db.row(connection.execute("SELECT * FROM hold_maps WHERE id=?", (require_id(map_id),)).fetchone())
        if row is None:
            raise HTTPException(404, "Hold map not found.")
        attempt = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (row["attempt_id"],)).fetchone())
        holds = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (map_id,))]
        return row, attempt, holds

    def wall_image(settings: Settings, row: dict[str, Any], attempt: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
        directory = settings.attempt_dir(attempt["id"])
        reference = cv2.imread(str(frame_path(settings, attempt, row["reference_frame_ms"])))
        cached, info_path = directory / "frames" / f"clean_{row['id']}.png", directory / "frames" / f"clean_{row['id']}.json"
        if cached.exists() and info_path.exists():
            return cv2.imread(str(cached)), json.loads(info_path.read_text())
        frames = []
        if attempt["duration_ms"] > 3000:           # a photo has nothing to combine
            for ms in np.linspace(0, attempt["duration_ms"] - 200, CLEAN_WALL_FRAMES):
                frames.append(cv2.imread(str(frame_path(settings, attempt, int(ms)))))
        image, info = hold_suggest.clean_wall(reference, frames)
        cv2.imwrite(str(cached), image)
        info_path.write_text(json.dumps(info))
        return image, info

    @router.post("/api/hold-maps/{map_id}/suggestions")
    def suggestions(map_id: str, body: SuggestRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, attempt, holds = load(connection, map_id)
        image, info = wall_image(settings, row, attempt)
        try:
            return {**hold_suggest.suggest(image, body.x, body.y, body.tolerance, holds), "image": info}
        except hold_suggest.SuggestionError as error:
            raise HTTPException(422, str(error)) from error

    @router.put("/api/hold-maps/{map_id}/scale")
    def put_scale(map_id: str, body: Scale, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, _, _ = load(connection, map_id)
            if np.hypot((body.x2 - body.x1) * row["width"], (body.y2 - body.y1) * row["height"]) < MIN_SCALE_LINE_PX:
                raise HTTPException(422, "The two scale points are too close together. Pick points farther apart.")
            connection.execute("UPDATE hold_maps SET scale=?, updated_at=? WHERE id=?", (json.dumps(body.model_dump()), db.now(), map_id))
            return body.model_dump()

    @router.delete("/api/hold-maps/{map_id}/scale", status_code=204)
    def delete_scale(map_id: str, settings: Settings = Depends(get_settings)) -> None:
        with db.session(settings.database) as connection:
            load(connection, map_id)
            connection.execute("UPDATE hold_maps SET scale=NULL, updated_at=? WHERE id=?", (db.now(), map_id))

    @router.get("/api/hold-maps/{map_id}/plan")
    def plan(map_id: str, height_cm: float = Query(ge=beta.HEIGHT_RANGE_CM[0], le=beta.HEIGHT_RANGE_CM[1]),
             wingspan_cm: float = Query(ge=beta.WINGSPAN_RANGE_CM[0], le=beta.WINGSPAN_RANGE_CM[1]),
             settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, attempt, holds = load(connection, map_id)
        public = {"id": row["id"], "name": row["name"], "hold_count": len(holds), "reference_frame_ms": row["reference_frame_ms"], "usable": False,
                  "message": "", "alignment": None, "frame_url": f"/api/attempts/{attempt['id']}/frame?ms={row['reference_frame_ms']}",
                  "holds": [{k: h[k] for k in ("id", "x", "y", "radius", "route", "hold_type", "role", "use")} for h in holds],
                  "width": row["width"], "height": row["height"]}
        scale = json.loads(row["scale"]) if row["scale"] else None
        measured = beta.body_from_measurements(height_cm, wingspan_cm)
        needs = beta.setup_needed(holds)
        if scale is None:
            needs.append("Set the picture's scale: mark two points on the wall and enter the real distance between them.")
        if needs:
            return {"status": "setup_needed", "needs": needs, "candidates": [], "hold_map": public, "body": measured.public(), "method": beta.BETA_VERSION}
        length = beta.torso_px(scale, row["width"], row["height"], measured.torso_cm)
        output = beta.candidate_sequences(holds, row["width"], row["height"], length, measured.body)
        for candidate in output["candidates"]:
            signature = json.dumps([candidate["start"], candidate["steps"]], sort_keys=True)
            candidate["id"] = "plan-" + hashlib.sha256(f"{map_id}|{signature}".encode()).hexdigest()[:12]
        output["assumptions"] = [a for a in output.get("assumptions", []) if "tracked limb lengths" not in a] + beta.MEASURED_ASSUMPTIONS
        return {**output, "hold_map": public, "body": measured.public(),
                "scale": {**scale, "px_per_cm": round(length / measured.torso_cm, 3)}}

    app.include_router(router)
