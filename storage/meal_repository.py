"""
CRUD operations for meal_entries, built on top of storage.db.transaction().

This layer assumes it only ever receives already-validated data (the API
layer / pydantic schemas are responsible for rejecting bad input before it
reaches here). It does not re-validate business rules beyond what the
schema CHECK constraints in storage.db enforce as a last line of defense.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from models.meal import MealEntry
from storage.db import transaction


class MealNotFoundError(Exception):
    """Raised when a meal entry with the given id does not exist."""

    def __init__(self, meal_id: int):
        self.meal_id = meal_id
        super().__init__(f"Meal entry {meal_id} not found")


def create_meal(entry: MealEntry) -> MealEntry:
    now = datetime.now().isoformat()
    with transaction(write=True) as conn:
        cur = conn.execute(
            """
            INSERT INTO meal_entries
                (product_name, weight_grams, consumed_at, calories,
                 proteins, fats, carbs, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.product_name,
                entry.weight_grams,
                entry.consumed_at.isoformat(),
                entry.calories,
                entry.proteins,
                entry.fats,
                entry.carbs,
                now,
                now,
            ),
        )
        new_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM meal_entries WHERE id = ?", (new_id,)
        ).fetchone()
        return MealEntry.from_row(row)


def get_meal(meal_id: int) -> MealEntry:
    with transaction(write=False) as conn:
        row = conn.execute(
            "SELECT * FROM meal_entries WHERE id = ?", (meal_id,)
        ).fetchone()
        if row is None:
            raise MealNotFoundError(meal_id)
        return MealEntry.from_row(row)


def list_meals(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> list[MealEntry]:
    """
    List meal entries, optionally filtered to the half-open range
    [start, end) on consumed_at. Both bounds are optional and independent,
    so callers can pass just `start`, just `end`, both, or neither.
    """
    query = "SELECT * FROM meal_entries WHERE 1=1"
    params: list[str] = []
    if start is not None:
        query += " AND consumed_at >= ?"
        params.append(start.isoformat())
    if end is not None:
        query += " AND consumed_at < ?"
        params.append(end.isoformat())
    query += " ORDER BY consumed_at ASC, id ASC"

    with transaction(write=False) as conn:
        rows = conn.execute(query, params).fetchall()
        return [MealEntry.from_row(row) for row in rows]


def update_meal(meal_id: int, entry: MealEntry) -> MealEntry:
    now = datetime.now().isoformat()
    with transaction(write=True) as conn:
        existing = conn.execute(
            "SELECT id FROM meal_entries WHERE id = ?", (meal_id,)
        ).fetchone()
        if existing is None:
            raise MealNotFoundError(meal_id)

        conn.execute(
            """
            UPDATE meal_entries
            SET product_name = ?,
                weight_grams = ?,
                consumed_at = ?,
                calories = ?,
                proteins = ?,
                fats = ?,
                carbs = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                entry.product_name,
                entry.weight_grams,
                entry.consumed_at.isoformat(),
                entry.calories,
                entry.proteins,
                entry.fats,
                entry.carbs,
                now,
                meal_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM meal_entries WHERE id = ?", (meal_id,)
        ).fetchone()
        return MealEntry.from_row(row)


def delete_meal(meal_id: int) -> None:
    with transaction(write=True) as conn:
        cur = conn.execute("DELETE FROM meal_entries WHERE id = ?", (meal_id,))
        if cur.rowcount == 0:
            raise MealNotFoundError(meal_id)
