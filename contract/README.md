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
| 6 | `member_edges` | list<int64> | edge_ids with from_id AND to_id in members and timestamp in [start_time, end_time] |
| 7 | `seed_edges` | list<int64> | member_edges with is_seed |
| 8 | `expanded_edges` | list<int64> | [] until Step 6-8 |
| 9 | `n_edges` | int64 | edges the aggregator used to form the ring |
| 10 | `start_time` | int64 | min timestamp of member_edges, loader basis |
| 11 | `end_time` | int64 | max timestamp of the aggregator's ring edges, loader basis |
| 12 | `duration_hours` | float64 | (end_time - start_time) / 3600 |
| 13 | `confidence` | float64 | aggregator confidence |
| 14 | `max_edge_prob` | float64 | max score among the aggregator's ring edges |
| 15 | `density` | float64 | n_edges / (n_members * (n_members - 1)) |
| 16 | `conservation_closure` | float64 | NaN until Step 6-8 |
| 17 | `topology_type` | string | one of TOPOLOGY_TYPES or 'UNKNOWN' |
| 18 | `topology_probs` | list<float64> | 8 probabilities in TOPOLOGY_TYPES order; uniform until Step 8 |
| 19 | `source_accounts` | list<int64> | [] until Step 8 |
| 20 | `sink_accounts` | list<int64> | [] until Step 8 |
| 21 | `mule_accounts` | list<int64> | [] until Step 8 |

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
