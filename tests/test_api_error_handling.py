"""Regression test for the NaN/Infinity 500-crash found by the independent
"breaker" pass (sessions/session-2.md, finding #1).

Root cause: Pydantic correctly rejects a NaN/Infinity request value, but the
rejected value itself is echoed back in the 422 error body via
``RequestValidationError.errors()``. Starlette's default ``JSONResponse``
calls ``json.dumps(..., allow_nan=False)``, which raises instead of emitting
a literal NaN/inf - turning an ordinary validation error into an unhandled
500.

No HTTP client (httpx) is used here, matching the project's existing
convention (see tests/test_product_catalog.py) of testing pure functions
directly rather than adding an HTTP-client dependency just for tests.
"""

import json
import math

from api.main import _sanitize_for_json


def test_sanitizes_nan_and_infinity_in_nested_structures():
    errors = [
        {
            "type": "greater_than_equal",
            "loc": ("body", "calories"),
            "msg": "Input should be greater than or equal to 0",
            "input": float("nan"),
            "ctx": {"ge": 0.0},
        },
        {
            "type": "less_than_equal",
            "loc": ("body", "weight_grams"),
            "msg": "Input should be less than or equal to 100000",
            "input": float("inf"),
            "ctx": {"le": 100000.0, "extra": [1.0, float("-inf"), {"nested": float("nan")}]},
        },
    ]

    sanitized = _sanitize_for_json(errors)

    # The whole point of the fix: this must not raise ValueError anymore.
    json.dumps(sanitized, allow_nan=False)

    assert sanitized[0]["input"] == "nan"
    assert sanitized[1]["input"] == "inf"
    assert sanitized[1]["ctx"]["extra"][1] == "-inf"
    assert sanitized[1]["ctx"]["extra"][2]["nested"] == "nan"


def test_leaves_finite_values_and_other_types_unchanged():
    payload = {
        "type": "greater_than",
        "loc": ["body", "weight_grams"],
        "msg": "Input should be greater than 0",
        "input": 0.0,
        "ctx": {"gt": 0.0},
        "count": 3,
        "name": "Куриная грудка",
        "ok": True,
        "nothing": None,
    }

    sanitized = _sanitize_for_json(payload)

    assert sanitized == payload
    # Sanity check: math.isfinite must be what gates the replacement, not
    # `value != value`-style NaN tricks that could misfire on other types.
    assert math.isfinite(sanitized["input"])
