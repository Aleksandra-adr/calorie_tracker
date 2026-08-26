#!/usr/bin/env python3
"""
weekly_export.py — workflow «недельный отчёт» для Трекера калорий.

Выгружает калории/БЖУ за 7 дней, начиная с --start-date, в CSV и/или PDF.

Устроен по аналогии с workflows/daily_report.py (см. его докстринг и
workflows/DEPENDENCIES_ASSUMED.md за подробностями контрактов storage/
api/calculations, на которые опирается этот скрипт):

    1. Берёт записи о приёмах пищи за 7 дней, начиная с --start-date
       (включительно), через один из адаптеров источника данных:
         - storage  — прямое чтение через storage.meal_repository.list_meals()
         - api      — HTTP GET {API_BASE_URL}/meals?start_date=...&end_date=...
                      (см. api/API_CONTRACT.md, п. 2 — диапазон дат уже
                      поддерживается контрактом как есть, без изменений)
         - mock     — локальная фикстура workflows/fixtures/sample_meals.json
       Нормализация полей (`normalize_meal`) и разбор даты (`meal_date_str`)
       переиспользуются напрямую из daily_report.py — не переизобретаются,
       чтобы оба workflow понимали одни и те же варианты именования полей
       (models/API: product_name/weight_grams/consumed_at/proteins/fats;
       черновик фронтенда и mock-фикстура: product/weight_g/date/protein/fat).

    2. Считает итоги:
         - за неделю целиком — через calculations.aggregate_week(meals, start_date)
           (готовая, протестированная функция — сумма и среднее за 7
           календарных дней, среднее = сумма/7);
         - по каждому из 7 дней отдельно — через calculations.aggregate_day,
           чтобы в отчёте была построчная раскладка по дням, а не только
           общий итог за неделю.
       При недоступности/несовместимости calculations/ — локальный
       fallback (простое суммирование), как в daily_report.py; источник
       агрегации логируется в консоли и в файлах отчёта.

    3. Сохраняет отчёт в --output-dir (по умолчанию workflows/output/):
         - week_<start-date>.csv  — построчно по дням + итоговая строка
           за неделю + строка среднего в день (stdlib `csv`, без новых
           зависимостей);
         - week_<start-date>.pdf  — таблица по дням + строка итогов
           за неделю, оформленная как читаемый документ (не дамп текста),
           через `fpdf2` (см. requirements-weekly-export.txt — отдельный
           файл зависимостей, чтобы не трогать общий requirements.txt).

Запуск:
    python workflows/weekly_export.py --start-date 2026-08-18 --source mock
    python workflows/weekly_export.py --start-date 2026-08-18 --source storage --format csv
    python workflows/weekly_export.py --start-date 2026-08-18 --source api \
        --api-base-url http://localhost:8000 --format pdf
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional

# Windows-консоль по умолчанию не всегда открывает stdout/stderr в UTF-8 —
# та же защита, что в daily_report.py.
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

# Project root importable для `import storage...` / `import calculations...`,
# каталог workflows/ importable для переиспользования daily_report.py —
# независимо от того, из какого CWD запускают скрипт.
for _p in (str(PROJECT_ROOT), str(WORKFLOWS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# normalize_meal/meal_date_str переиспользуются буквально, не копируются —
# единая точка правды о разборе полей приёма пищи для обоих workflow.
from daily_report import normalize_meal, meal_date_str  # noqa: E402

NUTRIENTS = ("calories", "proteins", "fats", "carbs")


# ---------------------------------------------------------------------------
# Адаптеры источников данных за диапазон [start, start+7 дней)
# ---------------------------------------------------------------------------

def _load_from_storage(start: date_cls, end_exclusive: date_cls) -> list[dict]:
    """Прямое чтение из storage/ — тот же контракт, что в daily_report.py
    (storage.db.init_db(), storage.meal_repository.list_meals(start, end),
    models.meal.MealEntry.to_dict()), но за диапазон дат, а не один день."""
    from storage.db import init_db
    from storage.meal_repository import list_meals

    init_db()

    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end_exclusive, time.min)
    entries = list_meals(start=start_dt, end=end_dt)
    return [normalize_meal(e.to_dict()) for e in entries]


def _load_from_api(start: date_cls, end_exclusive: date_cls, api_base_url: str) -> list[dict]:
    """HTTP GET {api_base_url}/meals?start_date=...&end_date=... — контракт
    из api/API_CONTRACT.md п.2 (полуоткрытый интервал [start_date, end_date),
    уже поддерживается API как есть, без доработок с нашей стороны)."""
    url = (
        f"{api_base_url.rstrip('/')}/meals"
        f"?start_date={start.isoformat()}&end_date={end_exclusive.isoformat()}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Unexpected API response shape from {url}: {type(payload)}")
    return [normalize_meal(item) for item in payload]


def _load_from_mock(start: date_cls, end_exclusive: date_cls, mock_file: Path) -> list[dict]:
    """Локальная фикстура — та же, что использует daily_report.py --source mock."""
    with open(mock_file, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    normalized = [normalize_meal(item) for item in raw_items]
    start_s, end_s = start.isoformat(), end_exclusive.isoformat()
    return [m for m in normalized if start_s <= meal_date_str(m) < end_s]


def get_meals_for_week(
    start: date_cls,
    source: str,
    api_base_url: Optional[str],
    mock_file: Path,
) -> tuple[list[dict], str]:
    """Возвращает (meals, source_used) за 7 дней [start, start+6]. source:
    storage|api|mock (без "auto" — в отличие от daily_report.py, недельная
    выгрузка явно указывает источник, чтобы не гадать, откуда взялись
    цифры в отчёте, который может уйти "во внешний мир" как файл)."""
    end_exclusive = start + timedelta(days=7)

    if source == "storage":
        return _load_from_storage(start, end_exclusive), "storage"
    if source == "api":
        if not api_base_url:
            raise ValueError("--source api requires --api-base-url")
        return _load_from_api(start, end_exclusive, api_base_url), "api"
    if source == "mock":
        return _load_from_mock(start, end_exclusive, mock_file), "mock"
    raise ValueError(f"Unknown source: {source!r}")


# ---------------------------------------------------------------------------
# Агрегация: calculations.aggregate_day/aggregate_week + локальный fallback
# ---------------------------------------------------------------------------

def _to_calc_meals(meals: list[dict]) -> list[dict]:
    """Строит для calculations/ отдельный список с полями
    date/calories/protein/fat/carbs (единственное число protein/fat!) из
    внутреннего нормализованного формата — тот же маппинг, что в
    daily_report.aggregate_day(), не трогая normalize_meal()."""
    return [
        {
            "date": m.get("consumed_at"),
            "calories": m.get("calories", 0),
            "protein": m.get("proteins", 0),
            "fat": m.get("fats", 0),
            "carbs": m.get("carbs", 0),
        }
        for m in meals
    ]


def _local_day_totals(meals: list[dict], day: date_cls) -> dict:
    day_str = day.isoformat()
    day_meals = [m for m in meals if meal_date_str(m) == day_str]
    totals = {k: 0.0 for k in NUTRIENTS}
    for m in day_meals:
        for k in NUTRIENTS:
            totals[k] += float(m.get(k, 0) or 0)
    totals["meals_count"] = len(day_meals)
    return totals


def build_daily_breakdown(meals: list[dict], start: date_cls) -> tuple[list[dict], str]:
    """Построчная раскладка по 7 дням недели. Возвращает (rows,
    aggregation_source), aggregation_source: "calculations" | "local_fallback"."""
    try:
        from calculations import aggregate_day as calc_aggregate_day

        calc_meals = _to_calc_meals(meals)
        rows = []
        for i in range(7):
            day = start + timedelta(days=i)
            result = calc_aggregate_day(calc_meals, day)
            rows.append(
                {
                    "date": day.isoformat(),
                    "calories": float(result.total.calories),
                    "proteins": float(result.total.protein),
                    "fats": float(result.total.fat),
                    "carbs": float(result.total.carbs),
                    "meals_count": int(result.meal_count),
                }
            )
        return rows, "calculations"
    except Exception as err:  # noqa: BLE001 - calculations/ может измениться/отсутствовать
        print(
            f"[weekly_export] calculations.aggregate_day unavailable ({err!r}), using local fallback",
            file=sys.stderr,
        )
        rows = []
        for i in range(7):
            day = start + timedelta(days=i)
            totals = _local_day_totals(meals, day)
            rows.append({"date": day.isoformat(), **totals})
        return rows, "local_fallback"


def build_week_totals(meals: list[dict], start: date_cls) -> tuple[dict, str]:
    """Итог + среднее за неделю. Использует calculations.aggregate_week —
    готовую протестированную функцию (сумма и среднее за 7 календарных
    дней, average = total/7), с локальным fallback при недоступности."""
    try:
        from calculations import aggregate_week as calc_aggregate_week

        calc_meals = _to_calc_meals(meals)
        result = calc_aggregate_week(calc_meals, start)
        total = {
            "calories": float(result.total.calories),
            "proteins": float(result.total.protein),
            "fats": float(result.total.fat),
            "carbs": float(result.total.carbs),
            "meals_count": int(result.meal_count),
        }
        average = {
            "calories": float(result.average.calories),
            "proteins": float(result.average.protein),
            "fats": float(result.average.fat),
            "carbs": float(result.average.carbs),
        }
        return {"total": total, "average": average, "end_date": result.end_date.isoformat()}, "calculations"
    except Exception as err:  # noqa: BLE001
        print(
            f"[weekly_export] calculations.aggregate_week unavailable ({err!r}), using local fallback",
            file=sys.stderr,
        )
        end = start + timedelta(days=6)
        end_s = end.isoformat()
        start_s = start.isoformat()
        totals = {k: 0.0 for k in NUTRIENTS}
        count = 0
        for m in meals:
            d = meal_date_str(m)
            if start_s <= d <= end_s:
                count += 1
                for k in NUTRIENTS:
                    totals[k] += float(m.get(k, 0) or 0)
        average = {k: round(totals[k] / 7, 2) for k in NUTRIENTS}
        totals["meals_count"] = count
        return {"total": totals, "average": average, "end_date": end_s}, "local_fallback"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

RU_DAY_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def write_csv(
    daily_rows: list[dict],
    week_totals: dict,
    start: date_cls,
    end: date_cls,
    meta: dict,
    out_path: Path,
) -> None:
    """Построчно по дням (дата, калории, белки, жиры, углеводы, число
    приёмов) + итоговая строка за неделю + строка среднего в день.

    utf-8-sig (BOM), чтобы Excel на Windows сразу открывал кириллицу без
    ручного выбора кодировки — CSV всё равно читается любым другим
    инструментом, который понимает BOM/UTF-8.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([f"Недельный отчёт: {start.isoformat()} — {end.isoformat()}"])
        writer.writerow([f"Источник данных: {meta['data_source']}", f"Источник агрегации: {meta['aggregation_source']}"])
        writer.writerow([])
        writer.writerow(
            ["Дата", "День недели", "Калории, ккал", "Белки, г", "Жиры, г", "Углеводы, г", "Приёмов пищи"]
        )
        for i, row in enumerate(daily_rows):
            writer.writerow(
                [
                    row["date"],
                    RU_DAY_NAMES[i],
                    row["calories"],
                    row["proteins"],
                    row["fats"],
                    row["carbs"],
                    row["meals_count"],
                ]
            )
        writer.writerow([])
        t = week_totals["total"]
        writer.writerow(
            ["ИТОГО за неделю", "", t["calories"], t["proteins"], t["fats"], t["carbs"], t["meals_count"]]
        )
        a = week_totals["average"]
        writer.writerow(
            ["Среднее в день", "", a["calories"], a["proteins"], a["fats"], a["carbs"], ""]
        )


# ---------------------------------------------------------------------------
# PDF (fpdf2)
# ---------------------------------------------------------------------------

def _find_unicode_font() -> Optional[Path]:
    """Ищет TTF-шрифт с поддержкой кириллицы для встраивания в PDF.

    fpdf2 из коробки поддерживает только встроенные PDF-шрифты (Helvetica/
    Times/Courier), которые понимают latin-1 и не могут напечатать
    кириллицу. В проекте сознательно не хранится бинарный файл шрифта
    (лишний бинарник в репозитории учебного проекта, вопросы лицензии) —
    вместо этого ищем уже установленный в системе Unicode-шрифт по
    стандартным путям Windows/Linux/macOS. Если ничего не найдено —
    build_pdf() переключается на английские подписи с core-шрифтом
    Helvetica, чтобы PDF не сломался на кириллице, а не молча выдал мусор.
    """
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def build_pdf(
    daily_rows: list[dict],
    week_totals: dict,
    start: date_cls,
    end: date_cls,
    meta: dict,
    out_path: Path,
) -> None:
    from fpdf import FPDF

    out_path.parent.mkdir(parents=True, exist_ok=True)

    font_path = _find_unicode_font()
    cyr_ok = font_path is not None

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    if cyr_ok:
        pdf.add_font("Body", "", str(font_path))
        family = "Body"
    else:
        family = "Helvetica"
        print(
            "[weekly_export] no Unicode TTF font found on this system - "
            "PDF will use English labels with the built-in Helvetica font "
            "instead of Cyrillic",
            file=sys.stderr,
        )

    def T(ru: str, en: str) -> str:
        return ru if cyr_ok else en

    pdf.set_font(family, size=16)
    pdf.cell(0, 10, T(f"Недельный отчёт: {start.isoformat()} — {end.isoformat()}",
                      f"Weekly report: {start.isoformat()} - {end.isoformat()}"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(family, size=10)
    pdf.cell(0, 6, T(f"Сформирован: {meta['generated_at']}", f"Generated: {meta['generated_at']}"),
              new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        T(
            f"Источник данных: {meta['data_source']}   |   Источник агрегации: {meta['aggregation_source']}",
            f"Data source: {meta['data_source']}   |   Aggregation source: {meta['aggregation_source']}",
        ),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(4)

    headers = [
        T("Дата", "Date"),
        T("День", "Day"),
        T("Калории, ккал", "Calories, kcal"),
        T("Белки, г", "Protein, g"),
        T("Жиры, г", "Fat, g"),
        T("Углеводы, г", "Carbs, g"),
        T("Приёмов", "Meals"),
    ]
    col_widths = [32, 18, 38, 30, 30, 34, 25]
    row_h = 8

    pdf.set_font(family, size=11)
    pdf.set_fill_color(225, 225, 225)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, row_h, h, border=1, align="C", fill=True)
    pdf.ln(row_h)

    pdf.set_font(family, size=10)
    for i, row in enumerate(daily_rows):
        pdf.cell(col_widths[0], row_h, row["date"], border=1)
        pdf.cell(col_widths[1], row_h, T(RU_DAY_NAMES[i], RU_DAY_NAMES[i]) if cyr_ok else "", border=1, align="C")
        pdf.cell(col_widths[2], row_h, f"{row['calories']:.0f}", border=1, align="R")
        pdf.cell(col_widths[3], row_h, f"{row['proteins']:.1f}", border=1, align="R")
        pdf.cell(col_widths[4], row_h, f"{row['fats']:.1f}", border=1, align="R")
        pdf.cell(col_widths[5], row_h, f"{row['carbs']:.1f}", border=1, align="R")
        pdf.cell(col_widths[6], row_h, str(row["meals_count"]), border=1, align="R")
        pdf.ln(row_h)

    t = week_totals["total"]
    pdf.set_fill_color(214, 235, 214)
    pdf.cell(col_widths[0], row_h, T("ИТОГО", "TOTAL"), border=1, fill=True)
    pdf.cell(col_widths[1], row_h, "", border=1, fill=True)
    pdf.cell(col_widths[2], row_h, f"{t['calories']:.0f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[3], row_h, f"{t['proteins']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[4], row_h, f"{t['fats']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[5], row_h, f"{t['carbs']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[6], row_h, str(t["meals_count"]), border=1, align="R", fill=True)
    pdf.ln(row_h)

    a = week_totals["average"]
    pdf.set_fill_color(223, 223, 240)
    pdf.cell(col_widths[0], row_h, T("Среднее/день", "Avg/day"), border=1, fill=True)
    pdf.cell(col_widths[1], row_h, "", border=1, fill=True)
    pdf.cell(col_widths[2], row_h, f"{a['calories']:.0f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[3], row_h, f"{a['proteins']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[4], row_h, f"{a['fats']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[5], row_h, f"{a['carbs']:.1f}", border=1, align="R", fill=True)
    pdf.cell(col_widths[6], row_h, "", border=1, fill=True)
    pdf.ln(row_h)

    pdf.output(str(out_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Недельный отчёт по калориям/БЖУ (CSV/PDF)")
    parser.add_argument(
        "--start-date", type=str, required=True, help="YYYY-MM-DD — начало недели (7 дней включительно)"
    )
    parser.add_argument(
        "--source", choices=["storage", "api", "mock"], required=True, help="Источник данных о приёмах пищи"
    )
    parser.add_argument("--format", choices=["csv", "pdf", "both"], default="both")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    parser.add_argument("--api-base-url", type=str, default=None, help="Базовый URL API (обязателен для --source api)")
    parser.add_argument("--mock-file", type=str, default=str(DEFAULT_MOCK_FILE))
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    start = date_cls.fromisoformat(args.start_date)
    end = start + timedelta(days=6)

    meals, source_used = get_meals_for_week(
        start,
        source=args.source,
        api_base_url=args.api_base_url,
        mock_file=Path(args.mock_file),
    )

    daily_rows, agg_day_source = build_daily_breakdown(meals, start)
    week_totals, agg_week_source = build_week_totals(meals, start)

    # Защита от расхождения между построчной раскладкой по дням и итогом
    # за неделю (не должно случиться при одинаковом источнике агрегации на
    # одном и том же диапазоне дат — но не молчим, если вдруг разошлось).
    sum_of_days = sum(row["meals_count"] for row in daily_rows)
    if sum_of_days != week_totals["total"]["meals_count"]:
        print(
            f"[weekly_export] WARNING: meals_count mismatch — "
            f"sum(daily_rows)={sum_of_days} vs week_totals={week_totals['total']['meals_count']}",
            file=sys.stderr,
        )

    meta = {
        "data_source": source_used,
        "aggregation_source": agg_week_source if agg_week_source == agg_day_source else f"{agg_day_source}/{agg_week_source}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / f"week_{start.isoformat()}.csv"
    pdf_path = output_dir / f"week_{start.isoformat()}.pdf"

    written = []
    if args.format in ("csv", "both"):
        write_csv(daily_rows, week_totals, start, end, meta, csv_path)
        written.append(csv_path)
    if args.format in ("pdf", "both"):
        build_pdf(daily_rows, week_totals, start, end, meta, pdf_path)
        written.append(pdf_path)

    print(f"Неделя: {start.isoformat()} — {end.isoformat()}")
    print(f"Источник данных: {source_used}  |  Источник агрегации: {meta['aggregation_source']}")
    print(f"Приёмов пищи за неделю: {week_totals['total']['meals_count']}")
    t = week_totals["total"]
    print(f"Итого: {t['calories']:.0f} ккал / {t['proteins']:.1f} Б / {t['fats']:.1f} Ж / {t['carbs']:.1f} У")
    a = week_totals["average"]
    print(f"Среднее в день: {a['calories']:.0f} ккал / {a['proteins']:.1f} Б / {a['fats']:.1f} Ж / {a['carbs']:.1f} У")
    for p in written:
        print(f"Файл: {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
