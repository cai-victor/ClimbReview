"""Filesystem locations for the local application."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .analysis.config import PipelineConfig, load_config

# A packaged desktop build (PyInstaller) unpacks its read-only resources (config, model, frontend) here.
FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(getattr(sys, "_MEIPASS")) if FROZEN else Path(__file__).resolve().parents[2]
_ID = re.compile(r"^[0-9a-f]{32}$")


class InvalidIdError(ValueError):
    pass


def require_id(value: str) -> str:
    """Generated IDs are the only path components that come from a request."""
    if not _ID.match(value):
        raise InvalidIdError(value)
    return value


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def database(self) -> Path:
        return self.data_dir / "climbreview.sqlite"

    @property
    def attempts_dir(self) -> Path:
        return self.data_dir / "attempts"

    @property
    def worker_lock(self) -> Path:
        return self.data_dir / "worker.lock"

    def attempt_dir(self, attempt_id: str) -> Path:
        return self._inside(self.attempts_dir / require_id(attempt_id))

    def run_dir(self, attempt_id: str, run_id: str) -> Path:
        return self._inside(self.attempt_dir(attempt_id) / "runs" / require_id(run_id))

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if self.attempts_dir.resolve() not in resolved.parents:
            raise InvalidIdError(str(path))
        return resolved

    def prepare(self) -> None:
        self.attempts_dir.mkdir(parents=True, exist_ok=True)


def user_data_dir() -> Path:
    """Where the desktop app keeps attempts and its database: the user's own app-data folder, never the bundle."""
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "ClimbReview"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "ClimbReview"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "ClimbReview"


def load_settings() -> Settings:
    configured = os.environ.get("CLIMBREVIEW_DATA_DIR")
    if configured:
        return Settings(Path(configured).resolve())
    return Settings(user_data_dir() if FROZEN else PROJECT_ROOT / "data" / "app")


def load_pipeline_config() -> PipelineConfig:
    return load_config(PROJECT_ROOT / "config" / "detectors.yaml")
