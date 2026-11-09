"""Normalization tests on generated clips: pixels and timestamps, not only metadata."""
from __future__ import annotations

import dataclasses
from fractions import Fraction

import numpy as np
import pytest

from app.analysis import ClimbReviewError
from app.analysis import pipeline
from app.analysis import video as v
from conftest import assert_quadrants, encode_frames, quadrant_frame, tag_rotation


def _normalize(source, tmp_path, config):
    p = v.probe(source)
    geometry = v.compute_geometry(p, config.analysis.longest_side_px)
    output = tmp_path / "canonical.mp4"
    v.normalize(source, output, geometry, config.analysis.canonical_fps)
    canonical = v.probe(output)
    frames = v.read_frame_map(output, canonical.time_base, config.analysis.canonical_fps)
    v.verify_canonical(canonical, frames, geometry)
    return p, geometry, canonical, frames, output


def _first_frame(path, canonical):
    return next(v.iter_rgb_frames(path, canonical.width, canonical.height))[1]


def test_landscape_stays_upright_with_exact_timestamps(tmp_path, config):
    source = encode_frames([quadrant_frame(640, 360)] * 30, tmp_path / "landscape.mp4")
    _, _, canonical, frames, output = _normalize(source, tmp_path, config)
    assert (canonical.width, canonical.height) == (640, 360)
    assert frames.frame_count == 30
    assert frames.timestamps_ms[:7] == (0, 33, 67, 100, 133, 167, 200)
    assert frames.timestamps_ms[3 * 9] == 900
    assert_quadrants(_first_frame(output, canonical))


@pytest.mark.parametrize("display_rotation", [-90, 90, 180])
def test_rotated_phone_style_clip_becomes_upright_exactly_once(tmp_path, config, display_rotation):
    """Stored pixels are rotated; metadata says how to display them upright."""
    upright = quadrant_frame(360, 640)
    stored = np.rot90(upright, k=-display_rotation // 90).copy()
    raw = encode_frames([stored] * 15, tmp_path / "raw.mp4")
    source = tag_rotation(raw, tmp_path / "tagged.mp4", display_rotation)
    probe, _, canonical, _, output = _normalize(source, tmp_path, config)
    assert probe.rotation_deg != 0
    assert canonical.rotation_deg == 0
    assert (canonical.width, canonical.height) == (360, 640)
    assert_quadrants(_first_frame(output, canonical))


def test_ten_bit_hevc_rotated_like_a_phone_clip(tmp_path, config):
    """Exercises the codec and bit depth phones commonly record, on generated pixels."""
    stored = np.rot90(quadrant_frame(360, 640), k=1).copy()
    raw = encode_frames([stored] * 15, tmp_path / "raw.mov", extra=[
        "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error:qp=8", "-tag:v", "hvc1",
    ])
    source = tag_rotation(raw, tmp_path / "phone_like.mov", -90)
    probe, _, canonical, _, output = _normalize(source, tmp_path, config)
    assert probe.codec == "hevc" and probe.pix_fmt == "yuv420p10le"
    assert (canonical.codec, canonical.pix_fmt) == ("h264", "yuv420p")
    assert_quadrants(_first_frame(output, canonical))


def test_variable_frame_timing_keeps_media_time(tmp_path, config):
    """Brightness encodes source time, so a frame-count mapping would fail."""
    def source_time(n):
        return n / 60 if n < 30 else 0.5 + (n - 30) / 15

    def luma(t):
        return 40 + 170 * (t / 1.5)

    images = [np.full((180, 320, 3), int(round(luma(source_time(n)))), np.uint8) for n in range(45)]
    source = encode_frames(images, tmp_path / "vfr.mp4", fps=60,
                           filters="setpts='if(lt(N,30),N,30+4*(N-30))'",  # integer ticks of 1/60 s
                           extra=["-fps_mode", "passthrough", "-video_track_timescale", "600", "-bf", "0"])
    probe = v.probe(source)
    timing = v.source_frame_timing(source, probe)
    assert timing["variable_frame_timing"] is True
    assert timing["interval_ms"]["min"] == pytest.approx(1000 / 60, abs=2)
    assert timing["interval_ms"]["max"] == pytest.approx(1000 / 15, abs=2)

    _, _, canonical, frames, output = _normalize(source, tmp_path, config)
    assert abs(frames.duration_ms - probe.duration_ms) <= 67
    for index, rgb in v.iter_rgb_frames(output, canonical.width, canonical.height):
        expected = luma(min(frames.timestamps_ms[index] / 1000, 1.5))
        assert abs(float(rgb[90, 160, 1]) - expected) <= 14, f"frame {index}"


def test_source_with_nonzero_start_time_begins_at_zero(tmp_path, config):
    images = [np.full((180, 320, 3), 60 + 6 * n, np.uint8) for n in range(30)]
    source = encode_frames(images, tmp_path / "offset.mp4", extra=["-output_ts_offset", "1.5"])
    probe, _, canonical, frames, output = _normalize(source, tmp_path, config)
    assert probe.start_time_s == pytest.approx(1.5, abs=0.05)
    assert frames.timestamps_ms[0] == 0
    assert frames.duration_ms == pytest.approx(1000, abs=67)
    assert abs(int(_first_frame(output, canonical)[90, 160, 1]) - 60) <= 12


def test_ntsc_rate_preserves_duration(tmp_path, config):
    images = [np.full((180, 320, 3), 120, np.uint8)] * 60
    source = encode_frames(images, tmp_path / "ntsc.mp4", fps=Fraction(30000, 1001))
    probe, _, _, frames, _ = _normalize(source, tmp_path, config)
    assert abs(frames.duration_ms - probe.duration_ms) <= 67


def test_non_square_pixels_become_square(tmp_path, config):
    source = encode_frames([quadrant_frame(640, 480)] * 10, tmp_path / "sar.mp4", filters="setsar=4/3")
    probe, geometry, canonical, _, output = _normalize(source, tmp_path, config)
    assert probe.sar == Fraction(4, 3)
    assert (canonical.width, canonical.height) == (854, 480)
    assert geometry.aspect_ratio_relative_error < 0.002
    assert_quadrants(_first_frame(output, canonical))


def test_audio_and_metadata_are_removed(tmp_path, config):
    import subprocess

    silent = encode_frames([quadrant_frame(320, 180)] * 15, tmp_path / "video.mp4")
    source = tmp_path / "with_audio.mp4"
    subprocess.run(
        [v.tool_path("ffmpeg"), "-nostdin", "-v", "error", "-i", str(silent), "-f", "lavfi", "-i",
         "anullsrc=r=44100:cl=mono", "-shortest", "-c:v", "copy", "-c:a", "aac",
         "-metadata", "location=+37.0-122.0/", str(source)], check=True,
    )
    assert v.probe(source).has_audio
    _, _, canonical, _, output = _normalize(source, tmp_path, config)
    assert not canonical.has_audio
    tags = subprocess.run([v.tool_path("ffprobe"), "-v", "error", "-show_entries", "format_tags=location",
                           "-of", "csv=p=0", str(output)], capture_output=True, text=True, check=True).stdout
    assert tags.strip() == ""


def _probe_like(**changes):
    base = v.VideoProbe("mov,mp4,m4a,3gp,3g2,mj2", 1000, 1000.0, "h264", None, "yuv420p", 1920, 1080, "1:1", 0,
                        "30/1", "1/30000", 0.0, None, None, False)
    return dataclasses.replace(base, **changes)


@pytest.mark.parametrize("changes,expected", [
    ({"width": 3840, "height": 2160}, (1280, 720)),
    ({"width": 3840, "height": 2160, "rotation_deg": 270}, (720, 1280)),
    ({"width": 640, "height": 360}, (640, 360)),  # no upscaling
    ({"width": 1081, "height": 1921, "rotation_deg": 0}, (720, 1280)),
])
def test_geometry_preserves_aspect_and_limits_longest_side(changes, expected):
    geometry = v.compute_geometry(_probe_like(**changes), 1280)
    assert geometry.canonical_size == expected
    assert max(geometry.canonical_size) <= 1280
    assert geometry.aspect_ratio_relative_error < 0.01
    assert all(side % 2 == 0 for side in geometry.canonical_size)


def test_text_file_named_mp4_is_rejected(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_text("not a video")
    with pytest.raises(v.SourceVideoError):
        v.probe(fake)


def test_container_is_probed_not_trusted_from_extension(tmp_path, config):
    source = encode_frames([quadrant_frame(320, 180)] * 5, tmp_path / "actually.mkv")
    renamed = source.rename(tmp_path / "renamed.mp4")
    with pytest.raises(v.SourceVideoError, match="Unsupported container"):
        v.validate_source(v.probe(renamed), config.analysis)


def test_duration_and_size_limits(config):
    v.validate_source(_probe_like(duration_ms=300_000.0, size_bytes=2_500_000_000), config.analysis)
    with pytest.raises(v.SourceVideoError, match="limit"):
        v.validate_source(_probe_like(duration_ms=300_001.0), config.analysis)
    with pytest.raises(v.SourceVideoError, match="limit"):
        v.validate_source(_probe_like(size_bytes=2_500_000_001), config.analysis)


def test_warnings_flag_hdr_slow_motion_and_sparse_frames(config):
    probe = _probe_like(color_transfer="smpte2084", avg_frame_rate="240/1", duration_ms=1000.0)
    timing = {"interval_ms": {"min": 4.0, "median": 4.0, "max": 150.0}}
    warnings = " ".join(pipeline.source_warnings(probe, timing, config, 1000))
    assert "HDR" in warnings and "slow motion" in warnings and "look like stillness" in warnings


@pytest.mark.parametrize("start,end", [(-1, 500), (500, 500), (600, 500), (0, 1001)])
def test_invalid_attempt_bounds_are_rejected(start, end):
    with pytest.raises(ClimbReviewError):
        pipeline._resolve_bounds(start, end, 1000)


def test_sparse_source_marks_repeated_samples():
    source_ms = [0.0, 500.0, 1000.0]  # 2 fps source; several 10 Hz samples show the same frame
    flags = v.repeated_sample_flags(source_ms, list(range(0, 1100, 100)), 30)
    assert flags == [False, True, True, True, True, False, True, True, True, True, False]


def test_dense_source_has_no_repeated_samples():
    source_ms = [i * 1000 / 30 for i in range(40)]
    assert not any(v.repeated_sample_flags(source_ms, list(range(0, 1300, 100)), 30))


def _hlg_clip(tmp_path, signals):
    """Gray HEVC clip whose patches hold known HLG signal values, tagged like a phone recording."""
    frame = np.zeros((360, 120 * len(signals), 3), np.uint8)
    for i, signal in enumerate(signals):
        frame[:, 120 * i: 120 * (i + 1)] = int(round(signal * 255))
    return encode_frames(
        [frame] * 15, tmp_path / "hlg.mov",
        filters="scale=out_color_matrix=bt2020:out_range=tv,format=yuv420p10le",
        extra=["-c:v", "libx265", "-x265-params", "log-level=error:qp=6:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
               "-tag:v", "hvc1"],
    )


def test_hlg_math_matches_known_operating_points():
    gray = lambda s: v.hlg_signal_to_sdr_signal(np.array([[s, s, s]], dtype=float))[0, 1] * 255
    assert gray(0.0) == pytest.approx(0, abs=1)
    assert gray(0.5) == pytest.approx(143, abs=3)   # about 51 nits scaled to 25% SDR, gamma 2.4
    assert gray(0.75) == pytest.approx(245, abs=4)  # HLG reference white lands near SDR white
    assert gray(1.0) <= 255


def test_hlg_source_is_converted_not_relabeled(tmp_path, config):
    signals = [0.0, 0.25, 0.5, 0.75]
    source = _hlg_clip(tmp_path, signals)
    probe = v.probe(source)
    assert v.is_hlg(probe)
    geometry = v.compute_geometry(probe, config.analysis.longest_side_px)
    output = tmp_path / "canonical.mp4"
    v.normalize(source, output, geometry, 30, tone_map_hlg=True)
    canonical = v.probe(output)
    frame = next(v.iter_rgb_frames(output, canonical.width, canonical.height))[1]
    expected = v.hlg_signal_to_sdr_signal(np.array([[s, s, s] for s in signals], dtype=float))[:, 1] * 255
    measured = [float(frame[180, 60 + 120 * i, 1]) for i in range(len(signals))]
    assert measured == pytest.approx(list(expected), abs=10)
    assert measured[3] > 225  # relabeling HLG as SDR would leave reference white near 191
