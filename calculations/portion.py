"""Расчёт калорийности и БЖУ порции продукта по его весу.

Этот модуль не зависит от models/ и не импортирует ничего оттуда.
Он работает с простыми, самостоятельно определёнными типами (см. NutritionPer100g
и Nutrition ниже), чтобы координатор мог позже состыковать его с реальной моделью
приёма пищи, просто преобразовав её поля в эти типы.

Минимальный контракт данных (подробнее в calculations/README.md):
    NutritionPer100g(calories, protein, fat, carbs) - пищевая ценность на 100 г
    продукта, все поля float >= 0.

    calculate_portion(per_100g, weight_g) -> Nutrition - калории и БЖУ порции
    заданного веса (в граммах), рассчитанные пропорционально весу и округлённые.
"""
from dataclasses import dataclass

# Точность округления результата.
CALORIE_ROUND_DIGITS = 0   # калории округляются до целого числа ккал
MACRO_ROUND_DIGITS = 1     # белки/жиры/углеводы округляются до 0.1 г


@dataclass(frozen=True)
class NutritionPer100g:
    """Пищевая ценность продукта на 100 г. Все поля должны быть >= 0."""

    calories: float
    protein: float
    fat: float
    carbs: float

    def __post_init__(self) -> None:
        for name in ("calories", "protein", "fat", "carbs"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value!r}")


@dataclass(frozen=True)
class Nutrition:
    """Рассчитанные калории и БЖУ (например, для одной порции, дня или недели)."""

    calories: float
    protein: float
    fat: float
    carbs: float


def _round_positive(value: float, ndigits: int) -> float:
    """Округляет value до ndigits знаков после запятой.

    Гарантирует инвариант: строго положительное значение никогда не
    округляется до нуля или отрицательного числа (минимально возможный
    результат при value > 0 - это один "квант" точности, то есть 10**-ndigits).
    """
    if value < 0:
        raise ValueError(f"Cannot round a negative nutrition value: {value!r}")
    if value == 0:
        return 0.0
    rounded = round(value, ndigits)
    quantum = 10 ** (-ndigits)
    if rounded <= 0:
        rounded = quantum
    return float(rounded)


def calculate_portion(per_100g: NutritionPer100g, weight_g: float) -> Nutrition:
    """Считает калории и БЖУ порции веса weight_g (в граммах).

    Формула: значение_на_100г * weight_g / 100, с последующим округлением
    (калории - до целого, БЖУ - до 0.1 г).

    weight_g должен быть >= 0. Если weight_g == 0, результат - нулевая порция.
    """
    if weight_g < 0:
        raise ValueError(f"weight_g must be >= 0, got {weight_g!r}")

    factor = weight_g / 100.0
    return Nutrition(
        calories=_round_positive(per_100g.calories * factor, CALORIE_ROUND_DIGITS),
        protein=_round_positive(per_100g.protein * factor, MACRO_ROUND_DIGITS),
        fat=_round_positive(per_100g.fat * factor, MACRO_ROUND_DIGITS),
        carbs=_round_positive(per_100g.carbs * factor, MACRO_ROUND_DIGITS),
    )
