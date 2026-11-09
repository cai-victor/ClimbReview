"""Causality, target correctness, grouping, baselines, and model persistence."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from app.forecast import dataset as ds
from app.forecast import model as md
from app.forecast.config import load_forecast_config
from app.forecast.split import freeze_split
from conftest import PROJECT_ROOT, no_pose_record, pose_record

W, H = 720, 1280
L_PX = 0.2 * H


@pytest.fixture(scope="module")
def fc():
    return load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")


def rec(i, t=None, **over):
    base = {"left_wrist": (0.3, 0.3), "right_wrist": (0.7, 0.3), "left_elbow": (0.35, 0.4), "right_elbow": (0.65, 0.4)}
    overrides = {k: {"x": v[0], "y": v[1]} for k, v in base.items()}
    for key, value in over.items():
        overrides[key] = value
    record = pose_record(i * 3, (i * 100) if t is None else t, **overrides)
    record.update({"camera_shift_px": 0.0, "camera_shift_response": 0.9, "repeated_source_frame": False})
    return record


def track(count=30, wrist_L_per_s=0.0, body_shift=0.0):
    rows = []
    for i in range(count):
        seconds = i / 10
        dx = wrist_L_per_s * seconds * L_PX / W
        shift = body_shift * seconds * L_PX / W
        over = {"left_wrist": {"x": 0.3 + dx + shift, "y": 0.3}}
        if body_shift:
            for name in ("right_wrist", "left_elbow", "right_elbow", "left_shoulder", "right_shoulder", "left_hip", "right_hip"):
                x0 = {"right_wrist": 0.7, "left_elbow": 0.35, "right_elbow": 0.65, "left_shoulder": 0.45, "right_shoulder": 0.55, "left_hip": 0.45, "right_hip": 0.55}[name]
                y0 = {"right_wrist": 0.3, "left_elbow": 0.4, "right_elbow": 0.4, "left_shoulder": 0.3, "right_shoulder": 0.3, "left_hip": 0.5, "right_hip": 0.5}[name]
                over[name] = {"x": x0 + shift, "y": y0}
        rows.append(rec(i, **over))
    return rows


def make(records, i, fc, config, side="left"):
    return ds.build_example(records, i, side, W, H, config.quality, fc)


def test_future_samples_cannot_change_features(fc, config):
    records = track(30, 0.8)
    original = make(records, 15, fc, config)
    changed = copy.deepcopy(records)
    for r in changed[16:]:
        for lm in r["landmarks"]:
            lm["x"], lm["y"] = 0.11, 0.97
    # Features come only from the history slice; the target and validity differ, not the inputs.
    history = changed[15 - fc.history_steps: 16]
    features, _ = ds.features_from_history(history, "left", W, H)
    assert np.array_equal(original.features, features)


def test_history_scale_ignores_future_torso(fc, config):
    records = track(30)
    changed = copy.deepcopy(records)
    for r in changed[16:]:
        for lm in r["landmarks"]:
            if "hip" in lm["name"]:
                lm["y"] += 0.1
    a = make(records, 15, fc, config)
    b = make(changed, 15, fc, config)
    assert a.scale_px == pytest.approx(L_PX)
    assert a.scale_px == b.scale_px and np.array_equal(a.features, b.features)


def test_target_is_body_relative_displacement_in_torso_lengths(fc, config):
    example = make(track(30, 0.8), 15, fc, config)
    assert example.status == ds.ELIGIBLE_PRIMARY
    assert example.target == pytest.approx([0.4, 0.0], abs=1e-9)  # 0.8 L/s for 0.5 s


def test_whole_body_translation_is_not_wrist_motion(fc, config):
    example = make(track(30, 0.0, body_shift=0.2), 15, fc, config)
    assert example.target == pytest.approx([0.0, 0.0], abs=1e-9)


def test_pixel_geometry_changes_with_axis_on_non_square_frame(fc, config):
    def moving(axis):
        rows = []
        for i in range(30):
            delta = 0.01 * i
            rows.append(rec(i, left_wrist={"x": 0.3 + (delta if axis == "x" else 0), "y": 0.3 + (delta if axis == "y" else 0)}))
        return rows
    x_target = make(moving("x"), 15, fc, config).target
    y_target = make(moving("y"), 15, fc, config).target
    assert x_target[0] == pytest.approx(0.05 * W / L_PX)
    assert y_target[1] == pytest.approx(0.05 * H / L_PX)


def test_constant_velocity_baseline_is_exact_on_linear_motion(fc, config):
    example = make(track(30, 0.8), 15, fc, config)
    prediction = ds.constant_velocity_prediction(example.features, "left", 300, fc.horizon_ms)
    assert prediction == pytest.approx(example.target, abs=1e-9)


@pytest.mark.parametrize("mutate,reason", [
    (lambda r: r[15].update({"landmarks": None, "pose_detected": False}), "history_landmark_unavailable"),
    (lambda r: [lm.update(visibility=0.1) for lm in r[10]["landmarks"] if lm["name"] == "left_elbow"], "history_landmark_unavailable"),
    (lambda r: [lm.update(visibility=0.1) for lm in r[20]["landmarks"] if lm["name"] == "left_wrist"], "target_or_horizon_landmark_unavailable"),
    (lambda r: [lm.update(visibility=0.1) for lm in r[18]["landmarks"] if lm["name"] == "left_wrist"], "target_or_horizon_landmark_unavailable"),
    (lambda r: r[12].update(timestamp_ms=r[12]["timestamp_ms"] + 90), "non_contiguous_history"),
    (lambda r: r[17].update(timestamp_ms=r[17]["timestamp_ms"] + 90), "non_contiguous_horizon"),
    (lambda r: r[12].update(repeated_source_frame=True), "repeated_source_frame_in_history"),
    (lambda r: r[18].update(repeated_source_frame=True), "repeated_source_frame_in_horizon"),
])
def test_missing_or_broken_windows_are_rejected_not_filled(fc, config, mutate, reason):
    records = track(30, 0.8)
    mutate(records)
    example = make(records, 15, fc, config)
    assert example.status == "rejected" and example.reason == reason
    assert example.features is None and example.target is None


def test_boundaries_require_real_history_and_future(fc, config):
    records = track(30)
    assert make(records, 3, fc, config).reason == "insufficient_history"
    assert make(records, 26, fc, config).reason == "no_target_sample"


def test_no_pose_target_rejected(fc, config):
    records = track(30)
    records[20] = no_pose_record(60, 2000)
    assert make(records, 15, fc, config).reason == "target_or_horizon_landmark_unavailable"


def test_implausible_torso_rejected_using_history_scale(fc, config):
    records = track(30)
    for name in ("left_hip", "right_hip"):
        [lm.update(y=0.31) for lm in records[20]["landmarks"] if lm["name"] == name]
    assert make(records, 15, fc, config).reason == "implausible_torso_at_target"


def test_camera_motion_is_a_stress_flag_not_an_input(fc, config):
    records = track(30, 0.8)
    moving = copy.deepcopy(records)
    for r in moving[6:21]:
        r["camera_shift_px"], r["camera_shift_response"] = 60.0, 0.9
    a, b = make(records, 15, fc, config), make(moving, 15, fc, config)
    assert a.status == ds.ELIGIBLE_PRIMARY and b.status == ds.ELIGIBLE_STRESS
    assert np.array_equal(a.features, b.features)


SOURCES = [{"clip_id": f"c{i}", "group_id": g, "event_id": e} for i, (g, e) in enumerate([
    ("a", "e1"), ("a", "e2"), ("b", "e1"), ("c", "e1"), ("d", "e1"), ("e", "e2"), ("f", "e2"), ("g", "e2"), ("h", "e3"),
])]


def test_split_keeps_groups_together_and_is_deterministic():
    first = freeze_split(SOURCES, 317)
    assert first == freeze_split(list(reversed(SOURCES)), 317)
    assert first["clips"]["c0"]["split"] == first["clips"]["c1"]["split"]
    assert set(first["groups"].values()) == {"train", "test"}


def _synthetic(n=400, side="left"):
    rng = np.random.default_rng(0)
    features = rng.normal(size=(n, len(ds.feature_names(side))))
    targets = np.c_[features[:, 0] * 0.3, features[:, 1] * -0.2] + rng.normal(scale=0.01, size=(n, 2))
    return features, targets, np.array([f"g{i % 8}" for i in range(n)])


def test_selection_folds_never_share_groups(fc, monkeypatch):
    seen = []
    original = md.GroupKFold

    class Recording(original):
        def split(self, X, y=None, groups=None):
            for a, b in super().split(X, y, groups):
                seen.append(set(groups[a]) & set(groups[b]))
                yield a, b

    monkeypatch.setattr(md, "GroupKFold", Recording)
    x, y, g = _synthetic()
    chosen = md.select_hyperparameters(x, y, g, "left", fc)
    assert seen and all(not overlap for overlap in seen) and chosen["alpha"] in fc.ridge_alphas


def test_saved_model_reproduces_sklearn_predictions_and_is_deterministic(tmp_path, fc):
    x, y, _ = _synthetic()
    artifact = md.fit_side_model(x, y, "left", 10.0, 300)
    again = md.fit_side_model(x, y, "left", 10.0, 300)
    assert md.canonical_json(artifact) == md.canonical_json(again)
    path = tmp_path / "m.json"
    path.write_text(md.canonical_json({"left": artifact}))
    loaded = md.load_model(path)["left"]
    direct = md._fit(x, y, 10.0).predict(x)
    assert md.predict(loaded, x) == pytest.approx(direct, abs=1e-9)
