"""Агрегация калорий/БЖУ по дню и неделе.

Принимает объекты с полями date/calories/protein/fat/carbs (dict или атрибуты) —
совместимо с models.meal.MealEntry напрямую, без адаптера.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date, timedelta


@dataclass
class Totals:
    calories: float
    protein: float
    fat: float
    carbs: float


def _field(meal, name):
    return meal[name] if isinstance(meal, dict) else getattr(meal, name)


def _meal_date(meal) -> Date:
    d = _field(meal, "date")
    if isinstance(d, str):
        return Date.fromisoformat(d)
    return d


def _sum(meals) -> Totals:
    return Totals(
        calories=round(sum(_field(m, "calories") for m in meals), 2),
        protein=round(sum(_field(m, "protein") for m in meals), 2),
        fat=round(sum(_field(m, "fat") for m in meals), 2),
        carbs=round(sum(_field(m, "carbs") for m in meals), 2),
    )


def aggregate_day(meals, target_date: Date) -> Totals:
    day_meals = [m for m in meals if _meal_date(m) == target_date]
    return _sum(day_meals)


def aggregate_week(meals, start_date: Date) -> Totals:
    end_date = start_date + timedelta(days=6)
    week_meals = [m for m in meals if start_date <= _meal_date(m) <= end_date]
    return _sum(week_meals)
