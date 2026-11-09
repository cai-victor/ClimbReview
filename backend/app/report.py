"""Summaries and exports built from stored results; no numbers are recomputed elsewhere."""
from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from .analysis.explain import attempt_digest, clock as digest_clock, limb_of

QUALITY_ORDER = {"good": 0, "fair": 1, "weak": 2}
CSV_COLUMNS = ["event_id", "type", "hand", "start_ms", "end_ms", "duration_ms", "truncated", "tracking_quality",
               "observation", "interpretation", "reflection_question", "detection_judgment", "usefulness",
               "context_tags", "note", "limb", "direction", "max_displacement_L", "net_displacement_L", "peak_speed_L_per_s",
               "context"]


def summarize(result: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Attempt-level counts using each detector's eligible time as its denominator."""
    coverage = result["coverage"]["detectors"]
    detection = result["detection"]["detectors"]
    low = coverage["low_movement"]
    digest = attempt_digest(result, events)
    low_events = [e for e in events if e["type"] == "low_movement"]
    low_ms = sum(e["end_ms"] - e["start_ms"] for e in low_events)
    ranked = sorted(events, key=lambda e: (QUALITY_ORDER[e["tracking_quality"]["label"]], -(e["end_ms"] - e["start_ms"])))
    bounds = result["attempt_bounds_ms"]
    return {
        "attempt_duration_ms": bounds["end"] - bounds["start"],
        "eligible": {name: {"eligible_ms": item["eligible_ms"], "fraction": item["fraction"], "status": item["status"]}
                     for name, item in coverage.items()},
        "low_movement_total_ms": low_ms if low["status"] == "available" else None,
        "low_movement_fraction_of_eligible": (round(low_ms / low["eligible_ms"], 4)
                                              if low["status"] == "available" and low["eligible_ms"] else None),
        "wrist_episode_counts": {side: detection[f"wrist_motion_{side}"]["event_count"] for side in ("left", "right")},
        "foot_analysis_available": digest is not None,
        "foot_episode_counts": {side: (detection.get(f"foot_motion_{side}") or {}).get("event_count") for side in ("left", "right")},
        "digest": digest,
        "review_priority": {
            "meaning": "A suggested order for rewatching, by tracking quality and duration. Not mistake severity.",
            "event_ids": [e["id"] for e in ranked[:3]],
        },
    }


def _review_fields(event: dict[str, Any]) -> list[Any]:
    review = event["review"]
    feedback = event["feedback"]
    evidence = event["evidence"]
    return [event["id"], event["type"], event["hand"] or "", event["start_ms"], event["end_ms"],
            event["end_ms"] - event["start_ms"], event["truncated"], event["tracking_quality"]["label"],
            feedback["observation"], feedback["interpretation"], feedback["reflection_question"],
            review["detection_judgment"], review["usefulness"], ";".join(review["context_tags"]), review["note"],
            limb_of(event) or "", evidence.get("direction", ""), evidence.get("max_displacement_L", ""),
            evidence.get("net_displacement_L", ""), evidence.get("peak_speed_L_per_s", ""), feedback.get("context", "")]


def events_csv(events: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for event in events:
        writer.writerow(_review_fields(event))
    return buffer.getvalue()


def _clock(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "n/a"
    minutes, seconds = divmod(milliseconds / 1000, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


def _percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.1f}%"


def full_export(attempt: dict[str, Any], run: dict[str, Any], result: dict[str, Any], events: list[dict[str, Any]],
                reflection: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "1.0", "attempt": attempt, "analysis_run": run, "result": result,
            "summary": summarize(result, events), "events": events, "reflection": reflection}


LABELS = {"low_movement": "Low visible movement", "wrist_motion": "Wrist movement", "foot_motion": "Foot movement"}
REPORT_CSS = """body{font:15px/1.5 system-ui,sans-serif;margin:24px auto;max-width:860px;padding:0 16px;color:#1b1f24}
table{border-collapse:collapse;width:100%;margin:8px 0 20px}th,td{border:1px solid #ccd2d9;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f1f3f5}.note{background:#fff7e0;border:1px solid #e8d48a;padding:10px;border-radius:6px}
.event{border:1px solid #ccd2d9;border-radius:6px;padding:10px 14px;margin:10px 0}h3{margin:4px 0}@media print{.event{break-inside:avoid}}"""


def html_report(export: dict[str, Any]) -> str:
    e = html.escape
    attempt, result, summary = export["attempt"], export["result"], export["summary"]
    parts = [f"<!doctype html><html lang=en><meta charset=utf-8><title>ClimbReview report: {e(attempt['title'])}</title>",
             f"<style>{REPORT_CSS}</style><h1>{e(attempt['title'])}</h1>"]
    parts.append("<p class=note>Events describe what was visible in the video. They are not technique scores. "
                 "Tracking labels are descriptive, not probabilities. Times are canonical-video time.</p>")
    bounds = result["attempt_bounds_ms"]
    parts.append(f"<p>Attempt: {_clock(bounds['start'])} to {_clock(bounds['end'])}. Route: {e(attempt['route_name']) or 'not recorded'}."
                 f" Grade: {e(attempt['grade']) or 'not recorded'}. Pipeline {e(result['pipeline_version'])}, "
                 f"detectors {e(result['detection']['detector_version'])}, configuration {e(result['config_hash'][:12])}.</p>")
    parts.append("<h2>Tracking coverage</h2><table><tr><th>Detector<th>Status<th>Eligible time<th>Fraction of attempt<th>Events")
    for name, item in result["coverage"]["detectors"].items():
        count = result["detection"]["detectors"][name]["event_count"]
        parts.append(f"<tr><td>{e(name)}<td>{e(item['status'])}<td>{'unavailable' if item['eligible_ms'] is None else _clock(item['eligible_ms'])}"
                     f"<td>{_percent(item['fraction'])}<td>{'unavailable' if count is None else count}")
    parts.append("</table>")
    parts.append(f"<p>Low visible movement: {_percent(summary['low_movement_fraction_of_eligible'])} of eligible time.</p>")
    if result["warnings"]:
        parts.append("<h2>Warnings</h2><ul>" + "".join(f"<li>{e(w)}" for w in result["warnings"]) + "</ul>")
    digest = summary.get("digest")
    if digest is None:
        parts.append("<p class=note>This analysis was made before foot tracking was added. Reanalyze the attempt to add left and right foot movement.</p>")
    else:
        parts.append("<h2>What moved</h2><table><tr><th>Limb<th>Episodes (uncertain)<th>Time analyzable<th>Largest movement")
        for item in digest["limbs"].values():
            parts.append(f"<tr><td>{e(item['label'])}<td>{'unavailable' if item['episodes'] is None else str(item['episodes']) + ' (' + str(item['uncertain_episodes']) + ')'}"
                         f"<td>{_percent(item['analyzable_fraction'])}<td>{e(item['largest']['text']) if item['largest'] else 'none'}")
        parts.append(f"</table><p>{e(digest['meaning'])}</p>")
        if digest["phases"]:
            parts.append("<h2>Sequence</h2><ul>" + "".join(f"<li>{digest_clock(p['start_ms'])}: {e(p['text'])}" for p in digest["phases"]) + "</ul>")
        if digest["repeated"]:
            parts.append("<h2>Repeated movement</h2><ul>" + "".join(f"<li>{e(r['text'])}" for r in digest["repeated"]) + "</ul>")
        if digest["rewatch"]:
            parts.append("<h2>Worth rewatching</h2><ul>" + "".join(f"<li>{digest_clock(r['start_ms'])}: {e(r['reason'])}" for r in digest["rewatch"]) + "</ul>")
        if digest["limits"]:
            parts.append("<h2>Where tracking prevents a conclusion</h2><ul>" + "".join(f"<li>{e(n['text'])}" for n in digest["limits"]) + "</ul>")
        if digest["prompts"]:
            parts.append("<h2>Questions for reflection</h2><ul>" + "".join(f"<li>{e(p)}" for p in digest["prompts"]) + "</ul>")
    parts.append("<h2>Events</h2>")
    if not export["events"]:
        parts.append("<p>No events were detected. This does not indicate good or bad climbing.</p>")
    for event in export["events"]:
        title = LABELS[event["type"]] + (f" ({event['hand']})" if event["hand"] else "")
        feedback, review = event["feedback"], event["review"]
        parts.append(
            f"<div class=event><h3>{_clock(event['start_ms'])} to {_clock(event['end_ms'])}: {e(title)}</h3>"
            f"<p><b>Observed:</b> {e(feedback['observation'])}</p>{'<p><b>At the same time:</b> ' + e(feedback['context']) + '</p>' if feedback.get('context') else ''}<p><b>Possible interpretation:</b> {e(feedback['interpretation'])}</p>"
            f"<p><b>Reflect:</b> {e(feedback['reflection_question'])}</p>"
            f"<p>Tracking quality (descriptive): {e(event['tracking_quality']['label'])}. "
            f"Your judgment: {e(review['detection_judgment'])}; usefulness: {e(review['usefulness'])}"
            f"{'; tags: ' + e(', '.join(review['context_tags'])) if review['context_tags'] else ''}.</p>"
            f"{'<p><b>Your note:</b> ' + e(review['note']) + '</p>' if review['note'] else ''}</div>")
    reflection = export["reflection"]
    parts.append(f"<h2>Reflection</h2><p><b>Observation:</b> {e(reflection['observation']) or 'none recorded'}</p>"
                 f"<p><b>Next-attempt focus:</b> {e(reflection['next_focus']) or 'none recorded'}</p>")
    parts.append("<h2>Reproducibility</h2><pre>" + e(json.dumps(
        {"pose_model_sha256": result["pose_model"]["sha256"], "environment": result["environment"]}, indent=2)) + "</pre></html>")
    return "".join(parts)
