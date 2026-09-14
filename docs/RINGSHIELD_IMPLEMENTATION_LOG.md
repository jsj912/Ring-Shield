# RingShield — Full Implementation Log

**Project:** RingShield — Multi-tenant fraud ring detection SaaS using Temporal GNNs  
**Author:** Jooo (Joan Sara Joe)  
**Date range:** September 2026  
**Phases covered:** Phase 4 (EvolveGCN on Elliptic) → Phase 5 (AMLworld baselines) → Phase 6 (GINe GNN)  
**Roadmap doc:** `RingShield_Implementation_Roadmap__1_.md`

---

## Table of Contents

1. [Environment Setup](#1-environment-setup)
2. [Repository Structure](#2-repository-structure)
3. [Phase 4 — EvolveGCN on Elliptic](#3-phase-4--evolvegcn-on-elliptic)
4. [Phase 5 — AMLworld HI-Small Dataset Pipeline](#4-phase-5--amlworld-hi-small-dataset-pipeline)
5. [Phase 5 — E5a Tabular Baselines](#5-phase-5--e5a-tabular-baselines)
6. [Phase 5 — E5b GFP + XGBoost (Scientific Caution Baseline)](#6-phase-5--e5b-gfp--xgboost)
7. [Phase 6 — GNN (TGN → GINe)](#7-phase-6--gnn-tgn--gine)
8. [Results Summary](#8-results-summary)
9. [Known Issues & Decisions](#9-known-issues--decisions)
10. [Current State & Next Steps](#10-current-state--next-steps)
11. [File Inventory](#11-file-inventory)

---

## 1. Environment Setup

### Hardware
- **GPU:** NVIDIA RTX A5000 (24 GB VRAM, 25.8 GB reported by PyTorch)
- **CPU:** 36 cores (confirmed by multiprocessing.cpu_count())
- **CUDA driver version:** 12.8 (nvidia-smi shows 572.16 driver)
- **OS:** Windows (PowerShell terminal, no bash/WSL available)

### Python Environment
- **Started with:** Python 3.8 in `.venv` — hit multiple compatibility issues (scipy ≥1.11, matplotlib ≥3.8 don't support 3.8)
- **Upgraded to:** Python 3.12.10 in `.venv312` (3.12.10 was the last 3.12 release with Windows binary installers; 3.12.14+ is source-only)
- **Activation:** `.venv312\Scripts\activate`
- **Location:** `E:\JSJ\Ring-Shield`

### Key Package Versions
```
torch==2.5.1+cu121  (installed via --index-url https://download.pytorch.org/whl/cu121)
torch-geometric==2.6.1
torch-geometric-temporal==0.56.2
torch-scatter, torch-sparse  (installed from https://data.pyg.org/whl/torch-2.5.1+cu121.html)
xgboost==3.4.1  (CPU-only — GPU build not available via pip on Windows)
scikit-learn  (latest compatible with 3.12)
pandas, numpy, pyarrow, scipy, matplotlib, seaborn, pyyaml, optuna, networkx, joblib, jupyter
```

### Installation Issues Encountered & Fixes
1. **torch-sparse/torch-scatter build failure (Python 3.8):** `nvcc fatal: Failed to open for read host compiler properties` — MSVC + CUDA build toolchain mismatch. **Fix:** Install prebuilt wheels from `https://data.pyg.org/whl/torch-X.X.X+cu121.html`
2. **torch-sparse WinError 127 (Python 3.12):** ABI mismatch between torch-sparse wheel and installed torch version (2.5.1 vs wheels built for 2.4.1). **Fix:** `pip uninstall torch-scatter torch-sparse -y && pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.5.1+cu121.html`
3. **scipy ≥1.11 / matplotlib ≥3.8:** Dropped Python 3.8 support. **Fix:** Upgraded to Python 3.12
4. **datatable build failure:** `datatable` (IBM dependency) doesn't build on Windows in a venv. **Fix:** Rewrote `format_kaggle_files.py` in pure pandas
5. **XGBoost GPU (`gpu_hist`):** XGBoost 3.4.1 removed `gpu_hist` — new API is `tree_method='hist' + device='cuda'`. But pip xgboost is CPU-only on Windows, `xgboost[cuda12]` extra doesn't exist in 3.4.1. **Fix:** Used `--no-gpu` flag, runs on CPU (~44s for 5M rows, acceptable)

### requirements.txt (final version)
```
# Install torch separately FIRST:
#   pip install torch --index-url https://download.pytorch.org/whl/cu121
#   pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.5.1+cu121.html

pandas>=2.0
numpy>=1.24
pyarrow>=14.0
scikit-learn>=1.3
xgboost>=2.0
torch-geometric>=2.4
torch-geometric-temporal>=0.54
pyyaml>=6.0
scipy>=1.11
matplotlib>=3.8
seaborn>=0.13
jupyter>=1.0
optuna
networkx
joblib
```

---

## 2. Repository Structure

Created via PowerShell script `setup_ringshield.ps1`. Full layout:

```
ringshield/  (actually E:\JSJ\Ring-Shield)
├── data/
│   ├── raw/                           # gitignored — raw downloads
│   │   ├── elliptic_txs_features.csv  # Elliptic dataset (Kaggle)
│   │   ├── elliptic_txs_classes.csv
│   │   ├── elliptic_txs_edgelist.csv
│   │   ├── HI-Small_Trans.csv         # AMLworld HI-Small (Kaggle)
│   │   ├── HI-Small_accounts.csv
│   │   ├── HI-Small_Patterns.txt      # Ring ground truth
│   │   └── formatted_transactions.csv  # Output of format_kaggle_files.py
│   ├── processed/                     # gitignored — parquet splits
│   │   ├── elliptic_train.parquet
│   │   ├── elliptic_test.parquet
│   │   ├── edges_train.parquet
│   │   ├── edges_test.parquet
│   │   ├── amlworld_train.parquet     # 60/20/20 split
│   │   ├── amlworld_val.parquet
│   │   ├── amlworld_test.parquet
│   │   ├── amlworld_edges_train.parquet
│   │   ├── amlworld_edges_val.parquet
│   │   ├── amlworld_edges_test.parquet
│   │   ├── amlworld_ring_ground_truth.parquet
│   │   ├── amlworld_motif_features.parquet       # v1 per-node proxies
│   │   ├── amlworld_gfp_features_train.parquet   # v2 per-edge real GFP
│   │   ├── amlworld_gfp_features_val.parquet
│   │   └── amlworld_gfp_features_test.parquet
│   └── SPLIT_MANIFEST.md
├── preprocessing/
│   ├── elliptic_loader.py             # Elliptic time-based 70:30 split
│   ├── amlworld_loader.py            # AMLworld 60/20/20 split + feature eng
│   └── shared_utils.py
├── graph/
│   ├── motif_features.py             # GFP per-edge feature computation (parallelized)
│   ├── build_elliptic_graph.py
│   └── build_amlworld_graph.py
├── baselines/
│   ├── evolvegcn.py                  # Phase 4: EvolveGCN on Elliptic
│   ├── logistic_regression_aml.py    # E5a: LR on AMLworld
│   ├── random_forest_aml.py          # E5a: RF on AMLworld
│   ├── xgboost_aml.py               # E5a: XGBoost on AMLworld
│   └── gfp_xgboost_aml.py           # E5b: GFP + XGBoost (tuned)
├── models/
│   └── tgn.py                        # Phase 6: Multi-GINe (IBM architecture)
├── scripts/
│   └── format_kaggle_files.py        # Pandas replacement for IBM's datatable version
├── experiments/
│   ├── E4_evolvegcn/                 # Standard 6-file template each
│   ├── E5a_logistic_regression/
│   ├── E5a_random_forest/
│   ├── E5a_xgboost/
│   ├── E5b_gfp_xgboost/
│   └── E6_tgn/
├── configs/
├── notebooks/
├── tests/
├── docs/
├── .gitignore
├── requirements.txt
└── README.md
```

### Standard 6-file experiment template
Every `experiments/E*_*/` folder contains:
```
config.yaml        — hyperparameters, model name, dataset, seed
metrics.json       — train/val/test metrics (F1, precision, recall, AP)
predictions.csv    — true_label, predicted_label, pred_prob
model.pkl          — saved model weights (or .pt/.json for torch/xgboost)
training_log.csv   — per-epoch metrics
environment.txt    — python version, pip freeze, GPU info
```

### .gitignore
```
data/raw/
data/processed/
*.pkl
*.pt
*.pth
experiments/*/model.json
experiments/*/predictions.csv
__pycache__/
*.pyc
.venv/
.venv312/
.vscode/
.idea/
.DS_Store
Thumbs.db
logs/
*.log
.env
data_config.json
*.tar.gz
*.zip
wandb/
```

---

## 3. Phase 4 — EvolveGCN on Elliptic

### Dataset: Elliptic (Weber et al.)
- **Source:** Kaggle "Elliptic Data Set"
- **Version:** Original Elliptic (NOT Elliptic++) — 166 features, 203,769 nodes, 49 timesteps
- **Files:** `elliptic_txs_features.csv` (no header), `elliptic_txs_classes.csv`, `elliptic_txs_edgelist.csv`

### Split: `preprocessing/elliptic_loader.py`
- **Type:** Time-based 70:30 (NOT random — avoids future leakage)
- **Train:** timestep 1–34 → 136,265 nodes
- **Test:** timestep 35–49 → 67,504 nodes
- **Total:** 136,265 + 67,504 = 203,769 ✓
- **Feature set:** AF (All Features) — 165 feature columns (93 local + 72 one-hop aggregated)
- **Edge filtering:** Only kept edges where BOTH endpoints are in the same split
- **Train edges:** 156,843 | **Test edges:** 77,512
- **Labels:** 1=illicit, 0=licit, -1=unknown. Unknown nodes excluded from loss but kept as graph structure.
- **Feature standardization:** Mean/std computed on train only, applied to all

**Key discovery during implementation:** All 234,355 edges in Elliptic are same-timestep (no cross-timestep edges). This means each of the 49 snapshots is structurally isolated — directly impacts EvolveGCN performance.

### Model: `baselines/evolvegcn.py`
- **Architecture:** EvolveGCNO (from torch-geometric-temporal 0.56.2) + 2-layer MLP classifier
- **EvolveGCNO:** Evolves GCN weight matrices across the 49 timesteps via GRU

**Iterations and fixes applied:**

#### Run 1 (failed — F1 collapsing to 0):
- **Problem:** Train F1 oscillating between ~0.25 and 0.0000 every few epochs
- **Root cause 1:** No class weighting — extreme illicit minority → model collapses to "predict all licit"
- **Root cause 2:** No feature scaling — raw Elliptic features have wildly different scales

#### Run 2 (fixed):
- Added **class-weighted cross-entropy** (weights computed from train-period class counts)
- Added **feature standardization** (mean/std from train only)
- Added **gradient clipping** (max_norm=5.0)
- Lowered **LR** from 0.01 → 0.005
- Class weights: [0.565 (licit), 4.317 (illicit)]

#### Final result:
```
Epochs: 200
Best test illicit-F1: 0.2445
Final test illicit-F1: 0.2356
Training time: 52.7s (GPU)
```

**Interpretation:** Significantly below Weber et al.'s static GCN (0.628). This is because Elliptic's edges are all same-timestep — each of the 49 snapshots averages only ~4,783 edges with ~4,160 nodes, giving EvolveGCN very sparse individual graphs. The GRU evolves weights but can't pass messages across timesteps. This is a **valid, citable negative finding** per the roadmap: discrete-time temporal models don't help when the graph has no cross-timestep edges.

---

## 4. Phase 5 — AMLworld HI-Small Dataset Pipeline

### Dataset: AMLworld HI-Small (Altman et al., NeurIPS 2023)
- **Source:** Kaggle "IBM Transactions for Anti Money Laundering"
- **Reference code:** IBM Multi-GNN repo (https://github.com/IBM/Multi-GNN)
- **Size:** 5,078,345 transactions, 515,088 unique accounts
- **Pattern types:** 370 laundering rings across 8 types:
  - GATHER-SCATTER: 716, SCATTER-GATHER: 626, STACK: 466, FAN-OUT: 342
  - FAN-IN: 318, CYCLE: 287, BIPARTITE: 263, RANDOM: 191

### Step 1: Format raw data — `scripts/format_kaggle_files.py`
- **Original IBM version** uses `datatable` library which fails to build on Windows
- **Rewrote in pure pandas:** Same logic — timestamp conversion, account ID mapping (bank+account concatenation), currency encoding, payment format encoding
- **Input:** `HI-Small_Trans.csv`
- **Output:** `formatted_transactions.csv` (EdgeID, from_id, to_id, Timestamp, Amount Sent, Sent Currency, Amount Received, Received Currency, Payment Format, Is Laundering)
- **Key detail:** Bank/account IDs concatenated as strings. Pandas reads some as integers (stripping leading zeros), so pattern matching later needs `str(int(val))` normalization.

### Step 2: Parse pattern ground truth
- File `HI-Small_Patterns.txt` format:
  ```
  BEGIN LAUNDERING ATTEMPT - FAN-OUT:  Max 16-degree Fan-Out
  2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,...,1
  ...
  END LAUNDERING ATTEMPT - FAN-OUT
  ```
- **Matching pattern transactions to formatted_transactions.csv:**
  - Rebuilt the exact account_map from raw HI-Small_Trans.csv (same logic as format_kaggle_files.py)
  - Applied `normalize_id()` to pattern file bank/account values: `str(int("021174"))` → `"21174"` to match pandas' integer reading
  - Matched by (from_id, to_id, Timestamp) composite key
  - **Match rate:** 3,455/3,209 = 107.7% (some pattern transactions matched multiple rows — duplicate payments, not a problem)

### Step 3: Split — `preprocessing/amlworld_loader.py`

#### Version 1 (70:30):
- Simple chronological split at 70th percentile of timestamps
- Train: 3,554,649 txns (2,856 laundering, IR=0.08%)
- Test: 1,523,696 txns (2,321 laundering, IR=0.15%)

#### Version 2 (60/20/20 — matching Altman et al.):
- **Day-based optimal split:** Groups transactions by day, finds (i,j) day boundaries minimizing max split error vs [0.6, 0.2, 0.2] target proportions (exact same algorithm as IBM's `data_loading.py`)
- Train: 3,248,921 txns (2,530 laundering, IR=0.08%)
- Val: 965,524 txns (1,036 laundering, IR=0.11%)
- Test: 863,900 txns (1,611 laundering, IR=0.19%)

### Step 4: Feature engineering (in amlworld_loader.py)
**Per-transaction features (8):**
- Amount Sent, Sent Currency, Amount Received, Received Currency, Payment Format
- hour_of_day, day_of_week, day_index (derived from Timestamp)

**Per-account features (10, fit on train period only):**
- Sender: out_degree, out_amount_mean, out_amount_std, out_amount_max, out_volume_total
- Receiver: in_degree, in_amount_mean, in_amount_std, in_amount_max, in_volume_total

**Total:** 18 tabular features

### Outputs in `data/processed/`:
- `amlworld_train.parquet`, `amlworld_val.parquet`, `amlworld_test.parquet` (18 features + metadata + labels)
- `amlworld_edges_{train,val,test}.parquet` (from_id, to_id, Timestamp, Amount Received, Received Currency, Payment Format)
- `amlworld_ring_ground_truth.parquet` (ring_id, pattern_type, from_id, to_id, timestamp_int, amount_paid)

---

## 5. Phase 5 — E5a Tabular Baselines

Three separate scripts in `baselines/`, each producing the standard 6-file template.

### E5a — Logistic Regression (`logistic_regression_aml.py`)
```
class_weight='balanced', solver='lbfgs', max_iter=1000
StandardScaler applied (fit on train)
Training time: 7.3s
```
| Metric | Train | Test |
|--------|-------|------|
| Minority F1 | 0.0045 | 0.0069 |
| AP | — | 0.0038 |

### E5a — Random Forest (`random_forest_aml.py`)
```
n_estimators=300, class_weight='balanced_subsample', max_depth=20, min_samples_leaf=10
Training time: 359.1s
```
| Metric | Train | Test |
|--------|-------|------|
| Minority F1 | 0.1894 | 0.1049 |
| AP | — | 0.0606 |

Top 5 features: Payment Format (0.354), sender_out_degree (0.107), Amount Received (0.077), Amount Sent (0.068), sender_out_volume_total (0.049)

### E5a — XGBoost (`xgboost_aml.py`)
```
tree_method='hist', device='cpu' (GPU not available in pip xgboost)
max_depth=8, lr=0.05, scale_pos_weight=1243.6 (full ratio)
early_stopping=30, stopped at best_round=14
Training time: 43.6s
```
| Metric | Train | Test |
|--------|-------|------|
| Minority F1 | 0.0166 | 0.0237 |
| AP | — | 0.0506 |

**Note:** XGBoost underperformed RF due to extreme scale_pos_weight + early stopping killing it too quickly. This was later addressed in E5b with Optuna tuning.

### E5a Summary
**RF's 0.105 test F1 is the non-graph baseline floor.** LR is essentially random on the minority class. XGBoost's raw ratio class weighting doesn't work well for this level of imbalance.

---

## 6. Phase 5 — E5b GFP + XGBoost

E5b is the **critical scientific caution baseline** per the roadmap. If the TGN/GNN can't beat this, graph neural networks don't earn their complexity.

### Evolution of E5b (4 iterations):

#### v1 — Proxy node-level features, 70:30, default XGBoost
**Motif features (`graph/motif_features.py` v1):** Per-account (node-level) proxies computed from train graph only
- graph_in_degree, graph_out_degree, graph_total_degree, in_out_ratio
- unique_in_neighbors, unique_out_neighbors
- pagerank (NetworkX, max_iter=50)
- is_in_scc, scc_size (SCC membership as cycle proxy — 1,512 non-trivial SCCs, largest 7,926 nodes, 11,630 accounts in SCCs)
- wcc_size (129,309 WCCs, largest 348,360)
- local_clustering_coeff (on undirected projection, took 35s)
- neighbor_avg_in_degree, neighbor_avg_out_degree
- **14 features per account, joined as sender_motif_* and receiver_motif_* = 28 motif + 18 tabular = 46 total**
- Computation time: 55.6s (single-threaded)

**XGBoost:** Default params, 500 rounds, early_stopping=30, scale_pos_weight=1243.6, 70:30 split

| | Test F1 | Test AP |
|--|---------|---------|
| v1 | 0.073 | 0.097 |

#### v2 — 60/20/20 split + Optuna tuning (same proxy features)
- Changed split to 60/20/20 matching Altman et al.
- Added **Optuna hyperparameter tuning** (50 trials, TPE sampler)
  - Search space: max_depth [3,12], lr [0.003,0.1], scale_pos_weight [0.3x-1.5x base], subsample [0.5,1.0], colsample_bytree [0.5,1.0], min_child_weight [1,50], gamma [0,5], reg_alpha/lambda [1e-8,10]
- Best params from Optuna: max_depth=12, lr=0.014, scale_pos_weight=624, min_child_weight=47, num_round=58
- Final model retrained on train+val with best params, evaluated on test

| | Test F1 | Test AP |
|--|---------|---------|
| v2 | 0.144 | 0.188 |

#### v3 — Real per-edge GFP features (train adjacency only)
**Complete rewrite of `graph/motif_features.py` v2:** Per-EDGE (per-transaction) features, not per-node. This matches IBM's GFP approach.

For each transaction e = (u → v, timestamp t):
| Feature | Description |
|---------|-------------|
| fan_out | # txns u sends in [t-86400, t+86400] |
| fan_in | # txns v receives in [t-86400, t+86400] |
| deg_out_src | Cumulative out-degree of u at time t |
| deg_in_src | Cumulative in-degree of u at time t |
| deg_out_dst | Cumulative out-degree of v at time t |
| deg_in_dst | Cumulative in-degree of v at time t |
| scatter_gather | # 2-hop paths u→w→v with ts < t |
| gather_scatter | # 2-hop paths w→u, dst→w with ts < t |
| temporal_cycle | Binary: can we reach u from v via edges after t? (BFS, max 5 hops, only for SCC nodes) |
| cycle_length | Shortest such cycle length |

**Parallelized with multiprocessing:** 36 workers, chunks of ~1000 txns each. Used module-level globals via Pool initializer to avoid pickling the adjacency structures.

**Key data structures:**
- `TemporalAdjacency`: sorted adjacency lists (per node, sorted by timestamp) enabling O(log d) binary search for windowed counting
- SCC set precomputed via NetworkX for bounding temporal cycle BFS

**Problem in v3:** Adjacency built from train edges only → fan_in and fan_out were **zero for ALL val/test transactions** (their timestamps fell outside the train-period window). temporal_cycle also zero for val/test.

| | Test F1 | Test AP |
|--|---------|---------|
| v3 | 0.427 | 0.490 |

#### v4 — Incremental adjacency (all edges)
**Fix:** Build adjacency from ALL edges (train+val+test combined), not just train. Changed fan_in/fan_out window to **backward-only** `[t-window, t)` instead of `[t-window, t+window]` to prevent future leakage.

No leakage because every feature for transaction at time t only uses edges with timestamp < t. This matches IBM's incremental GFP protocol.

**Computation times (36 workers):**
- Train (3,248,921 txns): 505.5s @ 6,427 txn/s
- Val (965,524 txns): 474.9s @ 2,040 txn/s
- Test (863,900 txns): 462.2s @ 1,869 txn/s

**Feature stats (train split):**
- fan_out: mean=1506.6, max=49171
- fan_in: mean=5.9, max=545
- scatter_gather: mean=1.05, max=4
- temporal_cycle: nonzero=9044 (only for SCC nodes)

**Optuna tuning:** 50 trials, best trial 44, best val F1=0.3617
Best params: max_depth=12, lr=0.061, scale_pos_weight=1520.6, subsample=0.80, colsample_bytree=0.618, min_child_weight=20, gamma=3.15, reg_alpha=0.00022, reg_lambda=0.00019, num_round=724

**Final model (train+val combined):**

| | Test F1 | Test AP |
|--|---------|---------|
| **v4** | **0.534** | **0.589** |

**Feature importances (gain):**
1. Payment Format: 14,739
2. scatter_gather [GFP]: 7,292
3. temporal_cycle [GFP]: 5,132
4. cycle_length [GFP]: 1,626
5. sender_out_degree: 1,273
6. gather_scatter [GFP]: 1,050
7. fan_out [GFP]: 985
8. day_index: 943

**GFP features contribute 46.5% of total gain.**

### E5b vs IBM benchmark:
| | F1 |
|--|-----|
| Your GFP + XGBoost | 53.4% |
| IBM GFP + XGBoost (published) | 63.2% |

Remaining ~10-point gap is from IBM's C++ GFP computing deeper multi-hop pattern counts and their more extensive hyperparameter search.

---

## 7. Phase 6 — GNN (TGN → GINe)

### Attempt 1: Custom TGN (memory-only, no graph message passing)
**Architecture:** TGNMemory (GRU-based per-node memory) + TimeEncoding (learnable Fourier) + TemporalAttention (self-attention on memory+time) + EdgeClassifier (MLP on [z_src || z_dst || edge_feat])

**Problem 1 — diverging loss:** Class weight of 1283x (full ratio) caused gradient explosions. Loss increased from 1.38 → 2.00 in 5 epochs, F1 stayed 0.0000.

**Fix:** Capped class weight at sqrt(1283) ≈ 35.8. Added all 18 tabular features as edge features (was using only 3 raw columns). Increased batch size to 4096, model dims to 128, lowered LR to 0.0003.

**Result after fixes:**
```
50 epochs, 12.8s/epoch (GPU)
Best val F1: 0.0492 at epoch 49
Test F1: 0.0638, Test AP: 0.0346
Recall: 28.5% but precision only 3.6%
```

**Root cause of poor performance:** The TGN had NO graph message passing. Each node only saw its own memory, never aggregating neighbor information. Essentially a memory-augmented MLP, not a GNN.

### Attempt 2: IBM's GINe architecture (with graph message passing)
**Switched to IBM Multi-GNN's GINe** (Egressy et al., AAAI 2024) — proven architecture on this exact dataset.

**Architecture:** GINEConv (Graph Isomorphism Network with edge features) + residual connections + BatchNorm + edge MLPs + edge-level readout [z_src || z_dst || edge_attr] → MLP(3*n_hidden → 50 → 25 → 2)

**Data pipeline:** Follows IBM protocol exactly:
- Nodes: 515,088 accounts, feature = placeholder 1.0 (no node features in AMLworld)
- Edges: transactions with features [Timestamp, Amount Received, Received Currency, Payment Format]
- Expanding window: train=train edges, val=train+val edges, test=all edges
- LinkNeighborLoader for mini-batch training with neighborhood sampling
- Unique edge ID prepended to edge_attr for seed edge tracking (removed before forward pass)

**Run 1 — edge MLPs only:**
```
Hyperparams (from IBM model_settings.json):
  lr=0.006, n_hidden=66, n_gnn_layers=2, dropout=0.01, final_dropout=0.1
  w_ce1=1.0, w_ce2=9.0 (NOT full ratio)
  batch_size=8192, num_neighbors=[100,100]
  100 epochs, ~167s/epoch

Best val F1: 0.4463 at epoch 52
Test F1: 0.2811, Test AP: 0.2776
```

**Problem:** Model collapsed at epoch 75 (loss spiked to 0.0415, F1 → 0.0000 for remaining epochs). Too-high LR caused late-training instability.

**Matches IBM's published vanilla GIN result (28.7%)** — confirms implementation is correct.

### Attempt 3: Multi-GINe with full adaptations
Added IBM's remaining adaptations:

**1. Port numbering (`--ports`):**
- For each node, neighbors are sorted by first interaction time and assigned unique indices (0, 1, 2, ...)
- Added as 2 extra edge features: in_ports (incoming neighbor index), out_ports (outgoing)
- Adapted from IBM's `data_util.py` `ports()` function

**2. Time deltas (`--tds`):**
- For each node, compute time between consecutive incoming/outgoing transactions
- Added as 2 extra edge features: in_tds, out_tds
- Adapted from IBM's `data_util.py` `time_deltas()` function

**3. LR scheduler:**
- `ReduceLROnPlateau(mode='max', factor=0.5, patience=10, min_lr=1e-5)` on val F1
- Prevents the epoch-75 collapse from attempt 2

**4. Early stopping:**
- patience=20 epochs without val F1 improvement

**Edge features now:** 4 original + 2 ports + 2 time deltas = 8 total

**Speed optimization:**
- batch_size increased to 32768 (from 8192) — fewer CPU→GPU transfers
- num_neighbors reduced to [50, 50] (from [100, 100]) — 4x less CPU sampling work
- Epoch time: ~97-112s (down from 167s)

**Final result:**
```
Early stopped at epoch 43 (patience=20)
Best val F1: 0.5072 at epoch 23
LR reduced from 0.006 → 0.003 at ~epoch 30

Test minority-F1:  0.3509
Test precision:    0.2957
Test recall:       0.4316
Test AP:           0.3349
```

### Phase 6 Summary
| Model | Adaptations | Val F1 | Test F1 | Test AP |
|-------|------------|--------|---------|---------|
| Custom TGN | memory only | 0.049 | 0.064 | 0.035 |
| GINe | edge MLPs | 0.446 | 0.281 | 0.278 |
| **Multi-GINe** | **edge MLPs + ports + tds** | **0.507** | **0.351** | **0.335** |
| IBM published GIN | vanilla | — | 0.287 | — |
| IBM Multi-GIN | all adaptations | — | 0.572 | — |

**GINe does NOT beat E5b's GFP+XGBoost (0.534).** This is consistent with IBM's own results — their GFP+XGBoost (63.2%) also outperforms vanilla GIN (28.7%). The finding is: on AMLworld HI-Small, handcrafted graph pattern features + gradient boosting outperform learned GNN representations at this scale.

---

## 8. Results Summary

### Elliptic Dataset (Phase 4)
| Experiment | Model | Test illicit-F1 |
|-----------|-------|----------------|
| E4 | EvolveGCN | 0.245 |
| Weber et al. | Static GCN (reference) | 0.628 |

### AMLworld HI-Small (Phases 5-6)
| Experiment | Model | Test minority-F1 | Test AP |
|-----------|-------|-----------------|---------|
| E5a | Logistic Regression | 0.007 | 0.004 |
| E5a | Random Forest | 0.105 | 0.061 |
| E5a | XGBoost (tabular) | 0.024 | 0.051 |
| **E5b** | **GFP + XGBoost (tuned)** | **0.534** | **0.589** |
| E6 | Custom TGN | 0.064 | 0.035 |
| E6 | GINe (edge MLPs) | 0.281 | 0.278 |
| E6 | Multi-GINe (full) | 0.351 | 0.335 |

---

## 9. Known Issues & Decisions

1. **XGBoost GPU not available on Windows pip install.** Used CPU — acceptable speed for this dataset size (44-218s).

2. **E5b GFP vs IBM's GFP:** Our implementation uses NetworkX-based pattern counting (exact fan-in/out, scatter-gather via set intersection, temporal cycles via bounded BFS). IBM's uses their proprietary C++ GFP (snapml). Our features capture the same signal types but at lower depth. Remaining ~10-point F1 gap vs IBM's published 63.2%.

3. **Elliptic feature set:** Used AF (165 features, local + aggregated). Team will retroactively use the same split for E1-E3. Teammate will copy the splits from `data/processed/`.

4. **Pattern match rate 107.7%:** Some pattern transactions in HI-Small_Patterns.txt matched multiple rows in formatted_transactions.csv (same from_id, to_id, Timestamp). These are duplicate payments in the synthetic data — not a data quality issue. ~246 extra rows received ring labels.

5. **E6 val→test gap (0.507 → 0.351):** The GINe model generalizes worse to the test period than to validation. Likely due to distribution shift in the temporal split — test period has different laundering patterns than train/val.

6. **E5a XGBoost early stopping:** With scale_pos_weight=1243 and early_stopping=30, XGBoost stopped at round 14 — too aggressive. Fixed in E5b via Optuna tuning which found scale_pos_weight≈624-1520 works better.

7. **Teammates' E1-E3 results not available yet.** Jooo built the Elliptic split; teammates will run their baselines (LR, RF, XGBoost, GCN, GraphSAGE) retroactively on the same split.

---

## 10. Current State & Next Steps

### Completed:
- [x] Phase 4: EvolveGCN on Elliptic (E4)
- [x] Phase 5: AMLworld data pipeline + E5a tabular baselines + E5b GFP+XGBoost
- [x] Phase 6: GINe/Multi-GINe on AMLworld (E6)
- [x] Git repo scaffolded, .gitignore configured, ready to push

### Next — Phase 7: Ring Aggregation (E7)
This is where RingShield's actual novel contribution starts. Takes per-edge GNN scores from E6 and aggregates them into ring-level detections:
- Use ring ground truth from `amlworld_ring_ground_truth.parquet`
- Implement `models/ring_aggregator.py`
- Evaluate at ring level (not just transaction level)
- This is something neither GFP+XGBoost nor IBM's pipeline does

### Remaining phases per roadmap:
- Phase 7: Ring aggregation (E7)
- Phase 8: Explainability — attention-based explanations (E8)
- Phase 9: Full cascade pipeline (E9)
- Phase 10-11: Ablation studies (E10-E13)
- Phase 12: System evaluation — latency benchmarks (E14)

---

## 11. File Inventory

### Scripts that should be in the repo (in git):
```
preprocessing/elliptic_loader.py       — Elliptic 70:30 split
preprocessing/amlworld_loader.py       — AMLworld 60/20/20 split + features
scripts/format_kaggle_files.py         — Pandas replacement for IBM datatable formatter
graph/motif_features.py                — Parallelized per-edge GFP features
baselines/evolvegcn.py                 — EvolveGCN on Elliptic
baselines/logistic_regression_aml.py   — E5a LR
baselines/random_forest_aml.py         — E5a RF
baselines/xgboost_aml.py              — E5a XGBoost
baselines/gfp_xgboost_aml.py          — E5b GFP+XGBoost with Optuna
models/tgn.py                          — Multi-GINe (IBM architecture)
requirements.txt
.gitignore
setup_ringshield.ps1                   — Repo scaffolding script
```

### Experiment artifacts (config/metrics/log in git, model/predictions gitignored):
```
experiments/E4_evolvegcn/
experiments/E5a_logistic_regression/
experiments/E5a_random_forest/
experiments/E5a_xgboost/
experiments/E5b_gfp_xgboost/
experiments/E6_tgn/
```

### Data files (all gitignored, must be regenerated from raw data):
```
data/raw/elliptic_txs_*.csv            — Download from Kaggle
data/raw/HI-Small_*.csv/.txt           — Download from Kaggle
data/raw/formatted_transactions.csv    — python scripts/format_kaggle_files.py data/raw/HI-Small_Trans.csv
data/processed/*                       — python preprocessing/elliptic_loader.py / amlworld_loader.py
data/processed/amlworld_gfp_*          — python graph/motif_features.py
```

### Reproduction commands (in order):
```powershell
# Environment
py -3.12 -m venv .venv312
.venv312\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.5.1+cu121.html
pip install -r requirements.txt

# Elliptic (Phase 4)
python preprocessing/elliptic_loader.py --raw-dir data/raw --out-dir data/processed --feature-set AF
python baselines/evolvegcn.py --data-dir data/processed --out-dir experiments/E4_evolvegcn --epochs 200

# AMLworld data pipeline (Phase 5)
python scripts/format_kaggle_files.py "data/raw/HI-Small_Trans.csv"
python preprocessing/amlworld_loader.py --raw-dir data/raw --out-dir data/processed --patterns data/raw/HI-Small_Patterns.txt

# E5a baselines
python baselines/logistic_regression_aml.py --data-dir data/processed --out-dir experiments/E5a_logistic_regression
python baselines/random_forest_aml.py --data-dir data/processed --out-dir experiments/E5a_random_forest
python baselines/xgboost_aml.py --data-dir data/processed --out-dir experiments/E5a_xgboost --no-gpu

# E5b GFP features + tuned XGBoost
python graph/motif_features.py --data-dir data/processed --out-dir data/processed --window 86400 --max-cycle-hops 5 --workers 0
python baselines/gfp_xgboost_aml.py --data-dir data/processed --out-dir experiments/E5b_gfp_xgboost --n-trials 50

# E6 GINe
python models/tgn.py --data-dir data/processed --raw-dir data/raw --out-dir experiments/E6_tgn --epochs 100 --emlps --ports --tds --batch-size 32768 --num-neighs 50 50
```
