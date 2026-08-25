"""Тесты для calculations/: unit-тесты на конкретных примерах + property-based
тесты на hypothesis.

Модуль calculations/ самостоятелен и не зависит от models/, поэтому здесь
приёмы пищи для агрегации представлены простыми dict'ами с полями
date/calories/protein/fat/carbs (контракт описан в calculations/README.md).
"""
import datetime
import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from calculations import (
    CALORIE_ROUND_DIGITS,
    MACRO_ROUND_DIGITS,
    NutritionPer100g,
    aggregate_day,
    aggregate_week,
    calculate_portion,
)

CAL_QUANTUM = 10 ** (-CALORIE_ROUND_DIGITS)   # 1
MACRO_QUANTUM = 10 ** (-MACRO_ROUND_DIGITS)   # 0.1


# ---------------------------------------------------------------------------
# Unit-тесты: calculate_portion, конкретные примеры с известным ответом
# ---------------------------------------------------------------------------

def test_portion_chicken_breast_150g():
    chicken = NutritionPer100g(calories=165, protein=31, fat=3.6, carbs=0)
    result = calculate_portion(chicken, 150)
    assert result.calories == 248.0
    assert result.protein == 46.5
    assert result.fat == 5.4
    assert result.carbs == 0.0


def test_portion_banana_50g():
    banana = NutritionPer100g(calories=89, protein=1.1, fat=0.3, carbs=23)
    result = calculate_portion(banana, 50)
    assert result.calories == 44.0
    assert result.protein == 0.6
    assert result.fat == 0.1
    assert result.carbs == 11.5


def test_portion_100g_equals_per_100g_values():
    product = NutritionPer100g(calories=200, protein=10, fat=5, carbs=20)
    result = calculate_portion(product, 100)
    assert result.calories == 200.0
    assert result.protein == 10.0
    assert result.fat == 5.0
    assert result.carbs == 20.0


def test_portion_zero_weight_gives_zero_nutrition():
    product = NutritionPer100g(calories=165, protein=31, fat=3.6, carbs=0)
    result = calculate_portion(product, 0)
    assert result == (0.0, 0.0, 0.0, 0.0) or (
        result.calories == 0.0
        and result.protein == 0.0
        and result.fat == 0.0
        and result.carbs == 0.0
    )


def test_portion_tiny_but_positive_never_rounds_to_zero():
    # Очень маленькая порция очень некалорийного продукта - результат
    # всё равно должен быть положительным, а не 0.
    product = NutritionPer100g(calories=0.001, protein=0, fat=0, carbs=0)
    result = calculate_portion(product, 0.001)
    assert result.calories > 0


def test_portion_negative_weight_raises():
    product = NutritionPer100g(calories=100, protein=1, fat=1, carbs=1)
    with pytest.raises(ValueError):
        calculate_portion(product, -10)


def test_nutrition_per_100g_rejects_negative_fields():
    with pytest.raises(ValueError):
        NutritionPer100g(calories=-1, protein=0, fat=0, carbs=0)


# ---------------------------------------------------------------------------
# Unit-тесты: aggregate_day / aggregate_week, конкретные примеры
# ---------------------------------------------------------------------------

MEALS = [
    {"date": "2026-08-24", "calories": 248, "protein": 46.5, "fat": 5.4, "carbs": 0},
    {"date": "2026-08-24", "calories": 44, "protein": 0.6, "fat": 0.1, "carbs": 11.5},
    {"date": "2026-08-25", "calories": 500, "protein": 20, "fat": 10, "carbs": 50},
]


def test_aggregate_day_sums_matching_meals_only():
    result = aggregate_day(MEALS, "2026-08-24")
    assert result.meal_count == 2
    assert result.total.calories == 292.0
    assert result.total.protein == 47.1
    assert result.total.fat == 5.5
    assert result.total.carbs == 11.5


def test_aggregate_day_accepts_date_object_and_iso_string_equally():
    by_str = aggregate_day(MEALS, "2026-08-25")
    by_date = aggregate_day(MEALS, datetime.date(2026, 8, 25))
    assert by_str.total == by_date.total
    assert by_str.meal_count == by_date.meal_count == 1


def test_aggregate_day_no_meals_gives_zero_total():
    result = aggregate_day(MEALS, "2099-01-01")
    assert result.meal_count == 0
    assert result.total.calories == 0.0
    assert result.total.protein == 0.0


def test_aggregate_week_sums_all_seven_days_and_averages():
    result = aggregate_week(MEALS, "2026-08-24")
    assert result.start_date == datetime.date(2026, 8, 24)
    assert result.end_date == datetime.date(2026, 8, 30)
    assert result.meal_count == 3
    assert result.total.calories == 792.0
    assert result.average.calories == round(792.0 / 7, CALORIE_ROUND_DIGITS)
    assert result.average.protein == round(67.1 / 7, MACRO_ROUND_DIGITS)


def test_aggregate_week_excludes_meals_outside_range():
    meals = MEALS + [{"date": "2026-09-05", "calories": 999, "protein": 1, "fat": 1, "carbs": 1}]
    result = aggregate_week(meals, "2026-08-24")
    assert result.meal_count == 3
    assert result.total.calories == 792.0


# ---------------------------------------------------------------------------
# Property-based тесты (hypothesis)
# ---------------------------------------------------------------------------

per_100g_strategy = st.builds(
    NutritionPer100g,
    calories=st.floats(min_value=0, max_value=900, allow_nan=False, allow_infinity=False),
    protein=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    fat=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    carbs=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)

weight_strategy = st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False)

positive_weight_strategy = st.floats(
    min_value=0.001, max_value=5000, allow_nan=False, allow_infinity=False
)

positive_calories_strategy = st.floats(
    min_value=0.0001, max_value=900, allow_nan=False, allow_infinity=False
)

scale_strategy = st.floats(min_value=0.01, max_value=20, allow_nan=False, allow_infinity=False)


@st.composite
def meal_dict(draw, on_date=None):
    date_value = on_date if on_date is not None else draw(
        st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2030, 12, 31))
    )
    return {
        "date": date_value,
        "calories": draw(st.floats(min_value=0, max_value=3000, allow_nan=False, allow_infinity=False)),
        "protein": draw(st.floats(min_value=0, max_value=300, allow_nan=False, allow_infinity=False)),
        "fat": draw(st.floats(min_value=0, max_value=300, allow_nan=False, allow_infinity=False)),
        "carbs": draw(st.floats(min_value=0, max_value=300, allow_nan=False, allow_infinity=False)),
    }


# (a) Сумма агрегата за день == сумма калорий/БЖУ отдельных приёмов пищи за
#     эту дату, для случайного набора приёмов (с "шумовыми" приёмами на
#     других датах, которые не должны попасть в сумму).
@settings(max_examples=100)
@given(
    target_date=st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2030, 12, 31)),
    noise=st.data(),
)
def test_property_day_aggregate_equals_manual_sum(target_date, noise):
    n_matching = noise.draw(st.integers(min_value=0, max_value=6))
    n_other = noise.draw(st.integers(min_value=0, max_value=4))
    other_date = target_date + datetime.timedelta(days=1)

    matching_meals = [
        noise.draw(meal_dict(on_date=target_date)) for _ in range(n_matching)
    ]
    other_meals = [noise.draw(meal_dict(on_date=other_date)) for _ in range(n_other)]

    all_meals = matching_meals + other_meals
    noise.draw(st.randoms()).shuffle(all_meals)

    expected_calories = round(
        math.fsum(m["calories"] for m in matching_meals), CALORIE_ROUND_DIGITS
    )
    expected_protein = round(
        math.fsum(m["protein"] for m in matching_meals), MACRO_ROUND_DIGITS
    )
    expected_fat = round(math.fsum(m["fat"] for m in matching_meals), MACRO_ROUND_DIGITS)
    expected_carbs = round(math.fsum(m["carbs"] for m in matching_meals), MACRO_ROUND_DIGITS)

    result = aggregate_day(all_meals, target_date)

    assert result.meal_count == n_matching
    assert result.total.calories == pytest.approx(expected_calories, abs=1e-6)
    assert result.total.protein == pytest.approx(expected_protein, abs=1e-6)
    assert result.total.fat == pytest.approx(expected_fat, abs=1e-6)
    assert result.total.carbs == pytest.approx(expected_carbs, abs=1e-6)


# (b) Линейность при масштабировании: если вес всех порций умножить на N,
#     то расчётные калории/БЖУ порции тоже умножаются на N, в пределах
#     погрешности округления.
#
# Обоснование допуска: округление до "кванта" q (1 ккал или 0.1 г) даёт
# погрешность |round(x) - x| <= q для любого x >= 0 (в т.ч. в вырожденном
# случае "положительное значение округлилось вверх до q, а не до 0").
# Тогда для scaled = calculate_portion(weight*N) и base = calculate_portion(weight):
#   |scaled - N*base| <= |round(raw*N) - raw*N| + N*|raw - round(raw)| <= q + N*q = q*(1+N).
@settings(max_examples=200)
@given(per_100g=per_100g_strategy, weight=positive_weight_strategy, n=scale_strategy)
def test_property_portion_scales_linearly_with_weight(per_100g, weight, n):
    base = calculate_portion(per_100g, weight)
    scaled = calculate_portion(per_100g, weight * n)

    eps = 1e-6
    cal_tolerance = CAL_QUANTUM * (1 + n) + eps
    macro_tolerance = MACRO_QUANTUM * (1 + n) + eps

    assert abs(scaled.calories - n * base.calories) <= cal_tolerance
    assert abs(scaled.protein - n * base.protein) <= macro_tolerance
    assert abs(scaled.fat - n * base.fat) <= macro_tolerance
    assert abs(scaled.carbs - n * base.carbs) <= macro_tolerance


# (c) Округление никогда не даёт отрицательное значение и не обнуляет
#     ненулевую порцию: если исходная порция > 0 и калорийность продукта > 0,
#     после округления калории должны быть > 0 (не 0 и не отрицательны).
@settings(max_examples=200)
@given(
    calories_per_100g=positive_calories_strategy,
    protein=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    fat=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    carbs=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    weight=positive_weight_strategy,
)
def test_property_rounding_never_zeroes_out_positive_portion(
    calories_per_100g, protein, fat, carbs, weight
):
    per_100g = NutritionPer100g(
        calories=calories_per_100g, protein=protein, fat=fat, carbs=carbs
    )
    result = calculate_portion(per_100g, weight)

    assert result.calories > 0
    # Общая гарантия неотрицательности всех полей.
    assert result.protein >= 0
    assert result.fat >= 0
    assert result.carbs >= 0


# (бонус) Агрегация по дню не зависит от порядка приёмов пищи в списке.
@settings(max_examples=100)
@given(
    target_date=st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2030, 12, 31)),
    data=st.data(),
)
def test_property_day_aggregate_is_order_independent(target_date, data):
    n = data.draw(st.integers(min_value=0, max_value=8))
    meals = [data.draw(meal_dict(on_date=target_date)) for _ in range(n)]

    shuffled = list(meals)
    data.draw(st.randoms()).shuffle(shuffled)

    result_original = aggregate_day(meals, target_date)
    result_shuffled = aggregate_day(shuffled, target_date)

    assert result_original.total == result_shuffled.total
    assert result_original.meal_count == result_shuffled.meal_count


# (бонус) calculate_portion никогда не возвращает отрицательные значения
# для валидных (неотрицательных) входов.
@settings(max_examples=200)
@given(per_100g=per_100g_strategy, weight=weight_strategy)
def test_property_portion_never_negative(per_100g, weight):
    result = calculate_portion(per_100g, weight)
    assert result.calories >= 0
    assert result.protein >= 0
    assert result.fat >= 0
    assert result.carbs >= 0
