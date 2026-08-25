"""
Domain model for a meal entry (приём пищи).

DESIGN DECISION (documented per task requirement):
----------------------------------------------------
Calories and macros (proteins/fats/carbs) are supplied DIRECTLY by the
caller when a meal entry is created/updated - they are NOT derived
automatically from `weight_grams` and a per-100g reference value in a
product catalog.

Why:
  - The project structure handed to this agent contains no "product
    catalog / reference food database" concept anywhere in models/,
    storage/, or api/ - and building one was out of scope for this task
    (it would also duplicate whatever calculations/ ends up doing).
  - Keeping calories/proteins/fats/carbs as plain required fields on the
    meal entry keeps storage/api simple, dependency-free, and lets the
    calculations/ module (owned by another agent) layer any "compute
    calories from a product catalog" logic on top later without a
    breaking schema change - it can simply compute the numbers and pass
    them into this same API/schema.
  - `weight_grams` is still stored, both because the task explicitly asks
    for it and because it is useful context (e.g. for a future per-100g
    reference feature) even though it is not currently used in a formula.

If a product-catalog-driven calculation is added later, the natural
extension point is: compute calories/proteins/fats/carbs client-side (or
in calculations/) from weight_grams * (per-100g values) and submit the
result through the existing MealEntryCreate/Update schemas - no schema
change required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class MealEntry:
    """Domain representation of a single meal entry / food record."""

    product_name: str
    weight_grams: float
    consumed_at: datetime
    calories: float
    proteins: float
    fats: float
    carbs: float
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    @classmethod
    def from_row(cls, row: Any) -> "MealEntry":
        """Build a MealEntry from a sqlite3.Row (or any Mapping-like row)."""
        return cls(
            id=row["id"],
            product_name=row["product_name"],
            weight_grams=row["weight_grams"],
            consumed_at=cls._parse_dt(row["consumed_at"]),
            calories=row["calories"],
            proteins=row["proteins"],
            fats=row["fats"],
            carbs=row["carbs"],
            created_at=cls._parse_dt(row["created_at"]),
            updated_at=cls._parse_dt(row["updated_at"]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_name": self.product_name,
            "weight_grams": self.weight_grams,
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
            "calories": self.calories,
            "proteins": self.proteins,
            "fats": self.fats,
            "carbs": self.carbs,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
