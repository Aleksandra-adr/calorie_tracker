"""Агрегация калорий и БЖУ приёмов пищи по дню и по неделе.

Этот модуль не импортирует ничего из models/. Функции принимают на вход
произвольную последовательность "приёмов пищи" - это может быть список
словарей или список объектов (например, экземпляров реальной модели из
models/), при условии что у каждого элемента есть поля, описанные ниже.

Минимальный контракт данных, который нужен от модели приёма пищи
(подробнее в calculations/README.md):
    - date: datetime.date | datetime.datetime | str в формате "YYYY-MM-DD"
    - calories: float  (уже рассчитанные калории порции, например через
      calculations.portion.calculate_portion)
    - protein: float
    - fat: float
    - carbs: float

Поля читаются как meal["date"] для dict, либо meal.date для объекта - то
есть подходит и dict, и dataclass/обычный класс с такими атрибутами.
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, List, Union

from .portion import CALORIE_ROUND_DIGITS, MACRO_ROUND_DIGITS, Nutrition

DateLike = Union[date, datetime, str]


def _to_date(value: DateLike) -> date:
    """Приводит date/datetime/ISO-строку к datetime.date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Unsupported date-like value: {value!r} ({type(value)!r})")


def _field(meal: Any, name: str) -> Any:
    """Достаёт поле name из meal - работает и для dict, и для объекта с атрибутами."""
    if isinstance(meal, dict):
        return meal[name]
    return getattr(meal, name)


def _meal_date(meal: Any) -> date:
    return _to_date(_field(meal, "date"))


def _sum_nutrition(meals: Iterable[Any]) -> Nutrition:
    calories: List[float] = []
    protein: List[float] = []
    fat: List[float] = []
    carbs: List[float] = []
    for meal in meals:
        calories.append(float(_field(meal, "calories")))
        protein.append(float(_field(meal, "protein")))
        fat.append(float(_field(meal, "fat")))
        carbs.append(float(_field(meal, "carbs")))
    return Nutrition(
        calories=round(math.fsum(calories), CALORIE_ROUND_DIGITS),
        protein=round(math.fsum(protein), MACRO_ROUND_DIGITS),
        fat=round(math.fsum(fat), MACRO_ROUND_DIGITS),
        carbs=round(math.fsum(carbs), MACRO_ROUND_DIGITS),
    )


@dataclass(frozen=True)
class DayAggregate:
    date: date
    total: Nutrition
    meal_count: int


def aggregate_day(meals: Iterable[Any], target_date: DateLike) -> DayAggregate:
    """Суммирует калории и БЖУ всех приёмов пищи из meals за дату target_date."""
    target = _to_date(target_date)
    day_meals = [meal for meal in meals if _meal_date(meal) == target]
    return DayAggregate(
        date=target,
        total=_sum_nutrition(day_meals),
        meal_count=len(day_meals),
    )


@dataclass(frozen=True)
class WeekAggregate:
    start_date: date
    end_date: date
    total: Nutrition
    average: Nutrition
    meal_count: int


def aggregate_week(meals: Iterable[Any], start_date: DateLike) -> WeekAggregate:
    """Суммирует и усредняет калории/БЖУ за 7 дней, начиная со start_date (включительно).

    average = total / 7 - среднее за календарную неделю, независимо от того,
    сколько дней фактически содержали приёмы пищи.
    """
    start = _to_date(start_date)
    end = start + timedelta(days=6)
    week_meals = [meal for meal in meals if start <= _meal_date(meal) <= end]
    total = _sum_nutrition(week_meals)
    average = Nutrition(
        calories=round(total.calories / 7, CALORIE_ROUND_DIGITS),
        protein=round(total.protein / 7, MACRO_ROUND_DIGITS),
        fat=round(total.fat / 7, MACRO_ROUND_DIGITS),
        carbs=round(total.carbs / 7, MACRO_ROUND_DIGITS),
    )
    return WeekAggregate(
        start_date=start,
        end_date=end,
        total=total,
        average=average,
        meal_count=len(week_meals),
    )
