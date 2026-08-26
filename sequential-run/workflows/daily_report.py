"""Workflow «дневной отчёт»: взять записи за дату -> посчитать итоги ->
сравнить с нормой -> сохранить сводку -> пометить как выполненное.

Повторный запуск с теми же исходными данными идемпотентен: статус run
"unchanged", файл сводки не переписывается.

Запуск:
    python workflows/daily_report.py --date 2026-08-24 --api-base-url http://localhost:8000
    python workflows/daily_report.py --date 2026-08-24 --source storage
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date as Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calculations.aggregation import aggregate_day  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_CONFIG = Path(__file__).parent / "config.json"


def load_norm(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def get_meals_from_api(base_url: str, target_date: Date) -> list[dict]:
    url = f"{base_url}/meals?date={target_date.isoformat()}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Не удалось получить данные с API {url}: {exc}") from exc


def get_meals_from_storage(target_date: Date) -> list[dict]:
    from storage import meal_repository as repo

    meals = repo.list_meals(start=target_date, end=target_date)
    return [m.to_dict() for m in meals]


def combined_hash(meals: list[dict], norm: dict) -> str:
    payload = json.dumps({"meals": meals, "norm": norm}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_summary(target_date: Date, meals: list[dict], norm: dict) -> dict:
    totals = aggregate_day(meals, target_date)
    totals_dict = asdict(totals)
    diff = {k: round(totals_dict[k] - norm[k], 2) for k in norm}
    return {
        "date": target_date.isoformat(),
        "meal_count": len(meals),
        "totals": totals_dict,
        "norm": norm,
        "diff": diff,
        "hash": combined_hash(meals, norm),
    }


def run(target_date: Date, source: str, api_base_url: str, config_path: Path) -> dict:
    norm = load_norm(config_path)
    if source == "api":
        meals = get_meals_from_api(api_base_url, target_date)
    elif source == "storage":
        meals = get_meals_from_storage(target_date)
    else:
        raise ValueError(f"Неизвестный источник: {source}")

    summary = build_summary(target_date, meals, norm)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{target_date.isoformat()}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("hash") == summary["hash"]:
            summary["status"] = "unchanged"
            return summary

    summary["status"] = "recomputed"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Дневной отчёт по калориям")
    parser.add_argument("--date", default=Date.today().isoformat())
    parser.add_argument("--source", choices=["api", "storage"], default="api")
    parser.add_argument("--api-base-url", default="http://localhost:8000")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    target_date = Date.fromisoformat(args.date)
    summary = run(target_date, args.source, args.api_base_url, Path(args.config))

    print(f"Дата: {summary['date']}")
    print(f"Приёмов пищи: {summary['meal_count']}")
    print(f"Итоги: {summary['totals']}")
    print(f"Норма: {summary['norm']}")
    print(f"Разница: {summary['diff']}")
    print(f"Статус: {summary['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
