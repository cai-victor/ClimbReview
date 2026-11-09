"""The one dedicated local worker process for heavy jobs.

A file lock guarantees a single worker. Each job is claimed by an atomic SQL update.
Partial output is written to a temporary directory and only renamed on success.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import sys
import time
import traceback
from typing import Any

from . import db
from .analysis import PIPELINE_VERSION, ClimbReviewError
from .analysis import pipeline, video
from .analysis.config import PipelineConfig
from .analysis.detectors import DETECTOR_VERSION
from .analysis.pose import MediaPipePoseDetector, load_verified_model_manifest, sample_frame_indices, write_jsonl
from .analysis.quality import explain_gaps, overlay_samples
from .settings import PROJECT_ROOT, Settings, load_pipeline_config, load_settings


class JobCancelled(Exception):
    pass


class WorkerShutdown(Exception):
    pass


class Worker:
    def __init__(self, settings: Settings, config: PipelineConfig):
        self.settings = settings
        self.config = config
        self.stopping = False

    # ---- job state helpers
    def _update(self, job_id: str, **fields: Any) -> None:
        assignments = ", ".join(f"{key}=?" for key in fields)
        with db.session(self.settings.database) as connection:
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*fields.values(), job_id))

    def _check(self, job_id: str) -> None:
        if self.stopping:
            raise WorkerShutdown()
        with db.session(self.settings.database) as connection:
            requested = connection.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
        if requested is None or requested["cancel_requested"]:
            raise JobCancelled()

    # ---- main loop
    def process_one(self) -> bool:
        with db.session(self.settings.database) as connection:
            job = db.claim_next_job(connection, os.getpid())
        if job is None:
            return False
        try:
            if job["kind"] == "import":
                self._run_import(job)
            else:
                self._run_analysis(job)
            self._update(job["id"], status="complete", stage="complete", finished_at=db.now())
        except JobCancelled:
            self._finish_unsuccessful(job, "cancelled", "Cancelled.")
        except WorkerShutdown:
            self._finish_unsuccessful(job, "interrupted", "The worker stopped before this job finished. Start it again to retry.")
        except ClimbReviewError as error:
            self._finish_unsuccessful(job, "failed", str(error))
        except Exception:  # A job must never take the worker down or stay 'running'.
            self._finish_unsuccessful(job, "failed", "Analysis failed unexpectedly. See diagnostic details.",
                                      traceback.format_exc())
        return True

    def _finish_unsuccessful(self, job: dict[str, Any], status: str, message: str, detail: str | None = None) -> None:
        self._update(job["id"], status=status, error=message, error_detail=detail, finished_at=db.now())
        if job["kind"] == "import":
            with db.session(self.settings.database) as connection:
                connection.execute("UPDATE attempts SET status='failed', error=? WHERE id=?", (message, job["attempt_id"]))
            directory = self.settings.attempt_dir(job["attempt_id"])
            (directory / "canonical.mp4").unlink(missing_ok=True)
            (directory / "canonical.partial.mp4").unlink(missing_ok=True)

    # ---- import
    def _run_import(self, job: dict[str, Any]) -> None:
        job_id, attempt_id = job["id"], job["attempt_id"]
        directory = self.settings.attempt_dir(attempt_id)
        with db.session(self.settings.database) as connection:
            attempt = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone())
        source = directory / f"source{attempt['source_ext']}"
        analysis_config = self.config.analysis
        self._update(job_id, stage="normalizing")
        probe = video.probe(source)
        video.validate_source(probe, analysis_config)
        timing = video.source_frame_timing(source, probe)
        geometry = video.compute_geometry(probe, analysis_config.longest_side_px)
        canonical = directory / "canonical.mp4"
        partial = directory / "canonical.partial.mp4"
        args = video.normalize(source, partial, geometry, analysis_config.canonical_fps,
                               lambda: self._check(job_id), tone_map_hlg=video.is_hlg(probe))
        canonical_probe = video.probe(partial)
        frames = video.read_frame_map(partial, canonical_probe.time_base, analysis_config.canonical_fps)
        video.verify_canonical(canonical_probe, frames, geometry)
        partial.replace(canonical)
        warnings = pipeline.source_warnings(probe, timing, self.config, frames.duration_ms)
        metadata = {
            "source_probe": probe.to_dict(), "source_frame_timing": timing,
            "canonical_probe": canonical_probe.to_dict(), "transform": {**geometry.__dict__, "ffmpeg_args": args,
            "color_conversion": "hlg_bt2020_to_sdr_bt709_lut_v1" if video.is_hlg(probe) else "none"},
            "source_times_ms": video.source_times_ms(source, probe.time_base),
        }
        (directory / "media.json").write_text(json.dumps(metadata, default=list, allow_nan=False))
        with db.session(self.settings.database) as connection:
            connection.execute(
                """UPDATE attempts SET status='ready', error=NULL, width=?, height=?, fps=?, frame_count=?, duration_ms=?,
                   attempt_start_ms=COALESCE(attempt_start_ms,0), attempt_end_ms=COALESCE(attempt_end_ms,?), warnings=? WHERE id=?""",
                (geometry.canonical_size[0], geometry.canonical_size[1], analysis_config.canonical_fps,
                 frames.frame_count, frames.duration_ms, frames.duration_ms, db.dumps(warnings), attempt_id))

    # ---- analysis
    def _run_analysis(self, job: dict[str, Any]) -> None:
        job_id, attempt_id = job["id"], job["attempt_id"]
        directory = self.settings.attempt_dir(attempt_id)
        with db.session(self.settings.database) as connection:
            attempt = db.row(connection.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone())
        media = json.loads((directory / "media.json").read_text())
        canonical = directory / "canonical.mp4"
        pose_config = self.config.pose_model
        model_path = PROJECT_ROOT / pose_config.model_path
        manifest = load_verified_model_manifest(model_path, PROJECT_ROOT / pose_config.manifest_path)
        frames = video.read_frame_map(canonical, media["canonical_probe"]["time_base"], self.config.analysis.canonical_fps)
        size = (attempt["width"], attempt["height"])
        start_ms, end_ms = job["attempt_start_ms"], job["attempt_end_ms"]
        indices = sample_frame_indices(frames, self.config.analysis.frame_stride, start_ms, end_ms)
        self._update(job_id, stage="extracting_pose", progress_total=len(indices), progress_done=0,
                     config_hash=self.config.content_hash(), pipeline_version=PIPELINE_VERSION, detector_version=DETECTOR_VERSION)

        def on_progress(done: int, total: int) -> None:
            if done % 5 == 0 or done == total:
                self._update(job_id, progress_done=done)
            self._check(job_id)

        started = time.perf_counter()
        with MediaPipePoseDetector(model_path, pose_config) as detector:
            analysis = pipeline.analyze_canonical(
                canonical, size, frames, indices, start_ms, end_ms, self.config, detector, media["source_times_ms"],
                on_progress, lambda stage: self._update(job_id, stage=stage))
        self._check(job_id)
        self._update(job_id, stage="generating_report")
        run_dir = self.settings.run_dir(attempt_id, job_id)
        partial = run_dir.with_name(run_dir.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        try:
            explain_gaps(analysis["coverage"], analysis["records"], analysis["validity"])
            pipeline.write_analysis_files(partial, analysis, self.config)
            overlay = overlay_samples(analysis["records"], analysis["validity"])
            (partial / "overlay.json").write_text(json.dumps(overlay, allow_nan=False, separators=(",", ":")))
            warnings = [*json.loads(attempt["warnings"]), *pipeline.analysis_warnings(analysis["coverage"])]
            result = {
                "schema_version": "1.0", "timebase": "canonical_video_ms", "pipeline_version": PIPELINE_VERSION,
                "attempt_bounds_ms": {"start": start_ms, "end": end_ms},
                "config_hash": self.config.content_hash(), "config": self.config.model_dump(),
                "pose_model": {**manifest, "options": pose_config.model_dump(exclude={"model_path", "manifest_path"}),
                               "running_mode": "VIDEO"},
                "environment": pipeline.environment_record(),
                "runtime_s": {"analysis": time.perf_counter() - started},
                "coverage": analysis["coverage"],
                "detection": {"detector_version": analysis["detection"]["detector_version"],
                              "detectors": analysis["detection"]["detectors"]},
                "warnings": warnings,
                "visual_alignment_review": pipeline.ALIGNMENT_NOT_REVIEWED,
            }
            (partial / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False, default=list))
            partial.replace(run_dir)
        finally:
            shutil.rmtree(partial, ignore_errors=True)
        summary = {
            "low_movement_fraction": analysis["coverage"]["detectors"]["low_movement"]["fraction"],
            "event_count": len(analysis["detection"]["events"]),
        }
        self._update(job_id, summary=db.dumps(summary))


def run_forever(settings: Settings, config: PipelineConfig) -> int:
    settings.prepare()
    db.initialize(settings.database)
    lock = settings.worker_lock.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("error: another ClimbReview worker is already running.", file=sys.stderr)
        return 2
    with db.session(settings.database) as connection:
        count = db.mark_interrupted_jobs(connection)
    if count:
        print(f"Marked {count} job(s) from an earlier worker as interrupted.", flush=True)
    worker = Worker(settings, config)

    def stop(*_: object) -> None:
        worker.stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Worker ready.", flush=True)
    while not worker.stopping:
        if not worker.process_one():
            time.sleep(0.4)
    return 0


def main() -> int:
    return run_forever(load_settings(), load_pipeline_config())


if __name__ == "__main__":
    raise SystemExit(main())
