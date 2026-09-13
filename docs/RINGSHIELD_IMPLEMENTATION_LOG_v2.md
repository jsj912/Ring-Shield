# RingShield — Full Implementation Log (v2)

**Project:** RingShield — Multi-tenant fraud ring detection SaaS using Temporal GNNs  
**Author:** Jooo (Joan Sara Joe)  
**Date range:** September 2026  
**Phases covered:** Phase 4 (EvolveGCN on Elliptic) → Phase 5 (AMLworld baselines) → Phase 6 (GINe + GATv2 GNN)  
**Roadmap doc:** `RingShield_Implementation_Roadmap__1_.md`

---

## Table of Contents

1. [Environment Setup](#1-environment-setup)
2. [Repository Structure](#2-repository-structure)
3. [Phase 4 — EvolveGCN on Elliptic](#3-phase-4--evolvegcn-on-elliptic)
4. [Phase 5 — AMLworld HI-Small Dataset Pipeline](#4-phase-5--amlworld-hi-small-dataset-pipeline)
5. [Phase 5 — E5a Tabular Baselines](#5-phase-5--e5a-tabular-baselines)
6. [Phase 5 — E5b GFP + XGBoost (Scientific Caution Baseline)](#6-phase-5--e5b-gfp--xgboost)
7. [Phase 6 — GNN: TGN → GINe → Multi-GINe → Multi-GATv2](#7-phase-6--gnn)
8. [Architecture Decision: Unified GATv2 Backbone](#8-architecture-decision)
9. [Results Summary](#9-results-summary)
10. [Known Issues & Decisions](#10-known-issues--decisions)
11. [Current State & Next Steps](#11-current-state--next-steps)
12. [File Inventory & Reproduction Commands](#12-file-inventory--reproduction-commands)

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
6. **IBM snapml GFP:** Not available on Windows or Python 3.12. **Fix:** Wrote custom GFP implementation using NetworkX + multiprocessing (36 cores)
7. **PyG BaseTransform breaking change:** `__call__` renamed to `forward` in newer PyG. **Fix:** Renamed method in AddEgoIds transform
8. **torch.fx tracing failure with GATv2:** `to_hetero()` uses symbolic tracing which can't handle `if return_attention:` branches. **Fix:** Moved attention extraction to separate `forward_with_attention()` method

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
│   │   ├── elliptic_{train,test}.parquet
│   │   ├── edges_{train,test}.parquet
│   │   ├── amlworld_{train,val,test}.parquet     # 60/20/20 split
│   │   ├── amlworld_edges_{train,val,test}.parquet
│   │   ├── amlworld_ring_ground_truth.parquet
│   │   ├── amlworld_motif_features.parquet       # v1 per-node proxies (legacy)
│   │   └── amlworld_gfp_features_{train,val,test}.parquet  # v2 per-edge real GFP
│   └── SPLIT_MANIFEST.md
├── preprocessing/
│   ├── elliptic_loader.py             # Elliptic time-based 70:30 split
│   ├── amlworld_loader.py            # AMLworld 60/20/20 split + feature eng
│   └── shared_utils.py
├── graph/
│   ├── motif_features.py             # GFP per-edge feature computation (parallelized, 36 cores)
│   ├── build_elliptic_graph.py
│   └── build_amlworld_graph.py
├── baselines/
│   ├── evolvegcn.py                  # Phase 4: EvolveGCN on Elliptic
│   ├── logistic_regression_aml.py    # E5a: LR on AMLworld
│   ├── random_forest_aml.py          # E5a: RF on AMLworld
│   ├── xgboost_aml.py               # E5a: XGBoost on AMLworld
│   └── gfp_xgboost_aml.py           # E5b: GFP + XGBoost (Optuna tuned)
├── models/
│   ├── tgn.py                        # Phase 6: Multi-GINe v2 (best performance: 0.599 F1)
│   └── gatv2.py                      # Phase 6: Multi-GATv2 (unified backbone: 0.551 F1 + attention)
├── scripts/
│   └── format_kaggle_files.py        # Pandas replacement for IBM's datatable version
├── experiments/
│   ├── E4_evolvegcn/                 # Standard 6-file template each
│   ├── E5a_logistic_regression/
│   ├── E5a_random_forest/
│   ├── E5a_xgboost/
│   ├── E5b_gfp_xgboost/
│   ├── E6_tgn/                       # Multi-GINe v2 results (3 seeds)
│   └── E6_gatv2/                     # Multi-GATv2 results (3 seeds) — unified backbone
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

Multi-seed experiments (E6_tgn, E6_gatv2) also have per-seed files:
```
model_best_seed{N}.pt, predictions_seed{N}.csv, training_log_seed{N}.csv
```

### .gitignore
```
data/raw/
data/processed/
*.pkl
*.pt
*.pth
experiments/*/model.json
experiments/*/model_best_*.pt
experiments/*/predictions*.csv
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
- **Labels:** 1=illicit, 0=licit, -1=unknown
- **Feature standardization:** Mean/std computed on train only, applied to all

**Key discovery:** All 234,355 edges in Elliptic are same-timestep (no cross-timestep edges). Each of the 49 snapshots is structurally isolated.

### Model: `baselines/evolvegcn.py`
- **Architecture:** EvolveGCNO (torch-geometric-temporal 0.56.2) + 2-layer MLP classifier

**Iterations:**

| Run | Issue | Fix |
|-----|-------|-----|
| 1 | F1 collapsing to 0.0000 (model predicts all licit) | Added class-weighted CE, feature standardization, gradient clipping (max_norm=5.0), lowered LR 0.01→0.005 |
| 2 | Stable but F1 still low | Class weights [0.565, 4.317], 200 epochs |

**Final result:** Best test illicit-F1 = **0.2445** (vs Weber et al.'s static GCN: 0.628)

**Interpretation:** Valid citable negative finding — discrete-time temporal models don't help when the graph has no cross-timestep edges. Each snapshot averages only ~4,783 edges.

---

## 4. Phase 5 — AMLworld HI-Small Dataset Pipeline

### Dataset: AMLworld HI-Small (Altman et al., NeurIPS 2023)
- **Source:** Kaggle "IBM Transactions for Anti Money Laundering"
- **Reference code:** IBM Multi-GNN repo (https://github.com/IBM/Multi-GNN)
- **Size:** 5,078,345 transactions, 515,088 unique accounts
- **Pattern types:** 370 laundering rings across 8 types: GATHER-SCATTER (716), SCATTER-GATHER (626), STACK (466), FAN-OUT (342), FAN-IN (318), CYCLE (287), BIPARTITE (263), RANDOM (191)

### Step 1: Format raw data — `scripts/format_kaggle_files.py`
- IBM's version uses `datatable` (fails on Windows) — rewrote in pure pandas
- Same logic: timestamp conversion, account ID mapping (bank+account concatenation), currency/format encoding
- Input: `HI-Small_Trans.csv` → Output: `formatted_transactions.csv`
- **Key detail:** Pandas reads some bank IDs as integers (strips leading zeros). Pattern matching later needs `str(int(val))` normalization.

### Step 2: Parse pattern ground truth
- Parsed `HI-Small_Patterns.txt` (BEGIN/END blocks per ring)
- Rebuilt account_map from raw CSV for matching
- Matched by (from_id, to_id, Timestamp) composite key
- **Match rate:** 3,455/3,209 = 107.7% (some duplicate payments matched multiple rows)

### Step 3: Split — `preprocessing/amlworld_loader.py`
- **Version 1 (70:30):** Simple chronological split — later abandoned
- **Version 2 (60/20/20 matching Altman et al.):** Day-based optimal split using IBM's exact algorithm (minimize max split error vs [0.6, 0.2, 0.2])
  - Train: 3,248,921 txns (2,530 laundering, IR=0.08%)
  - Val: 965,524 txns (1,036 laundering, IR=0.11%)
  - Test: 863,900 txns (1,611 laundering, IR=0.19%)

### Step 4: Feature engineering
**Per-transaction features (8):** Amount Sent, Sent Currency, Amount Received, Received Currency, Payment Format, hour_of_day, day_of_week, day_index

**Per-account features (10, fit on train only):** sender out_degree/amount_mean/std/max/volume_total, receiver in_degree/amount_mean/std/max/volume_total

**Total:** 18 tabular features

---

## 5. Phase 5 — E5a Tabular Baselines

### E5a — Logistic Regression
- class_weight='balanced', solver='lbfgs', max_iter=1000, StandardScaler
- Training: 7.3s | **Test F1: 0.0069** | Test AP: 0.0038

### E5a — Random Forest
- n_estimators=300, class_weight='balanced_subsample', max_depth=20, min_samples_leaf=10
- Training: 359s | **Test F1: 0.1049** | Test AP: 0.0606
- Top features: Payment Format (0.354), sender_out_degree (0.107), Amount Received (0.077)

### E5a — XGBoost
- tree_method='hist', device='cpu', max_depth=8, lr=0.05, scale_pos_weight=1243.6
- Early stopped at round 14 | Training: 44s | **Test F1: 0.0237** | Test AP: 0.0506
- XGBoost underperformed RF due to extreme scale_pos_weight + premature early stopping

**E5a Summary:** RF's 0.105 is the non-graph baseline floor.

---

## 6. Phase 5 — E5b GFP + XGBoost

E5b is the **critical scientific caution baseline** — if GNNs can't beat this, they don't earn their complexity.

### Evolution across 4 iterations:

| Version | What changed | Test F1 | Test AP |
|---------|-------------|---------|---------|
| v1 | Per-node proxy features (14 motif), 70/30 split, default XGBoost | 0.073 | 0.097 |
| v2 | + 60/20/20 split + Optuna tuning (50 trials) | 0.144 | 0.188 |
| v3 | + Real per-edge GFP features (10 features per transaction) | 0.427 | 0.490 |
| **v4** | **+ Incremental adjacency (all edges, backward-only window)** | **0.534** | **0.589** |

### v1 → v2 changes (2x improvement):
- Split changed from 70/30 to 60/20/20 (matching Altman et al.)
- Added Optuna hyperparameter tuning: 50 trials, TPE sampler
- Search space: max_depth [3,12], lr [0.003,0.1], scale_pos_weight [0.3x-1.5x base], subsample, colsample, min_child_weight, gamma, reg_alpha, reg_lambda
- Best: max_depth=12, lr=0.014, scale_pos_weight=624, min_child_weight=47

### v2 → v3 changes (3x improvement):
**Complete rewrite of `graph/motif_features.py`** — per-EDGE features instead of per-node proxies:

| Feature | Description |
|---------|-------------|
| fan_out | # txns sender sends in [t-86400, t) |
| fan_in | # txns receiver gets in [t-86400, t) |
| deg_out_src/in_src | Cumulative degree of sender at time t |
| deg_out_dst/in_dst | Cumulative degree of receiver at time t |
| scatter_gather | # 2-hop paths src→w→dst with ts < t |
| gather_scatter | # 2-hop paths w→src, dst→w with ts < t |
| temporal_cycle | BFS from dst back to src via edges after t (max 5 hops, SCC nodes only) |
| cycle_length | Shortest such cycle length |

**Parallelized:** multiprocessing.Pool with 36 workers, adjacency structures passed via initializer globals. ~6,400 txn/s on train split.

### v3 → v4 changes (fixed zero fan_in/fan_out on test):
- **Problem:** Adjacency built from train edges only → fan_in/fan_out were ZERO for all val/test transactions
- **Fix:** Build adjacency from ALL edges (train+val+test), use backward-only window [t-Δ, t) — no leakage since each transaction only sees edges before its timestamp
- Fan_out went from zero to mean=1506.6 on train, actually computing for test now

### Final E5b v4 results:
- Optuna: 50 trials, best trial 44, best val F1=0.3617
- Best params: max_depth=12, lr=0.061, scale_pos_weight=1520.6, num_round=724
- **Test F1: 0.534, Test AP: 0.589**
- **GFP features contribute 46.5% of total gain**
- Top GFP features: scatter_gather (7,292 gain), temporal_cycle (5,132), cycle_length (1,626)

### E5b vs IBM benchmark:
| Model | F1 |
|-------|-----|
| Your GFP+XGBoost | 53.4% |
| IBM GFP+XGBoost (published) | 63.2% |
| Gap | ~10 points (IBM uses deeper multi-hop pattern counting via C++ GFP) |

---

## 7. Phase 6 — GNN: TGN → GINe → Multi-GINe → Multi-GATv2

Phase 6 went through 5 major iterations to find the right architecture.

### Attempt 1: Custom TGN (memory-only, no graph message passing)
- Architecture: TGNMemory (GRU) + TimeEncoding (Fourier) + TemporalAttention + EdgeClassifier MLP
- **Problem 1:** Class weight 1283x → gradient explosion, loss diverging
- **Fix:** Capped weight at sqrt(1283)≈35.8, added all 18 tabular features as edge features, batch_size 4096, model dims 128
- **Result:** Test F1 = 0.064, AP = 0.035
- **Root cause:** No graph message passing — each node only saw its own memory. Essentially a memory-augmented MLP, not a GNN.

### Attempt 2: GINe (IBM Multi-GNN architecture, edge MLPs only)
- Switched to IBM's proven GINe with GINEConv + residual + BatchNorm + edge readout
- Uses LinkNeighborLoader for mini-batch training with neighborhood sampling
- IBM's hyperparameters: lr=0.006, n_hidden=66, n_gnn_layers=2, w_ce=[1.0, 9.0], batch_size=8192
- **Result:** Test F1 = 0.281, AP = 0.278
- Matches IBM's published vanilla GIN (28.7%) — confirms implementation is correct
- **Problem:** Collapsed at epoch 75 (loss spiked, F1→0)

### Attempt 3: Multi-GINe v1 (+ ports + time deltas + LR scheduler + early stopping)
- Added port numbering (2 extra edge features: in/out ports)
- Added time deltas (2 extra edge features: in/out tds)
- Added ReduceLROnPlateau (factor=0.5, patience=10) + early stopping (patience=20)
- Speed optimization: batch_size 32768, num_neighbors [50,50]
- **Result:** Test F1 = 0.351, AP = 0.335
- Still doesn't beat E5b's 0.534

### Attempt 4: Multi-GINe v2 (+ reverse MP + ego IDs + GFP edge features + threshold tuning + multi-seed)
**The breakthrough run.** Added all remaining adaptations:

| Adaptation | What it does | Impact |
|-----------|-------------|--------|
| Reverse MP (--reverse-mp) | HeteroData with 'to'/'rev_to' edge types, model gets separate weights per direction | Major — bidirectional money flow |
| Ego IDs (--ego) | Binary node flag marking seed edge endpoints in each mini-batch | Major — enables cycle detection (Egressy core result) |
| GFP features (--gfp) | Per-edge GFP features from motif_features.py fed as additional edge features (log1p transformed) | Moderate — 46% of XGBoost gain came from these |
| Threshold tuning | Sweep 0.05-0.95 on val, pick best F1 threshold | Critical — thresholds ranged 0.46-0.71 across seeds |
| Multi-seed (--seeds 1 42 123) | 3 seeds, reports mean ± std | Removes variance noise |
| num_neighbors [100,100] | Full neighborhood sampling restored | Captures hub accounts |

**Multi-GINe v2 Results (3 seeds):**

| Seed | Test F1 | Test AP | Threshold |
|------|---------|---------|-----------|
| 1 | 0.608 | 0.588 | 0.46 |
| 42 | 0.586 | 0.653 | 0.65 |
| 123 | 0.603 | 0.567 | 0.71 |
| **Mean** | **0.599 ± 0.009** | **0.603 ± 0.037** | — |

**Beats E5b (0.534) ✅ and IBM Multi-GIN (0.572) ✅**

**Novel finding:** GNN + GFP combined approach (0.599) outperforms both standalone GFP+XGBoost (0.534) and IBM's standalone Multi-GIN (0.572).

### Attempt 5: Multi-GATv2 (attention-based variant for unified backbone)
**Motivation:** E8 (explainability) needs attention weights. GINEConv is sum-aggregation — no attention. Swapped to GATv2Conv which produces per-neighbor attention weights natively.

**Architecture:** Same as Multi-GINe v2 but:
- GINEConv → GATv2Conv (n_heads=4, n_hidden=64 divisible by heads)
- forward() is clean for torch.fx tracing (no if-branches)
- Separate forward_with_attention() method for E8 inference
- All same adaptations: reverse MP, ego IDs, ports, tds, GFP, threshold tuning

**torch.fx tracing issue:** `to_hetero()` couldn't handle `if return_attention:` in forward(). Fix: moved attention extraction to separate method.

**Multi-GATv2 Results (3 seeds):**

| Seed | Test F1 | Test AP | Threshold |
|------|---------|---------|-----------|
| 1 | 0.559 | 0.542 | 0.53 |
| 42 | 0.540 | 0.530 | 0.54 |
| 123 | 0.553 | 0.512 | 0.65 |
| **Mean** | **0.551 ± 0.008** | **0.528 ± 0.012** | — |

**Beats E5b (0.534) ✅** — close enough to GINe (5-point gap) to use as unified backbone.

---

## 8. Architecture Decision: Unified GATv2 Backbone

**Decision:** Use **Multi-GATv2 as the unified backbone** for all downstream phases (E7, E8, E9).

| Criterion | GINe | GATv2 | Winner |
|-----------|------|-------|--------|
| Test F1 | 0.599 | 0.551 | GINe |
| Beats E5b | ✅ | ✅ | Tie |
| Attention weights for E8 | ❌ | ✅ | **GATv2** |
| Unified narrative | ❌ (need 2 models) | ✅ (one model does everything) | **GATv2** |
| Reproducibility (std) | ±0.009 | ±0.008 | Tie |

**Rationale:** The project's core novelty is explainability + detection + drift learning in a unified architecture. Using one model for all phases is a stronger story than having the best score. The 5-point F1 gap (0.551 vs 0.599) is acknowledged in one sentence: *"A GINe variant achieves 0.599 F1 but lacks attention; we use GATv2 (0.551) as our unified backbone for native explainability."*

**Paper framing:** *"Our Multi-GATv2 achieves 0.551 F1 on HI-Small while providing native per-neighbor attention weights for explainable fraud detection — a unified architecture for detection, explanation, and ring aggregation."*

### How attention weights flow to E8:
```python
# During E8 inference, load saved GATv2 weights on the RAW (non-hetero) model:
model = GATv2e(...)
model.load_state_dict(torch.load("experiments/E6_gatv2/model.pkl"))
output = model.forward_with_attention(x, edge_index, edge_attr)
attention_per_layer = model.attention_weights
# attention_per_layer[i]["weights"] = per-neighbor attention scores for layer i
```

### Which checkpoint is used where:

| Phase | Checkpoint | Why |
|-------|-----------|-----|
| E7 (Ring Aggregation) | `E6_gatv2/model.pkl` | Per-edge scores → ring-level |
| E8 (Explainability) | `E6_gatv2/model.pkl` + `forward_with_attention()` | Native attention weights |
| E9 (Full Cascade) | `E6_gatv2/model.pkl` | Pipeline stage |
| E12 (Static vs temporal ablation) | Both `E6_tgn/` and `E6_gatv2/` | Comparison |

---

## 9. Results Summary

### Elliptic Dataset (Phase 4)
| Experiment | Model | Test illicit-F1 |
|-----------|-------|----------------|
| E4 | EvolveGCN | 0.245 |
| Weber et al. (reference) | Static GCN | 0.628 |

### AMLworld HI-Small (Phases 5-6) — All Experiments

| Experiment | Model | Test F1 | Test AP | Notes |
|-----------|-------|---------|---------|-------|
| E5a | Logistic Regression | 0.007 | 0.004 | — |
| E5a | Random Forest | 0.105 | 0.061 | Non-graph floor |
| E5a | XGBoost (tabular) | 0.024 | 0.051 | — |
| E5b v1 | GFP+XGB (proxy, 70/30) | 0.073 | 0.097 | — |
| E5b v2 | GFP+XGB (+60/20/20 +Optuna) | 0.144 | 0.188 | — |
| E5b v3 | GFP+XGB (+real per-edge GFP) | 0.427 | 0.490 | — |
| **E5b v4** | **GFP+XGB (+incremental adj)** | **0.534** | **0.589** | **Scientific caution baseline** |
| E6 | Custom TGN | 0.064 | 0.035 | Failed — no graph MP |
| E6 | GINe (edge MLPs) | 0.281 | 0.278 | Matches IBM GIN |
| E6 | Multi-GINe v1 (+ports +tds) | 0.351 | 0.335 | — |
| **E6** | **Multi-GINe v2 (all adaptations)** | **0.599±0.009** | **0.603±0.037** | **Best overall** |
| **E6** | **Multi-GATv2 (unified backbone)** | **0.551±0.008** | **0.528±0.012** | **Used for E7-E9** |

### vs IBM Published Benchmarks

| Model | F1 | Source |
|-------|-----|--------|
| IBM GIN | 28.7% | Egressy et al. |
| IBM GIN + Edge Updates | 47.7% | Egressy et al. |
| IBM Multi-GIN (all) | 57.2% | Egressy et al. |
| IBM GFP+XGBoost | 63.2% | Altman et al. |
| **Your Multi-GINe v2** | **59.9%** | This work |
| **Your Multi-GATv2** | **55.1%** | This work |
| **Your GFP+XGBoost** | **53.4%** | This work |

---

## 10. Known Issues & Decisions

1. **XGBoost GPU not available on Windows pip.** Used CPU — acceptable speed.
2. **GFP gap vs IBM (~10 points):** Custom NetworkX implementation vs IBM's C++ GFP (snapml). Same feature types, lower depth.
3. **Elliptic feature set:** AF (165 features). Teammates will reuse same split for E1-E3.
4. **Pattern match rate 107.7%:** Duplicate payments in synthetic data matched multiple rows. Not a quality issue.
5. **E6 val→test gap (GINe 0.507→0.351 in v1):** Fixed by threshold tuning in v2. Thresholds ranged 0.46-0.71.
6. **Epoch time bottleneck:** LinkNeighborLoader CPU sampling dominates (~80% of epoch time), not GPU compute. batch_size and num_neighbors are the main speed knobs.
7. **GATv2 vs GINe performance gap (5 points):** Accepted tradeoff for unified attention-based backbone. IBM's GAT also slightly underperforms GIN on this dataset.
8. **Teammates' E1-E3 results:** Not available yet. Jooo built the Elliptic split; teammates will run retroactively.

---

## 11. Current State & Next Steps

### Completed:
- [x] Phase 4: EvolveGCN on Elliptic (E4) — negative finding, valid
- [x] Phase 5: AMLworld pipeline + E5a tabular baselines + E5b GFP+XGBoost (0.534)
- [x] Phase 6: Multi-GINe v2 (0.599) + Multi-GATv2 (0.551) — both beat E5b
- [x] Architecture decision: GATv2 as unified backbone
- [x] Git repo scaffolded, .gitignore configured

### Next — Phase 7: Ring Aggregation (E7)
RingShield's **actual novel contribution** starts here:
- Takes per-edge GATv2 fraud probability scores
- Aggregates them into ring-level detections using `models/ring_aggregator.py`
- Uses ring ground truth from `amlworld_ring_ground_truth.parquet` (370 rings, 8 pattern types)
- Evaluates at ring level (not just transaction level)
- **This is something neither GFP+XGBoost nor IBM's pipeline does**

### Remaining phases:
- Phase 7: Ring aggregation (E7)
- Phase 8: Explainability — attention-based explanations from GATv2 (E8)
- Phase 9: Full cascade pipeline (E9)
- Phase 10-11: Ablation studies (E10-E13)
- Phase 12: System evaluation — latency benchmarks (E14)

### Key for E8 explainability:
GATv2's `forward_with_attention()` method extracts per-layer attention weights during inference. E8's `attention_explainer.py` reads these to generate per-transaction explanations: "flagged because X% attention went to transfers from account Y within Z hours."

---

## 12. File Inventory & Reproduction Commands

### Scripts in the repo:
```
preprocessing/elliptic_loader.py
preprocessing/amlworld_loader.py
scripts/format_kaggle_files.py
graph/motif_features.py              # Parallelized per-edge GFP (36 cores)
baselines/evolvegcn.py
baselines/logistic_regression_aml.py
baselines/random_forest_aml.py
baselines/xgboost_aml.py
baselines/gfp_xgboost_aml.py         # Optuna-tuned, per-edge GFP
models/tgn.py                         # Multi-GINe v2 (best perf)
models/gatv2.py                       # Multi-GATv2 (unified backbone)
requirements.txt
.gitignore
```

### Full reproduction (in order):
```powershell
# === Environment ===
py -3.12 -m venv .venv312
.venv312\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install torch-scatter torch-sparse -f https://data.pyg.org/whl/torch-2.5.1+cu121.html
pip install -r requirements.txt
pip install optuna

# === Phase 4: Elliptic ===
python preprocessing/elliptic_loader.py --raw-dir data/raw --out-dir data/processed --feature-set AF
python baselines/evolvegcn.py --data-dir data/processed --out-dir experiments/E4_evolvegcn --epochs 200

# === Phase 5: AMLworld data pipeline ===
python scripts/format_kaggle_files.py "data/raw/HI-Small_Trans.csv"
python preprocessing/amlworld_loader.py --raw-dir data/raw --out-dir data/processed --patterns data/raw/HI-Small_Patterns.txt

# === Phase 5: E5a baselines ===
python baselines/logistic_regression_aml.py --data-dir data/processed --out-dir experiments/E5a_logistic_regression
python baselines/random_forest_aml.py --data-dir data/processed --out-dir experiments/E5a_random_forest
python baselines/xgboost_aml.py --data-dir data/processed --out-dir experiments/E5a_xgboost --no-gpu

# === Phase 5: E5b GFP features + tuned XGBoost ===
python graph/motif_features.py --data-dir data/processed --out-dir data/processed --window 86400 --max-cycle-hops 5 --workers 0
python baselines/gfp_xgboost_aml.py --data-dir data/processed --out-dir experiments/E5b_gfp_xgboost --n-trials 50

# === Phase 6: Multi-GINe v2 (best performance) ===
python models/tgn.py --raw-dir data/raw --data-dir data/processed --out-dir experiments/E6_tgn --epochs 100 --emlps --ports --tds --reverse-mp --ego --gfp --num-neighs 100 100 --seeds 1 42 123

# === Phase 6: Multi-GATv2 (unified backbone for E7-E9) ===
python models/gatv2.py --raw-dir data/raw --data-dir data/processed --out-dir experiments/E6_gatv2 --epochs 100 --emlps --ports --tds --reverse-mp --ego --gfp --num-neighs 100 100 --seeds 1 42 123
```
