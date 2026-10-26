"""Display labels for integer codes emitted by AMLworld preprocessing."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# The committed maps (contract/make_code_maps.py); data/processed/ holds them only after preprocessing.
CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contract"


@lru_cache(maxsize=4)
def _reverse_map(path_value: str) -> dict[int, str]:
    path = Path(path_value)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"label map must contain a JSON object: {path}")
    raw = raw.get("name_to_code", raw)      # the contract files nest the map beside their provenance
    return {int(code): str(label) for label, code in raw.items()}


def _map_path(variable: str, name: str) -> str:
    if os.environ.get(variable):
        return os.environ[variable]
    processed = Path("data/processed") / name
    return str(processed if processed.is_file() else CONTRACT_DIR / name)


def currency_label(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.isdigit():
        return value
    path = _map_path("RINGSHIELD_CURRENCY_MAP", "currency_map.json")
    code = int(value)
    return _reverse_map(path).get(code, f"Currency {code}")


def payment_format_label(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.isdigit():
        return value
    path = _map_path("RINGSHIELD_PAYMENT_FORMAT_MAP", "payment_format_map.json")
    code = int(value)
    return _reverse_map(path).get(code, f"Format {code}")
