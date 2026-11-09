"""Probing, canonical normalization, and frame/time mapping via FFmpeg.

All FFmpeg calls use argument arrays (never shell strings). The canonical video
is upright, square-pixel, constant-frame-rate H.264 starting at time zero; every
later timestamp in the project is a media millisecond of that file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from . import ClimbReviewError
from .config import AnalysisConfig

HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}
# ffprobe reports both MP4 and MOV as this demuxer; the extension is not trusted.
SUPPORTED_DEMUXER = "mov"


class SourceVideoError(ClimbReviewError):
    """The source file cannot be accepted or decoded."""


def tool_path(name: str) -> str:
    """Prefer the project environment's FFmpeg tools over anything on PATH."""
    local = Path(sys.prefix) / "bin" / name
    found = str(local) if local.exists() else shutil.which(name)
    if not found:
        raise ClimbReviewError(f"{name} is missing. Run scripts/setup_env.sh, then use .venv/bin/python.")
    return found


def tool_version(name: str) -> str:
    return subprocess.run([tool_path(name), "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]


def _ratio(value: Any) -> Fraction | None:
    """Parse ffprobe ratios such as '30000/1001' or '4:3'; 0 or N/A become None."""
    if not value or value in {"N/A", "0/0", "0:1"}:
        return None
    try:
        parsed = Fraction(str(value).replace(":", "/"))
    except (ValueError, ZeroDivisionError):
        return None
    return parsed if parsed > 0 else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class VideoProbe:
    demuxer: str
    size_bytes: int
    duration_ms: float | None
    codec: str
    profile: str | None
    pix_fmt: str | None
    width: int
    height: int
    sample_aspect_ratio: str
    rotation_deg: int
    avg_frame_rate: str | None
    time_base: str
    start_time_s: float | None
    color_transfer: str | None
    color_primaries: str | None
    has_audio: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sar(self) -> Fraction:
        return _ratio(self.sample_aspect_ratio) or Fraction(1)


def _rotation_from_stream(stream: dict[str, Any]) -> int:
    """Return rotation as a right angle in [0, 360), rejecting anything else."""
    raw: Any = None
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            raw = side["rotation"]
            break
    if raw is None:
        raw = stream.get("tags", {}).get("rotate", 0)
    value = _float(raw) or 0.0
    if value % 90:
        raise SourceVideoError(
            f"Video has a non-right-angle rotation ({value} degrees). Re-export it upright."
        )
    return int(value) % 360


def probe(path: Path) -> VideoProbe:
    result = subprocess.run(
        [tool_path("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SourceVideoError(f"Video could not be read: {result.stderr.strip() or 'ffprobe failed'}")
    info = json.loads(result.stdout)
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise SourceVideoError("File has no video stream.")
    v = videos[0]
    duration_s = _float(v.get("duration")) or _float(fmt.get("duration"))
    return VideoProbe(
        demuxer=fmt.get("format_name", ""),
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        duration_ms=None if duration_s is None else duration_s * 1000,
        codec=v.get("codec_name", "unknown"),
        profile=v.get("profile"),
        pix_fmt=v.get("pix_fmt"),
        width=int(v["width"]),
        height=int(v["height"]),
        sample_aspect_ratio=v.get("sample_aspect_ratio") or "1:1",
        rotation_deg=_rotation_from_stream(v),
        avg_frame_rate=v.get("avg_frame_rate"),
        time_base=v["time_base"],
        start_time_s=_float(v.get("start_time")),
        color_transfer=v.get("color_transfer"),
        color_primaries=v.get("color_primaries"),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def validate_source(p: VideoProbe, cfg: AnalysisConfig) -> None:
    """Apply project limits to what the file actually contains."""
    if SUPPORTED_DEMUXER not in p.demuxer.split(","):
        raise SourceVideoError(f"Unsupported container ({p.demuxer}). Provide an MP4 or MOV file.")
    if p.duration_ms is None:
        raise SourceVideoError("Video duration could not be determined. Re-export the clip as MP4.")
    if p.duration_ms > cfg.max_duration_s * 1000:
        raise SourceVideoError(
            f"Video lasts {p.duration_ms / 1000:.1f} s; the limit is {cfg.max_duration_s:g} s. Trim it first."
        )
    if p.size_bytes > cfg.max_upload_mb * 1_000_000:
        raise SourceVideoError(
            f"File is {p.size_bytes / 1e6:.1f} MB; the limit is {cfg.max_upload_mb:g} MB. Trim or re-export it."
        )


def _packet_seconds(path: Path, time_base: str) -> list[Fraction]:
    """Presentation times of every video packet, in display order."""
    result = subprocess.run(
        [tool_path("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts",
         "-print_format", "json", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SourceVideoError(f"Could not read frame timing: {result.stderr.strip()}")
    base = Fraction(time_base)
    pts = [p["pts"] for p in json.loads(result.stdout).get("packets", []) if p.get("pts") not in (None, "N/A")]
    return sorted(Fraction(int(x)) * base for x in pts)


def source_times_ms(path: Path, time_base: str) -> list[float]:
    """Source frame presentation times relative to the first frame."""
    times = _packet_seconds(path, time_base)
    return [float((t - times[0]) * 1000) for t in times] if times else []


def repeated_sample_flags(source_ms: list[float], sample_ms: list[int], canonical_fps: int) -> list[bool]:
    """True where a sample shows the same source frame as the previous sample.

    Constant-rate conversion repeats frames when the source has large frame gaps.
    A repeated frame carries no new observation, so it must not look like stillness.
    """
    if not source_ms:
        return [False] * len(sample_ms)
    source = np.asarray(source_ms)
    half_frame = 500 / canonical_fps
    ids = np.searchsorted(source, np.asarray(sample_ms, dtype=float) + half_frame, side="right") - 1
    return [False, *[bool(a == b) for a, b in zip(ids, ids[1:])]][: len(sample_ms)]


def source_frame_timing(path: Path, p: VideoProbe) -> dict[str, Any]:
    """Describe the source's real frame spacing so variable timing is explicit."""
    times = _packet_seconds(path, p.time_base)
    if len(times) < 2:
        return {"frame_count": len(times), "variable_frame_timing": None,
                "interval_ms": None, "first_pts_ms": float(times[0] * 1000) if times else None}
    intervals = np.array([float((b - a) * 1000) for a, b in zip(times, times[1:])])
    return {
        "frame_count": len(times),
        "first_pts_ms": float(times[0] * 1000),
        "interval_ms": {
            "min": float(intervals.min()), "median": float(np.median(intervals)), "max": float(intervals.max()),
        },
        # Descriptive only: > 2 ms of spread exceeds container timestamp rounding.
        "variable_frame_timing": bool(intervals.max() - intervals.min() > 2.0),
    }


@dataclass(frozen=True)
class CanonicalGeometry:
    """Exact mapping from coded source pixels to canonical pixels."""
    source_coded_size: tuple[int, int]
    source_sar: str
    rotation_deg: int
    upright_display_size: tuple[float, float]
    canonical_size: tuple[int, int]
    scale_x: float
    scale_y: float
    aspect_ratio_relative_error: float


def compute_geometry(p: VideoProbe, longest_side_px: int) -> CanonicalGeometry:
    """Apply SAR, then rotation, then a uniform downscale rounded to even sizes."""
    display_w, display_h = float(p.width * p.sar), float(p.height)
    if p.rotation_deg in (90, 270):
        display_w, display_h = display_h, display_w
    longest = max(display_w, display_h)
    scale = min(1.0, longest_side_px / longest)
    width = max(2, 2 * round(display_w * scale / 2))
    height = max(2, 2 * round(display_h * scale / 2))
    return CanonicalGeometry(
        source_coded_size=(p.width, p.height),
        source_sar=p.sample_aspect_ratio,
        rotation_deg=p.rotation_deg,
        upright_display_size=(display_w, display_h),
        canonical_size=(width, height),
        scale_x=width / display_w,
        scale_y=height / display_h,
        aspect_ratio_relative_error=abs((width / height) / (display_w / display_h) - 1),
    )


def normalization_args(geometry: CanonicalGeometry, canonical_fps: int) -> list[str]:
    """FFmpeg arguments between input and output paths.

    FFmpeg's default autorotate applies the display matrix exactly once, before
    this filter graph, and the output carries no rotation metadata.
    """
    width, height = geometry.canonical_size
    video_filter = (
        "setpts=PTS-STARTPTS,"
        f"fps=fps={canonical_fps}:round=near,"
        f"scale={width}:{height}:flags=lanczos:out_color_matrix=bt709:out_range=tv,"
        "setsar=1,format=yuv420p"
    )
    return [
        "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", video_filter, "-fps_mode", "passthrough",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
        "-bf", "0", "-g", str(canonical_fps // 2),
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-video_track_timescale", str(canonical_fps * 1000),
        "-movflags", "+faststart",
    ]


def normalize(
    source: Path, output: Path, geometry: CanonicalGeometry, canonical_fps: int,
    check_cancel: Callable[[], None] | None = None,
) -> list[str]:
    """Create the canonical file. `check_cancel` may raise to stop FFmpeg."""
    args = normalization_args(geometry, canonical_fps)
    command = [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", str(source), *args, str(output)]
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stderr=stderr, stdout=subprocess.DEVNULL)
        try:
            while process.poll() is None:
                if check_cancel is not None:
                    check_cancel()
                time.sleep(0.1)
        except BaseException:
            process.kill()
            process.wait()
            output.unlink(missing_ok=True)
            raise
        if process.returncode != 0:
            output.unlink(missing_ok=True)
            stderr.seek(0)
            detail = stderr.read().decode(errors="replace").strip()[-600:]
            raise SourceVideoError(f"Video could not be decoded: {detail}")
    return args


@dataclass(frozen=True)
class FrameMap:
    """Actual presentation time of each canonical frame, indexed by frame number."""
    timestamps_ms: tuple[int, ...]
    frame_period_ms: float

    @property
    def frame_count(self) -> int:
        return len(self.timestamps_ms)

    @property
    def duration_ms(self) -> int:
        return round(self.frame_count * self.frame_period_ms)


def read_frame_map(path: Path, time_base: str, canonical_fps: int) -> FrameMap:
    times = _packet_seconds(path, time_base)
    if not times:
        raise SourceVideoError("Normalization produced no video frames.")
    return FrameMap(tuple(round(t * 1000) for t in times), 1000 / canonical_fps)


def verify_canonical(p: VideoProbe, frames: FrameMap, geometry: CanonicalGeometry) -> None:
    """Post-conditions every later stage relies on; violation is a pipeline bug."""
    problems = []
    if p.rotation_deg != 0:
        problems.append(f"rotation metadata {p.rotation_deg}")
    if (p.width, p.height) != geometry.canonical_size:
        problems.append(f"size {p.width}x{p.height} != {geometry.canonical_size}")
    if p.sar != 1:
        problems.append(f"non-square pixels {p.sample_aspect_ratio}")
    if p.codec != "h264" or p.pix_fmt != "yuv420p":
        problems.append(f"codec/pix_fmt {p.codec}/{p.pix_fmt}")
    if p.has_audio:
        problems.append("audio present")
    if frames.timestamps_ms[0] != 0:
        problems.append(f"first frame at {frames.timestamps_ms[0]} ms")
    expected = [round(i * frames.frame_period_ms) for i in range(frames.frame_count)]
    if list(frames.timestamps_ms) != expected:
        problems.append("frame timestamps are not constant-rate")
    if problems:
        raise ClimbReviewError("Canonical video failed verification: " + "; ".join(problems))


def iter_rgb_frames(path: Path, width: int, height: int) -> Iterator[tuple[int, np.ndarray]]:
    """Decode every frame, in order, as RGB. Stops FFmpeg if the caller stops early."""
    frame_bytes = width * height * 3
    process = subprocess.Popen(
        [tool_path("ffmpeg"), "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0", "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    try:
        index = 0
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                return
            yield index, np.frombuffer(buffer, np.uint8).reshape(height, width, 3)
            index += 1
    finally:
        process.stdout.close()
        process.terminate()
        process.wait()
