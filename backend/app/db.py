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
  event_type TEXT NOT NULL CHECK (event_type IN ('low_movement','wrist_motion','foot_motion','unscorable')),
  hand TEXT CHECK (hand IN ('left','right')),
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  applies_to TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS annotation_intervals_set ON annotation_intervals(set_id, start_ms);
CREATE TABLE IF NOT EXISTS hold_maps (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  reference_frame_ms INTEGER NOT NULL,
  frame_index INTEGER NOT NULL,
  canonical_sha256 TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS holds (
  id TEXT PRIMARY KEY,
  map_id TEXT NOT NULL REFERENCES hold_maps(id) ON DELETE CASCADE,
  x REAL NOT NULL,
  y REAL NOT NULL,
  radius REAL NOT NULL,
  route TEXT NOT NULL DEFAULT '',
  hold_type TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS holds_map ON holds(map_id, created_at);
CREATE TABLE IF NOT EXISTS coaching_feedback (
  run_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  cue_id TEXT NOT NULL,
  decision TEXT NOT NULL DEFAULT 'unreviewed',
  trial_outcome TEXT NOT NULL DEFAULT 'not_tried',
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_id, cue_id)
);
CREATE TABLE IF NOT EXISTS foot_placement_reviews (
  run_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  placement_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unreviewed',
  hold_id TEXT,
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_id, placement_id)
);
CREATE TABLE IF NOT EXISTS hold_map_alignment (
  map_id TEXT NOT NULL REFERENCES hold_maps(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  detail TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (map_id, run_id)
);
CREATE TABLE IF NOT EXISTS candidate_ids (
  run_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  detail TEXT NOT NULL
);
"""
ADDED_COLUMNS = {
    "holds": {"role": "TEXT NOT NULL DEFAULT ''", "use": "TEXT NOT NULL DEFAULT ''"},
    "attempts": {"problem_label": "TEXT NOT NULL DEFAULT ''", "climber_label": "TEXT NOT NULL DEFAULT ''"},
}
ACTIVE = ("queued", "running")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _migrate_annotation_types(connection: sqlite3.Connection) -> None:
    """Allow foot_motion in databases made earlier. SQLite cannot alter a CHECK, so the table is copied in one transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='annotation_intervals'").fetchone()["sql"]
        if "foot_motion" not in definition:
            connection.execute("ALTER TABLE annotation_intervals RENAME TO annotation_intervals_old")
            connection.execute("DROP INDEX IF EXISTS annotation_intervals_set")
            start = SCHEMA.index("CREATE TABLE IF NOT EXISTS annotation_intervals")
            end = SCHEMA.index("CREATE TABLE IF NOT EXISTS hold_maps")
            for statement in SCHEMA[start:end].split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("INSERT INTO annotation_intervals SELECT * FROM annotation_intervals_old")
            connection.execute("DROP TABLE annotation_intervals_old")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Additive only: existing rows keep their values and new columns start empty."""
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f'ALTER TABLE {table} ADD COLUMN "{name}" {definition}')
    connection.commit()


def initialize(path: Path) -> None:
    connection = _connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.commit()
        _migrate_annotation_types(connection)
        _add_missing_columns(connection)
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
