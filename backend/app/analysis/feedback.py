"""Deterministic, versioned event wording generated only from stored evidence."""
from __future__ import annotations

from typing import Any

LOW_TEMPLATE = "low-movement-v1"
WRIST_TEMPLATE = "wrist-motion-v1"


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.1f}"


def feedback_for(event: dict[str, Any]) -> dict[str, str]:
    evidence = event["evidence"]
    if event["type"] == "low_movement":
        return {
            "template_version": LOW_TEMPLATE,
            "observation": f"The tracked wrists, ankles, and hips moved little in the video for about "
                           f"{_seconds(evidence['duration_ms'])} seconds.",
            "interpretation": "This could be a planned rest, a moment of route planning, or something else. "
                              "The video alone cannot say which.",
            "reflection_question": "Was this pause intentional, and what were you deciding here?",
        }
    side = event["hand"]
    truncated = " The start or end of this movement was cut off by a tracking gap or the attempt bounds." \
        if event["truncated"] else ""
    return {
        "template_version": WRIST_TEMPLATE,
        "observation": f"The {side} wrist moved visibly for about {_seconds(evidence['duration_ms'])} seconds, "
                       f"reaching about {evidence['max_displacement_L']:.1f} torso lengths from where it started."
                       f"{truncated}",
        "interpretation": "This may be a reach, a repositioning, or another arm movement. Wrist motion alone does "
                          "not show a hold was gripped or released.",
        "reflection_question": "What was this hand doing here, and was that what you intended?",
    }
