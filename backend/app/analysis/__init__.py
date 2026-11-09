"""ClimbReview analysis pipeline (feasibility milestone)."""

PIPELINE_VERSION = "0.2.1-footwork"
SCHEMA_VERSION = "1.1"


class ClimbReviewError(Exception):
    """An expected failure with a short, user-actionable message."""
