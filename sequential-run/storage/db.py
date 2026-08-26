"""Подключение к SQLite и атомарные транзакции."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DB_PATH = os.environ.get(
    "CALORIE_TRACKER_DB",
    str(Path(__file__).parent / "calorie_tracker.db"),
)

_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product TEXT NOT NULL,
    weight_g REAL NOT NULL CHECK (weight_g > 0),
    date TEXT NOT NULL,
    calories REAL NOT NULL CHECK (calories >= 0),
    protein REAL NOT NULL CHECK (protein >= 0),
    fat REAL NOT NULL CHECK (fat >= 0),
    carbs REAL NOT NULL CHECK (carbs >= 0)
);
CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(date);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(write: bool = False):
    """Контекстный менеджер: commit при успехе, rollback при исключении.

    Запись сериализуется через threading.Lock, чтобы параллельные
    write-запросы не гонялись друг с другом.
    """
    lock_acquired = False
    if write:
        _write_lock.acquire()
        lock_acquired = True
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        if lock_acquired:
            _write_lock.release()
