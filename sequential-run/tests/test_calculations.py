from datetime import date, timedelta

import pytest
from hypothesis import given, strategies as st

from calculations.aggregation import aggregate_day, aggregate_week
from calculations.portion import NutritionPer100g, calculate_portion

# ---------- unit-тесты ----------


def test_calculate_portion_basic():
    chicken = NutritionPer100g(calories=165, protein=31, fat=3.6, carbs=0)
    result = calculate_portion(chicken, 150)
    assert result.calories == pytest.approx(247.5, abs=1)
    assert result.protein == pytest.approx(46.5, abs=0.1)
    assert result.fat == pytest.approx(5.4, abs=0.1)
    assert result.carbs == 0


def test_calculate_portion_100g_equals_reference():
    banana = NutritionPer100g(calories=89, protein=1.1, fat=0.3, carbs=22.8)
    result = calculate_portion(banana, 100)
    assert result.calories == 89
    assert result.protein == 1.1


def test_calculate_portion_zero_weight_is_zero():
    p = NutritionPer100g(calories=200, protein=10, fat=5, carbs=20)
    result = calculate_portion(p, 0)
    assert result.calories == 0
    assert result.protein == 0


def test_negative_per_100g_rejected():
    with pytest.raises(ValueError):
        NutritionPer100g(calories=-1, protein=0, fat=0, carbs=0)


def test_negative_weight_rejected():
    p = NutritionPer100g(calories=100, protein=1, fat=1, carbs=1)
    with pytest.raises(ValueError):
        calculate_portion(p, -50)


def test_aggregate_day_manual_example():
    d = date(2026, 8, 24)
    meals = [
        {"date": d, "calories": 100, "protein": 10, "fat": 5, "carbs": 10},
        {"date": d, "calories": 200, "protein": 20, "fat": 10, "carbs": 20},
        {"date": d + timedelta(days=1), "calories": 999, "protein": 99, "fat": 99, "carbs": 99},
    ]
    total = aggregate_day(meals, d)
    assert total.calories == 300
    assert total.protein == 30
    assert total.fat == 15
    assert total.carbs == 30


def test_aggregate_week_manual_example():
    start = date(2026, 8, 24)
    meals = [
        {"date": start + timedelta(days=i), "calories": 100, "protein": 1, "fat": 1, "carbs": 1}
        for i in range(7)
    ]
    meals.append(
        {"date": start + timedelta(days=8), "calories": 1000, "protein": 0, "fat": 0, "carbs": 0}
    )
    total = aggregate_week(meals, start)
    assert total.calories == 700


# ---------- property-based тесты (hypothesis) ----------

meal_strategy = st.fixed_dictionaries(
    {
        "calories": st.floats(min_value=0, max_value=5000, allow_nan=False),
        "protein": st.floats(min_value=0, max_value=500, allow_nan=False),
        "fat": st.floats(min_value=0, max_value=500, allow_nan=False),
        "carbs": st.floats(min_value=0, max_value=500, allow_nan=False),
    }
)


@given(st.lists(meal_strategy, min_size=0, max_size=20))
def test_property_day_sum_equals_manual_sum(nutrition_values):
    d = date(2026, 1, 1)
    meals = [{"date": d, **v} for v in nutrition_values]
    total = aggregate_day(meals, d)
    expected_calories = round(sum(v["calories"] for v in nutrition_values), 2)
    assert total.calories == pytest.approx(expected_calories, abs=0.05)


@given(
    calories=st.floats(min_value=0.01, max_value=1000, allow_nan=False),
    protein=st.floats(min_value=0, max_value=200, allow_nan=False),
    fat=st.floats(min_value=0, max_value=200, allow_nan=False),
    carbs=st.floats(min_value=0, max_value=200, allow_nan=False),
    weight=st.floats(min_value=1, max_value=2000, allow_nan=False),
    factor=st.floats(min_value=0.01, max_value=20, allow_nan=False),
)
def test_property_linear_scaling_of_weight(calories, protein, fat, carbs, weight, factor):
    per_100g = NutritionPer100g(calories=calories, protein=protein, fat=fat, carbs=carbs)
    base = calculate_portion(per_100g, weight)
    scaled = calculate_portion(per_100g, weight * factor)
    # допуск учитывает погрешность округления на обоих концах (0 знаков у калорий, 1 у БЖУ)
    tolerance = 1 * (1 + factor)
    assert abs(scaled.calories - base.calories * factor) <= tolerance


@given(
    calories=st.floats(min_value=0.0001, max_value=1000, allow_nan=False),
    weight=st.floats(min_value=0.001, max_value=2000, allow_nan=False),
)
def test_property_rounding_never_zeroes_positive_portion(calories, weight):
    per_100g = NutritionPer100g(calories=calories, protein=0, fat=0, carbs=0)
    result = calculate_portion(per_100g, weight)
    assert result.calories > 0
    assert result.calories >= 0


@given(st.lists(meal_strategy, min_size=1, max_size=15))
def test_property_day_aggregate_order_independent(nutrition_values):
    d = date(2026, 1, 1)
    meals = [{"date": d, **v} for v in nutrition_values]
    forward = aggregate_day(meals, d)
    backward = aggregate_day(list(reversed(meals)), d)
    assert forward == backward
