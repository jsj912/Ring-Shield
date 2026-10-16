"""Write a deterministic, synthetic two-tenant contract fixture for API smoke tests.

The fixture contains no ground-truth labels or account numbers. It exercises shared
cross-bank ring edges, one-sided tenant visibility, and edges invisible to both tenants.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402

BANKS = {"tenant_a": 210, "tenant_b": 220, "other_a": 230, "other_b": 240}
ACCOUNT_BANK = {
    101: BANKS["tenant_a"],
    102: BANKS["tenant_a"],
    201: BANKS["tenant_b"],
    202: BANKS["tenant_b"],
    301: BANKS["other_a"],
    401: BANKS["other_b"],
}


def _edge(edge_id: int, from_id: int, to_id: int, timestamp: int,
          amount: float, *, is_seed: bool = False) -> dict:
    from_bank, to_bank = ACCOUNT_BANK[from_id], ACCOUNT_BANK[to_id]
    return {
        "edge_id": edge_id,
        "tenant_id": from_bank,
        "from_id": from_id,
        "to_id": to_id,
        "from_bank": from_bank,
        "to_bank": to_bank,
        "timestamp": timestamp,
        "amount_sent": amount,
        "amount_received": amount * 0.99,
        "currency_sent": 1,
        "currency_received": 1,
        "payment_format": 2,
        "score_raw": 0.97 if is_seed else 0.42,
        "score_calibrated": 0.95 if is_seed else 0.40,
        "is_seed": is_seed,
        "model_id": "demo-model",
        "seed": 7,
    }


def _ring(tenant_id: int) -> dict:
    return {
        "ring_id": "demo-cycle",
        "tenant_id": tenant_id,
        "aggregator_id": "demo",
        "members": [101, 201, 102, 202],
        "n_members": 4,
        "member_edges": [1, 2, 3, 4],
        "seed_edges": [1],
        "expanded_edges": [2, 3, 4],
        "expanded_edge_probs": [0.61, 0.59, 0.63],
        "n_edges": 4,
        "start_time": 100,
        "end_time": 130,
        "duration_hours": 30 / 3600,
        "confidence": 0.91,
        "max_edge_prob": 0.97,
        "density": 4 / (4 * 3),
        "conservation_closure": 0.88,
        "topology_type": "GATHER-SCATTER",
        "topology_probs": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "source_accounts": [101],
        "sink_accounts": [102],
        "mule_accounts": [201, 202],
    }


def build_fixture(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    edges = [
        _edge(1, 101, 201, 100, 100.0, is_seed=True),
        _edge(2, 101, 202, 110, 99.0),
        _edge(3, 201, 102, 120, 98.0),
        _edge(4, 202, 102, 130, 101.0),
        _edge(5, 201, 301, 140, 25.0),  # visible only to tenant 220
        _edge(6, 301, 401, 150, 15.0),  # visible to neither loaded tenant
    ]
    rings = [_ring(BANKS["tenant_a"]), _ring(BANKS["tenant_b"])]
    if any(list(row) != SCORED_EDGES_ORDER for row in edges):
        raise ValueError("synthetic scored-edge fixture is out of contract column order")
    if any(list(row) != RINGS_ORDER for row in rings):
        raise ValueError("synthetic ring fixture is out of contract column order")

    account_map_path = output_dir / "account_bank.csv"
    with account_map_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["account_id", "bank_code"], lineterminator="\n")
        writer.writeheader()
        writer.writerows({"account_id": account_id, "bank_code": bank}
                         for account_id, bank in sorted(ACCOUNT_BANK.items()))

    scored_edges_path = output_dir / "scored_edges.parquet"
    rings_path = output_dir / "rings.parquet"
    pq.write_table(pa.Table.from_pylist(edges), scored_edges_path,
                   compression="zstd", use_dictionary=False, write_statistics=False)
    pq.write_table(pa.Table.from_pylist(rings), rings_path,
                   compression="zstd", use_dictionary=False, write_statistics=False)

    manifest = {
        "fixture_version": 1,
        "synthetic": True,
        "ground_truth_included": False,
        "account_numbers_included": False,
        "loaded_tenants": [BANKS["tenant_a"], BANKS["tenant_b"]],
        "expected_visible_edge_ids": {
            str(BANKS["tenant_a"]): [1, 2, 3, 4],
            str(BANKS["tenant_b"]): [1, 2, 3, 4, 5],
        },
        "expected_ring_ids": {
            str(BANKS["tenant_a"]): ["demo-cycle"],
            str(BANKS["tenant_b"]): ["demo-cycle"],
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "account_map": account_map_path,
        "scored_edges": scored_edges_path,
        "rings": rings_path,
        "manifest": manifest_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "platform_demo")
    args = parser.parse_args(argv)
    try:
        paths = build_fixture(args.output_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({name: str(path) for name, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
