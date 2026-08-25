"""
FastAPI application exposing CRUD endpoints for meal entries.

Run with:
    uvicorn api.main:app --reload

(run from the project root so that the `models`, `storage`, and `api`
packages are importable - see requirements.txt / README notes from the
coordinator's report for full setup instructions.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from calculations.portion import calculate_portion
from models.meal import MealEntry
from storage.db import init_db
from storage.meal_repository import (
    MealNotFoundError,
    create_meal,
    delete_meal,
    get_meal,
    list_meals,
    update_meal,
)
from storage.product_catalog import find_product_by_name, search_products

from api.schemas import (
    ErrorResponse,
    MealEntryCreate,
    MealEntryResponse,
    MealEntryUpdate,
    PortionResponse,
    ProductResponse,
)

app = FastAPI(
    title="Calorie Tracker API",
    description="CRUD API for meal entries (приёмы пищи).",
    version="1.0.0",
)

# The frontend may be opened directly as a file:// page (origin "null") or
# served from an arbitrary local dev port, so CORS is opened wide for this
# learning project. Tighten this before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


def _to_domain(payload: MealEntryCreate, meal_id: Optional[int] = None) -> MealEntry:
    return MealEntry(
        id=meal_id,
        product_name=payload.product_name,
        weight_grams=payload.weight_grams,
        consumed_at=payload.consumed_at,
        calories=payload.calories,
        proteins=payload.proteins,
        fats=payload.fats,
        carbs=payload.carbs,
    )


def _to_response(entry: MealEntry) -> MealEntryResponse:
    return MealEntryResponse(
        id=entry.id,
        product_name=entry.product_name,
        weight_grams=entry.weight_grams,
        consumed_at=entry.consumed_at,
        calories=entry.calories,
        proteins=entry.proteins,
        fats=entry.fats,
        carbs=entry.carbs,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


@app.exception_handler(MealNotFoundError)
def _meal_not_found_handler(request, exc: MealNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": f"Meal entry {exc.meal_id} not found"},
    )


@app.post(
    "/meals",
    response_model=MealEntryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}},
)
def create_meal_entry(payload: MealEntryCreate) -> MealEntryResponse:
    entry = create_meal(_to_domain(payload))
    return _to_response(entry)


@app.get("/meals", response_model=list[MealEntryResponse])
def list_meal_entries(
    date_: Optional[date] = Query(
        None, alias="date", description="Return entries for this single calendar day (YYYY-MM-DD)."
    ),
    start_date: Optional[datetime] = Query(
        None, description="Inclusive start of period (ISO date or datetime). Ignored if `date` is set."
    ),
    end_date: Optional[datetime] = Query(
        None, description="Exclusive end of period (ISO date or datetime). Ignored if `date` is set."
    ),
) -> list[MealEntryResponse]:
    if date_ is not None and (start_date is not None or end_date is not None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either `date` or `start_date`/`end_date`, not both.",
        )

    if date_ is not None:
        start = datetime.combine(date_, datetime.min.time())
        end = start + timedelta(days=1)
    else:
        start = start_date
        end = end_date
        if start is not None and end is not None and start > end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must not be after end_date.",
            )

    entries = list_meals(start=start, end=end)
    return [_to_response(e) for e in entries]


@app.get(
    "/meals/{meal_id}",
    response_model=MealEntryResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_meal_entry(meal_id: int) -> MealEntryResponse:
    entry = get_meal(meal_id)
    return _to_response(entry)


@app.put(
    "/meals/{meal_id}",
    response_model=MealEntryResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_meal_entry(meal_id: int, payload: MealEntryUpdate) -> MealEntryResponse:
    entry = update_meal(meal_id, _to_domain(payload, meal_id=meal_id))
    return _to_response(entry)


@app.delete(
    "/meals/{meal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
def delete_meal_entry(meal_id: int) -> None:
    delete_meal(meal_id)
    return None


@app.get("/products", response_model=list[ProductResponse])
def search_products_endpoint(
    q: str = Query(
        ...,
        min_length=1,
        description="Substring to search for in product name (case-insensitive).",
    ),
) -> list[ProductResponse]:
    """Search the built-in product reference catalog by name substring.

    Used by the frontend's autocomplete when adding a meal. Returns an
    empty list (not 404) when nothing matches, consistent with how
    `GET /meals` returns `[]` for an empty period.
    """
    matches = search_products(q)
    return [
        ProductResponse(
            name=p.name,
            calories=p.per_100g.calories,
            protein=p.per_100g.protein,
            fat=p.per_100g.fat,
            carbs=p.per_100g.carbs,
        )
        for p in matches
    ]


@app.get(
    "/products/portion",
    response_model=PortionResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_product_portion(
    product_name: str = Query(
        ..., description="Exact product name as returned by GET /products (case-insensitive)."
    ),
    weight_grams: float = Query(..., ge=0, le=100000, description="Portion weight in grams."),
) -> PortionResponse:
    """Recalculate calories/proteins/fats/carbs for a catalog product at a given weight.

    This is the single place that calls `calculations.calculate_portion` -
    the frontend calls this endpoint instead of reimplementing the
    "per_100g * weight_g / 100" formula in JavaScript, so there is exactly
    one implementation of the formula in the whole project.
    """
    product = find_product_by_name(product_name)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product '{product_name}' not found in catalog",
        )
    nutrition = calculate_portion(product.per_100g, weight_grams)
    return PortionResponse(
        product_name=product.name,
        weight_grams=weight_grams,
        calories=nutrition.calories,
        proteins=nutrition.protein,
        fats=nutrition.fat,
        carbs=nutrition.carbs,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
