"""Column contracts shared by the two teammates — the single source of truth.

If contract/README.md, the Implementation Plan (Section 5) or either spec ever
disagree with this file, this file wins. `python contract/schema.py` regenerates
contract/README.md from the tables below; a test asserts the README is in sync.

Column order in each dict *is* the contract order.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# scored_edges: one row per test-period transaction (edge). NO ground truth here
# (PR-50): labels live in labels_test.parquet.
# --------------------------------------------------------------------------- #
SCORED_EDGES_COLUMNS = {
    "edge_id": ("int64", "arange index assigned by scripts/format_kaggle_files.py (row of formatted_transactions.csv); unique"),
    "tenant_id": ("int64", "= from_bank for now"),
    "from_id": ("int64", "sending account id (loader account_map)"),
    "to_id": ("int64", "receiving account id"),
    "from_bank": ("int64", "bank id of the sending account"),
    "to_bank": ("int64", "bank id of the receiving account"),
    "timestamp": ("int64", "seconds since dataset start, loader basis (= amlworld_*.parquet Timestamp)"),
    "amount_sent": ("float64", "'Amount Sent'"),
    "amount_received": ("float64", "'Amount Received'"),
    "currency_sent": ("int64", "loader integer encoding of 'Sent Currency'"),
    "currency_received": ("int64", "loader integer encoding of 'Received Currency'"),
    "payment_format": ("int64", "loader integer encoding of 'Payment Format'"),
    "score_raw": ("float64", "model pred_prob; NaN when the model produced no score"),
    "score_calibrated": ("float64", "== score_raw until Step 3 adds calibration"),
    "is_seed": ("bool", "predicted_label == 1; False when score_raw is NaN"),
    "model_id": ("string", "e.g. 'gine'"),
    "seed": ("int64", "training seed of the model that produced score_raw"),
}

# --------------------------------------------------------------------------- #
# labels_test: internal only, never handed to the platform.
# --------------------------------------------------------------------------- #
LABELS_COLUMNS = {
    "edge_id": ("int64", "joins 1:1 to scored_edges.edge_id"),
    "true_label": ("int64", "'Is Laundering' from amlworld_test.parquet"),
}

# --------------------------------------------------------------------------- #
# rings: one row per predicted ring.
# --------------------------------------------------------------------------- #
TOPOLOGY_TYPES = ["FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER",
                  "CYCLE", "RANDOM", "BIPARTITE", "STACK"]  # AMLworld pattern names, 8 classes

RINGS_COLUMNS = {
    "ring_id": ("string", "f'{aggregator_id}-{ring_idx}'"),
    "tenant_id": ("int64", "most common from_bank among members"),
    "aggregator_id": ("string", "e.g. 'cc' (connected components)"),
    "members": ("list<int64>", "account ids"),
    "n_members": ("int64", "len(members)"),
    "member_edges": ("list<int64>", "edge_ids with from_id AND to_id in members and timestamp in [start_time, end_time]"),
    "seed_edges": ("list<int64>", "member_edges with is_seed"),
    "expanded_edges": ("list<int64>", "[] until Step 6-8"),
    "n_edges": ("int64", "edges the aggregator used to form the ring"),
    "start_time": ("int64", "min timestamp of member_edges, loader basis"),
    "end_time": ("int64", "max timestamp of the aggregator's ring edges, loader basis"),
    "duration_hours": ("float64", "(end_time - start_time) / 3600"),
    "confidence": ("float64", "aggregator confidence"),
    "max_edge_prob": ("float64", "max score among the aggregator's ring edges"),
    "density": ("float64", "n_edges / (n_members * (n_members - 1))"),
    "conservation_closure": ("float64", "NaN until Step 6-8"),
    "topology_type": ("string", "one of TOPOLOGY_TYPES or 'UNKNOWN'"),
    "topology_probs": ("list<float64>", "8 probabilities in TOPOLOGY_TYPES order; uniform until Step 8"),
    "source_accounts": ("list<int64>", "[] until Step 8"),
    "sink_accounts": ("list<int64>", "[] until Step 8"),
    "mule_accounts": ("list<int64>", "[] until Step 8"),
}

SCORED_EDGES_ORDER = list(SCORED_EDGES_COLUMNS)
LABELS_ORDER = list(LABELS_COLUMNS)
RINGS_ORDER = list(RINGS_COLUMNS)


def pandas_dtypes(spec: dict) -> dict:
    """dtype map usable with DataFrame.astype (list columns are left to pyarrow)."""
    return {c: t for c, (t, _) in spec.items() if not t.startswith("list<")}


# --------------------------------------------------------------------------- #
# inputs we depend on
# --------------------------------------------------------------------------- #
# Exact header of the legacy predictions_with_ids.csv (E6, produced by the deleted score_test_set.py)
PREDICTIONS_WITH_IDS_COLUMNS = [
    "EdgeID", "from_id", "to_id", "Timestamp",
    "true_label", "pred_prob", "predicted_label",
]

# Test-parquet -> contract renames (step 1.2, item 4)
TEST_PARQUET_RENAMES = {
    "EdgeID": "edge_id",
    "Timestamp": "timestamp",
    "Amount Sent": "amount_sent",
    "Amount Received": "amount_received",
    "Sent Currency": "currency_sent",
    "Received Currency": "currency_received",
    "Payment Format": "payment_format",
}

# Exact header of the legacy E7 ring CSVs (models/ring_aggregator.py)
E7_RING_CSV_COLUMNS = [
    "n_members", "n_edges", "confidence", "max_edge_prob", "density",
    "start_time", "end_time", "duration_hours", "ring_idx", "members",
]


# --------------------------------------------------------------------------- #
# README generation
# --------------------------------------------------------------------------- #
def _table(spec: dict) -> str:
    rows = ["| # | column | type | meaning |", "|---|---|---|---|"]
    for i, (c, (t, d)) in enumerate(spec.items(), 1):
        rows.append(f"| {i} | `{c}` | {t} | {d} |")
    return "\n".join(rows)


def render_readme() -> str:
    return f"""# contract/

The hand-off files between the edge-scoring side and the ring side.
**This file is generated from `contract/schema.py`** (`python contract/schema.py`);
edit the schema, not this page. If a spec or the Implementation Plan disagrees with
`schema.py`, `schema.py` wins.

| File | Producer | Columns |
|---|---|---|
| `out/scored_edges_<model>_<seed>.parquet` | `make_scored_edges.py` | `SCORED_EDGES_COLUMNS` |
| `out/labels_{{train,val,test}}.parquet` | `make_labels.py` (internal, never shipped; `labels_test` also written by `make_scored_edges.py`) | `LABELS_COLUMNS` |
| `out/rings_stub_<aggregator>.parquet` | `make_rings_stub.py` | `RINGS_COLUMNS` |

Parquets are git-ignored; the `*.log.json` beside each one (row counts, inputs, git
commit) is committed and is the only thing quoted from these folders.

```bash
python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
python contract/make_rings_stub.py --e7-csv experiments/legacy_E7_test_tuned/rings_gine.csv --scored-edges contract/out/scored_edges_gine_1.parquet --aggregator-id cc
python -m pytest contract/tests -q
```

Status (Step 1): scores are **not yet calibrated** (`score_calibrated == score_raw`,
replaced in Step 3) and rings are the **connected-components baseline** (replaced in
Steps 6-8).

## scored_edges

No ground truth in this file (PR-50).

{_table(SCORED_EDGES_COLUMNS)}

## labels_<split> (internal)

Read by `evaluation/edge_metrics.py`; never joined into a shipped file.

{_table(LABELS_COLUMNS)}

## rings

`topology_probs` order: {', '.join(TOPOLOGY_TYPES)}.

{_table(RINGS_COLUMNS)}

## Time basis

`timestamp`, `start_time`, `end_time` are in the **loader basis** (seconds since the
first day 00:00 minus 10 s, as in `data/processed/amlworld_*.parquet`). The legacy
model scripts re-based time to their own minimum, so `predictions_with_ids.csv` and the
E7 ring CSVs are `legacy_csv_time_offset_s` (10 s, `configs/paths.yaml`) lower; the
contract scripts assert and add that offset. `models/score.py` (Step 3.3) writes
loader-basis timestamps directly.

## Account -> bank map

`from_bank` / `to_bank` come from `data/processed/account_bank.parquet`
(`account_id, bank_code, account_number`; built by `preprocessing/account_bank.py` from
`HI-Small_Trans.csv` with the loader's key rule, `str(bank) + str(account)`, ids in
first-appearance order, and validated 100% against `HI-Small_accounts.csv`).
"""


def write_readme(path: Path = REPO_ROOT / "contract" / "README.md") -> Path:
    path.write_text(render_readme(), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    print(f"wrote {write_readme()}")
