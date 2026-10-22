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
    "currency_sent": ("int64", "loader integer encoding of 'Sent Currency'; decode with contract/currency_map.json"),
    "currency_received": ("int64", "loader integer encoding of 'Received Currency'; decode with contract/currency_map.json"),
    "payment_format": ("int64", "loader integer encoding of 'Payment Format'; decode with contract/payment_format_map.json"),
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
    "member_edges": ("list<int64>", "edge_ids with from_id AND to_id in members and timestamp in "
                     "[start_time, end_time]. This is EVERY edge among the member accounts in the "
                     "ring's span, not only the ones the aggregator used -- including self-loop "
                     "currency conversions, which are 38.7 % of predicted member edges and are "
                     "NEVER laundering in AMLworld (0 of 72,170). Filter them out of evidence and "
                     "flow shares: see 'What member_edges contains' below"),
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
    # AMLworld amounts carry a currency code and 55.2 % of test rings span more than one currency,
    # so a raw cross-currency ratio compares mismatched units. The v1 fields keep their raw-sum
    # definition so existing artefacts and downstream consumers are unchanged; these carry the
    # currency-partitioned values beside them.
    #
    # CORRECTED 2026-10-14. Two statements that stood here were false, both found by the XAI
    # teammate's measurement:
    #   * "no single edge is cross-currency" -- 13,627 test edges (1.58 %) have
    #     currency_sent != currency_received, with a real amount on each side;
    #   * "51.9 % of the ring-accounts a closure is computed on have disjoint in/out currency sets"
    #     -- not reproducible. The figures are 521 of 881 two-sided ring-accounts (59.1 %), or 521
    #     of 4,280 ring-accounts (12.2 %), identical under both flow bookings.
    # The `partitioned` mode these columns hold is therefore SUPERSEDED by
    # `account_roles(..., currency="converted")`, which converts with the generator's own fixed
    # rates (contract/fx_rates.json) and leaves only 3 of 4,280 accounts undetermined, against
    # 571 here. These columns are kept as published; nothing is regenerated.
    # See docs/PITFALLS.md entries 3b and 3c, docs/FX_RATES.md and docs/MIGRATION.md.
    "conservation_closure_ccy": ("float64", "ring-level closure computed per currency and summed over currencies "
                                 "that appear on BOTH sides of an account; NaN when no currency does -- 521 of "
                                 "881 two-sided ring-accounts (59.1 %), or 12.2 % of all 4,280. SUPERSEDED by "
                                 "account_roles(currency='converted'), which converts with the generator's "
                                 "own fixed rates instead of withholding; kept as published. "
                                 "`conservation_closure` (v1) remains the RAW cross-currency ratio and is "
                                 "what `confidence` uses"),
    "n_accounts_ccy_undefined": ("int64", "ring accounts whose inflow and outflow currency sets are disjoint, so "
                                 "no per-currency closure exists for them; the denominator behind "
                                 "conservation_closure_ccy"),
    "source_accounts_ccy": ("list<int64>", "source accounts under currency-partitioned flows (opt-in roles); the "
                            "v1 `source_accounts` stays raw-sum"),
    "sink_accounts_ccy": ("list<int64>", "sink accounts under currency-partitioned flows"),
    "mule_accounts_ccy": ("list<int64>", "mule accounts under currency-partitioned flows"),
    "undetermined_accounts_ccy": ("list<int64>", "accounts whose role could not be decided from "
                                  "same-currency evidence: their inflow and outflow currencies do not "
                                  "overlap, or the overlap carries too little flow to judge. Not "
                                  "'peripheral'. SUPERSEDED 2026-10-14: the exchange rates ARE recoverable "
                                  "(contract/fx_rates.json), and under currency='converted' 568 of these "
                                  "571 accounts resolve -- 86 % of them to mule. Kept as published; prefer "
                                  "the converted roles. Render any remaining undetermined explicitly"),
    "n_roles_changed_ccy": ("int64", "accounts whose role differs between the raw and the "
                            "currency-aware assignment; the size of the disagreement, visible without "
                            "recomputing either"),
    "n_currencies": ("int64", "distinct currency codes on the ring's member edges (1 = the raw and "
                     "currency-partitioned definitions coincide)"),}

# The eight columns schema v2 added, named once so the v1 view below is derived and cannot drift.
RINGS_COLUMNS_V2_ADDED = (
    "conservation_closure_ccy", "n_accounts_ccy_undefined", "source_accounts_ccy",
    "sink_accounts_ccy", "mule_accounts_ccy", "undetermined_accounts_ccy",
    "n_roles_changed_ccy", "n_currencies",
)

# The rings contract as it stood at schema v1, for reading or validating a file written before the
# v2 bump -- `contract/out/v1/*.parquet`, and any artefact a consumer kept. A reader should branch
# on `ringshield.rings.rings_schema_version(path)` and pick the matching spec rather than sniff the
# column list.
RINGS_COLUMNS_V1 = {c: v for c, v in RINGS_COLUMNS.items() if c not in RINGS_COLUMNS_V2_ADDED}
assert len(RINGS_COLUMNS_V1) == len(RINGS_COLUMNS) - 8 == 22, (
    f"RINGS_COLUMNS_V1 should hold 22 columns, got {len(RINGS_COLUMNS_V1)}")
RINGS_ORDER_V1 = list(RINGS_COLUMNS_V1)

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

## What `member_edges` contains

`member_edges` is **every** edge with both endpoints among `members` and a timestamp inside
[`start_time`, `end_time`]. It is a superset of what the aggregator used: `seed_edges` and
`expanded_edges` are the edges the pipeline acted on, and `member_edges` additionally sweeps in
whatever else those accounts did in that window.

**The largest single category of that extra traffic is currency conversion.** AMLworld records an
exchange as a **self-loop**: one account, `from_id == to_id`, with
`Sent Currency != Received Currency` and a real amount on each side. Measured over the five shipped
`full` seeds:

| edge set | edges | cross-currency |
|---|---:|---:|
| `member_edges` | 7,520 | **2,912 (38.7 %)**, in 489 of 560 rings |
| `seed_edges` + `expanded_edges` | 4,316 | 33 (0.76 %) |

**None of them is laundering.** Across all three splits, **0 of 72,170** cross-currency edges carry
`Is Laundering`, and 0 of the 1,611 laundering test edges is a conversion. Truth rings contain no
conversions at all, while 1.53 % of non-member edges are conversions.

**The filter is label-free and exact:**

```python
is_conversion = se["currency_sent"] != se["currency_received"]
# equivalently, and this is 96.95 % of them:
is_self_conversion = (se["from_id"] == se["to_id"]) & is_conversion
```

**Recommendation for the L4 explainability layer:** exclude conversions from the ring's **evidence
edges** and from **`w_flow`**. They carry no laundering signal, they are an artefact of how the
dataset represents an exchange rather than a transfer between parties, and a self-loop moves no
money between accounts, so counting it in a flow share dilutes every real edge's share. Excluding
them needs **no schema change** - it is a filter on `member_edges` at read time.

This is a statement about what the column holds, not a change to it: `member_edges` keeps its
definition and the shipped files are untouched.

## Time basis

`timestamp`, `start_time`, `end_time` are in the **loader basis** (seconds since the
first day 00:00 minus 10 s, as in `data/processed/amlworld_*.parquet`). The legacy
model scripts re-based time to their own minimum, so `predictions_with_ids.csv` and the
E7 ring CSVs are `legacy_csv_time_offset_s` (10 s, `configs/paths.yaml`) lower; the
contract scripts assert and add that offset. `models/score.py` (Step 3.3) writes
loader-basis timestamps directly.

## Decoding the integer codes

`currency_sent`, `currency_received` and `payment_format` are integers assigned by
`scripts/format_kaggle_files.py` in order of **first appearance** in the raw transactions file. The
formatter kept no record of the mapping, so `contract/make_code_maps.py` reproduces the encoding
and writes it out, asserting the result row-for-row against the processed parquets before it
writes anything (5,078,345 rows, 0 mismatches on Timestamp, Sent Currency,
Received Currency and Payment Format).

* **`contract/currency_map.json`** - 15 currencies.
* **`contract/payment_format_map.json`** - 7 payment formats.
* **`contract/bank_names.json`** - 30,470 bank ids to names.

**Currency 0 is `US Dollar`.** Not because it is the commonest, but because within each raw row
the formatter assigns the *receiving* currency before the *payment* currency, so code 0 is the
first row's **receiving** currency. The order carries no meaning beyond that.

Currencies: 0 = US Dollar | 1 = Bitcoin | 2 = Euro | 3 = Australian Dollar | 4 = Yuan | 5 = Rupee | 6 = Yen | 7 = Mexican Peso | 8 = UK Pound | 9 = Ruble | 10 = Canadian Dollar | 11 = Swiss Franc | 12 = Brazil Real | 13 = Saudi Riyal | 14 = Shekel

Payment formats:

| code | name |
|---|---|
| 0 | Reinvestment |
| 1 | Cheque |
| 2 | Credit Card |
| 3 | ACH |
| 4 | Cash |
| 5 | Wire |
| 6 | Bitcoin |

**The codes are not ordered by anything.** They are an artefact of row order in the raw file, so a
numeric comparison on them (`payment_format < 3.5`) selects an arbitrary set of names. The shipped
GFP+XGBoost baseline nevertheless feeds all three as `float32` features - see
`baselines/refit_data.py` - which is recorded there rather than changed, because changing it would
make the model incomparable with the published numbers.

**Bank names do exist.** `<dataset>_accounts.csv` carries `Bank Name` beside `Bank ID`, and the
contract's `from_bank` / `to_bank` **are** that `Bank ID`:
30,470 of 30,470 bank codes used across the splits resolve
to a name. A name is **not** a unique key - 30,470 ids share
20,053 distinct names - so use it for display and never as a join key.

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
