"""Pydantic-схемы — валидация на границе API."""
from __future__ import annotations

from datetime import date as Date

from pydantic import BaseModel, Field


class MealCreate(BaseModel):
    product: str = Field(min_length=1, max_length=200)
    weight_g: float = Field(gt=0)
    date: Date
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    carbs: float = Field(ge=0)


class MealUpdate(MealCreate):
    pass


class MealOut(MealCreate):
    id: int
