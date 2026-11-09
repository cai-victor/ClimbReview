"""Performance review endpoints. Results are computed from stored analysis files, so existing runs are not reprocessed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import cv2
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .analysis import alignment as alignment_module
from .analysis import beta, coaching
from .holds import frame_path
from .settings import Settings, require_id

COMPARE_MIN_COVERAGE = 0.6
ALIGNMENT_MESSAGES = {
    None: "Check this hold map against the video before comparing marks with your movement.",
    "camera_moved": "The background moved relative to the reference frame, so these marks cannot be compared with tracked joints.",
    "could_not_verify": "The background could not be measured well enough to confirm the marks line up with the video.",
}


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["unreviewed", "will_try", "intentional", "disagree", "cannot_tell"] = "unreviewed"
    trial_outcome: Literal["not_tried", "helped", "no_change", "worse", "unclear"] = "not_tried"
    note: str = Field(default="", max_length=2000)


class PlacementReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["unreviewed", "on_marked_hold", "on_unmarked_hold", "intentional_smear", "not_placed", "cannot_tell"] = "unreviewed"
    hold_id: str | None = None
    note: str = Field(default="", max_length=1000)


def _candidate_id(map_id: str, candidate: dict[str, Any]) -> str:
    signature = json.dumps([candidate["start"], candidate["steps"]], sort_keys=True)
    return "beta-" + hashlib.sha256(f"{map_id}|{signature}".encode()).hexdigest()[:12]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def register_coaching(app: FastAPI, get_settings) -> None:
    router = APIRouter()

    def load_run(connection, run_id: str, settings: Settings) -> tuple[dict[str, Any], dict[str, Any], Path]:
        job = db.row(connection.execute("SELECT * FROM jobs WHERE id=? AND kind='analysis'", (require_id(run_id),)).fetchone())
        if job is None:
            raise HTTPException(404, "Analysis not found.")
        if job["status"] != "complete":
            raise HTTPException(409, "This analysis has no completed results.")
        attempt = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (job["attempt_id"],)).fetchone())
        return job, attempt, settings.run_dir(job["attempt_id"], job["id"])

    def read_files(directory: Path) -> dict[str, Any] | None:
        names = {"result": "result.json", "events": "events.json", "movement": "movement.json", "overlay": "overlay.json"}
        if not all((directory / name).exists() for name in names.values()):
            return None
        return {key: json.loads((directory / name).read_text()) for key, name in names.items()}

    def maps_of(connection, attempt_id: str) -> list[dict[str, Any]]:
        maps = [dict(r) for r in connection.execute("SELECT * FROM hold_maps WHERE attempt_id=? ORDER BY created_at DESC", (attempt_id,))]
        for item in maps:
            item["holds"] = [dict(h) for h in connection.execute("SELECT * FROM holds WHERE map_id=? ORDER BY created_at, id", (item["id"],))]
        return maps

    def alignment_of(connection, map_id: str, run_id: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT detail FROM hold_map_alignment WHERE map_id=? AND run_id=?", (map_id, run_id)).fetchone()
        return json.loads(row["detail"]) if row else None

    def hold_context(connection, attempt_id: str, run_id: str, map_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        maps = [m for m in maps_of(connection, attempt_id) if m["holds"]]
        chosen = next((m for m in maps if m["id"] == map_id), None) if map_id else (maps[0] if maps else None)
        if chosen is None:
            return None, None
        check = alignment_of(connection, chosen["id"], run_id)
        status = None if check is None else check["status"]
        usable = status == "fixed_verified"
        context = {"usable": usable, "holds": chosen["holds"], "message": ALIGNMENT_MESSAGES.get(status, "")}
        public = {"id": chosen["id"], "name": chosen["name"], "hold_count": len(chosen["holds"]), "reference_frame_ms": chosen["reference_frame_ms"],
                  "alignment": check, "usable": usable, "message": context["message"], "frame_url": f"/api/attempts/{attempt_id}/frame?ms={chosen['reference_frame_ms']}",
                  "holds": [{k: h[k] for k in ("id", "x", "y", "radius", "route", "hold_type", "role", "use")} for h in chosen["holds"]]}
        return context, public

    def compute(connection, job, attempt, directory, map_id: str | None) -> dict[str, Any]:
        files = read_files(directory)
        if files is None or "foot_motion_left" not in files["result"]["detection"]["detectors"]:
            return {"available": False, "needs_reanalysis": True, "version": coaching.COACHING_VERSION,
                    "reason": "This older analysis has no foot data. Reanalyze the attempt to get performance review."}
        context, public_map = hold_context(connection, attempt["id"], job["id"], map_id)
        output = coaching.build_coaching(files["result"], files["events"]["events"], files["movement"], files["overlay"]["samples"],
                                         attempt["width"], attempt["height"], context)
        output["hold_map"] = public_map
        output["attempt_bounds_ms"] = files["result"]["attempt_bounds_ms"]
        return output

    def merge_reviews(connection, run_id: str, output: dict[str, Any]) -> dict[str, Any]:
        if not output.get("available"):
            return output
        rows = {r["cue_id"]: dict(r) for r in connection.execute("SELECT * FROM coaching_feedback WHERE run_id=?", (run_id,))}
        blank = {"decision": "unreviewed", "trial_outcome": "not_tried", "note": ""}
        for card in output["cards"]:
            stored = rows.get(card["id"])
            card["feedback"] = {k: stored[k] for k in blank} if stored else dict(blank)
        reviews = {r["placement_id"]: dict(r) for r in connection.execute("SELECT * FROM foot_placement_reviews WHERE run_id=?", (run_id,))}
        for item in output["placements"]:
            stored = reviews.get(item["id"])
            item["review"] = {k: stored[k] for k in ("status", "hold_id", "note")} if stored else {"status": "unreviewed", "hold_id": None, "note": ""}
        chosen = [c for c in output["cards"] if c["feedback"]["decision"] == "will_try"]
        open_cards = [c for c in output["cards"] if c["feedback"]["decision"] == "unreviewed"]
        output["plan"] = {"chosen": [{"id": c["id"], "title": c["title"], "start_ms": c["start_ms"], "try_this": c["try_this"], "trial_outcome": c["feedback"]["trial_outcome"]} for c in chosen],
                          "suggested": None if chosen or not open_cards else {"id": open_cards[0]["id"], "title": open_cards[0]["title"], "start_ms": open_cards[0]["start_ms"], "try_this": open_cards[0]["try_this"]}}
        return output

    @router.get("/api/analyses/{run_id}/coaching")
    def get_coaching(run_id: str, map_id: str | None = Query(default=None), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, attempt, directory = load_run(connection, run_id, settings)
            return merge_reviews(connection, job["id"], compute(connection, job, attempt, directory, map_id))

    @router.put("/api/analyses/{run_id}/coaching/{cue_id}")
    def put_decision(run_id: str, cue_id: str, body: Decision, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, attempt, directory = load_run(connection, run_id, settings)
            output = compute(connection, job, attempt, directory, None)
            known = {c["id"] for c in output.get("cards", [])}
            known |= {c["id"] for item in connection.execute("SELECT detail FROM candidate_ids WHERE run_id=?", (job["id"],)) for c in json.loads(item["detail"])}
            if cue_id not in known:
                raise HTTPException(404, "That suggestion is not part of this analysis.")
            connection.execute(
                """INSERT INTO coaching_feedback(run_id, cue_id, decision, trial_outcome, note, updated_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(run_id, cue_id) DO UPDATE SET decision=excluded.decision, trial_outcome=excluded.trial_outcome, note=excluded.note, updated_at=excluded.updated_at""",
                (job["id"], cue_id, body.decision, body.trial_outcome, body.note, db.now()))
            return body.model_dump()

    @router.put("/api/analyses/{run_id}/placements/{placement_id}")
    def put_placement(run_id: str, placement_id: str, body: PlacementReview, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, attempt, directory = load_run(connection, run_id, settings)
            output = compute(connection, job, attempt, directory, None)
            if placement_id not in {p["id"] for p in output.get("placements", [])}:
                raise HTTPException(404, "That foot placement is not part of this analysis.")
            if body.status == "on_marked_hold":
                known = {h["id"] for h in (output.get("hold_map") or {}).get("holds", [])}
                if body.hold_id not in known:
                    raise HTTPException(422, "Choose which marked hold the foot was on.")
            elif body.hold_id is not None:
                raise HTTPException(422, "Only a placement on a marked hold has a hold.")
            connection.execute(
                """INSERT INTO foot_placement_reviews(run_id, placement_id, status, hold_id, note, updated_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(run_id, placement_id) DO UPDATE SET status=excluded.status, hold_id=excluded.hold_id, note=excluded.note, updated_at=excluded.updated_at""",
                (job["id"], placement_id, body.status, body.hold_id, body.note, db.now()))
            return body.model_dump()

    @router.post("/api/analyses/{run_id}/hold-maps/{map_id}/alignment")
    def check_alignment(run_id: str, map_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, attempt, directory = load_run(connection, run_id, settings)
            row = db.row(connection.execute("SELECT * FROM hold_maps WHERE id=? AND attempt_id=?", (require_id(map_id), attempt["id"])).fetchone())
        if row is None:
            raise HTTPException(404, "Hold map not found for this attempt.")
        samples = json.loads((directory / "overlay.json").read_text())["samples"]
        by_time = sorted(samples, key=lambda s: s["t"])

        def read_frame(ms: int):
            image = cv2.imread(str(frame_path(settings, attempt, ms)))
            return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        def nearest(ms: int):
            best = min(by_time, key=lambda s: abs(s["t"] - ms), default=None)
            return best if best is not None and abs(best["t"] - ms) <= 100 else None

        bounds = (job["attempt_start_ms"], job["attempt_end_ms"])
        detail = alignment_module.check_reference(read_frame, row["reference_frame_ms"], alignment_module.check_times(*bounds), nearest)
        with db.session(settings.database) as connection:
            connection.execute(
                """INSERT INTO hold_map_alignment(map_id, run_id, status, detail, updated_at) VALUES (?,?,?,?,?)
                   ON CONFLICT(map_id, run_id) DO UPDATE SET status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at""",
                (map_id, job["id"], detail["status"], json.dumps(detail), db.now()))
        return detail

    @router.get("/api/analyses/{run_id}/candidate-beta")
    def candidate_beta(run_id: str, map_id: str | None = Query(default=None), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            job, attempt, directory = load_run(connection, run_id, settings)
            _, public = hold_context(connection, attempt["id"], job["id"], map_id)
            files = read_files(directory)
            if public is None:
                return {"status": "no_map", "needs": ["Mark the holds on this route to get candidate sequences."], "candidates": [], "hold_map": None}
            if files is None:
                return {"status": "setup_needed", "needs": ["Reanalyze this attempt so reach lengths can be estimated."], "candidates": [], "hold_map": public}
            length = files["movement"]["L_px"]
            body = None if not length else beta.body_model(files["overlay"]["samples"], attempt["width"], attempt["height"], length)
            output = beta.candidate_sequences(public["holds"], attempt["width"], attempt["height"], length or 1.0, body)
            for candidate in output["candidates"]:
                candidate["id"] = _candidate_id(public["id"], candidate)
            if output["candidates"]:
                connection.execute("INSERT INTO candidate_ids(run_id, detail) VALUES (?,?) ON CONFLICT(run_id) DO UPDATE SET detail=excluded.detail",
                                   (job["id"], json.dumps([{"id": c["id"]} for c in output["candidates"]])))
            rows = {r["cue_id"]: dict(r) for r in connection.execute("SELECT * FROM coaching_feedback WHERE run_id=?", (job["id"],))}
            blank = {"decision": "unreviewed", "trial_outcome": "not_tried", "note": ""}
            for candidate in output["candidates"]:
                stored = rows.get(candidate["id"])
                candidate["feedback"] = {k: stored[k] for k in blank} if stored else dict(blank)
            return {**output, "hold_map": public}

    @router.get("/api/attempts/{attempt_id}/comparison")
    def comparison(attempt_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
        with db.session(settings.database) as connection:
            target = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (require_id(attempt_id),)).fetchone())
            if target is None:
                raise HTTPException(404, "Attempt not found.")
            problem, climber = _norm(target["problem_label"]), _norm(target["climber_label"])
            base = {"meaning": "Outcome is what you entered. Other rows are tracking proxies, shown only when both feet were analyzable for most of the attempt. They do not show that one attempt was better."}
            if not problem or not climber:
                return {**base, "status": "needs_labels", "attempts": []}
            rows = [dict(r) for r in connection.execute("SELECT * FROM attempts WHERE status='ready' ORDER BY created_at")]
            matched = [r for r in rows if _norm(r["problem_label"]) == problem and _norm(r["climber_label"]) == climber]
            attempts = []
            for row in matched:
                job = db.row(connection.execute("SELECT * FROM jobs WHERE attempt_id=? AND kind='analysis' AND status='complete' ORDER BY created_at DESC LIMIT 1", (row["id"],)).fetchone())
                item: dict[str, Any] = {"id": row["id"], "title": row["title"], "outcome": row["outcome"], "is_current": row["id"] == attempt_id, "run_id": None, "metrics": None}
                if job:
                    directory = settings.run_dir(row["id"], job["id"])
                    output = compute(connection, job, row, directory, None)
                    if output.get("available"):
                        files = read_files(directory)
                        item["run_id"] = job["id"]
                        item["metrics"] = _metrics(files, output)
                attempts.append(item)
            return {**base, "status": "ready" if sum(a["metrics"] is not None for a in attempts) >= 2 else "no_match", "attempts": attempts}

    def _metrics(files: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        coverage = files["result"]["coverage"]["detectors"]
        detection = files["result"]["detection"]["detectors"]
        bounds = files["result"]["attempt_bounds_ms"]
        fractions = [coverage[k]["fraction"] for k in ("foot_motion_left", "foot_motion_right")]
        covered = all(f is not None and f >= COMPARE_MIN_COVERAGE for f in fractions)
        eligible_ms = sum(coverage[k]["eligible_ms"] or 0 for k in ("foot_motion_left", "foot_motion_right"))
        steps = sum(detection[k]["event_count"] or 0 for k in ("foot_motion_left", "foot_motion_right"))
        tally = output["reach_tally"]
        kinds: dict[str, int] = {}
        for card in output["cards"]:
            kinds[card["kind"]] = kinds.get(card["kind"], 0) + 1
        return {"attempt_ms": bounds["end"] - bounds["start"], "foot_coverage": fractions, "coverage_ok": covered,
                "foot_moves_per_analyzable_minute": round(steps / (eligible_ms / 120000), 1) if covered and eligible_ms else None,
                "reaches_evaluated": tally["reaches_evaluated"], "reaches_with_foot_setup": tally["with_foot_setup_before"] if covered else None,
                "suggestion_counts": kinds if covered else None}

    app.include_router(router)
