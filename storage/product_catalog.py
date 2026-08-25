"""
Small, read-only reference catalog of common food products with their
nutritional value per 100 g.

WHY THIS EXISTS / WHERE IT PLUGS IN
------------------------------------
`models/meal.py` documents an intentional, honestly-flagged gap: meal
entries store calories/proteins/fats/carbs as values typed in directly by
the caller, because at the time there was no product catalog to compute
them from. `calculations/portion.py` has a working, tested
`calculate_portion(per_100g, weight_g)` function that nobody calls.

This module closes exactly that gap on the "data" side: it provides a
small seed catalog (~19 common products, see `products_seed.json`) and a
case-insensitive substring search over it, so the API (`api/main.py`) can
expose `GET /products?q=...` for autocomplete and `GET /products/portion`
for weight-based recalculation - which in turn calls the existing,
already-tested `calculations.calculate_portion` instead of re-implementing
the "per-100g * weight / 100" formula a second time.

DESIGN NOTES
------------
- Placed in `storage/` (not `models/`) because it is read-only reference
  *data* loaded from a JSON seed file, analogous to how `storage/db.py`
  loads/serves persisted data - it is not a mutable domain entity like
  `models/meal.py`. There is no database table for it (it's small, fixed,
  and ships with the repo); if the catalog ever needs to grow, become
  editable, or be queried more richly, promoting it into a real SQLite
  table alongside `meal_entries` would be the natural next step, but that
  was judged out of scope for a ~15-20 item reference list.
- Uses `calculations.portion.NutritionPer100g` as the per-100g value type
  directly (rather than inventing a parallel dataclass) so that
  `calculate_portion` can be called on it without any adapter/mapping step.
- Loaded once at import time into an in-memory list - the catalog is small
  and static for the lifetime of the process, so there is no need for a
  database round trip on every search.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from calculations.portion import NutritionPer100g

CATALOG_PATH = Path(__file__).resolve().parent / "products_seed.json"


@dataclass(frozen=True)
class Product:
    """A single catalog entry: a product name plus its per-100g nutrition."""

    name: str
    per_100g: NutritionPer100g


def _load_catalog(path: Path = CATALOG_PATH) -> List[Product]:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        Product(
            name=item["name"],
            per_100g=NutritionPer100g(
                calories=item["calories"],
                protein=item["protein"],
                fat=item["fat"],
                carbs=item["carbs"],
            ),
        )
        for item in raw
    ]


# Loaded once at import time - see "DESIGN NOTES" above.
_CATALOG: List[Product] = _load_catalog()


def search_products(query: str) -> List[Product]:
    """Case-insensitive substring search over product names.

    Returns an empty list for a blank/whitespace-only query (rather than
    "everything"), so that an autocomplete UI that fires on every
    keystroke doesn't dump the whole catalog before the user has typed
    anything meaningful.
    """
    q = query.strip().lower()
    if not q:
        return []
    return [p for p in _CATALOG if q in p.name.lower()]


def find_product_by_name(name: str) -> Optional[Product]:
    """Exact (case-insensitive, whitespace-trimmed) lookup by product name.

    Used by the portion-recalculation endpoint: the frontend always sends
    back the exact `name` it got from a `search_products` result, so an
    exact match is sufficient and unambiguous (no need for fuzzy matching).
    """
    target = name.strip().lower()
    for p in _CATALOG:
        if p.name.lower() == target:
            return p
    return None


def all_products() -> List[Product]:
    """Return the full catalog (mainly useful for tests/debugging)."""
    return list(_CATALOG)
