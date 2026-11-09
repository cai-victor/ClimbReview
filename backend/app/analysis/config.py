"""Typed, strict loading of the analysis configuration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import ClimbReviewError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisConfig(_Strict):
    canonical_fps: int = Field(gt=0)
    inference_fps: int = Field(gt=0)
    longest_side_px: int = Field(ge=64)
    max_duration_s: float = Field(gt=0)
    max_upload_mb: float = Field(gt=0)

    @model_validator(mode="after")
    def _stride_is_integer(self) -> "AnalysisConfig":
        if self.canonical_fps % self.inference_fps:
            raise ValueError("inference_fps must divide canonical_fps exactly")
        return self

    @property
    def frame_stride(self) -> int:
        return self.canonical_fps // self.inference_fps

    @property
    def sample_period_ms(self) -> float:
        return 1000 / self.inference_fps


class PoseModelConfig(_Strict):
    model_path: str
    manifest_path: str
    num_poses: Literal[1]
    min_pose_detection_confidence: float = Field(ge=0, le=1)
    min_pose_presence_confidence: float = Field(ge=0, le=1)
    min_tracking_confidence: float = Field(ge=0, le=1)
    delegate: Literal["CPU", "GPU"]


class QualityConfig(_Strict):
    min_visibility: float = Field(ge=0, le=1)
    min_presence_if_available: float = Field(ge=0, le=1)
    out_of_frame_margin: float = Field(ge=0)
    fill_missing_gaps: Literal[False]
    max_sample_gap_factor: float = Field(ge=1)
    min_scale_samples: int = Field(ge=1)
    min_torso_fraction_of_diagonal: float = Field(ge=0)
    min_torso_ratio_to_attempt_scale: float = Field(ge=0)
    max_torso_ratio_to_attempt_scale: float = Field(gt=0)
    camera_max_speed_L_per_s: float = Field(gt=0)
    camera_min_correlation_response: float = Field(ge=0, le=1)


class FeaturesConfig(_Strict):
    smoothing_window_s: float = Field(ge=0)
    speed_window_s: float = Field(gt=0)
    min_speed_span_s: float = Field(gt=0)


class LowMovementConfig(_Strict):
    max_joint_speed_L_per_s: float = Field(gt=0)
    min_duration_s: float = Field(gt=0)
    max_fully_observed_interruption_s: float = Field(ge=0)


class WristMotionConfig(_Strict):
    onset_speed_L_per_s: float = Field(gt=0)
    offset_speed_L_per_s: float = Field(gt=0)
    offset_dwell_s: float = Field(ge=0)
    min_duration_s: float = Field(gt=0)
    min_displacement_L: float = Field(ge=0)

    @model_validator(mode="after")
    def _hysteresis_order(self) -> "WristMotionConfig":
        if self.offset_speed_L_per_s > self.onset_speed_L_per_s:
            raise ValueError("offset speed must not exceed onset speed")
        return self


class FootMotionConfig(WristMotionConfig):
    # Marks an episode uncertain; it never removes one. See docs/DECISIONS.md D52.
    unstable_shin_std_L: float = Field(gt=0)
    unstable_max_ankle_visibility: float = Field(gt=0, le=1)
    unstable_half_window_s: float = Field(gt=0)
    uncertain_min_fraction: float = Field(gt=0, le=1)


class FeasibilityConfig(_Strict):
    low_movement_target_fraction: float = Field(ge=0, le=1)


class PipelineConfig(_Strict):
    analysis: AnalysisConfig
    pose_model: PoseModelConfig
    quality: QualityConfig
    features: FeaturesConfig
    low_movement: LowMovementConfig
    wrist_motion: WristMotionConfig
    foot_motion: FootMotionConfig | None = None  # absent in runs stored before foot analysis existed
    feasibility: FeasibilityConfig

    def content_hash(self) -> str:
        canonical = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_config(path: Path) -> PipelineConfig:
    try:
        return PipelineConfig.model_validate(yaml.safe_load(path.read_text()))
    except FileNotFoundError as exc:
        raise ClimbReviewError(f"Configuration file not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise ClimbReviewError(f"Invalid configuration {path}: {exc}") from exc
