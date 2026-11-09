"""Orchestrates one feasibility run and writes its versioned outputs."""
from __future__ import annotations

import csv
import json
import platform
import shutil
import time
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import PIPELINE_VERSION, SCHEMA_VERSION, ClimbReviewError
from . import overlay as overlay_module
from . import pose as pose_module
from . import quality, video

ALIGNMENT_NOT_REVIEWED = {
    "status": "not_reviewed",
    "note": "Software cannot establish alignment. A person must inspect overlay.mp4 and contact_sheet.jpg.",
}
PROVENANCE_CHOICES = ("user_supplied_unverified", "synthetic_test_media")


def _resolve_bounds(start: int | None, end: int | None, duration_ms: int) -> tuple[int, int]:
    resolved_start = 0 if start is None else start
    resolved_end = duration_ms if end is None else end
    if not 0 <= resolved_start < resolved_end <= duration_ms:
        raise ClimbReviewError(
            f"Invalid attempt bounds {resolved_start}-{resolved_end} ms; need 0 <= start < end <= {duration_ms}."
        )
    return resolved_start, resolved_end


def source_warnings(p: video.VideoProbe, timing: dict[str, Any], cfg, canonical_ms: int) -> list[str]:
    warnings: list[str] = []
    if p.color_transfer in video.HDR_TRANSFERS:
        warnings.append(
            f"Source is HDR ({p.color_transfer}). This FFmpeg build cannot tone-map, so canonical colors may look "
            "washed out, which could affect pose quality. Prefer recording with HDR off."
        )
    intervals = timing.get("interval_ms")
    if intervals and intervals["max"] > cfg.analysis.sample_period_ms:
        warnings.append(
            f"Source has a {intervals['max']:.0f} ms frame interval, longer than the "
            f"{cfg.analysis.sample_period_ms:.0f} ms sample period. Repeated canonical frames can look like stillness."
        )
    rate = video._ratio(p.avg_frame_rate)
    if rate is not None and rate > 90:
        warnings.append(
            f"Source averages {float(rate):.0f} fps and may be slow motion. It is analyzed at encoded playback "
            "time; original capture timing is not reconstructed."
        )
    if p.duration_ms is not None and abs(canonical_ms - p.duration_ms) > 2000 / cfg.analysis.canonical_fps:
        warnings.append(f"Canonical duration {canonical_ms} ms differs from source {p.duration_ms:.0f} ms.")
    return warnings


def environment_record() -> dict[str, Any]:
    import cv2
    import mediapipe

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "mediapipe": mediapipe.__version__,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "ffmpeg": video.tool_version("ffmpeg"),
        "ffprobe": video.tool_version("ffprobe"),
    }


def _write_timeline(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def _percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def render_report(run: dict[str, Any]) -> str:
    coverage = run["coverage"]
    scale = coverage["attempt_scale"]
    lines = [
        f"# Feasibility report: {run['clip_id']}",
        "",
        f"**Data provenance:** `{run['data_provenance']}`",
        "",
        "**Tracking quality on this clip is UNVERIFIED until a person inspects the overlay.** "
        "The coverage below counts landmarks the model reported as usable. It does not show they are on the right joints.",
        "",
        f"- Canonical video: {run['canonical']['width']}x{run['canonical']['height']}, "
        f"{run['canonical']['frame_count']} frames, {run['canonical']['duration_ms']} ms",
        f"- Attempt bounds: {run['attempt_bounds_ms']['start']}-{run['attempt_bounds_ms']['end']} ms (canonical media time)",
        f"- Sampled frames: {coverage['sampled_frames']}; pose returned on "
        f"{coverage['pose_detected_samples']} ({_percent(coverage['pose_detected_fraction'])})",
        f"- Attempt scale: {scale['status']}, L = {scale['L_px']} px from {scale['reliable_samples']} samples",
        f"- Inference: {run['runtime_s']['pose_extraction']:.2f} s, "
        f"{run['runtime_s']['inference_samples_per_s']:.1f} samples/s on {run['pose_model']['options']['delegate']}",
        "",
        "| Detector | Status | Eligible ms | Attempt ms | Fraction | Longest segment ms | Gaps |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, item in coverage["detectors"].items():
        status = item["status"] if item["reason"] is None else f"{item['status']} ({item['reason']})"
        eligible = "null" if item["eligible_ms"] is None else item["eligible_ms"]
        lines.append(f"| {name} | {status} | {eligible} | {item['attempt_ms']} | {_percent(item['fraction'])} | "
                     f"{item['longest_eligible_segment_ms']} | {len(item['gaps'])} |")
    lines += ["", "## Warnings", ""]
    lines += [f"- {w}" for w in run["warnings"]] or ["- None recorded."]
    lines += [
        "", "## Manual review (fill in after watching overlay.mp4)", "",
        "- [ ] Upright orientation is correct",
        "- [ ] Skeleton sits on the climber's joints during ordinary movement",
        "- [ ] Overlay stays on the intended climber (no jump to another person)",
        "- [ ] Left/right labels do not swap",
        "- [ ] Hands and feet are visible when reported as available",
        "- Notes on occlusion, implausible positions, and unsupported conditions:",
        "",
    ]
    return "\n".join(lines)


DetectorFactory = Callable[[], Any]


def run_analysis(
    source: Path, output: Path, config, project_root: Path, clip_id: str,
    attempt_start_ms: int | None = None, attempt_end_ms: int | None = None,
    data_provenance: str = "user_supplied_unverified", overwrite: bool = False,
    detector_factory: DetectorFactory | None = None,
) -> dict[str, Any]:
    """Run the feasibility stages. Outputs appear at `output` only on full success."""
    if data_provenance not in PROVENANCE_CHOICES:
        raise ClimbReviewError(f"Unknown data provenance: {data_provenance}")
    if not source.is_file():
        raise ClimbReviewError(f"Video not found: {source}")
    if output.exists() and not overwrite:
        raise ClimbReviewError(f"Output already exists: {output}. Pass --overwrite to replace it.")
    if output.exists() and not (output / "run.json").exists():
        raise ClimbReviewError(f"Refusing to replace {output}: it is not a previous run directory.")

    model_path = project_root / config.pose_model.model_path
    manifest = pose_module.load_verified_model_manifest(model_path, project_root / config.pose_model.manifest_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / f".{output.name}.partial-{uuid.uuid4().hex[:8]}"
    work.mkdir()
    try:
        run = _run_stages(source, work, config, manifest, model_path, clip_id, attempt_start_ms, attempt_end_ms,
                          data_provenance, detector_factory)
        if output.exists():
            shutil.rmtree(output)
        work.rename(output)
        return run
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_stages(
    source: Path, work: Path, config, manifest: dict[str, Any], model_path: Path, clip_id: str,
    attempt_start_ms: int | None, attempt_end_ms: int | None, data_provenance: str,
    detector_factory: DetectorFactory | None,
) -> dict[str, Any]:
    fps = config.analysis.canonical_fps
    runtime: dict[str, float] = {}

    print("[1/5] Probing and normalizing source", flush=True)
    began = time.perf_counter()
    source_probe = video.probe(source)
    video.validate_source(source_probe, config.analysis)
    timing = video.source_frame_timing(source, source_probe)
    geometry = video.compute_geometry(source_probe, config.analysis.longest_side_px)
    canonical_path = work / "canonical.mp4"
    args = video.normalize(source, canonical_path, geometry, fps)
    canonical_probe = video.probe(canonical_path)
    frames = video.read_frame_map(canonical_path, canonical_probe.time_base, fps)
    video.verify_canonical(canonical_probe, frames, geometry)
    start_ms, end_ms = _resolve_bounds(attempt_start_ms, attempt_end_ms, frames.duration_ms)
    runtime["normalization"] = time.perf_counter() - began

    print("[2/5] Extracting pose landmarks", flush=True)
    size = geometry.canonical_size
    indices = pose_module.sample_frame_indices(frames, config.analysis.frame_stride, start_ms, end_ms)
    began = time.perf_counter()
    factory = detector_factory or (lambda: pose_module.MediaPipePoseDetector(model_path, config.pose_model))
    with factory() as detector:
        records = pose_module.extract_poses(canonical_path, size, frames, indices, detector)
    runtime["pose_extraction"] = time.perf_counter() - began
    runtime["inference_samples_per_s"] = len(records) / runtime["pose_extraction"] if records else 0.0
    pose_module.write_jsonl(records, work / "poses.jsonl")

    print("[3/5] Computing tracking coverage", flush=True)
    coverage = quality.compute_coverage(
        records, size[0], size[1], start_ms, end_ms, config.quality, config.analysis.sample_period_ms,
        config.feasibility.low_movement_target_fraction,
    )
    _write_timeline(quality.timeline_rows(records, config.quality), work / "coverage_timeline.csv")
    (work / "coverage.json").write_text(json.dumps(coverage, indent=2, allow_nan=False) + "\n")

    print("[4/5] Rendering diagnostic overlay", flush=True)
    began = time.perf_counter()
    overlay_module.render_overlay(canonical_path, size, records, config.quality, config.analysis.inference_fps,
                                  work / "overlay.mp4", work / "contact_sheet.jpg")
    runtime["overlay_render"] = time.perf_counter() - began

    print("[5/5] Writing run record", flush=True)
    run: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "id": f"run-{uuid.uuid4().hex[:12]}",
        "clip_id": clip_id,
        "pipeline_version": PIPELINE_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_provenance": data_provenance,
        "visual_alignment_review": ALIGNMENT_NOT_REVIEWED,
        "timebase": "canonical_video_ms",
        "attempt_bounds_ms": {"start": start_ms, "end": end_ms},
        "source": {
            "filename": source.name,
            "sha256": pose_module.sha256_file(source),
            "probe": source_probe.to_dict(),
            "frame_timing": timing,
        },
        "canonical": {
            "width": size[0], "height": size[1], "fps": fps,
            "frame_count": frames.frame_count, "duration_ms": frames.duration_ms,
            "probe": canonical_probe.to_dict(),
        },
        "transform": {
            **geometry.__dict__,
            "ffmpeg_args": ["-i", "<source>", *args, "<canonical.mp4>"],
        },
        "sampling": {
            "inference_fps": config.analysis.inference_fps,
            "frame_stride": config.analysis.frame_stride,
            "first_frame_index": indices[0] if indices else None,
            "sample_count": len(indices),
        },
        "pose_model": {**manifest, "options": config.pose_model.model_dump(exclude={"model_path", "manifest_path"}),
                       "running_mode": "VIDEO"},
        "config_hash": config.content_hash(),
        "config": config.model_dump(),
        "environment": environment_record(),
        "runtime_s": runtime,
        "coverage": coverage,
        "warnings": source_warnings(source_probe, timing, config, frames.duration_ms),
        "artifacts": ["canonical.mp4", "poses.jsonl", "coverage.json", "coverage_timeline.csv",
                      "overlay.mp4", "contact_sheet.jpg", "report.md", "run.json"],
    }
    (work / "run.json").write_text(json.dumps(run, indent=2, allow_nan=False, default=_json_default) + "\n")
    (work / "report.md").write_text(render_report(run))
    return run


def _json_default(value: Any) -> Any:
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Not JSON serializable: {type(value)}")


