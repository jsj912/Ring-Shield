# contract/

The hand-off files between the edge-scoring side and the ring side.
**This file is generated from `contract/schema.py`** (`python contract/schema.py`);
edit the schema, not this page. If a spec or the Implementation Plan disagrees with
`schema.py`, `schema.py` wins.

| File | Producer | Columns |
|---|---|---|
| `out/scored_edges_<model>_<seed>.parquet` | `make_scored_edges.py` | `SCORED_EDGES_COLUMNS` |
| `out/labels_{train,val,test}.parquet` | `make_labels.py` (internal, never shipped; `labels_test` also written by `make_scored_edges.py`) | `LABELS_COLUMNS` |
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

| # | column | type | meaning |
|---|---|---|---|
| 1 | `edge_id` | int64 | arange index assigned by scripts/format_kaggle_files.py (row of formatted_transactions.csv); unique |
| 2 | `tenant_id` | int64 | = from_bank for now |
| 3 | `from_id` | int64 | sending account id (loader account_map) |
| 4 | `to_id` | int64 | receiving account id |
| 5 | `from_bank` | int64 | bank id of the sending account |
| 6 | `to_bank` | int64 | bank id of the receiving account |
| 7 | `timestamp` | int64 | seconds since dataset start, loader basis (= amlworld_*.parquet Timestamp) |
| 8 | `amount_sent` | float64 | 'Amount Sent' |
| 9 | `amount_received` | float64 | 'Amount Received' |
| 10 | `currency_sent` | int64 | loader integer encoding of 'Sent Currency' |
| 11 | `currency_received` | int64 | loader integer encoding of 'Received Currency' |
| 12 | `payment_format` | int64 | loader integer encoding of 'Payment Format' |
| 13 | `score_raw` | float64 | model pred_prob; NaN when the model produced no score |
| 14 | `score_calibrated` | float64 | isotonic calibration fit on the val split (models/calibrate.py, Step 3c); == score_raw for files written before calibration |
| 15 | `is_seed` | bool | seed-fraction rule (configs/threshold_rule.yaml): score_raw > quantile(1 - k*/100) within the split, strict; Step 1 files used predicted_label == 1. False when score_raw is NaN |
| 16 | `model_id` | string | e.g. 'gine' |
| 17 | `seed` | int64 | training seed of the model that produced score_raw |

## labels_<split> (internal)

Read by `evaluation/edge_metrics.py`; never joined into a shipped file.

| # | column | type | meaning |
|---|---|---|---|
| 1 | `edge_id` | int64 | joins 1:1 to scored_edges.edge_id |
| 2 | `true_label` | int64 | 'Is Laundering' from amlworld_test.parquet |

## rings

`topology_probs` order: FAN-OUT, FAN-IN, GATHER-SCATTER, SCATTER-GATHER, CYCLE, RANDOM, BIPARTITE, STACK.

| # | column | type | meaning |
|---|---|---|---|
| 1 | `ring_id` | string | f'{aggregator}-{model_id}-{seed}-{idx}' (Step 5 CLI rule, e.g. 'cc-gine_causal-1-0'; the Step 1 stub used f'{aggregator_id}-{ring_idx}') |
| 2 | `tenant_id` | int64 | sender bank (from_bank) of the ring's earliest seed edge, ties -> smallest edge_id (Step 5 rule; the Step 1 stub used the most common bank among members). The platform derives the full set of banks with a member itself |
| 3 | `aggregator_id` | string | e.g. 'cc' (connected components) |
| 4 | `members` | list<int64> | account ids |
| 5 | `n_members` | int64 | len(members) |
| 6 | `member_edges` | list<int64> | edge_ids with from_id AND to_id in members and timestamp in [start_time, end_time]. This is EVERY edge among the member accounts in the ring's span, not only the ones the aggregator used -- including self-loop currency conversions, which are 38.7 % of predicted member edges and are NEVER laundering in AMLworld (0 of 72,170). Filter them out of evidence and flow shares: see 'What member_edges contains' below |
| 7 | `seed_edges` | list<int64> | member_edges with is_seed |
| 8 | `expanded_edges` | list<int64> | member_edges the expansion policy added around the seeds (Step 6); [] for the cc aggregator |
| 9 | `expanded_edge_probs` | list<float64> | the expansion policy's probability for each edge of expanded_edges, same order and length (Step 8); [] when nothing was expanded. The XAI layer needs it because an expanded edge's own detector score is low by definition |
| 10 | `n_edges` | int64 | edges the aggregator used to form the ring |
| 11 | `start_time` | int64 | min timestamp of member_edges, loader basis |
| 12 | `end_time` | int64 | max timestamp of the aggregator's ring edges, loader basis |
| 13 | `duration_hours` | float64 | (end_time - start_time) / 3600 |
| 14 | `confidence` | float64 | mean score_calibrated over seed_edges x conservation_closure (Step 8 definition). When conservation_closure is NaN (no source or no sink) the closure factor is dropped and confidence is the mean alone; the run log counts those rings (n_rings_closure_nan) |
| 15 | `max_edge_prob` | float64 | max score among the aggregator's ring edges |
| 16 | `density` | float64 | n_edges / (n_members * (n_members - 1)) |
| 17 | `conservation_closure` | float64 | 1 - |sum of inflow at the ring's sinks - sum of outflow at its sources| / max(those two sums), clipped to [0, 1], over the ring's seed + expanded edges with amounts deduplicated on (from_id, to_id, timestamp, amount_received). NaN when the ring has no source or no sink (roles per configs/roles.yaml) |
| 18 | `topology_type` | string | one of TOPOLOGY_TYPES or 'UNKNOWN' |
| 19 | `topology_probs` | list<float64> | 8 probabilities in TOPOLOGY_TYPES order, summing to 1 (Step 8 typing head; uniform with topology_type 'UNKNOWN' when no head is attached) |
| 20 | `source_accounts` | list<int64> | members whose role is 'source' (configs/roles.yaml: no inflow, or inflow / outflow < tau_role 0.25, over the ring's deduplicated flows) |
| 21 | `sink_accounts` | list<int64> | members whose role is 'sink' (no outflow, or outflow / inflow < tau_role) |
| 22 | `mule_accounts` | list<int64> | members whose role is 'mule' (both flows, closure >= 1 - tau_role, passed on within 72 h) or 'holder' (same but held longer); ringshield.roles.account_roles returns the two separately |
| 23 | `conservation_closure_ccy` | float64 | ring-level closure computed per currency and summed over currencies that appear on BOTH sides of an account; NaN when no currency does -- 521 of 881 two-sided ring-accounts (59.1 %), or 12.2 % of all 4,280. SUPERSEDED by account_roles(currency='converted'), which converts with the generator's own fixed rates instead of withholding; kept as published. `conservation_closure` (v1) remains the RAW cross-currency ratio and is what `confidence` uses |
| 24 | `n_accounts_ccy_undefined` | int64 | ring accounts whose inflow and outflow currency sets are disjoint, so no per-currency closure exists for them; the denominator behind conservation_closure_ccy |
| 25 | `source_accounts_ccy` | list<int64> | source accounts under currency-partitioned flows (opt-in roles); the v1 `source_accounts` stays raw-sum |
| 26 | `sink_accounts_ccy` | list<int64> | sink accounts under currency-partitioned flows |
| 27 | `mule_accounts_ccy` | list<int64> | mule accounts under currency-partitioned flows |
| 28 | `undetermined_accounts_ccy` | list<int64> | accounts whose role could not be decided from same-currency evidence: their inflow and outflow currencies do not overlap, or the overlap carries too little flow to judge. Not 'peripheral'. SUPERSEDED 2026-10-14: the exchange rates ARE recoverable (contract/fx_rates.json), and under currency='converted' 568 of these 571 accounts resolve -- 86 % of them to mule. Kept as published; prefer the converted roles. Render any remaining undetermined explicitly |
| 29 | `n_roles_changed_ccy` | int64 | accounts whose role differs between the raw and the currency-aware assignment; the size of the disagreement, visible without recomputing either |
| 30 | `n_currencies` | int64 | distinct currency codes on the ring's member edges (1 = the raw and currency-partitioned definitions coincide) |

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

## Account -> bank map

`from_bank` / `to_bank` come from `data/processed/account_bank.parquet`
(`account_id, bank_code, account_number`; built by `preprocessing/account_bank.py` from
`HI-Small_Trans.csv` with the loader's key rule, `str(bank) + str(account)`, ids in
first-appearance order, and validated 100% against `HI-Small_accounts.csv`).
