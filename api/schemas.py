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
