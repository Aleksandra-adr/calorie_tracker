#!/usr/bin/env python3
"""
daily_report.py — workflow «дневной отчёт» для Трекера калорий.

Что делает (см. workflows/DEPENDENCIES_ASSUMED.md за подробностями и
источниками контрактов):

    1. Берёт записи о приёмах пищи за указанную дату (по умолчанию —
       сегодня) через один из адаптеров источника данных:
         - storage  (по умолчанию, если доступен) — прямое чтение через
           storage.meal_repository.list_meals() + models.meal.MealEntry
         - api      — HTTP GET {API_BASE_URL}/meals?date=YYYY-MM-DD
         - mock     — локальная фикстура workflows/fixtures/sample_meals.json
       См. функции _load_from_storage / _load_from_api / _load_from_mock —
       это и есть "ADAPTER SWAP POINT": если контракт storage/api
       изменится, править нужно только внутри этих функций.

    2. Считает итоги дня (калории, белки, жиры, углеводы) — пробует
       импортировать calculations.aggregate_day(meals), при её отсутствии
       использует локальный fallback _aggregate_day_local().

    3. Сравнивает итоги с нормой (по умолчанию — референс для рациона
       2000 ккал; настраивается через --calories/--proteins/--fats/--carbs
       или --config <path.json>).

    4. Сохраняет сводку в workflows/output/<YYYY-MM-DD>.json и
       workflows/output/<YYYY-MM-DD>.md.

    5. Идемпотентность: сводка помечается хэшем исходных данных + нормы
       (meta.combined_hash). Повторный запуск с тем же набором данных и
       той же нормой на ту же дату:
         - не переписывает файлы отчёта (их содержимое было бы побайтово
           идентично — mtime тоже не трогаем, это и есть доказательство
           идемпотентности), в консоль выводится статус "unchanged" —
           "уже выполнено на эту дату, данные не менялись";
         - при этом в workflows/output/run_log.jsonl всегда добавляется
           запись о факте запуска (аудит-лог самих запусков, отдельно от
           отчёта), со статусом created / unchanged / recomputed.
       Если данные или норма изменились — файлы отчёта перезаписываются
       (status "recomputed"), либо `--force` заставляет перезаписать
       принудительно даже без изменений (полезно для отладки).

Запуск:
    python workflows/daily_report.py
    python workflows/daily_report.py --date 2026-08-24
    python workflows/daily_report.py --source mock
    python workflows/daily_report.py --calories 2200 --proteins 120
    python workflows/daily_report.py --config workflows/config.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

# Windows-консоль по умолчанию не всегда открывает stdout/stderr в UTF-8,
# из-за чего кириллица в выводе превращается в "?????". Переключаем явно,
# если интерпретатор это поддерживает (Python 3.7+, io.TextIOWrapper).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

WORKFLOWS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOWS_DIR.parent
OUTPUT_DIR = WORKFLOWS_DIR / "output"
FIXTURES_DIR = WORKFLOWS_DIR / "fixtures"
DEFAULT_MOCK_FILE = FIXTURES_DIR / "sample_meals.json"
DEFAULT_CONFIG_FILE = WORKFLOWS_DIR / "config.json"
RUN_LOG_FILE = OUTPUT_DIR / "run_log.jsonl"

# Project root must be importable so `import storage...` / `import
# calculations...` work when this script is run directly
# (`python workflows/daily_report.py`), regardless of CWD.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Референсная норма для рациона ~2000 ккал (см. DEPENDENCIES_ASSUMED.md
# п.3). Настраивается через CLI / --config.
DEFAULT_NORMS = {
    "calories": 2000,
    "proteins": 50,
    "fats": 65,
    "carbs": 300,
}

NUTRIENTS = ("calories", "proteins", "fats", "carbs")


# ---------------------------------------------------------------------------
# Нормализация записи о приёме пищи в единый внутренний формат
# ---------------------------------------------------------------------------

def normalize_meal(raw: dict) -> dict:
    """Приводит запись из любого известного источника к единому виду:

        {id, product_name, weight_grams, consumed_at, calories,
         proteins, fats, carbs}

    Понимает как схему models.meal.MealEntry / api.schemas
    (product_name, weight_grams, proteins, fats, carbs), так и черновик
    фронтенда frontend/API_CONTRACT_ASSUMED.md (product, weight_g,
    protein, fat, carbs, date).
    """

    def pick(*keys, default=None):
        for k in keys:
            if k in raw and raw[k] is not None:
                return raw[k]
        return default

    return {
        "id": pick("id"),
        "product_name": pick("product_name", "product", default=""),
        "weight_grams": pick("weight_grams", "weight_g", default=0),
        "consumed_at": pick("consumed_at", "date", default=""),
        "calories": float(pick("calories", default=0) or 0),
        "proteins": float(pick("proteins", "protein", default=0) or 0),
        "fats": float(pick("fats", "fat", default=0) or 0),
        "carbs": float(pick("carbs", default=0) or 0),
    }


def meal_date_str(meal: dict) -> str:
    """Достаёт YYYY-MM-DD из нормализованного поля consumed_at, которое
    может быть либо чистой датой, либо ISO datetime."""
    raw = str(meal.get("consumed_at", ""))
    return raw[:10]


# ---------------------------------------------------------------------------
# Адаптеры источников данных ("ADAPTER SWAP POINT")
# ---------------------------------------------------------------------------

def _load_from_storage(target_date: date_cls) -> list[dict]:
    """Прямое чтение из storage/ (см. DEPENDENCIES_ASSUMED.md п.1a).

    Бросает исключение, если storage/models недоступны или их контракт
    изменился несовместимо — вызывающая сторона решает, падать или
    переключаться на следующий источник.
    """
    from storage.db import init_db  # локальный импорт: адаптер может отсутствовать
    from storage.meal_repository import list_meals

    init_db()  # безопасно вызывать повторно (CREATE TABLE IF NOT EXISTS)

    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    entries = list_meals(start=day_start, end=day_end)
    return [normalize_meal(e.to_dict()) for e in entries]


def _load_from_api(target_date: date_cls, api_base_url: str) -> list[dict]:
    """HTTP GET {api_base_url}/meals?date=YYYY-MM-DD (см.
    DEPENDENCIES_ASSUMED.md п.1b — контракт пока черновой, взят из
    frontend/API_CONTRACT_ASSUMED.md, т.к. api/API_CONTRACT.md ещё нет).
    """
    url = f"{api_base_url.rstrip('/')}/meals?date={target_date.isoformat()}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Unexpected API response shape from {url}: {type(payload)}")
    return [normalize_meal(item) for item in payload]


def _load_from_mock(target_date: date_cls, mock_file: Path = DEFAULT_MOCK_FILE) -> list[dict]:
    """Локальная фикстура — резервный источник для разработки/проверки
    повторяемости workflow, когда ни storage, ни api недоступны."""
    with open(mock_file, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    normalized = [normalize_meal(item) for item in raw_items]
    return [m for m in normalized if meal_date_str(m) == target_date.isoformat()]


def get_meals_for_date(
    target_date: date_cls,
    source: str = "auto",
    api_base_url: Optional[str] = None,
    mock_file: Path = DEFAULT_MOCK_FILE,
) -> tuple[list[dict], str]:
    """Возвращает (meals, source_used). source: auto|storage|api|mock."""

    api_base_url = api_base_url or os.environ.get("DAILY_REPORT_API_BASE_URL")

    if source == "storage":
        return _load_from_storage(target_date), "storage"
    if source == "api":
        if not api_base_url:
            raise ValueError("--source api requires --api-base-url or DAILY_REPORT_API_BASE_URL")
        return _load_from_api(target_date, api_base_url), "api"
    if source == "mock":
        return _load_from_mock(target_date, mock_file), "mock"

    if source != "auto":
        raise ValueError(f"Unknown source: {source!r}")

    # auto: storage -> api (если задан base url) -> mock
    try:
        return _load_from_storage(target_date), "storage"
    except Exception as storage_err:  # noqa: BLE001 - намеренно широкий fallback
        print(f"[daily_report] storage adapter unavailable ({storage_err!r}), trying api/mock", file=sys.stderr)

    if api_base_url:
        try:
            return _load_from_api(target_date, api_base_url), "api"
        except Exception as api_err:  # noqa: BLE001
            print(f"[daily_report] api adapter unavailable ({api_err!r}), falling back to mock", file=sys.stderr)

    return _load_from_mock(target_date, mock_file), "mock"


# ---------------------------------------------------------------------------
# Агрегация (calculations/ либо локальный fallback)
# ---------------------------------------------------------------------------

def _aggregate_day_local(meals: list[dict]) -> dict:
    totals = {k: 0.0 for k in NUTRIENTS}
    for m in meals:
        for k in NUTRIENTS:
            totals[k] += float(m.get(k, 0) or 0)
    totals["meals_count"] = len(meals)
    return totals


def aggregate_day(meals: list[dict], target_date: date_cls) -> tuple[dict, str]:
    """Возвращает (totals, aggregation_source). Пробует реальный
    calculations.aggregate_day (см. DEPENDENCIES_ASSUMED.md п.2), иначе —
    локальный fallback.

    Реальный контракт calculations.aggregate_day(meals, target_date) ->
    DayAggregate(date, total=Nutrition(calories, protein, fat, carbs),
    meal_count) ожидает на входе элементы с полями date/calories/protein/
    fat/carbs (единственное число protein/fat!) — отличается от
    proteins/fats в models.meal / нашего normalize_meal(). Поэтому здесь
    строится совместимый по именам вход именно для вызова calculations,
    не трогая сам normalize_meal() (используется остальным кодом).
    """
    try:
        from calculations import aggregate_day as calc_aggregate_day  # type: ignore

        calc_input = [
            {
                "date": m.get("consumed_at"),
                "calories": m.get("calories", 0),
                "protein": m.get("proteins", 0),
                "fat": m.get("fats", 0),
                "carbs": m.get("carbs", 0),
            }
            for m in meals
        ]
        result = calc_aggregate_day(calc_input, target_date)
        totals = {
            "calories": float(result.total.calories),
            "proteins": float(result.total.protein),
            "fats": float(result.total.fat),
            "carbs": float(result.total.carbs),
        }
        totals["meals_count"] = int(result.meal_count)
        return totals, "calculations"
    except Exception as err:  # noqa: BLE001 - calculations/ может ещё не существовать/измениться
        print(f"[daily_report] calculations.aggregate_day unavailable ({err!r}), using local fallback", file=sys.stderr)
        return _aggregate_day_local(meals), "local_fallback"


# ---------------------------------------------------------------------------
# Сравнение с нормой
# ---------------------------------------------------------------------------

def compute_diff(totals: dict, norms: dict) -> dict:
    diff = {}
    for k in NUTRIENTS:
        actual = round(float(totals.get(k, 0)), 2)
        norm = float(norms.get(k, 0))
        delta = round(actual - norm, 2)
        percent = round((actual / norm * 100), 1) if norm else None
        diff[k] = {
            "actual": actual,
            "norm": norm,
            "diff": delta,
            "percent_of_norm": percent,
        }
    return diff


# ---------------------------------------------------------------------------
# Конфиг норм
# ---------------------------------------------------------------------------

def load_norms(config_path: Optional[Path], overrides: dict) -> dict:
    norms = dict(DEFAULT_NORMS)
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            file_cfg = json.load(f)
        for k in NUTRIENTS:
            if k in file_cfg:
                norms[k] = file_cfg[k]
    for k in NUTRIENTS:
        if overrides.get(k) is not None:
            norms[k] = overrides[k]
    return norms


# ---------------------------------------------------------------------------
# Хэш исходных данных (идемпотентность)
# ---------------------------------------------------------------------------

def compute_combined_hash(meals: list[dict], norms: dict) -> str:
    meals_sorted = sorted(meals, key=lambda m: (str(m.get("consumed_at")), str(m.get("id"))))
    payload = json.dumps({"meals": meals_sorted, "norms": norms}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Сборка сводки
# ---------------------------------------------------------------------------

def build_summary(
    target_date: date_cls,
    meals: list[dict],
    totals: dict,
    norms: dict,
    diff: dict,
    source_used: str,
    aggregation_source: str,
    combined_hash: str,
) -> dict:
    return {
        "date": target_date.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meals_count": len(meals),
        "totals": {k: round(float(totals.get(k, 0)), 2) for k in NUTRIENTS},
        "norms": norms,
        "diff": diff,
        "meals": meals,
        "meta": {
            "data_source": source_used,
            "aggregation_source": aggregation_source,
            "combined_hash": combined_hash,
        },
    }


def render_markdown(summary: dict) -> str:
    lines = [
        f"# Дневной отчёт — {summary['date']}",
        "",
        f"Сформирован: {summary['generated_at']}  ",
        f"Источник данных: `{summary['meta']['data_source']}`  ",
        f"Источник агрегации: `{summary['meta']['aggregation_source']}`  ",
        f"Приёмов пищи за день: {summary['meals_count']}",
        "",
        "| Показатель | Факт | Норма | Разница | % от нормы |",
        "|---|---|---|---|---|",
    ]
    ru_names = {"calories": "Калории, ккал", "proteins": "Белки, г", "fats": "Жиры, г", "carbs": "Углеводы, г"}
    for k in NUTRIENTS:
        d = summary["diff"][k]
        pct = f"{d['percent_of_norm']}%" if d["percent_of_norm"] is not None else "—"
        lines.append(f"| {ru_names[k]} | {d['actual']} | {d['norm']} | {d['diff']:+} | {pct} |")

    lines += ["", "## Приёмы пищи", ""]
    if not summary["meals"]:
        lines.append("_Нет записей за эту дату._")
    else:
        lines.append("| Продукт | Вес, г | Калории | Белки | Жиры | Углеводы |")
        lines.append("|---|---|---|---|---|---|")
        for m in summary["meals"]:
            lines.append(
                f"| {m.get('product_name', '')} | {m.get('weight_grams', '')} | "
                f"{m.get('calories', '')} | {m.get('proteins', '')} | "
                f"{m.get('fats', '')} | {m.get('carbs', '')} |"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Запись результата + идемпотентность
# ---------------------------------------------------------------------------

def append_run_log(entry: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def save_summary(summary: dict, force: bool = False) -> str:
    """Записывает summary в workflows/output/<date>.json и .md.

    Возвращает статус: "created" | "unchanged" | "recomputed".
    Всегда добавляет запись в run_log.jsonl.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"{summary['date']}.json"
    md_path = OUTPUT_DIR / f"{summary['date']}.md"

    status = "created"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing_hash = existing.get("meta", {}).get("combined_hash")
        except (json.JSONDecodeError, OSError):
            existing_hash = None

        if existing_hash == summary["meta"]["combined_hash"] and not force:
            status = "unchanged"
        else:
            status = "recomputed"

    if status in ("created", "recomputed") or force:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(render_markdown(summary))

    append_run_log(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "date": summary["date"],
            "status": status,
            "combined_hash": summary["meta"]["combined_hash"],
            "meals_count": summary["meals_count"],
            "totals": summary["totals"],
            "data_source": summary["meta"]["data_source"],
        }
    )
    return status


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Дневной отчёт по калориям/БЖУ")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD, по умолчанию — сегодня")
    parser.add_argument("--source", choices=["auto", "storage", "api", "mock"], default="auto")
    parser.add_argument("--api-base-url", type=str, default=None, help="Базовый URL API, например http://localhost:8000")
    parser.add_argument("--mock-file", type=str, default=str(DEFAULT_MOCK_FILE))
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG_FILE), help="JSON-файл с нормой по умолчанию")
    parser.add_argument("--calories", type=float, default=None)
    parser.add_argument("--proteins", type=float, default=None)
    parser.add_argument("--fats", type=float, default=None)
    parser.add_argument("--carbs", type=float, default=None)
    parser.add_argument("--force", action="store_true", help="Перезаписать отчёт, даже если данные не изменились")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    target_date = date_cls.fromisoformat(args.date) if args.date else date_cls.today()
    config_path = Path(args.config) if args.config else None
    norms = load_norms(
        config_path,
        {"calories": args.calories, "proteins": args.proteins, "fats": args.fats, "carbs": args.carbs},
    )

    meals, source_used = get_meals_for_date(
        target_date,
        source=args.source,
        api_base_url=args.api_base_url,
        mock_file=Path(args.mock_file),
    )

    totals, aggregation_source = aggregate_day(meals, target_date)
    diff = compute_diff(totals, norms)
    combined_hash = compute_combined_hash(meals, norms)

    summary = build_summary(
        target_date, meals, totals, norms, diff, source_used, aggregation_source, combined_hash
    )
    status = save_summary(summary, force=args.force)

    print(f"Дата: {summary['date']}")
    print(f"Источник данных: {source_used}  |  Источник агрегации: {aggregation_source}")
    print(f"Приёмов пищи: {summary['meals_count']}")
    print("Итоги / норма / разница:")
    ru_names = {"calories": "Калории", "proteins": "Белки", "fats": "Жиры", "carbs": "Углеводы"}
    for k in NUTRIENTS:
        d = diff[k]
        pct = f"{d['percent_of_norm']}%" if d["percent_of_norm"] is not None else "—"
        print(f"  {ru_names[k]:10s}: {d['actual']:>8} / {d['norm']:>8}  ({d['diff']:+.2f}, {pct})")
    status_ru = {
        "created": "создан новый отчёт",
        "unchanged": "уже выполнено на эту дату — данные не менялись, файл не перезаписан",
        "recomputed": "данные изменились с прошлого запуска — отчёт пересчитан",
    }[status]
    print(f"Статус: {status} ({status_ru})")
    print(f"Файл: {OUTPUT_DIR / (summary['date'] + '.json')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
