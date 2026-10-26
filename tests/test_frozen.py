"""The headline numbers frozen for the 2026-10-30 review (results/FROZEN.json) must not change.

Each entry names its source file and where in it the number sits; the test re-reads every source and
fails on any difference, and on any source that is missing or no longer holds exactly one match.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN = REPO_ROOT / "results" / "FROZEN.json"


def _number(text: str):
    try:
        value = float(text)
    except ValueError:
        return text
    return int(value) if value.is_integer() and "." not in text and "e" not in text.lower() else value


def extract(source: dict):
    path = REPO_ROOT / source["path"]
    if source["kind"] == "json":
        value = json.loads(path.read_text(encoding="utf-8"))
        for key in source["key"]:
            value = value[key]
        return value
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle)
                if all(row[column] == wanted for column, wanted in source["where"].items())]
    assert len(rows) == 1, f"{source['path']} {source['where']}: {len(rows)} matching rows"
    return _number(rows[0][source["column"]])


def _entries():
    return json.loads(FROZEN.read_text(encoding="utf-8"))["numbers"]


def test_frozen_ids_are_unique():
    ids = [entry["id"] for entry in _entries()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entry", _entries(), ids=lambda entry: entry["id"])
def test_frozen_number_unchanged(entry):
    got = extract(entry["source"])
    frozen = entry["value"]
    if isinstance(frozen, float):
        assert isinstance(got, (int, float)) and math.isclose(got, frozen, rel_tol=0, abs_tol=1e-12), \
            f"{entry['id']}: {entry['source']['path']} now gives {got!r}, frozen {frozen!r}"
    else:
        assert got == frozen, f"{entry['id']}: {entry['source']['path']} now gives {got!r}, frozen {frozen!r}"
