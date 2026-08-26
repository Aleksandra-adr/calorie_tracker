# API-контракт

Базовый URL: `http://localhost:8000`

## POST /meals
Тело: `{"product": str, "weight_g": float>0, "date": "YYYY-MM-DD", "calories": float>=0, "protein": float>=0, "fat": float>=0, "carbs": float>=0}`
Ответ 201: то же + `"id": int`. Ошибка 422 при нарушении ограничений.

## GET /meals?date=YYYY-MM-DD
## GET /meals?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
Ответ 200: список `MealOut` (пустой список, если ничего нет). 400, если указаны и `date`, и диапазон одновременно.

## GET /meals/{id}
200 `MealOut` или 404.

## PUT /meals/{id}
Тело как в POST. 200 `MealOut` или 404.

## DELETE /meals/{id}
204 или 404.

## GET /health
`{"status": "ok"}`
