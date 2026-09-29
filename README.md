# RingShield

RingShield is a research prototype for detecting money-laundering *rings* — groups of
accounts that move funds through cycles, fan-in/fan-out, scatter-gather and similar
motifs — in transaction graphs. Rather than scoring transactions one at a time, it
(1) scores every edge of a temporal transaction graph with a GNN that has been fed
per-edge graph-motif (GFP) features, then (2) aggregates the highest-scoring edges into
connected account groups and evaluates those groups against a ring ground truth. All
experiments run on the IBM AMLworld **HI-Small** dataset with a day-based 60/20/20
train/validation/test split; thresholds and hyper-parameters are selected on the
validation split only.

## What is implemented

Everything below exists in the repo and has been run on this workstation (RTX A5000). **Every
number in `results/` recomputes from an `experiments/<run>/metrics.json`** — `evaluation/audit_tables.py`
checks 18 headline rows mechanically and currently reports *18 traceable, 0 mismatched*.

Claims live in one place: **`docs/FINDINGS.md`** (A: what the pipeline achieves, B: what it does
not, C: measurement findings about the dataset). Commands live in **`docs/REPRODUCE.md`**.
Traps live in **`docs/PITFALLS.md`**.

### Pipeline

| Layer | What it does | Entry point | Output |
|---|---|---|---|
| L0 preprocessing | raw CSV → splits, ring ground truth, GFP motif features; stable `edge_id` by mergesort, hash-pinned | `scripts/format_kaggle_files.py`, `preprocessing/amlworld_loader.py`, `graph/motif_features.py` | `data/processed/` |
| L1 detector | Multi-GINe edge classifier, causal neighbour sampling, 5 seeds | `models/tgn.py --causal` | `experiments/R1_gine_causal` |
| L1 scoring / calibration | split scoring + head-input embeddings; isotonic fitted on val only | `models/score.py`, `models/calibrate.py` | `scores_*.parquet`, `calibrator_seed*.pkl` |
| L2 seeds | strict quantile cut at the val-chosen k\* (0.1 % / `min_size` 3) | `configs/threshold_rule.yaml` | — |
| L3a expansion | candidate generation + LightGBM policy trained on **cross-scored** train data | `ringshield/expand/` | `experiments/R3_expansion` |
| L3b partition | shared-account pair affinity + average linkage | `ringshield/partition/` | `experiments/R4_partition` |
| L3c roles / typing | account roles, ring confidence, topology head, leave-one-out XAI | `ringshield/roles.py`, `ringshield/typing/` | `experiments/R5_typing` |
| Contract | `scored_edges` and `rings` v1 parquets for the platform side | `contract/` | `contract/out/` |
| CLI | `run` / `train` / `eval` / `export-model` | `python -m ringshield` | `docs/CLI.md` |

### Experiments behind the reported tables

| ID | What | Result |
|---|---|---|
| **R1** | detector, 5 seeds, causal | test edge F1 0.5967 ± 0.070 |
| **R2** | B0 ring baseline, 3 detectors | gine 0.521 ± 0.045, gfpxgb 0.344, density 0.014 |
| **R3** | expansion: policy vs rule baselines vs ablations | proposed 0.582; **quiet-member recall 0.005 → 0.21** |
| **R4** | partition: 5 methods + CSGM | full 0.589; the stage is **not** significant on this detector |
| **R5** | roles and topology typing | head 0.219 on the primary window, 0.594 on `whole` |
| **R6** | detector swap: MEGA-GNN and GFP-XGBoost | **+9.4 edge-F1 points buys 0.000 ring-F1** |
| **R7** | held-out pattern types (3 arms) + LI-Small | transfer holds on CYCLE at undiminished precision |
| **R9** | statistics: bootstrap CIs, permutation tests, Holm | every table carries an interval |
| **R11b/c** | seed-budget reallocation (ensemble, per-account) | allocation is **not** the binding constraint |

### Headline findings

1. **Edge F1 is not a proxy for ring recovery.** MEGA-GNN beats our detector by 9.4 edge-F1 points
   and produces the same rings (0.5208 vs 0.5213). The two disagree on *which* edges to seed
   (Jaccard 0.415) and agree on how many rings a 0.1 % budget reaches (128.8 vs 129.6 of 174).
2. **Expansion recovers quiet members** — 0.5 % → 21 % — but a two-line rule matches it; the learned
   policy buys *purity* (0.926 vs 0.518 added-member precision), not recall.
3. **The ceiling is structural.** 28 % of rings are below `min_size`, 19 % are untouched by any
   detector edge, and **80.7 %** of the largest residual class is in a piece of the ring that is
   *disconnected inside the evaluation window* — 99.6 % for STACK even across the whole test split.
4. **Both ends of the AMLworld timeline are generator artefacts**, reproduced in two releases: day 0
   holds ~34 % of training edges at 10× density, and the test tail collapses to a ~60 % base rate on
   ≤ 0.13 % of edges.

### Deliberately not done

* **Step 12 (structuring stress test)** — premise weakened by findings B13/B15; see `docs/REPRODUCE.md`.
* **LI-Small method numbers** — 38 matchable rings cannot separate any method; its scope, tail and
  day-0 analyses are the reported result.
* **`rings_full` for mega / gfpxgb** — the contract builder is pinned to the shipped detector and
  asserts it reproduces the R4 run. Those detectors are research comparisons under
  `experiments/R6_full/`, not contract deliveries.
* Elliptic, EvolveGCN, GATv2, the escalation cascade, attention-based XAI — out of scope (Step 1).

Seeds come from `configs/seeds.yaml` (`[1, 2, 3, 4, 5]`), paths from `configs/paths.yaml`
(`$RINGSHIELD_PATHS` selects a per-dataset file). Pre-R1 runs used the seeds in their own
`config.yaml`.

## Reproduction (steps completed so far)

Environment (Windows, PowerShell):

```bash
py -3.12 -m venv .venv312
.\.venv312\Scripts\Activate.ps1
pip install -r requirements.txt
```

Data — place the Kaggle *IBM Transactions for AML* HI-Small files in `data/raw/`, then:

```bash
python scripts/format_kaggle_files.py "data/raw/HI-Small_Trans.csv"
python preprocessing/amlworld_loader.py --raw-dir data/raw --out-dir data/processed --patterns data/raw/HI-Small_Patterns.txt
python graph/motif_features.py --data-dir data/processed --out-dir data/processed --window 86400 --max-cycle-hops 5 --workers 0
```

Baselines:

```bash
python baselines/logistic_regression_aml.py --data-dir data/processed --out-dir experiments/E5a_logistic_regression
python baselines/random_forest_aml.py --data-dir data/processed --out-dir experiments/E5a_random_forest
python baselines/xgboost_aml.py --data-dir data/processed --out-dir experiments/E5a_xgboost --no-gpu
python baselines/gfp_xgboost_aml.py --data-dir data/processed --out-dir experiments/E5b_gfp_xgboost --n-trials 50
```

Multi-GINe edge classifier and scored test edges:

```bash
python models/tgn.py --raw-dir data/raw --data-dir data/processed --out-dir experiments/E6_tgn --epochs 100 --emlps --ports --tds --reverse-mp --ego --gfp --num-neighs 100 100 --seeds 1 42 123
python models/score.py --run-dir experiments/E6_tgn --seed 1 --split test --non-causal   # legacy E6 checkpoint
```

Contract files (Step 1.2-1.3) and checks:

```bash
python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
python contract/make_rings_stub.py --e7-csv experiments/legacy_E7_test_tuned/rings_gine.csv --scored-edges contract/out/scored_edges_gine_1.parquet --aggregator-id cc
python scripts/data_manifest.py --check
python -m pytest contract/tests -q
```

Step 3b (causal training, scoring, leak row, edge metrics):

```bash
python contract/make_labels.py
python models/tgn.py --arch gine --causal --seeds 1 2 3 4 5 --out-dir experiments/R1_gine_causal --epochs 100 --emlps --ports --tds --reverse-mp --ego --gfp --num-neighs 100 100
python models/score.py --run-dir experiments/R1_gine_causal --seeds 1 2 3 4 5 --splits val test train --embeddings-for val test
python models/score.py --run-dir experiments/E6_tgn --seeds 1 42 123 --splits val test --non-causal --out-dir experiments/R1_gine_noncausal
python evaluation/edge_metrics.py --run-dir experiments/R1_gine_causal experiments/R1_gine_noncausal
```

Step 3a (data regeneration, loader tests; no training):

```bash
python scripts/format_kaggle_files.py data/raw/HI-Small_Trans.csv
python preprocessing/amlworld_loader.py --raw-dir data/raw --out-dir data/processed --patterns data/raw/HI-Small_Patterns.txt
python scripts/remap_edge_ids.py --old <previous formatted_transactions.csv> --apply-gfp data/processed --apply-preds experiments/E6_tgn/predictions_with_ids.csv
python scripts/data_manifest.py
python -m pytest tests contract/tests preprocessing/tests -q
```

L0 additions (Step 2):

```bash
python preprocessing/account_bank.py
python preprocessing/ring_scope.py --gt data/processed/amlworld_ring_ground_truth.parquet --splits data/processed --out docs/ring_scope.json
python -m pytest preprocessing/tests contract/tests -q
```

## Hardware

All runs so far: Intel Xeon W-2295 (18C/36T, 3.0 GHz), 128 GB RAM, NVIDIA RTX A5000
(24 GB), Windows 11 Pro, Python 3.12.10, PyTorch 2.5.1+cu121, PyG 2.8.0, XGBoost 3.4.1.
