"""Hold suggestions, picture scale, and route planning from entered body measurements.

None of this needs an analysis run, so it also works for an imported photo.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

import cv2
import numpy as np
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .analysis import beta, hold_suggest, wall_grid
from .holds import frame_path
from .settings import Settings, require_id

WALL_FRAMES = 25
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


def wall_paths(settings: Settings, row: dict[str, Any], attempt: dict[str, Any], run: dict[str, Any] | None):
    """Cache location. It names the analysis used, so a newer analysis rebuilds the picture."""
    stem = settings.attempt_dir(attempt["id"]) / "frames" / f"wallv2_{row['id']}_{run['id'][:12] if run else 'untracked'}"
    return stem.with_suffix(".png"), stem.with_suffix(".json")


def build_wall_image(settings: Settings, attempt: dict[str, Any], reference_ms: int, cache: Path | None, run_id: str | None) -> tuple[np.ndarray, dict[str, Any]]:
    """The clearest available picture of the wall for one reference frame, combined from across the video when possible."""
    info_path = None if cache is None else cache.with_suffix(".json")
    if cache is not None and cache.exists() and info_path.exists():
        return cv2.imread(str(cache)), json.loads(info_path.read_text())
    reference = cv2.imread(str(frame_path(settings, attempt, reference_ms)))
    frames: list[np.ndarray] = []
    masks: list[np.ndarray | None] | None = None
    if attempt["duration_ms"] > 3000:               # a photo has nothing to combine
        overlay = None if run_id is None else settings.run_dir(attempt["id"], run_id) / "overlay.json"
        if overlay is not None and overlay.exists():
            samples = json.loads(overlay.read_text())["samples"]
            chosen = [samples[int(i)] for i in np.linspace(0, len(samples) - 1, min(WALL_FRAMES, len(samples)))] if samples else []
            masks = []
            for sample in chosen:                    # only moments where the tracker looked for the climber
                frames.append(cv2.imread(str(frame_path(settings, attempt, sample["t"]))))
                masks.append(hold_suggest.climber_mask(reference.shape[:2], sample["joints"]))
        else:
            frames = [cv2.imread(str(frame_path(settings, attempt, int(ms)))) for ms in np.linspace(0, attempt["duration_ms"] - 200, WALL_FRAMES)]
    image, info = hold_suggest.clean_wall(reference, frames, masks)
    times = [s["t"] for s in chosen] if masks is not None else [int(ms) for ms in np.linspace(0, attempt["duration_ms"] - 200, WALL_FRAMES)] if frames else []
    info["registered"] = [{"t": times[item["index"]], "matrix": item["matrix"]} for item in info.get("registered", [])]
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(cache), image)
        info_path.write_text(json.dumps(info))
    return image, info


def wall_geometry(settings: Settings, attempt: dict[str, Any], reference_ms: int, cache: Path, run_id: str | None, holds: list[dict[str, Any]]) -> dict[str, Any]:
    """The bolt-grid fit for one wall picture, started near the holds. Cached beside the picture."""
    focus = None if not holds else (float(np.mean([h["x"] for h in holds])) * attempt["width"], float(np.mean([h["y"] for h in holds])) * attempt["height"])
    key = "any" if focus is None else f"{focus[0] / attempt['width']:.1f}_{focus[1] / attempt['height']:.1f}"
    path = cache.with_name(f"{cache.stem}_grid_{key}.json")
    if path.exists():
        return json.loads(path.read_text())
    image, _ = build_wall_image(settings, attempt, reference_ms, cache, run_id)
    fit = wall_grid.fit_image(image, attempt["width"], attempt["height"], focus)
    path.write_text(json.dumps(fit))
    return fit


def planning_geometry(settings: Settings, row: dict[str, Any], attempt: dict[str, Any], run: dict[str, Any] | None, holds: list[dict[str, Any]], rectify: bool):
    """The wall plane for a hold map when it can be trusted, and what to tell the climber about it."""
    if not rectify:
        return None, {"applied": False, "reason": "Wall-angle correction is switched off."}
    fit = wall_geometry(settings, attempt, row["reference_frame_ms"], wall_paths(settings, row, attempt, run)[0], run["id"] if run else None, holds)
    return wall_grid.correction_for(fit, holds, row["width"], row["height"])


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
        with db.session(settings.database) as connection:
            run = db.row(connection.execute(
                "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone())
        path = wall_paths(settings, row, attempt, run)[0]
        image, info = build_wall_image(settings, attempt, row["reference_frame_ms"], path, run["id"] if run else None)
        return image, info

    @router.get("/api/hold-maps/{map_id}/wall-image")
    def get_wall_image(map_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
        with db.session(settings.database) as connection:
            row, attempt, _ = load(connection, map_id)
            run = db.row(connection.execute(
                "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone())
        wall_image(settings, row, attempt)
        return FileResponse(wall_paths(settings, row, attempt, run)[0], media_type="image/png", headers={"Cache-Control": "no-cache"})

    @router.get("/api/hold-maps/{map_id}/wall-info")
    def get_wall_info(map_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, attempt, _ = load(connection, map_id)
        _, info = wall_image(settings, row, attempt)
        return {**{k: v for k, v in info.items() if k != "registered"}, "image_url": f"/api/hold-maps/{map_id}/wall-image", "combined": info["basis"] != "reference_frame"}

    @router.post("/api/hold-maps/{map_id}/suggestions")
    def suggestions(map_id: str, body: SuggestRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, attempt, holds = load(connection, map_id)
        image, info = wall_image(settings, row, attempt)
        try:
            return {**hold_suggest.suggest(image, body.x, body.y, body.tolerance, holds), "image": {k: v for k, v in info.items() if k != "registered"}}
        except hold_suggest.SuggestionError as error:
            raise HTTPException(422, str(error)) from error

    @router.post("/api/hold-maps/{map_id}/fit")
    def fit(map_id: str, body: SuggestRequest, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        """A circle sized to the colored region under one point. Nothing is saved."""
        with db.session(settings.database) as connection:
            row, attempt, _ = load(connection, map_id)
        image, _ = wall_image(settings, row, attempt)
        try:
            return hold_suggest.fit_region(image, body.x, body.y, body.tolerance)
        except hold_suggest.SuggestionError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/api/hold-maps/{map_id}/wall-geometry")
    def get_wall_geometry(map_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        """The fitted bolt grid for this map's wall picture, so the climber can see whether it sits on the real holes."""
        with db.session(settings.database) as connection:
            row, attempt, holds = load(connection, map_id)
            run = db.row(connection.execute(
                "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone())
        wall_image(settings, row, attempt)
        fit = wall_geometry(settings, attempt, row["reference_frame_ms"], wall_paths(settings, row, attempt, run)[0], run["id"] if run else None, holds)
        _, summary = wall_grid.correction_for(fit, holds, row["width"], row["height"])
        return {"status": fit["status"], "reason": fit.get("reason"), "grid_points": fit.get("grid_points", []), "summary": summary}

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
             rectify: bool = Query(default=True), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            row, attempt, holds = load(connection, map_id)
            latest = db.row(connection.execute(
                "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone())
        public = {"id": row["id"], "name": row["name"], "hold_count": len(holds), "reference_frame_ms": row["reference_frame_ms"], "usable": False,
                  "message": "", "alignment": None, "frame_url": f"/api/hold-maps/{map_id}/wall-image",
                  "holds": [{k: h[k] for k in ("id", "x", "y", "radius", "route", "hold_type", "role", "use", "pull", "start_limb")} for h in holds],
                  "width": row["width"], "height": row["height"]}
        scale = json.loads(row["scale"]) if row["scale"] else None
        measured = beta.body_from_measurements(height_cm, wingspan_cm)
        needs = beta.setup_needed(holds)
        tracked_px = None
        if scale is None:
            with db.session(settings.database) as connection:
                run = db.row(connection.execute(
                    "SELECT id FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (attempt["id"],)).fetchone())
            movement = None if run is None else settings.run_dir(attempt["id"], run["id"]) / "movement.json"
            if movement is not None and movement.exists():
                tracked_px = json.loads(movement.read_text()).get("L_px")
        if scale is None and not tracked_px:
            needs.append("Set the picture's scale: mark two points on the wall and enter the real distance between them.")
        if needs:
            return {"status": "setup_needed", "needs": needs, "candidates": [], "hold_map": public, "body": measured.public(), "method": beta.BETA_VERSION}
        length = beta.torso_px(scale, row["width"], row["height"], measured.torso_cm) if scale else float(tracked_px)
        plane, perspective = planning_geometry(settings, row, attempt, latest, holds, rectify)
        points, to_image, radii = None, None, None
        if plane is not None:
            width, height = row["width"], row["height"]
            if scale:        # the marked line is measured on the wall plane too
                ends = plane.plane([[scale["x1"] * width, scale["y1"] * height], [scale["x2"] * width, scale["y2"] * height]])
                torso_units = float(np.linalg.norm(ends[1] - ends[0])) / scale["cm"] * measured.torso_cm
            else:            # the tracked torso, converted where the holds are
                centroid = [float(np.mean([h["x"] for h in holds])) * width, float(np.mean([h["y"] for h in holds])) * height]
                torso_units = float(tracked_px) * plane.local_scale(centroid)
            points = plane.plane([[h["x"] * width, h["y"] * height] for h in holds]) / torso_units
            to_image = beta.plane_to_image(plane, torso_units, width, height)
            radii = beta.plane_radii(plane, holds, width, height, torso_units)
        output = beta.candidate_sequences(holds, row["width"], row["height"], length, measured.body, points, to_image, radii)
        output["perspective"] = perspective
        for candidate in output["candidates"]:
            signature = json.dumps([candidate["start"], candidate["steps"]], sort_keys=True)
            candidate["id"] = "plan-" + hashlib.sha256(f"{map_id}|{signature}".encode()).hexdigest()[:12]
        output["assumptions"] = [a for a in output.get("assumptions", []) if "tracked limb lengths" not in a] + beta.MEASURED_ASSUMPTIONS
        if scale is None:
            output["assumptions"].append("No scale line was set, so the picture's scale comes from the climber's tracked torso in the video. It assumes the climber in the video is the person whose measurements you entered.")
        return {**output, "hold_map": public, "body": measured.public(), "scale_source": "marked_line" if scale else "tracked_torso",
                "scale": {**(scale or {}), "px_per_cm": round(length / measured.torso_cm, 3)}}

    app.include_router(router)
