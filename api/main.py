"""
FastAPI application exposing CRUD endpoints for meal entries.

Run with:
    uvicorn api.main:app --reload

(run from the project root so that the `models`, `storage`, and `api`
packages are importable - see requirements.txt / README notes from the
coordinator's report for full setup instructions.)
"""

from __future__ import annotations


import json
import tempfile

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

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

from api.schemas import (
    ErrorResponse,
    MealEntryCreate,
    MealEntryResponse,
    MealEntryUpdate,
    MealsSummaryResponse,
    NutrientDiff,
)

# --- Дневная норма калорий/БЖУ -------------------------------------------
#
# Единый источник истины для значений по умолчанию — workflows/config.json
# (тот же файл читает workflows/daily_report.py). api/ читает его как
# ПРОСТОЙ JSON-файл с данными (не импортирует пакет workflows/), чтобы не
# создавать зависимость между независимо развиваемыми зонами проекта —
# тот же принцип, что и у calculations/ (см. REPORT.md, п.3.2).
#
# Если файл недоступен/повреждён — используются те же числа (2000/50/65/300),
# что и DEFAULT_NORMS в workflows/daily_report.py, так что поведение не
# расходится между workflow-отчётом и живым API даже в этом случае.
NUTRIENTS = ("calories", "proteins", "fats", "carbs")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
NORMS_CONFIG_PATH = _PROJECT_ROOT / "workflows" / "config.json"

DEFAULT_NORMS: dict[str, float] = {
    "calories": 2000.0,
    "proteins": 50.0,
    "fats": 65.0,
    "carbs": 300.0,
}

# "Близко к норме" начинается с этого процента (включительно); 100%+ = "exceeded".
NEAR_NORM_THRESHOLD_PERCENT = 90.0


def _load_default_norms() -> dict[str, float]:
    norms = dict(DEFAULT_NORMS)
    try:
        with open(NORMS_CONFIG_PATH, "r", encoding="utf-8") as f:
            file_cfg = json.load(f)
        for key in NUTRIENTS:
            if key in file_cfg:
                norms[key] = float(file_cfg[key])
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        # Файл отсутствует/битый/не JSON — тихо остаёмся на DEFAULT_NORMS,
        # это учебный вспомогательный эндпоинт, а не критичная настройка.
        pass
    return norms


def _diff_status(percent_of_norm: Optional[float]) -> str:
    if percent_of_norm is None:
        return "ok"
    if percent_of_norm >= 100.0:
        return "exceeded"
    if percent_of_norm >= NEAR_NORM_THRESHOLD_PERCENT:
        return "near"
    return "ok"

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


@app.get("/meals/summary", response_model=MealsSummaryResponse)
def get_meals_summary(
    date_: date = Query(..., alias="date", description="Calendar day to summarize, YYYY-MM-DD."),
    calories: Optional[float] = Query(
        None, ge=0, description="Override the calories norm for this request only (does not persist)."
    ),
    proteins: Optional[float] = Query(
        None, ge=0, description="Override the proteins norm (grams) for this request only."
    ),
    fats: Optional[float] = Query(
        None, ge=0, description="Override the fats norm (grams) for this request only."
    ),
    carbs: Optional[float] = Query(
        None, ge=0, description="Override the carbs norm (grams) for this request only."
    ),
) -> MealsSummaryResponse:
    """Дневные итоги калорий/БЖУ + норма + флаги превышения по показателю.

    Норма по умолчанию берётся из workflows/config.json (тот же файл, что
    использует workflows/daily_report.py) — единый источник истины на
    2026-08-25. Можно переопределить точечно через query-параметры
    ?calories=&proteins=&fats=&carbs= — переопределение действует только
    на этот конкретный запрос, ничего не сохраняется на сервере.

    Считать превышение здесь, а не заново в JS на фронтенде, выбрано
    потому что: 1) норма и логика "факт/норма/статус" уже есть и проверена
    в workflows/daily_report.py::compute_diff — этот эндпоинт зеркалит её,
    так что появляется один явный контракт вместо двух независимых
    реализаций сравнения (Python workflow и JS), которые могли бы разойтись;
    2) сумма по дню в любом случае должна быть посчитана по полному набору
    записей за день, а не по тому, что уже отрисовано в текущей таблице
    фронтенда — надёжнее взять её из storage напрямую, как в GET /meals.
    """
    start = datetime.combine(date_, datetime.min.time())
    end = start + timedelta(days=1)
    entries = list_meals(start=start, end=end)

    totals = {key: 0.0 for key in NUTRIENTS}
    for entry in entries:
        totals["calories"] += entry.calories
        totals["proteins"] += entry.proteins
        totals["fats"] += entry.fats
        totals["carbs"] += entry.carbs

    norms = _load_default_norms()
    overrides = {"calories": calories, "proteins": proteins, "fats": fats, "carbs": carbs}
    for key, value in overrides.items():
        if value is not None:
            norms[key] = value

    diff: dict[str, NutrientDiff] = {}
    for key in NUTRIENTS:
        actual = round(totals[key], 2)
        norm = norms[key]
        delta = round(actual - norm, 2)
        percent = round(actual / norm * 100, 1) if norm else None
        diff[key] = NutrientDiff(
            actual=actual,
            norm=norm,
            diff=delta,
            percent_of_norm=percent,
            status=_diff_status(percent),
        )

    return MealsSummaryResponse(
        date=date_.isoformat(),
        meals_count=len(entries),
        totals={key: round(totals[key], 2) for key in NUTRIENTS},
        norms=norms,
        diff=diff,
    )


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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/reports/weekly",
    responses={
        200: {"content": {"text/csv": {}, "application/pdf": {}}},
        422: {"model": ErrorResponse},
    },
)
def get_weekly_report(
    start_date: date = Query(..., description="Start of the week (YYYY-MM-DD), inclusive."),
    format: str = Query("csv", pattern="^(csv|pdf)$", description="csv or pdf"),
):
    """Generate and download the weekly CSV/PDF report for the 7-day period
    starting at ``start_date`` (see workflows/weekly_export.py - this
    endpoint is a thin HTTP wrapper around the same aggregation/rendering
    functions, reading meals directly from storage/ rather than looping
    back through HTTP).
    """
    # Local import: keeps workflows/ a script-first module (importable, but
    # not a hard dependency of the API at process-startup time) and avoids
    # any import-order surprises between api/ and workflows/.
    from workflows.weekly_export import (
        build_daily_breakdown,
        build_pdf,
        build_week_totals,
        get_meals_for_week,
        write_csv,
    )

    try:
        meals, source_used = get_meals_for_week(start_date, "storage", None, Path())
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Could not load meals from storage: {err!r}") from err

    daily_rows, agg_day_source = build_daily_breakdown(meals, start_date)
    week_totals, agg_week_source = build_week_totals(meals, start_date)
    end_date = start_date + timedelta(days=6)
    meta = {
        "data_source": source_used,
        "aggregation_source": agg_week_source if agg_week_source == agg_day_source else f"{agg_day_source}/{agg_week_source}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    tmp_dir = Path(tempfile.gettempdir())
    filename = f"week_{start_date.isoformat()}.{format}"

    if format == "csv":
        out_path = tmp_dir / f"api_weekly_report_{start_date.isoformat()}.csv"
        write_csv(daily_rows, week_totals, start_date, end_date, meta, out_path)
        return FileResponse(out_path, media_type="text/csv; charset=utf-8", filename=filename)

    out_path = tmp_dir / f"api_weekly_report_{start_date.isoformat()}.pdf"
    build_pdf(daily_rows, week_totals, start_date, end_date, meta, out_path)
    return FileResponse(out_path, media_type="application/pdf", filename=filename)
