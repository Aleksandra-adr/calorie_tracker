"""
SQLite connection management + schema migration for the calorie tracker.

- The DB file is created automatically on first use (CREATE TABLE IF NOT
  EXISTS), no manual migration step required.
- WAL journal mode is enabled for better read/write concurrency.
- All write operations must go through `transaction(write=True)`, which
  serializes writers with a module-level lock. SQLite only supports a
  single writer at a time regardless of process/thread count, so the
  lock avoids "database is locked" errors under concurrent write
  requests and guarantees atomic commit-or-rollback semantics.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# Default DB file lives inside storage/, next to this module.
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "calorie_tracker.db"

# Allow overriding the DB location (handy for tests: use ":memory:" or a tmp file).
DB_PATH = Path(os.environ.get("CALORIE_TRACKER_DB", str(DEFAULT_DB_PATH)))

_write_lock = threading.Lock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    weight_grams REAL NOT NULL CHECK (weight_grams > 0),
    consumed_at TEXT NOT NULL,
    calories REAL NOT NULL CHECK (calories >= 0),
    proteins REAL NOT NULL CHECK (proteins >= 0),
    fats REAL NOT NULL CHECK (fats >= 0),
    carbs REAL NOT NULL CHECK (carbs >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meal_entries_consumed_at
    ON meal_entries (consumed_at);
"""


def get_connection() -> sqlite3.Connection:
    """Open a new connection configured for safe concurrent access."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    """Create the schema if it doesn't exist yet. Safe to call repeatedly."""
    if str(DB_PATH) != ":memory:":
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(write: bool = False):
    """
    Context manager yielding a sqlite3.Connection wrapped in a transaction.

    - Commits automatically on clean exit.
    - Rolls back automatically if an exception propagates.
    - When write=True, serializes access via a process-wide lock so that
      concurrent write requests cannot race each other or corrupt state.
    """
    if write:
        _write_lock.acquire()
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        if write:
            _write_lock.release()
