# `python -m ringshield` — the research CLI (Step 5)

Three commands the platform harnesses (R10 / R11) call: `run`, `train`, `eval`. They work
today with the connected-components aggregator (`cc`) and keep the same command line and
output schemas when the `expand` (Step 6–7) and `full` (Step 8) aggregators arrive. A fourth,
research-side command (`export-model`) turns a validated experiment into a model directory.

Run from the repository root with the project interpreter (`.venv312`):

```bash
.venv312/Scripts/python.exe -m ringshield --help
```

Exit codes: `0` success · `2` usage / validation error (one-line message on stderr) · `1`
unexpected failure. Every command writes a JSON record next to its output (`<out>.log.json`
for `run`, `version.json` for `train`, the metrics file itself for `eval`) with the git commit
and every parameter it used.

## 1. `run` — scored edges → rings

```bash
.venv312/Scripts/python.exe -m ringshield run \
    --scores contract/out/scored_edges_gfpxgb_1.parquet \
    --model-dir models/artifacts/cc_gfpxgb_seed1 \
    --aggregator cc \
    --out experiments/R2_b0/gfpxgb/seed1/rings_cli.parquet
# [ringshield run] 97 rings from 863,900 edges (864 seeds, q=0.957895, 0 tied on the boundary) -> ...
```

Tenant-scoped inference — restrict the input to a set of edges:

```bash
.venv312/Scripts/python.exe -m ringshield run \
    --scores contract/out/scored_edges_gfpxgb_1.parquet \
    --edge-subset my_bank_edges.parquet \
    --model-dir models/artifacts/cc_gfpxgb_seed1 --aggregator cc \
    --out rings_my_bank.parquet
```

| argument | meaning |
|---|---|
| `--scores` | a **scored_edges** parquet in the contract layout (`contract/schema.py::SCORED_EDGES_COLUMNS`: `edge_id, tenant_id, from_id, to_id, from_bank, to_bank, timestamp, amount_*, currency_*, payment_format, score_raw, score_calibrated, is_seed, model_id, seed`). `score_calibrated` may equal `score_raw` when no calibration exists. |
| `--edge-subset` | optional parquet with an `edge_id` column. Only those edges are read; everything else (the quantile, components, member edges) is computed **within the subset**. |
| `--model-dir` | a model directory (§4). It fixes the aggregator, its validation-chosen parameters, and the `model_id` / `seed` of the scorer whose scores are expected. |
| `--aggregator` | `cc`, `expand` (Step 6) or `full` (Step 7: expansion + partition). If given, it overrides the model dir's aggregator (a note is printed). |
| `--gfp`, `--embeddings` | `expand` / `full`: the split's GFP parquet (`data/processed/amlworld_gfp_features_<split>.parquet`) and the R1 embeddings parquet of the same detector seed and split. Without `--gfp` the policy's GFP features are zero; without `--embeddings` its cosine features are missing (a note is printed either way). |
| `--out` | the rings parquet (§3); `<out>.log.json` is written beside it. |
| `--split val\|test` | research convenience only: lets `--scores` be a bare `models/score.py` file (`edge_id, timestamp, score_raw`), which is then joined with `data/processed/amlworld_<split>.parquet`. The platform should always pass a contract file. |
| `--seed-frac-pct`, `--min-size`, `--max-gap-hours` | override the model dir's parameters (leave alone in production). |

**Rules the platform can rely on**

* **Seed cut-off.** Seeds are the edges with `score_raw > q`, where `q` is the
  `(100 − seed_frac_pct)` percentile of the non-NaN `score_raw` values **of the edges given**
  (after `--edge-subset`). The cut is strict: edges tied exactly at `q` are excluded, so a
  plateau of indistinguishable scores is never swept in. `seed_frac_pct` comes from the model
  dir (chosen on validation per `configs/threshold_rule.yaml`); the log records `q`, the seed
  count and how many edges were tied on the boundary. Selection always uses `score_raw`;
  `score_calibrated` only feeds `confidence` / `max_edge_prob`.
* **`ring_id = f"{aggregator}-{model_id}-{seed}-{idx}"`**, e.g. `cc-gfpxgb-1-0`, `idx` in
  descending order of `confidence`. Unique within one output file; not stable across runs
  with different inputs.
* **`tenant_id` = the sender bank (`from_bank`) of the ring's earliest seed edge** (earliest
  `timestamp`; ties → the smallest `edge_id`). The platform derives the full set of banks
  with a member itself from `members` / `member_edges`; 98.9 % of AMLworld rings span more
  than one bank, so a single tenant column cannot carry that.
* **Edges.** `seed_edges` = the thresholded edges of the component; `member_edges` = every
  edge of the input with both endpoints in `members` and `timestamp` within
  `[start_time, end_time]`; `seed_edges ⊆ member_edges`; every listed edge is in the input
  (and therefore in the subset when one is given). `expanded_edges` is empty, `topology_type`
  is `UNKNOWN` with uniform `topology_probs`, `conservation_closure` is NaN and the role
  lists are empty until Steps 6–8 fill them — the columns are already there.
* **`expand` (Step 6).** The model dir carries the expansion operating point (`params.delta_t_h`,
  `params.p_min`, `max_hops`, `max_events_per_query`, `policy_kind`, the detector head constants
  for `dead_region`) and the trained policy under `policy/`. Seeds are selected exactly as for
  `cc`; each seed component is then grown by the policy inside
  `[min seed time − delta_t, max seed time + delta_t]` and rings are the components of
  seed + expanded edges (an added edge can merge two seed components). `expanded_edges` is
  filled, `conservation_closure` is the mean in/out closure over the ring's included accounts
  that have both flows (NaN if none); `seed_edges ⊆ member_edges`, `expanded_edges ⊆
  member_edges`, seed and expanded sets are disjoint. `topology_type` / roles still wait for
  Steps 7–8. Example: `models/artifacts/expand_gine_causal_seed1` with
  `--gfp data/processed/amlworld_gfp_features_test.parquet --embeddings experiments/R1_gine_causal/embeddings_test_seed1.parquet`.
* **`full` (Step 7).** As `expand`, then every expanded component is partitioned into attempts
  by the model dir's `params.partition` (`average` / `pivot` with the trained `affinity/`, or the
  baselines `b2` / `b3` / `b4`) at its val-chosen `params.partition_cell`. Rings of one component
  may share a hub account; every ring has ≥ `min_size` members (fragments below it are
  re-attached before rings are formed). Example: `models/artifacts/full_gine_causal_seed1`.
* **Determinism.** Same input, same model dir → identical output (the clustering seed is in `model.json`).

## 2. `train` — analyst verdicts in, new model directory out

```bash
.venv312/Scripts/python.exe -m ringshield train \
    --component expansion \
    --labels labels_2026-09-18.parquet \
    --base-model-dir models/artifacts/cc_gfpxgb_seed1 \
    --out-model-dir models/artifacts/cc_gfpxgb_seed1_v2
# [ringshield train] expansion: {'confirm': 12, 'reject': 3} -> ... (version 2, 12 confirmed rings in extra_labels.parquet; no retraining yet)
```

`labels.parquet` schema (validated; any violation → exit 2 with the reason):

| column | type | rule |
|---|---|---|
| `ring_id` | string | non-null, unique in the file (the `ring_id` the platform received from `run`) |
| `member_accounts` | list\<int64\> | non-empty for `confirm` / `partial` |
| `member_edges` | list\<int64\> | integers |
| `verdict` | string | one of `confirm`, `reject`, `partial` |

What it does today (no learned component exists yet): validates the file, copies the base
model directory to `--out-model-dir` (must be a different path; an existing target is
replaced), appends the **confirmed** rows to `<out>/extra_labels.parquet` (kept across rounds,
with `added_utc`, `source_labels`, `component`), bumps `version` in `model.json` and writes
`version.json` (`retrained: false`, label counts, base dir, git commit). `--component` is one
of `expansion | affinity | typing` and is recorded. Steps 6–8 put real retraining behind this
exact interface; the platform's call does not change.

## 3. `eval` — rings vs ground truth

```bash
.venv312/Scripts/python.exe -m ringshield eval \
    --rings experiments/R2_b0/gfpxgb/seed1/rings_cli.parquet \
    --truth data/processed/amlworld_ring_ground_truth.parquet \
    --scope test_visible --window primary \
    --scores contract/out/scored_edges_gfpxgb_1.parquet \
    --out experiments/R2_b0/gfpxgb/seed1/metrics_cli.json
# [ringshield eval] 81 rings vs 174 truth rings (test_visible, primary): P 0.5185 R 0.2414 F1 0.3294 R>=3 0.3246 -> ...
```

| argument | meaning |
|---|---|
| `--rings` | a rings parquet from `run` |
| `--truth` | the ring ground-truth parquet (`ring_id, pattern_type, from_id, to_id, timestamp_int, …`) |
| `--scope` | `test_visible` (default; `docs/RING_GROUND_TRUTH_DEFINITION.md` §4) or `strict` / `majority` / `start` |
| `--window` | evaluation window name from `configs/eval_window.yaml` (`primary` = test days 8–9, default; `tail`; `whole`; `val`), or give `--t-min --t-max` (loader-basis seconds) explicitly |
| `--scores` | optional; when given, predicted rings are restricted to their edges inside the window (the same rule the research tables use). Without it the rings' full member sets are scored. |
| `--holdout` | JSON manifest for the promotion gate: `{"truth_ring_ids": [...]}` restricts the ground truth to those rings (`ring_ids` is accepted as an alias), `{"pred_ring_ids": [...]}` restricts the predicted rings; both may be present |
| `--match-threshold` | Jaccard for a match, default 0.5 (fixed by the ground-truth definition; 0.3 / 0.7 are reported as a sweep) |

`metrics.json` holds `ring_precision`, `ring_recall`, `ring_f1`, `member_coverage`,
`mean_jaccard`, `n_predicted / n_truth / n_matched`, `ring_recall_ge3` (recall over truth
rings with ≥ 3 visible members), `per_pattern` recall, the Jaccard 0.3 / 0.7 sweep, and the
window / holdout it was computed on.

## 4. Model directories

A model directory is a folder with `model.json`:

```json
{
  "model_id": "gfpxgb", "seed": 1, "aggregator": "cc",
  "params": {"seed_frac_pct": 0.1, "min_size": 3, "max_gap_hours": null},
  "feature_set": "trailing_closescycle",
  "threshold_rule": "configs/threshold_rule.yaml (strict quantile on score_raw)",
  "source": "experiments/R2_b0/gfpxgb/seed1 (ringshield/run_rings.py config.yaml, chosen on val)",
  "version": 1, "created_utc": "...", "git_commit": "..."
}
```

`train` adds `version.json` and `extra_labels.parquet`; Steps 6–8 add the learned components
next to them. The research side creates one from a validated experiment:

```bash
.venv312/Scripts/python.exe -m ringshield export-model --run-dir experiments/R2_b0/gfpxgb/seed1 --out-model-dir models/artifacts/cc_gfpxgb_seed1
```

Available now: `models/artifacts/cc_gine_causal_seed1` (Multi-GINe, causal, trailing features,
seed 1, cc, 0.1 % / min_size 3 — the model behind `contract/out/rings_stub_cc.parquet`),
`models/artifacts/cc_gfpxgb_seed1` (GFP + XGBoost, seed 1, cc, 0.1 % / min_size 3) and
`models/artifacts/expand_gine_causal_seed1` (the Step 6 expansion policy on the seed-1 gine
scores: cc cell 0.1 % / 3, Δt 24 h, p_min 0.7; `export-model` from an `expand` run copies the
policy files into the model dir) and `models/artifacts/full_gine_causal_seed1` (the same plus
the Step 7 affinity, average linkage cut 0.5; `export-model` from a `full` run copies `policy/`
and `affinity/`). Contract
scored_edges to feed them: `contract/out/scored_edges_gine_causal_1{,_val}.parquet`,
`contract/out/scored_edges_gfpxgb_1{,_val}.parquet`.

## 5. Checks

```bash
.venv312/Scripts/python.exe -m pytest tests/test_cli.py -q      # 5 tests, ~10 s, on a 1 % sample
```

The tests run all three commands on a 1 % sample of the test split with the gfpxgb scores,
including a run restricted to a single bank via `--edge-subset` that asserts every member
edge and seed edge of every ring is inside the subset, and check the `ring_id` / `tenant_id`
rules, the labels validation (a bad verdict exits 2), version bumps across two `train`
rounds, and the holdout manifest.
