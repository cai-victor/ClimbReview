"""ClimbReview analysis pipeline (feasibility milestone)."""

PIPELINE_VERSION = "0.1.0-feasibility"
SCHEMA_VERSION = "1.0"


class ClimbReviewError(Exception):
    """An expected failure with a short, user-actionable message."""
