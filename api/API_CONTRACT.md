# API Contract — Calorie Tracker (актуально, факт)

Этот файл — единственный источник правды по HTTP API. Он описывает то,
что РЕАЛЬНО реализовано в `api/main.py` + `api/schemas.py`, а не
предположение. Написан после реализации и ручной проверки всех
эндпоинтов (curl) на локально поднятом сервере.

Базовый URL по умолчанию: `http://127.0.0.1:8000` (порт задаётся при
запуске uvicorn, см. requirements/README-инструкцию в отчёте).

CORS: включён `CORSMiddleware` с `allow_origins=["*"]`,
`allow_credentials=False` — фронтенд, открытый как `file://` (origin
`null`) или с любого `localhost:*`, может обращаться к API без
дополнительной настройки.

## Модель "приём пищи" (meal entry)

Поля (все обязательны при создании/полном обновлении):

| Поле          | Тип                    | Ограничение                          |
|---------------|------------------------|---------------------------------------|
| `product_name`| string                 | 1..200 символов, не пустая после strip|
| `weight_grams`| number (float)         | `> 0`, `<= 100000`                    |
| `consumed_at` | string, ISO 8601 datetime | обязателен; дата+время, напр. `"2026-08-24T08:30:00"` (дата без времени `"2026-08-24"` тоже парсится pydantic'ом как полночь) |
| `calories`    | number (float)         | `>= 0`                                |
| `proteins`    | number (float)         | `>= 0`, граммы                        |
| `fats`        | number (float)         | `>= 0`, граммы                        |
| `carbs`       | number (float)         | `>= 0`, граммы                        |

Плюс поля, генерируемые сервером и возвращаемые в ответах (не передаются
в запросах): `id` (int), `created_at` (ISO datetime), `updated_at` (ISO
datetime).

**Важное архитектурное решение:** `calories`/`proteins`/`fats`/`carbs`
задаются напрямую вызывающей стороной при создании/обновлении записи —
они НЕ вычисляются автоматически на сервере из `weight_grams` и
какого-то справочника продуктов (справочника продуктов в проекте нет).
Причины и точка расширения — см. docstring в `models/meal.py`.

## Эндпоинты

### 1. Создать приём пищи

```
POST /meals
Content-Type: application/json
```

Тело запроса — `MealEntryCreate` (все поля из таблицы выше обязательны).

Пример запроса:
```json
{
  "product_name": "Овсяная каша",
  "weight_grams": 250,
  "consumed_at": "2026-08-24T08:30:00",
  "calories": 300,
  "proteins": 10,
  "fats": 6,
  "carbs": 50
}
```

Ответ `201 Created`:
```json
{
  "id": 1,
  "product_name": "Овсяная каша",
  "weight_grams": 250.0,
  "consumed_at": "2026-08-24T08:30:00",
  "calories": 300.0,
  "proteins": 10.0,
  "fats": 6.0,
  "carbs": 50.0,
  "created_at": "2026-08-24T17:47:49.642586",
  "updated_at": "2026-08-24T17:47:49.642586"
}
```

Ошибки: `422 Unprocessable Entity` при невалидных данных (стандартный
формат ошибок FastAPI/pydantic):
```json
{"detail": [{"type": "greater_than", "loc": ["body", "weight_grams"], "msg": "Input should be greater than 0", "input": -5, "ctx": {"gt": 0.0}}]}
```

### 2. Список приёмов пищи (за дату или за период)

```
GET /meals
GET /meals?date=YYYY-MM-DD
GET /meals?start_date=<ISO datetime>&end_date=<ISO datetime>
```

- Без параметров — вернёт ВСЕ записи (отсортированы по `consumed_at`, затем `id`, по возрастанию).
- `date` — записи за один календарный день (интервал `[date 00:00:00, date+1 00:00:00)` по `consumed_at`).
- `start_date` / `end_date` — задают полуоткрытый интервал `[start_date, end_date)`; можно указать только один из них (тогда другая граница не ограничена).
- `date` и `start_date`/`end_date` вместе — `400 Bad Request`:
  `{"detail": "Provide either \`date\` or \`start_date\`/\`end_date\`, not both."}`
- `start_date > end_date` — `400 Bad Request`.
- Нет записей за период — `200 OK`, пустой массив `[]` (НЕ 404).

Ответ `200 OK`: JSON-массив объектов в формате ответа п.1.

### 3. Получить одну запись

```
GET /meals/{id}
```

Ответ `200 OK` — объект в формате ответа п.1.
Ошибка `404 Not Found`, если записи с таким `id` нет:
```json
{"detail": "Meal entry 99999 not found"}
```

### 4. Обновить запись (полная замена)

```
PUT /meals/{id}
Content-Type: application/json
```

Тело — `MealEntryUpdate`, ВСЕ поля из таблицы выше обязательны (это не
частичный PATCH — все значения перезаписываются, включая те, что не
менялись). `id`, `created_at` не изменяются; `updated_at` обновляется
сервером на текущее время.

Ответ `200 OK` — обновлённый объект.
Ошибки: `404 Not Found` (нет записи), `422` (невалидные данные — как в п.1).

### 5. Удалить запись

```
DELETE /meals/{id}
```

Ответ `204 No Content` (пустое тело) при успехе.
Ошибка `404 Not Found`, если записи нет.

### 6. Health check

```
GET /health
```

Ответ `200 OK`: `{"status": "ok"}`. Не требует БД (не гарантирует, что
`init_db()` выполнился, только что процесс жив).

### 7. Недельный отчёт (CSV/PDF) — добавлено веткой `feature/weekly-export`

```
GET /reports/weekly?start_date=YYYY-MM-DD&format=csv|pdf
```

Тонкая HTTP-обёртка вокруг `workflows/weekly_export.py` (см. этот файл —
там же формат CSV/PDF описан подробно и живой прогон CLI-версии). Данные
всегда читаются напрямую из `storage/` (тот же процесс, та же БД, без
HTTP-петли на себя же).

- `start_date` — обязателен, начало недели (7 дней, `start_date` …
  `start_date + 6`, включительно).
- `format` — `csv` (по умолчанию) или `pdf`.
- Ответ `200 OK`: файл `week_<start_date>.<format>` с заголовком
  `Content-Disposition: attachment` (скачивание), `Content-Type`
  `text/csv; charset=utf-8` для CSV и `application/pdf` для PDF.
- `422 Unprocessable Entity` — некорректные `start_date`/`format`
  (стандартная ошибка валидации FastAPI/pydantic, формат как в п.1).
- `500 Internal Server Error` — не удалось прочитать `storage/` (см.
  `detail` в теле ответа).

Проверено вживую: `uvicorn`, `POST /meals` создаёт запись,
`GET /reports/weekly?start_date=...&format=csv` и `...&format=pdf`
возвращают `200 OK` с ожидаемыми `Content-Type`/`Content-Disposition` и
непустым телом (файлы сопоставимого размера с локальным прогоном CLI на
тех же данных).

## Общие соглашения об ошибках

- `400 Bad Request` — некорректная комбинация query-параметров (см. `GET /meals`).
- `404 Not Found` — тело `{"detail": "Meal entry {id} not found"}`.
- `422 Unprocessable Entity` — стандартная структура ошибок валидации FastAPI/pydantic v2 (список объектов с `type/loc/msg/input`).
- `500 Internal Server Error` — непойманная ошибка сервера (не должна возникать в штатной работе).

## Известные несовпадения с предположениями других модулей (на 2026-08-24)

Другие агенты уже писали код параллельно и до появления этого файла
опирались на предположения. Расхождения, которые должен свести
координатор:

1. **`frontend/API_CONTRACT_ASSUMED.md`** предполагает другие имена полей
   и другой формат даты:
   - `product` вместо `product_name`
   - `weight_g` вместо `weight_grams`
   - `date` (только `YYYY-MM-DD`, без времени) вместо `consumed_at` (полный ISO datetime)
   - `protein`/`fat` (единственное число) вместо `proteins`/`fats`
   - Также фронтенд не упоминает `PUT`/`DELETE` — они в реальном API есть.
   - Реальный контракт (этот файл) — приоритетный; фронтенду нужно будет
     адаптировать `mapMealFromApi`/`mapMealToApi` в `frontend/app.js`
     (судя по `API_CONTRACT_ASSUMED.md`, эта функция — единая точка
     подмены и уже спроектирована с этим в виду).
   - Совпадает: путь `/meals`, query-параметр `date` для фильтрации по
     дню, пустой массив `[]` при отсутствии записей (не 404).

2. **`storage/` и `models/`** — подтверждены `workflows/DEPENDENCIES_ASSUMED.md`
   как совпадающие 1:1 с тем, что реально реализовано здесь
   (`product_name, weight_grams, consumed_at, calories, proteins, fats,
   carbs, id, created_at, updated_at`; `list_meals(start, end)` — интервал
   `[start, end)` по `consumed_at`). Расхождений нет.

3. **`calculations/aggregation.py`** ожидает у объектов приёма пищи поля
   `date, calories, protein, fat, carbs` (единственное число `protein/fat`,
   и `date` вместо `consumed_at`) через duck-typing (dict или объект с
   атрибутами) — не совпадает буквально с `models.meal.MealEntry`
   (`consumed_at`, `proteins`, `fats`). Модуль не импортирует `models/`
   напрямую, так что технической ошибки импорта не будет, но
   вызывающему коду (workflow) нужно самому маппить поля — что он,
   судя по `normalize_meal()` в `daily_report.py`, уже умеет делать для
   обоих вариантов именования.

## Добавлено 2026-08-25: `GET /meals/summary` — дневная норма и превышение

Новый эндпоинт (не переопределяет ничего из перечисленного выше), добавлен
в рамках задачи «предупреждение о превышении дневной нормы» в живом
продукте (в отличие от `workflows/daily_report.py`, который считает то же
самое офлайн, для отчёта).

```
GET /meals/summary?date=YYYY-MM-DD
GET /meals/summary?date=YYYY-MM-DD&calories=2200&proteins=120&fats=70&carbs=280
```

- `date` (обязателен) — календарный день, тот же смысл, что у `date` в
  `GET /meals?date=...` (интервал `[date 00:00:00, date+1 00:00:00)` по
  `consumed_at`).
- `calories`/`proteins`/`fats`/`carbs` (все опциональны, `>= 0`) —
  переопределяют норму **только для этого запроса**, ничего не
  сохраняется на сервере. Если не переданы — норма берётся из
  `workflows/config.json` (тот же файл, что использует
  `workflows/daily_report.py`) — единый источник истины для значений по
  умолчанию (2000 ккал / 50 Б / 65 Ж / 300 У на 2026-08-25). Файл читается
  как данные (JSON), без импорта пакета `workflows/` — `api/` и
  `workflows/` остаются независимыми зонами. Если файл недоступен —
  используются те же числа как захардкоженный fallback внутри `api/main.py`.

Считает сумму калорий/БЖУ по всем записям за день (напрямую через
`storage.meal_repository.list_meals`, как и `GET /meals?date=...`) и
сравнивает с нормой. Логика статуса: `percent_of_norm = actual / norm * 100`;
`status = "exceeded"`, если `percent_of_norm >= 100`; `"near"`, если
`90 <= percent_of_norm < 100`; иначе `"ok"`. Пороги захардкожены в
`api/main.py` (`NEAR_NORM_THRESHOLD_PERCENT = 90.0`), не настраиваются
через query.

Ответ `200 OK` (`MealsSummaryResponse` из `api/schemas.py`):
```json
{
  "date": "2026-08-25",
  "meals_count": 2,
  "totals": {"calories": 2200.0, "proteins": 40.0, "fats": 70.0, "carbs": 310.0},
  "norms": {"calories": 2000.0, "proteins": 50.0, "fats": 65.0, "carbs": 300.0},
  "diff": {
    "calories": {"actual": 2200.0, "norm": 2000.0, "diff": 200.0, "percent_of_norm": 110.0, "status": "exceeded"},
    "proteins": {"actual": 40.0, "norm": 50.0, "diff": -10.0, "percent_of_norm": 80.0, "status": "ok"},
    "fats": {"actual": 70.0, "norm": 65.0, "diff": 5.0, "percent_of_norm": 107.7, "status": "exceeded"},
    "carbs": {"actual": 310.0, "norm": 300.0, "diff": 10.0, "percent_of_norm": 103.3, "status": "exceeded"}
  }
}
```

Нет записей за день — `200 OK`, `meals_count: 0`, все `totals` нулевые,
`diff[k].status` не может быть `"exceeded"`/`"near"` при нулевом факте
(если норма не переопределена в 0 явно). `422 Unprocessable Entity` —
если `date` не парсится как дата или переопределения нормы отрицательны
(стандартный формат ошибок FastAPI/pydantic, как в остальном API).

Используется фронтендом (`frontend/app.js::apiGetSummary`) для того,
чтобы подсветить итоговую строку таблицы «Приёмы пищи за день» и вывести
текстовые предупреждения вида «Превышена норма по калориям на 200 ккал
(110% от нормы)» — см. `frontend/app.js::renderNormWarnings` и
`.norm-warning`/`.summary-row.exceeded-norm` в `frontend/style.css`.
