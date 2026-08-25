# Зависимости workflow «дневной отчёт» от других модулей

Этот файл фиксирует, что `workflows/daily_report.py` ожидает от `storage/`,
`api/` и `calculations/`. Часть пунктов на момент написания уже
подтверждена реальным кодом (прочитано, не редактировалось), часть —
всё ещё предположение с чёткой точкой подмены в скрипте.

Дата фиксации: 2026-08-24. Если контракты изменятся после этой даты —
перечитать соответствующие файлы и поправить адаптеры в
`daily_report.py` (маркеры `ADAPTER SWAP POINT` в коде).

## 1. Источник данных о приёмах пищи за день

Приоритет источников в `get_meals_for_date()` (`--source auto`, можно
принудительно задать `--source storage|api|mock`):

### 1a. `storage/` — ПОДТВЕРЖДЕНО, используется как основной источник

На момент работы над workflow в `storage/` уже существует реальный код:

- `storage/db.py`: `init_db()` (безопасно вызывать повторно, создаёт
  таблицу `meal_entries`, если её нет), `transaction()`, SQLite-файл
  `storage/calorie_tracker.db` (путь переопределяется через переменную
  окружения `CALORIE_TRACKER_DB`).
- `storage/meal_repository.py`: `list_meals(start: datetime | None, end:
  datetime | None) -> list[MealEntry]` — фильтр по `consumed_at` в
  полуоткрытом интервале `[start, end)`.
- `models/meal.py`: `MealEntry` с полями `product_name, weight_grams,
  consumed_at (datetime), calories, proteins, fats, carbs, id,
  created_at, updated_at` и методом `to_dict()`.

Workflow вызывает `storage.db.init_db()` (идемпотентно) и
`storage.meal_repository.list_meals(start=<полночь даты>,
end=<полночь следующего дня>)`, затем `MealEntry.to_dict()` на каждой
записи. Это прямое чтение из storage, без HTTP — обосновано тем, что
API ещё не поднимается как сервис (см. ниже), а storage уже даёт готовую
функцию выборки по диапазону дат.

Если сигнатура `list_meals`/`MealEntry` изменится — поправить
`_load_from_storage()` в `daily_report.py`.

### 1b. `api/` — ПОДТВЕРЖДЕНО и живьём протестировано

`api/` изначально (в начале работы над этим workflow) был пуст, затем
в процессе работы появились `api/schemas.py`, `api/main.py` (FastAPI-
приложение) и `api/API_CONTRACT.md` (авторитетный, "как реализовано"
контракт). Реальный контракт:

`GET {API_BASE_URL}/meals?date=YYYY-MM-DD` -> JSON-массив объектов с
полями `id, product_name, weight_grams, consumed_at, calories, proteins,
fats, carbs, created_at, updated_at` — то есть 1:1 совпадает с
`models.meal.MealEntry` (множественное число `proteins/fats`), НЕ с
черновиком `frontend/API_CONTRACT_ASSUMED.md` (там `protein/fat`
единственное число, `product`/`weight_g`/`date` — этот черновик сам
`api/API_CONTRACT.md` называет устаревшим и требующим адаптации со
стороны фронтенда).

`_load_from_api()` уже был реализован через `normalize_meal()`, которая
понимает оба варианта именования полей (`proteins`/`protein`,
`fats`/`fat`, `product_name`/`product`, `weight_grams`/`weight_g`) — то
есть код не пришлось переписывать под реальный контракт, только
проверить.

Проверено вживую: поднят `uvicorn api.main:app` на `127.0.0.1:8123`,
через него создано 2 тестовые записи (`POST /meals`), затем
`daily_report.py --source api --api-base-url http://127.0.0.1:8123`
корректно получил и агрегировал их (2 приёма пищи, сумма калорий/БЖУ
совпала с ручным расчётом), повторный запуск дал `status: unchanged`.
После проверки тестовые записи удалены через `DELETE /meals/{id}`, чтобы
не оставлять мусор в общей БД для других агентов/тестов.

### 1c. Локальный mock/fixture — запасной вариант

Если ни storage, ни API недоступны (например, скрипт запускают в
окружении без модулей проекта, или БД пуста/отсутствует и это ошибка
импорта, а не просто «на сегодня записей нет»), используется
`workflows/fixtures/sample_meals.json` — список тестовых записей в
формате, приближённом к черновику фронтенда (`product, weight_g, date,
calories, protein, fat, carbs`), тоже проходит через `normalize_meal()`.
Это чисто для локальной проверки повторяемости workflow и явно
логируется как `source: "mock"` в итоговой сводке — сводка с
`source: "mock"` не следует путать с реальными данными.

Как переключить принудительно: `python daily_report.py --source mock`
или `--source storage` / `--source api --api-base-url http://localhost:8000`.

## 2. Агрегация БЖУ/калорий — `calculations/`

ПОДТВЕРЖДЕНО (появилось в процессе работы, контракт отличается от
первоначального предположения — код в `daily_report.py` уже подстроен):

```python
from calculations import aggregate_day
aggregate_day(meals: Iterable[Any], target_date: date|datetime|str) -> DayAggregate
# DayAggregate(date, total=Nutrition(calories, protein, fat, carbs), meal_count)
```

Важные особенности реального контракта (`calculations/aggregation.py`,
`calculations/portion.py`):
- Принимает `target_date` вторым аргументом и сам фильтрует переданные
  `meals` по дате (`meal["date"] == target_date`).
- У каждого элемента `meals` читаются поля `date, calories, protein,
  fat, carbs` — **protein/fat в единственном числе**, в отличие от
  `models.meal.MealEntry` / `storage`, где поля называются
  `proteins/fats` (множественное число). Это несостыковка между
  агентами calculations/ и models/storage, а не опечатка в этом
  workflow — учтена явно.
- Возвращает dataclass `DayAggregate`, не dict; калории округлены до
  целого, БЖУ — до 0.1 г (округление на стороне calculations/).

`daily_report.aggregate_day(meals, target_date)` строит для вызова
`calculations.aggregate_day` отдельный список dict с полями
`date/calories/protein/fat/carbs`, смэппленными из внутреннего
нормализованного формата (`consumed_at/calories/proteins/fats/carbs`),
не трогая сам `normalize_meal()`, которым пользуется остальной код.
Если импорт/вызов `calculations.aggregate_day` бросает исключение (модуль
удалили, контракт снова поменялся и т.п.) — используется локальный
fallback `_aggregate_day_local()` (простое суммирование). Обе ветки
логируются в поле `meta.aggregation_source` итоговой сводки
(`"calculations"` или `"local_fallback"`).

`calculations/` не редактировалась и не будет — только чтение при
попытке импорта. Если контракт снова изменится — поправить маппинг
внутри `aggregate_day()` в `daily_report.py`.

## Побочный артефакт от живого теста API

При проверке HTTP-адаптера (см. п.1b) вызов `storage.db.init_db()`
(происходит на старте FastAPI-приложения) создал файл
`storage/calorie_tracker.db` — это ожидаемое штатное поведение самого
`storage/db.py` ("создаётся автоматически при первом использовании"), не
результат редактирования кода в `storage/`. Тестовые записи из него
удалены через `DELETE /meals/{id}` до завершения работы, так что таблица
`meal_entries` в этом файле пустая. Файл оставлен как есть (попытка
удалить его была заблокирована защитой инструментов, т.к. `storage/` —
не моя зона); координатор/владелец `storage/` может удалить его или
добавить `*.db` в `.gitignore` по своему усмотрению — на работу
`daily_report.py` его наличие/отсутствие не влияет (`init_db()`
идемпотентен).

## 3. Норма БЖУ/калорий по умолчанию

Не зависит от других модулей — задаётся в самом workflow
(`DEFAULT_NORMS` в `daily_report.py`), ориентир — референсные значения
для рациона 2000 ккал (стандартная маркировка nutrition facts):
калории 2000, белки 50 г, жиры 65 г, углеводы 300 г. Настраивается через
CLI (`--calories/--proteins/--fats/--carbs`) и/или JSON-конфиг
(`--config path/to/config.json`, см. `workflows/config.json` как пример).
