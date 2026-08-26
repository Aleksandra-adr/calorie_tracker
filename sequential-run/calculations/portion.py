"""Расчёт калорий/БЖУ порции по весу."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NutritionPer100g:
    calories: float
    protein: float
    fat: float
    carbs: float

    def __post_init__(self) -> None:
        for name in ("calories", "protein", "fat", "carbs"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} не может быть отрицательным")


@dataclass(frozen=True)
class Nutrition:
    calories: float
    protein: float
    fat: float
    carbs: float


def _scale_round(value_per_100g: float, weight_g: float, ndigits: int) -> float:
    raw = value_per_100g * weight_g / 100
    rounded = round(raw, ndigits)
    if raw > 0 and rounded == 0:
        # округление не должно обнулять ненулевую порцию
        rounded = 10 ** (-ndigits)
    return max(rounded, 0.0)


def calculate_portion(per_100g: NutritionPer100g, weight_g: float) -> Nutrition:
    if weight_g < 0:
        raise ValueError("weight_g не может быть отрицательным")
    return Nutrition(
        calories=_scale_round(per_100g.calories, weight_g, 0),
        protein=_scale_round(per_100g.protein, weight_g, 1),
        fat=_scale_round(per_100g.fat, weight_g, 1),
        carbs=_scale_round(per_100g.carbs, weight_g, 1),
    )
