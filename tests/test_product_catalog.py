"""Tests for storage/product_catalog.py - the product reference catalog
used by GET /products and GET /products/portion.

Kept as plain unit tests against the module directly (no FastAPI
TestClient/httpx dependency needed) - this project's requirements.txt
does not include httpx, so hitting the module functions directly keeps
these tests dependency-free.
"""
from calculations.portion import calculate_portion
from storage.product_catalog import all_products, find_product_by_name, search_products


def test_catalog_has_a_reasonable_number_of_products():
    products = all_products()
    assert 15 <= len(products) <= 25


def test_catalog_entries_have_non_negative_nutrition():
    for p in all_products():
        assert p.per_100g.calories >= 0
        assert p.per_100g.protein >= 0
        assert p.per_100g.fat >= 0
        assert p.per_100g.carbs >= 0


def test_search_is_case_insensitive_substring_match():
    results = search_products("банан")
    assert any(p.name == "Банан" for p in results)

    results_upper = search_products("БАНАН")
    assert [p.name for p in results_upper] == [p.name for p in results]


def test_search_matches_substring_anywhere_in_name():
    results = search_products("грудка")
    assert any(p.name == "Куриная грудка" for p in results)


def test_search_partial_prefix_returns_multiple_matches():
    # "тв" matches both "Творог 5%" and "Сыр твёрдый (Российский)"
    results = search_products("тв")
    names = {p.name for p in results}
    assert "Творог 5%" in names
    assert "Сыр твёрдый (Российский)" in names


def test_search_with_no_match_returns_empty_list():
    assert search_products("несуществующий продукт xyz123") == []


def test_search_blank_query_returns_empty_list():
    assert search_products("") == []
    assert search_products("   ") == []


def test_find_product_by_name_exact_case_insensitive():
    found = find_product_by_name("банан")
    assert found is not None
    assert found.name == "Банан"


def test_find_product_by_name_unknown_returns_none():
    assert find_product_by_name("не существует") is None


def test_portion_recalculation_uses_calculate_portion_end_to_end():
    """Sanity check that the catalog's per-100g values compose correctly
    with the existing, independently-tested calculate_portion function -
    this is exactly the call the API's GET /products/portion makes."""
    chicken = find_product_by_name("Куриная грудка")
    assert chicken is not None

    result = calculate_portion(chicken.per_100g, 150)
    assert result.calories == 248.0
    assert result.protein == 46.5
    assert result.fat == 5.4
    assert result.carbs == 0.0
