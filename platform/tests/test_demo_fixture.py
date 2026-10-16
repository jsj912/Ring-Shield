from __future__ import annotations

import csv
import json
from pathlib import Path
import sys

import pyarrow.parquet as pq

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.make_demo_fixture import build_fixture  # noqa: E402
from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402


def test_demo_fixture_is_deterministic_and_exercises_visibility(tmp_path):
    first = build_fixture(tmp_path / "first")
    second = build_fixture(tmp_path / "second")

    edges = pq.read_table(first["scored_edges"]).to_pylist()
    rings = pq.read_table(first["rings"]).to_pylist()
    edges_again = pq.read_table(second["scored_edges"]).to_pylist()
    rings_again = pq.read_table(second["rings"]).to_pylist()
    manifest = json.loads(first["manifest"].read_text(encoding="utf-8"))
    with first["account_map"].open(encoding="utf-8", newline="") as handle:
        account_columns = next(csv.reader(handle))

    assert list(edges[0]) == SCORED_EDGES_ORDER
    assert list(rings[0]) == RINGS_ORDER
    assert edges == edges_again
    assert rings == rings_again
    assert account_columns == ["account_id", "bank_code"]
    assert "account_number" not in account_columns
    assert "true_label" not in edges[0]
    assert manifest["ground_truth_included"] is False
    assert manifest["account_numbers_included"] is False

    for bank_code, expected_ids in manifest["expected_visible_edge_ids"].items():
        visible = {
            row["edge_id"] for row in edges
            if row["from_bank"] == int(bank_code) or row["to_bank"] == int(bank_code)
        }
        assert sorted(visible) == expected_ids
    assert {row["tenant_id"] for row in rings} == {210, 220}
