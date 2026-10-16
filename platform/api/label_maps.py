"""Display labels for integer codes emitted by AMLworld preprocessing."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def _reverse_map(path_value: str) -> dict[int, str]:
    path = Path(path_value)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"label map must contain a JSON object: {path}")
    return {int(code): str(label) for label, code in raw.items()}


def currency_label(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.isdigit():
        return value
    path = os.environ.get("RINGSHIELD_CURRENCY_MAP", "data/processed/currency_map.json")
    code = int(value)
    return _reverse_map(path).get(code, f"Currency {code}")


def payment_format_label(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.isdigit():
        return value
    path = os.environ.get("RINGSHIELD_PAYMENT_FORMAT_MAP", "data/processed/payment_format_map.json")
    code = int(value)
    return _reverse_map(path).get(code, f"Format {code}")
