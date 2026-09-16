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

Everything below exists in the repo and has been run at least once on this workstation.
Numbers are the ones written in the corresponding `experiments/<ID>/metrics.json`.

| Component | File | Output folder | Status |
|---|---|---|---|
| AMLworld loader (raw CSV → train/val/test Parquet, day-based split, ring ground truth) | `preprocessing/amlworld_loader.py` | `data/processed/` | done |
| Per-edge GFP motif features (fan-in/out, cycles, scatter-gather, degree) | `graph/motif_features.py` | `data/processed/amlworld_gfp_features_*.parquet` | done |
| Tabular baselines (LogReg / RF / XGBoost) | `baselines/*_aml.py` | `experiments/E5a_*` | done |
| GFP + XGBoost with Optuna search | `baselines/gfp_xgboost_aml.py` | `experiments/E5b_gfp_xgboost` | done — test F1 0.534 |
| Multi-GINe edge classifier (edge-MLPs, ports, time deltas, reverse MP, ego IDs, GFP) | `models/tgn.py` | `experiments/E6_tgn` | done — test F1 0.599 ± 0.009 over seeds {1, 42, 123} |
| Test-set scoring with edge IDs (checkpoint chosen by val F1) | `score_test_set.py` | `experiments/E6_tgn/predictions_with_ids.csv` (untracked) | done |
| Ring aggregation from scored edges | `models/ring_aggregator.py` | `experiments/legacy_E7_test_tuned` | runs, but its thresholds were tuned on the test set — **not reported** |
| Ring metrics (precision / recall / F1, member coverage, Jaccard) | `evaluation/ring_metrics.py` | — | done |

Not implemented (removed in Step 1 because they were stubs or dead ends): the Elliptic
pipeline, EvolveGCN, GATv2, rule engine, cascade pipeline, explainability, ablations,
latency benchmark. See `docs/PROGRESS.md` for the step-by-step log.

Seeds for every future run come from `configs/seeds.yaml` (`[1, 2, 3, 4, 5]`); paths
from `configs/paths.yaml`. The E5b/E6 runs above pre-date that rule and used the seeds
recorded in their own `config.yaml`.

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
python score_test_set.py --arch gine --raw-dir data/raw --data-dir data/processed --ckpt experiments/E6_tgn/model_best_seed1.pt --n-hidden 66 --threshold 0.46 --out experiments/E6_tgn/predictions_with_ids.csv
```

Contract files (Step 1.2):

```bash
python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
python -m pytest contract/tests -q
```

## Hardware

All runs so far: Intel Xeon W-2295 (18C/36T, 3.0 GHz), 128 GB RAM, NVIDIA RTX A5000
(24 GB), Windows 11 Pro, Python 3.12.10, PyTorch 2.5.1+cu121, PyG 2.8.0, XGBoost 3.4.1.
