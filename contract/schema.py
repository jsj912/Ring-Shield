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
    "score_calibrated": ("float64", "isotonic calibration fit on the val split (models/calibrate.py, Step 3c); == score_raw for files written before calibration"),
    "is_seed": ("bool", "seed-fraction rule (configs/threshold_rule.yaml): score_raw > quantile(1 - k*/100) within the split, strict; Step 1 files used predicted_label == 1. False when score_raw is NaN"),
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

# Contract schema version of the rings table. v1 = Step 8 (the first full rings contract);
# v2 = Step 14, which ADDS the currency-aware fields below without changing any v1 field's meaning.
# Written into the parquet key-value metadata by ringshield.rings.write_rings_parquet so a reader
# can tell the two apart without inspecting the column list.
RINGS_SCHEMA_VERSION = 2

RINGS_COLUMNS = {
    "ring_id": ("string", "f'{aggregator}-{model_id}-{seed}-{idx}' (Step 5 CLI rule, e.g. 'cc-gine_causal-1-0'; the Step 1 stub used f'{aggregator_id}-{ring_idx}')"),
    "tenant_id": ("int64", "sender bank (from_bank) of the ring's earliest seed edge, ties -> smallest edge_id (Step 5 rule; the Step 1 stub used the most common bank among members). The platform derives the full set of banks with a member itself"),
    "aggregator_id": ("string", "e.g. 'cc' (connected components)"),
    "members": ("list<int64>", "account ids"),
    "n_members": ("int64", "len(members)"),
    "member_edges": ("list<int64>", "edge_ids with from_id AND to_id in members and timestamp in [start_time, end_time]"),
    "seed_edges": ("list<int64>", "member_edges with is_seed"),
    "expanded_edges": ("list<int64>", "member_edges the expansion policy added around the seeds (Step 6); [] for the cc aggregator"),
    "expanded_edge_probs": ("list<float64>", "the expansion policy's probability for each edge of expanded_edges, same order and length (Step 8); [] when nothing was expanded. The XAI layer needs it because an expanded edge's own detector score is low by definition"),
    "n_edges": ("int64", "edges the aggregator used to form the ring"),
    "start_time": ("int64", "min timestamp of member_edges, loader basis"),
    "end_time": ("int64", "max timestamp of the aggregator's ring edges, loader basis"),
    "duration_hours": ("float64", "(end_time - start_time) / 3600"),
    "confidence": ("float64", "mean score_calibrated over seed_edges x conservation_closure (Step 8 definition). When conservation_closure is NaN (no source or no sink) the closure factor is dropped and confidence is the mean alone; the run log counts those rings (n_rings_closure_nan)"),
    "max_edge_prob": ("float64", "max score among the aggregator's ring edges"),
    "density": ("float64", "n_edges / (n_members * (n_members - 1))"),
    "conservation_closure": ("float64", "1 - |sum of inflow at the ring's sinks - sum of outflow at its sources| / max(those two sums), clipped to [0, 1], over the ring's seed + expanded edges with amounts deduplicated on (from_id, to_id, timestamp, amount_received). NaN when the ring has no source or no sink (roles per configs/roles.yaml)"),
    "topology_type": ("string", "one of TOPOLOGY_TYPES or 'UNKNOWN'"),
    "topology_probs": ("list<float64>", "8 probabilities in TOPOLOGY_TYPES order, summing to 1 (Step 8 typing head; uniform with topology_type 'UNKNOWN' when no head is attached)"),
    "source_accounts": ("list<int64>", "members whose role is 'source' (configs/roles.yaml: no inflow, or inflow / outflow < tau_role 0.25, over the ring's deduplicated flows)"),
    "sink_accounts": ("list<int64>", "members whose role is 'sink' (no outflow, or outflow / inflow < tau_role)"),
    "mule_accounts": ("list<int64>", "members whose role is 'mule' (both flows, closure >= 1 - tau_role, passed on within 72 h) or 'holder' (same but held longer); ringshield.roles.account_roles returns the two separately"),

    # ---- schema v2 (Step 14, currency correction) ---------------------------------------------
    # AMLworld amounts carry a currency code and 55.2 % of test rings span more than one currency;
    # 51.9 % of the ring-accounts a closure is computed on have DISJOINT in/out currency sets, so a
    # raw cross-currency ratio is arithmetic on mismatched units. The v1 fields keep their raw-sum
    # definition so existing artefacts and downstream consumers are unchanged; these carry the
    # currency-partitioned values beside them. See docs/PITFALLS.md and docs/MIGRATION.md.
    "conservation_closure_ccy": ("float64", "ring-level closure computed per currency and summed over currencies "
                                 "that appear on BOTH sides of an account; NaN when no currency does, which is "
                                 "~52 % of ring-accounts. `conservation_closure` (v1) remains the RAW "
                                 "cross-currency ratio and is what `confidence` uses"),
    "n_accounts_ccy_undefined": ("int64", "ring accounts whose inflow and outflow currency sets are disjoint, so "
                                 "no per-currency closure exists for them; the denominator behind "
                                 "conservation_closure_ccy"),
    "source_accounts_ccy": ("list<int64>", "source accounts under currency-partitioned flows (opt-in roles); the "
                            "v1 `source_accounts` stays raw-sum"),
    "sink_accounts_ccy": ("list<int64>", "sink accounts under currency-partitioned flows"),
    "mule_accounts_ccy": ("list<int64>", "mule accounts under currency-partitioned flows"),
    "undetermined_accounts_ccy": ("list<int64>", "accounts whose role CANNOT be decided from "
                                  "same-currency evidence: their inflow and outflow currencies do not "
                                  "overlap, or the overlap carries too little flow to judge. Not "
                                  "'peripheral' -- whether they are mules depends on the exchange rate. "
                                  "Render explicitly; never collapse into another role"),
    "n_roles_changed_ccy": ("int64", "accounts whose role differs between the raw and the "
                            "currency-aware assignment; the size of the disagreement, visible without "
                            "recomputing either"),
    "n_currencies": ("int64", "distinct currency codes on the ring's member edges (1 = the raw and "
                     "currency-partitioned definitions coincide)"),}

SCORED_EDGES_ORDER = list(SCORED_EDGES_COLUMNS)
LABELS_ORDER = list(LABELS_COLUMNS)
RINGS_ORDER = list(RINGS_COLUMNS)


def pandas_dtypes(spec: dict) -> dict:
    """dtype map usable with DataFrame.astype (list columns are left to pyarrow)."""
    return {c: t for c, (t, _) in spec.items() if not t.startswith("list<")}


# The only float columns the contract permits to be NaN; both column docs say when and why.
# Every other float field has a real value in every shipped ring, so a NaN default there would
# hand a consumer a missing number dressed as a measured one.
RINGS_NAN_OK = ("conservation_closure", "conservation_closure_ccy")


def ring_record(**overrides) -> dict:
    """One rings-contract row as a dict: every column of RINGS_COLUMNS present, correctly typed.

    Defaults are the empty-but-valid values, not placeholders:

        int64            0            counts and ids
        float64          0.0          except RINGS_NAN_OK, which default to NaN
        string           ""           except topology_type, which is "UNKNOWN"
        list<int64>      []           members, member_edges, the role arrays, ...
        list<float64>    []           except topology_probs, which is uniform over TOPOLOGY_TYPES
                                      so that a bare record is already a valid distribution

    Why this exists: the type of a rings column cannot be recovered from an absent value. Building
    a frame as `pd.DataFrame(rows, columns=RINGS_ORDER)` with rows that omit a column gives that
    column all-NaN float64, which passes a column-NAME check and fails a type check -- and the
    failure surfaces as the wrong diagnosis. Every producer of a rings row should start here, so a
    future schema version reaches them all at once.

    An override key that is not a contract column is refused, because a silently ignored typo is
    how a column ends up at its default in a shipped file.
    """
    unknown = sorted(k for k in overrides if k not in RINGS_COLUMNS)
    if unknown:
        raise KeyError(f"not rings-contract columns: {unknown}; "
                       f"did you mean one of {sorted(RINGS_COLUMNS)}?")
    rec: dict = {}
    for col, (typ, _) in RINGS_COLUMNS.items():
        if typ == "int64":
            rec[col] = 0
        elif typ == "float64":
            rec[col] = float("nan") if col in RINGS_NAN_OK else 0.0
        elif typ == "string":
            rec[col] = "UNKNOWN" if col == "topology_type" else ""
        elif typ == "bool":
            rec[col] = False
        elif typ == "list<int64>":
            rec[col] = []
        elif typ == "list<float64>":
            rec[col] = ([1.0 / len(TOPOLOGY_TYPES)] * len(TOPOLOGY_TYPES)
                        if col == "topology_probs" else [])
        else:                                     # pragma: no cover - a new contract type
            raise AssertionError(f"ring_record: no default for contract type {typ!r} ({col})")
    rec.update(overrides)
    return rec


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
| `out/rings_stub_<aggregator>.parquet` | `python -m ringshield run` (Step 3c+; `make_rings_stub.py` for the Step 1 file) | `RINGS_COLUMNS` |

Parquets are git-ignored; the `*.log.json` beside each one (row counts, inputs, git
commit) is committed and is the only thing quoted from these folders.

```bash
python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
python contract/make_rings_stub.py --e7-csv experiments/legacy_E7_test_tuned/rings_gine.csv --scored-edges contract/out/scored_edges_gine_1.parquet --aggregator-id cc
python -m pytest contract/tests -q
```

Status (Step 3c / 5): `scored_edges_gine_causal_1.parquet` carries isotonic-calibrated
scores and `is_seed` from the seed-fraction rule; `rings_stub_cc.parquet` is the
connected-components baseline built from it by `python -m ringshield run` (replaced in
Steps 6-8). The Step 1 files (`scored_edges_gine_1.parquet`, `rings_stub_cc_step1_legacy.parquet`)
are kept for the Step 1 checks only.

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
