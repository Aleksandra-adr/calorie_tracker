"""CRUD-операции над приёмами пищи. Не валидирует бизнес-правила —
доверяет вызывающей стороне (API-слою)."""
from __future__ import annotations

from datetime import date as Date

from models.meal import MealEntry
from storage.db import transaction


def create_meal(meal: MealEntry) -> MealEntry:
    with transaction(write=True) as conn:
        cur = conn.execute(
            "INSERT INTO meals (product, weight_g, date, calories, protein, fat, carbs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                meal.product,
                meal.weight_g,
                meal.date.isoformat(),
                meal.calories,
                meal.protein,
                meal.fat,
                meal.carbs,
            ),
        )
        meal.id = cur.lastrowid
        return meal


def get_meal(meal_id: int) -> MealEntry | None:
    with transaction() as conn:
        row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
        return MealEntry.from_row(dict(row)) if row else None


def list_meals(start: Date | None = None, end: Date | None = None) -> list[MealEntry]:
    query = "SELECT * FROM meals"
    params: list[str] = []
    conditions = []
    if start is not None:
        conditions.append("date >= ?")
        params.append(start.isoformat())
    if end is not None:
        conditions.append("date <= ?")
        params.append(end.isoformat())
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY date, id"
    with transaction() as conn:
        rows = conn.execute(query, params).fetchall()
        return [MealEntry.from_row(dict(r)) for r in rows]


def update_meal(meal_id: int, meal: MealEntry) -> MealEntry | None:
    with transaction(write=True) as conn:
        cur = conn.execute(
            "UPDATE meals SET product=?, weight_g=?, date=?, calories=?, protein=?, "
            "fat=?, carbs=? WHERE id=?",
            (
                meal.product,
                meal.weight_g,
                meal.date.isoformat(),
                meal.calories,
                meal.protein,
                meal.fat,
                meal.carbs,
                meal_id,
            ),
        )
        if cur.rowcount == 0:
            return None
        meal.id = meal_id
        return meal


def delete_meal(meal_id: int) -> bool:
    with transaction(write=True) as conn:
        cur = conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        return cur.rowcount > 0
