"""FastAPI CRUD-эндпоинты для приёмов пищи."""
from __future__ import annotations

from datetime import date as Date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import MealCreate, MealOut, MealUpdate
from models.meal import MealEntry
from storage import meal_repository as repo
from storage.db import init_db

app = FastAPI(title="Трекер калорий API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/meals", response_model=MealOut, status_code=201)
def create_meal(payload: MealCreate) -> MealEntry:
    meal = MealEntry(**payload.model_dump())
    return repo.create_meal(meal)


@app.get("/meals", response_model=list[MealOut])
def list_meals(
    date: Date | None = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
) -> list[MealEntry]:
    if date is not None and (start_date is not None or end_date is not None):
        raise HTTPException(400, "Нельзя одновременно указывать date и start_date/end_date")
    if date is not None:
        return repo.list_meals(start=date, end=date)
    return repo.list_meals(start=start_date, end=end_date)


@app.get("/meals/{meal_id}", response_model=MealOut)
def get_meal(meal_id: int) -> MealEntry:
    meal = repo.get_meal(meal_id)
    if meal is None:
        raise HTTPException(404, "Приём пищи не найден")
    return meal


@app.put("/meals/{meal_id}", response_model=MealOut)
def update_meal(meal_id: int, payload: MealUpdate) -> MealEntry:
    meal = MealEntry(**payload.model_dump())
    updated = repo.update_meal(meal_id, meal)
    if updated is None:
        raise HTTPException(404, "Приём пищи не найден")
    return updated


@app.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int) -> None:
    if not repo.delete_meal(meal_id):
        raise HTTPException(404, "Приём пищи не найден")
