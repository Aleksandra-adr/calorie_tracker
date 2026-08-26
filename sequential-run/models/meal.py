"""Доменная модель приёма пищи.

Калории и БЖУ хранятся как значения всей порции, введённые вызывающей стороной
(вручную или через calculations.calculate_portion на границе API/фронтенда) —
справочника продуктов в проекте нет, поэтому модель не вычисляет их сама.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date


@dataclass
class MealEntry:
    product: str
    weight_g: float
    date: Date
    calories: float
    protein: float
    fat: float
    carbs: float
    id: int | None = None

    @staticmethod
    def from_row(row: dict) -> "MealEntry":
        return MealEntry(
            id=row["id"],
            product=row["product"],
            weight_g=row["weight_g"],
            date=Date.fromisoformat(row["date"]),
            calories=row["calories"],
            protein=row["protein"],
            fat=row["fat"],
            carbs=row["carbs"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product": self.product,
            "weight_g": self.weight_g,
            "date": self.date.isoformat(),
            "calories": self.calories,
            "protein": self.protein,
            "fat": self.fat,
            "carbs": self.carbs,
        }
