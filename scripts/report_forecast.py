#!/usr/bin/env python3
"""Generate a standalone HTML report from stored forecast artifacts. Contains no video frames."""
from __future__ import annotations

import base64
import html
import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from _bootstrap import PROJECT_ROOT  # noqa: E402
from app.forecast import model as md  # noqa: E402
from app.forecast.config import load_forecast_config  # noqa: E402
from app.forecast.dataset import ELIGIBLE_PRIMARY, ELIGIBLE_STRESS, SIDES, constant_velocity_prediction  # noqa: E402

ROOT = PROJECT_ROOT / "data" / "public_training"
COLORS = {"ridge": "#2a78d6", "persistence": "#eb6834", "constant_velocity": "#1baf7a"}
LABELS = {"ridge": "Ridge (learned)", "persistence": "Persistence", "constant_velocity": "Constant velocity"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
METHODS = tuple(LABELS)


def style(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color(GRID)
    axis.tick_params(colors=MUTED, length=0)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)


def encode(figure) -> str:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight", facecolor="#fcfcfb")
    plt.close(figure)
    return base64.b64encode(buffer.getvalue()).decode()


def group_chart(section: dict) -> str:
    groups = sorted(section["per_group"])
    figure, axis = plt.subplots(figsize=(7.2, 3.2))
    width = 0.8 / len(METHODS)
    for offset, method in enumerate(METHODS):
        values = [section["per_group"][g][method]["mae_L"] for g in groups]
        positions = np.arange(len(groups)) + (offset - 1) * width
        axis.bar(positions, values, width * 0.92, color=COLORS[method], label=LABELS[method])
    axis.set_xticks(np.arange(len(groups)), [g.replace("_", " ") for g in groups], color=INK, fontsize=9)
    axis.set_ylabel("Mean endpoint error (torso lengths)", color=MUTED, fontsize=9)
    style(axis)
    axis.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.16), fontsize=9)
    return encode(figure)


def example_chart(data, artifact, config, mask) -> str:
    """Fixed rule: for each test clip, the example nearest the median Ridge error."""
    clips = sorted(set(data["clip"][mask]))
    if not clips:
        return ""
    columns = min(4, len(clips))
    rows = int(np.ceil(len(clips) / columns))
    figure, axes = plt.subplots(rows, columns, figsize=(2.3 * columns, 2.5 * rows), squeeze=False)
    for axis in axes.ravel():
        axis.set_visible(False)
    for axis, clip in zip(axes.ravel(), clips):
        axis.set_visible(True)
        index = np.flatnonzero(mask & (data["clip"] == clip))
        side_indices = {s: index[data["side"][index] == s] for s in SIDES}
        side = max(SIDES, key=lambda s: len(side_indices[s]))
        chosen = side_indices[side]
        predictions = md.predict(artifact["sides"][side], data["features"][chosen])
        errors = md.endpoint_errors(predictions, data["targets"][chosen])
        k = int(np.argsort(errors)[len(errors) // 2])
        row = data["features"][chosen][k]
        window = artifact["sides"][side]["constant_velocity_window_ms"]
        vectors = {"observed": data["targets"][chosen][k], "ridge": predictions[k],
                   "constant_velocity": constant_velocity_prediction(row, side, window, config.horizon_ms),
                   "persistence": np.zeros(2)}
        for name, vector in vectors.items():
            color = INK if name == "observed" else COLORS[name]
            axis.annotate("", xy=(vector[0], -vector[1]), xytext=(0, 0), arrowprops={"arrowstyle": "-|>", "color": color, "lw": 2})
        extent = max(0.25, max(float(np.abs(v).max()) for v in vectors.values()) * 1.25)
        axis.set_xlim(-extent, extent); axis.set_ylim(-extent, extent); axis.set_aspect("equal")
        axis.axhline(0, color=GRID, lw=0.8); axis.axvline(0, color=GRID, lw=0.8)
        axis.set_title(f"{clip[:18]} ({side})", fontsize=8, color=MUTED)
        axis.tick_params(labelsize=7, colors=MUTED, length=0)
        axis.spines[["top", "right", "left", "bottom"]].set_visible(False)
    handles = [plt.Line2D([], [], color=INK, lw=2, label="Observed")] + [plt.Line2D([], [], color=COLORS[m], lw=2, label=LABELS[m]) for m in ("ridge", "constant_velocity")]
    figure.legend(handles=handles, frameon=False, ncol=3, loc="upper center", fontsize=9)
    figure.subplots_adjust(top=1 - 0.5 / (2.5 * rows))
    return encode(figure)


def table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def number(value: float) -> str:
    return f"{value:.4f}"


def section_html(title: str, section: dict) -> str:
    if not section.get("n_examples"):
        return f"<h3>{html.escape(title)}</h3><p>No eligible examples.</p>"
    rows = [[LABELS[m], number(section["pooled"][m]["mae_L"]), number(section["pooled"][m]["rmse_L"]), number(section["macro_group_mae_L"][m]),
             number(section["macro_clip_mae_L"][m])] for m in METHODS]
    wins = section["groups_where_ridge_beats"]
    return (f"<h3>{html.escape(title)}</h3><p>{section['n_examples']} examples, {section['n_clips']} clips, {section['n_groups']} groups. Overlapping windows are correlated, so the examples are not independent.</p>"
            + table(["Method", "Pooled MAE (L)", "Pooled RMSE (L)", "Macro-group MAE (L)", "Macro-clip MAE (L)"], rows)
            + f"<p>Ridge had lower group MAE than persistence in {wins['persistence']} of {section['n_groups']} groups and than constant velocity in {wins['constant_velocity']} of {section['n_groups']} groups.</p>")


def main() -> int:
    config = load_forecast_config(PROJECT_ROOT / "config" / "forecast.yaml")
    results = json.loads((PROJECT_ROOT / "evaluation" / "forecast" / f"results_{config.version}.json").read_text())
    artifact = json.loads((ROOT / "models" / f"{config.version}.json").read_text())
    selection = json.loads((ROOT / "models" / f"{config.version}_selection.json").read_text())
    data = np.load(ROOT / "dataset" / f"{config.version}.npz")
    sources = json.loads((PROJECT_ROOT / "config" / "public_training_sources.json").read_text())["sources"]
    split = json.loads((PROJECT_ROOT / "config" / "public_training_split.json").read_text())
    primary = (data["split"] == "test") & np.isin(data["status"], (ELIGIBLE_PRIMARY, ELIGIBLE_STRESS))
    all_windows = results["held_out_test_all_windows"]
    test = all_windows
    parts = [
        "<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Wrist-motion forecast</title>"
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1b1f24;background:#fcfcfb}table{border-collapse:collapse;width:100%;margin:8px 0 16px;font-size:.88rem}th,td{border-bottom:1px solid #dfe2e6;padding:5px 6px;text-align:left}img{max-width:100%}.note{background:#fff7e0;border:1px solid #e8d48a;border-radius:6px;padding:10px}</style>",
        "<h1>Experimental wrist-motion forecast</h1>",
        "<p class=note><strong>What this is:</strong> a Ridge model predicting where a tracked wrist moves relative to the hips over the next 0.5 s. Targets are later pose estimates, not human ground truth. It is separate from pose inference, from the event rules, and from any technique judgment. Errors are in torso lengths, not centimeters.</p>",
        section_html("Held-out public test groups, all reliable windows", all_windows),
        section_html("Held-out public test groups, steady camera only", results["held_out_test_primary"]),
    ]
    if test.get("n_examples"):
        parts.append(f"<img alt='Mean endpoint error by test group for each method' src='data:image/png;base64,{group_chart(test)}'>")
        rows = [[g.replace("_", " "), test["per_group"][g]["ridge"]["n"]] + [number(test["per_group"][g][m]["mae_L"]) for m in METHODS] for g in sorted(test["per_group"])]
        parts.append(table(["Group", "Examples", *[LABELS[m] for m in METHODS]], rows))
        parts.append("<h3>Example predictions</h3><p>For each test clip, the example nearest the median Ridge error, chosen by a fixed rule. Arrows show displacement over 0.5 s from the wrist's position, with image-up as up. Axis units are torso lengths.</p>")
        parts.append(f"<img alt='Observed versus predicted wrist displacement examples' src='data:image/png;base64,{example_chart(data, artifact, config, primary)}'>")
    parts.append(section_html("Held-out test groups, camera moving (stress)", results["held_out_test_camera_moving_stress"]))
    parts.append(section_html("Personal development clips, steady camera (stress, not held out)", results["personal_dev_stress_primary"]))
    parts.append(section_html("Personal development clips, camera moving (stress)", results["personal_dev_stress_camera_moving"]))
    parts.append("<h2>Model selection (training groups only)</h2>")
    parts.append(table(["Side", "Examples", "Groups", "Clips", "Chosen alpha", "CV window"], [[s, v["n_examples"], v["n_groups"], v["n_clips"], v["alpha"], f"{v['constant_velocity_window_ms']} ms"] for s, v in selection.items()]))
    parts.append("<h2>Split</h2>" + table(["Group", "Split"], sorted(split["groups"].items())) + f"<p>{html.escape(split['rule'])} Earlier public development clips were train-only. The two reserved personal clips were not used.</p>")
    parts.append("<h2>Sources</h2>" + table(["Clip", "Group", "Event", "Author", "License", "Source"], [[s["clip_id"], s["group_id"], s["event_id"], s["author"], s["license"], s["page_url"]] for s in sources]))
    parts.append(f"<p>Model {html.escape(results['model_sha256'][:16])}, dataset {html.escape(results['dataset_content_sha256'][:16])}.</p></html>")
    output = ROOT / "report"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"training_report_{config.version}.html").write_text("".join(parts))
    print(output / f"training_report_{config.version}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
