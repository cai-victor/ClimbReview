"""Configuration for the experimental forecast."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ForecastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    sample_period_ms: int = Field(gt=0)
    history_steps: int = Field(gt=0)
    step_tolerance_ms: int = Field(ge=0)
    horizon_steps: int = Field(gt=0)
    horizon_ms: int = Field(gt=0)
    min_torso_fraction_of_diagonal: float = Field(ge=0)
    torso_ratio_min: float = Field(gt=0)
    torso_ratio_max: float = Field(gt=0)
    camera_max_speed_L_per_s: float = Field(gt=0)
    camera_min_correlation_response: float = Field(ge=0)
    train_population: Literal["all_eligible", "primary_only"]
    ridge_alphas: tuple[float, ...]
    constant_velocity_windows_ms: tuple[int, ...]
    cv_folds: int = Field(ge=2)
    seed: int


def load_forecast_config(path: Path) -> ForecastConfig:
    return ForecastConfig.model_validate(yaml.safe_load(path.read_text()))
