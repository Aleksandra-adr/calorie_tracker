"""Самостоятельный модуль расчётов калорийности и БЖУ.

Не зависит от models/, storage/, api/ и т.д. Принимает на вход только
простые типы (числа, dict, объекты с нужными атрибутами) - см.
calculations/README.md за описанием минимального контракта данных.
"""
from .portion import (
    CALORIE_ROUND_DIGITS,
    MACRO_ROUND_DIGITS,
    Nutrition,
    NutritionPer100g,
    calculate_portion,
)
from .aggregation import (
    DayAggregate,
    WeekAggregate,
    aggregate_day,
    aggregate_week,
)

__all__ = [
    "CALORIE_ROUND_DIGITS",
    "MACRO_ROUND_DIGITS",
    "Nutrition",
    "NutritionPer100g",
    "calculate_portion",
    "DayAggregate",
    "WeekAggregate",
    "aggregate_day",
    "aggregate_week",
]
