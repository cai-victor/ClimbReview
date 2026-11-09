"""SQLite persistence. The database is the source of truth for job state."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  route_name TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  outcome TEXT NOT NULL DEFAULT '',
  focus TEXT NOT NULL DEFAULT '',
  single_climber_confirmed INTEGER NOT NULL DEFAULT 0,
  fixed_camera_confirmed INTEGER NOT NULL DEFAULT 0,
  original_filename TEXT NOT NULL,
  source_ext TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  width INTEGER, height INTEGER, fps INTEGER, frame_count INTEGER, duration_ms INTEGER,
  attempt_start_ms INTEGER, attempt_end_ms INTEGER,
  warnings TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('import','analysis')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','complete','failed','cancelled','interrupted')),
  stage TEXT NOT NULL,
  progress_done INTEGER NOT NULL DEFAULT 0,
  progress_total INTEGER,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  error TEXT, error_detail TEXT,
  attempt_start_ms INTEGER, attempt_end_ms INTEGER,
  config_hash TEXT, pipeline_version TEXT, detector_version TEXT,
  summary TEXT,
  worker_pid INTEGER,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS jobs_attempt ON jobs(attempt_id, created_at);
CREATE TABLE IF NOT EXISTS event_reviews (
  run_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  event_id TEXT NOT NULL,
  detection_judgment TEXT NOT NULL DEFAULT 'unreviewed',
  usefulness TEXT NOT NULL DEFAULT 'unrated',
  context_tags TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_id, event_id)
);
CREATE TABLE IF NOT EXISTS reflections (
  attempt_id TEXT PRIMARY KEY REFERENCES attempts(id) ON DELETE CASCADE,
  observation TEXT NOT NULL DEFAULT '',
  next_focus TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS annotation_sets (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  rater_alias TEXT NOT NULL,
  clip_id TEXT NOT NULL,
  climber_id TEXT NOT NULL DEFAULT '',
  route_id TEXT NOT NULL DEFAULT '',
  split TEXT NOT NULL DEFAULT '',
  synthetic_test_fixture INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (attempt_id, rater_alias)
);
CREATE TABLE IF NOT EXISTS annotation_intervals (
  id TEXT PRIMARY KEY,
  set_id TEXT NOT NULL REFERENCES annotation_sets(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (event_type IN ('low_movement','wrist_motion','unscorable')),
  hand TEXT CHECK (hand IN ('left','right')),
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  applies_to TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS annotation_intervals_set ON annotation_intervals(set_id, start_ms);
"""
ACTIVE = ("queued", "running")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path) -> None:
    connection = _connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect(path)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def row(result: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if result is None else dict(result)


def active_job(connection: sqlite3.Connection, attempt_id: str) -> dict[str, Any] | None:
    return row(connection.execute(
        "SELECT * FROM jobs WHERE attempt_id=? AND status IN ('queued','running') ORDER BY created_at LIMIT 1",
        (attempt_id,)).fetchone())


def claim_next_job(connection: sqlite3.Connection, worker_pid: int) -> dict[str, Any] | None:
    """Atomically move the oldest queued job to running; a single statement owns it."""
    return row(connection.execute(
        """UPDATE jobs SET status='running', worker_pid=?, started_at=?
           WHERE id=(SELECT id FROM jobs WHERE status='queued' ORDER BY created_at, id LIMIT 1) AND status='queued'
           RETURNING *""", (worker_pid, now())).fetchone())


def mark_interrupted_jobs(connection: sqlite3.Connection) -> int:
    """A freshly started sole worker owns nothing, so 'running' rows are stale."""
    rows = connection.execute(
        "UPDATE jobs SET status='interrupted', finished_at=?, error=? WHERE status='running' RETURNING id, attempt_id, kind",
        (now(), "The worker stopped before this job finished. Start it again to retry.")).fetchall()
    for item in rows:
        if item["kind"] == "import":
            connection.execute("UPDATE attempts SET status='failed', error=? WHERE id=?",
                               ("Import was interrupted. Retry the import.", item["attempt_id"]))
    return len(rows)


def dumps(value: Any) -> str:
    return json.dumps(value, allow_nan=False)
