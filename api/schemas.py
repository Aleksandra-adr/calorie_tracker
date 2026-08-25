"""
Pydantic request/response schemas - the validation boundary of the API.

All incoming data is validated here (types, ranges, required fields)
BEFORE it ever reaches storage/. storage/ additionally has CHECK
constraints as a defense-in-depth last line, but it should never be the
first thing to reject bad input in normal operation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MealEntryBase(BaseModel):
    product_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Name of the food product, e.g. 'Овсяная каша'",
    )
    weight_grams: float = Field(
        ..., gt=0, le=100000, description="Weight in grams, must be > 0"
    )
    consumed_at: datetime = Field(
        ..., description="Date (and, ideally, time) the meal was consumed, ISO 8601"
    )
    calories: float = Field(..., ge=0, description="Calories (kcal), must be >= 0")
    proteins: float = Field(..., ge=0, description="Proteins in grams, must be >= 0")
    fats: float = Field(..., ge=0, description="Fats in grams, must be >= 0")
    carbs: float = Field(..., ge=0, description="Carbohydrates in grams, must be >= 0")

    @field_validator("product_name")
    @classmethod
    def strip_and_validate_product_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("product_name must not be blank")
        return v


class MealEntryCreate(MealEntryBase):
    """Body for POST /meals."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "product_name": "Овсяная каша",
                "weight_grams": 250,
                "consumed_at": "2026-08-24T08:30:00",
                "calories": 300,
                "proteins": 10,
                "fats": 6,
                "carbs": 50,
            }
        }
    )


class MealEntryUpdate(MealEntryBase):
    """Body for PUT /meals/{id}. Full replace - all fields required."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "product_name": "Овсяная каша с бананом",
                "weight_grams": 300,
                "consumed_at": "2026-08-24T08:30:00",
                "calories": 380,
                "proteins": 11,
                "fats": 7,
                "carbs": 65,
            }
        }
    )


class MealEntryResponse(MealEntryBase):
    """Response shape returned by all endpoints."""

    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    detail: str


class ProductResponse(BaseModel):
    """One entry from the built-in product reference catalog (GET /products).

    Values are PER 100 G of the product - unlike MealEntry* above, which
    describe an actual portion. Field names deliberately match
    `calculations.portion.NutritionPer100g` (`protein`/`fat`/`carbs`,
    singular) rather than `MealEntryBase` (`proteins`/`fats`, plural), to
    make the "this is a per-100g reference value, not a portion" distinction
    visible in the shape of the response itself.
    """

    name: str = Field(..., description="Product name, e.g. 'Банан'")
    calories: float = Field(..., ge=0, description="Calories per 100 g")
    protein: float = Field(..., ge=0, description="Protein per 100 g, grams")
    fat: float = Field(..., ge=0, description="Fat per 100 g, grams")
    carbs: float = Field(..., ge=0, description="Carbohydrates per 100 g, grams")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"name": "Банан", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 23.0}
        }
    )


class PortionResponse(BaseModel):
    """Response for GET /products/portion - a recalculated portion.

    Unlike ProductResponse (per 100 g), this describes an actual portion of
    the given weight, so field names match MealEntryBase (`calories`,
    `proteins`, `fats`, `carbs`, plural) - the frontend can drop these
    values straight into the meal-creation form fields. The numbers here
    are produced by `calculations.calculate_portion`, the same function
    tested in `tests/test_calculations.py`, not re-implemented here - this
    endpoint exists specifically so the frontend never has to duplicate
    the "per_100g * weight_g / 100" formula in JavaScript.
    """

    product_name: str
    weight_grams: float = Field(..., ge=0, le=100000)
    calories: float = Field(..., ge=0)
    proteins: float = Field(..., ge=0)
    fats: float = Field(..., ge=0)
    carbs: float = Field(..., ge=0)
