"""Regressions from independent review of whole-window foot explanations."""
import pytest

from app.analysis.explain import limb_state


@pytest.mark.parametrize("missing", [0, 20])
def test_a_missing_boundary_cannot_be_described_as_continuously_quiet(missing):
    # A short hidden step at either boundary must remain unknown, even when
    # more than 90% of samples show the same ankle position.
    positions = [0.5] * 21
    runs = [0] * 21
    positions[missing] = None
    runs[missing] = None
    series = {"t": list(range(0, 2100, 100)), "width": 100, "height": 100, "L_px": 100,
              "limbs": {"left_foot": {"x": positions, "y": positions, "run": runs}}}
    hand = {"id": "synthetic-hand", "type": "wrist_motion", "hand": "right",
            "start_ms": 0, "end_ms": 2000, "evidence": {}}
    result = limb_state(hand, [hand], series, "left_foot")
    assert result["observed_fraction"] > 0.9
    assert result["state"] == "unknown"

