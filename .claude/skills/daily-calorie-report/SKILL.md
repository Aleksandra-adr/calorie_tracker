---
name: daily-calorie-report
description: Use when asked to run, regenerate, or explain the daily calorie report for the «Трекер калорий» project — a repeatable procedure that pulls a day's meals, aggregates totals, compares them to a nutrition norm, and saves a summary file. Triggers on "дневной отчёт", "отчёт по калориям за день", "daily calorie report", "прогони workflow".
---

# Дневной отчёт по калориям

Повторяемая процедура: взять записи о приёмах пищи за дату → посчитать
итоги → сравнить с нормой → сохранить сводку → пометить как выполненное.
Вся логика уже реализована в [`workflows/daily_report.py`](../../workflows/daily_report.py) —
этот скилл описывает, **как** и **когда** его вызывать, и что означает
каждый шаг, чтобы процедуру можно было использовать не задумываясь,
что происходит внутри.

## Шаг 1 — откуда берутся данные

Источник выбирается автоматически (`--source auto`, по умолчанию) в таком
порядке, с логированием, какой сработал:

1. **`storage/`** — прямое чтение `storage.meal_repository.list_meals()`
   за диапазон `[полночь даты, полночь следующего дня)`. Основной источник,
   не требует запущенного API-сервера.
2. **`api/`** — HTTP `GET {API_BASE_URL}/meals?date=YYYY-MM-DD`, если
   `storage/` недоступен и указан `--api-base-url` (или переменная
   `DAILY_REPORT_API_BASE_URL`).
3. **mock** — `workflows/fixtures/sample_meals.json`, если ни то ни другое
   не сработало. Используется для проверки самой процедуры без реальных
   данных; в сводке это явно помечается `"data_source": "mock"`.

Источник можно зафиксировать явно: `--source storage`, `--source api`,
`--source mock`.

## Шаг 2 — как считается итог

Записи приводятся к единому виду (`normalize_meal()`, понимает разные
варианты именования полей), затем сумма калорий/белков/жиров/углеводов за
дату считается через `calculations.aggregate_day()`. Если модуль
`calculations/` недоступен или бросает исключение — автоматический
локальный fallback (простое суммирование), с явной пометкой
`"aggregation_source": "local_fallback"` в сводке, чтобы разница в
источнике расчёта не потерялась незаметно.

## Шаг 3 — как сравнивается с нормой

Норма по умолчанию — референс для рациона ~2000 ккал (2000 ккал / 50 г
белка / 65 г жиров / 300 г углеводов), задана в
[`workflows/config.json`](../../workflows/config.json). Переопределяется:

- своим JSON-файлом: `--config path/to/config.json`;
- точечно через CLI: `--calories 2200 --proteins 120` (перекрывает и
  дефолт, и файл конфига).

Для каждого нутриента считается `факт − норма` и `% от нормы`.

## Шаг 4 — куда сохраняется файл

- `workflows/output/<YYYY-MM-DD>.json` — полная сводка (итоги, норма,
  разница, список приёмов пищи, `meta.combined_hash`).
- `workflows/output/<YYYY-MM-DD>.md` — та же сводка, читаемая таблица.
- `workflows/output/run_log.jsonl` — аудит-лог **каждого запуска**
  (created / unchanged / recomputed), независимо от того, изменился ли
  сам отчёт — так видно историю запусков, а не только последний результат.

**Идемпотентность:** сводка хэшируется (`meta.combined_hash` = sha256 от
приёмов пищи + нормы). Повторный запуск с теми же исходными данными на ту
же дату не переписывает `.json`/`.md` (mtime не меняется) и печатает
`unchanged`. Если данные или норма изменились — `recomputed`, файлы
перезаписываются. `--force` перезаписывает принудительно даже без
изменений (для отладки).

## Как вызвать заново

```bash
# базовый запуск: сегодняшняя дата, источник auto
python workflows/daily_report.py

# конкретная дата
python workflows/daily_report.py --date 2026-08-24

# явно через живой API
python workflows/daily_report.py --date 2026-08-24 --source api --api-base-url http://localhost:8000

# явно через storage (без сервера)
python workflows/daily_report.py --date 2026-08-24 --source storage

# своя норма
python workflows/daily_report.py --calories 2200 --proteins 120

# принудительный пересчёт
python workflows/daily_report.py --date 2026-08-24 --force
```

Ожидаемый повторный результат: второй запуск с тем же источником, той же
датой и той же нормой печатает `Статус: unchanged` и не трогает файлы
отчёта — это и есть доказательство повторяемости, а не только заявление
о ней.

## Когда этот скилл неприменим

Если контракт `storage/`, `api/` или `calculations/` изменится
несовместимо — сначала почитай
[`workflows/DEPENDENCIES_ASSUMED.md`](../../workflows/DEPENDENCIES_ASSUMED.md),
где отмечены точки подмены (`ADAPTER SWAP POINT` в коде), и поправь адаптер
внутри `daily_report.py`, а не логику этого скилла.
