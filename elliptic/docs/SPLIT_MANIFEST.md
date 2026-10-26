# SPLIT_MANIFEST.md — Elliptic Dataset

## Source
- Dataset: Elliptic Data Set (Bitcoin transaction graph)
- Source URL: https://www.kaggle.com/datasets/ellipticco/elliptic-data-set
- Reference paper: Weber et al. 2019, "Anti-Money Laundering in Bitcoin:
  Experimenting with Graph Convolutional Networks for Financial Forensics"
  (arXiv:1908.02591)

## Raw file checksums (SHA-256)
elliptic_txs_features.csv fd7f83573443c9e302e371d3f110e3b6224160f5d1ed8a287757936127800ff0
elliptic_txs_classes.csv 93e2e7b2405c735ba752bf6ba06b947561deddd1f5a8fc91e46f6a4c0e439493
elliptic_txs_edgelist.csv a35053ba68a98e4382cae2ba65b9d9e36b23b6439e02dff084971b1b72a5156e

HI-Small_Trans.csv b19d39f515523373f991b689c07e11e7b0b95c17a2c27a87d91584ae16c5b040
HI-Small_Patterns.txt 2c546b5ce6009e73851f0139af053cf845f08bf92f3bc82fe1eb937dec2ef39b


## Raw dataset shape (sanity check)
- Number of timesteps: 49
- Total labeled nodes: 46,564 (matches Weber et al.'s reported 46,564 labeled transactions)
  - Licit (label=0): 42,019
  - Illicit (label=1): 4,545
- Unlabeled nodes: 157,205
- Total nodes: 203,769 (verified, per Weber et al.)
- Total edges: 234,355 (verified, per Weber et al.)
- All labeled rows accounted for: True (confirmed by loader sanity check)

## Split definition
- Split type: chronological by `time_step` — **not** `sklearn.train_test_split` (no random shuffling; a random split would leak future graph structure into training).
- Train: timesteps 1–34 (inclusive)
- Test: timesteps 35–49 (inclusive)
- Val (reserved, not used until cascade/threshold-tuning work in later phases): timesteps 30–34, carved from the tail of train
- Rationale: replicates Weber et al.'s 70:30 chronological split (49 × 0.7 ≈ 34.3 → 34 train / 15 test)

## Resulting row counts (labeled only, used for Phase 1 tabular baselines)
- Train rows: 29,894  (illicit: 3,462, licit: 26,432)
- Test rows: 16,670  (illicit: 1,083, licit: 15,587)

## Feature set decision
- Chosen: **AF (All Features)** — all 165 model features (166 raw columns minus `txId` minus `time_step`)
- Excluded from model features: `time_step` (used only for split filtering — including it as a feature would let a model trivially separate train/test by time, a leakage risk)
- Rationale: AF is the feature set behind Weber et al.'s headline RF=0.796 result; using it (not the weaker 94-dim LF set) keeps the tabular baselines maximally strong, so any later GNN improvement is a genuine signal rather than an artifact of an artificially weak baseline.
- Documented in: `configs/elliptic_features.yaml`

## Files produced
- `data/processed/elliptic_train.parquet` — labeled rows, timesteps 1–34
- `data/processed/elliptic_test.parquet` — labeled rows, timesteps 35–49
- `data/processed/elliptic_all.parquet` — all 203,769 rows (incl. unlabeled), for Phase 2 graph construction

## Verification status
- [x] Checksums recorded (this file, above)
- [x] Timestep count = 49 confirmed
- [x] Label counts match Weber et al. (42,019 licit / 4,545 illicit) confirmed
- [x] Train/test row counts confirmed sum to 46,564 (fill in above, then check this box)
- [x] `tests/test_split_no_leakage.py` passes

## Phase 2 — Graph Object

- File: data/processed/elliptic_graph.pt (torch_geometric.data.Data)
- x.shape: [203769, 165]
- edge_index.shape: [2, 234355]
- train_mask sum: 29894
- test_mask sum: 16670
- Cross-check: train_mask.sum() + test_mask.sum() = 46564 == Phase 1 labeled total (46,564) — confirmed
- Manual edge spot-check (edge index 1000 → CSV line 1002, txId pair 230437638,232908760): confirmed match

### Transductive framing (read before modifying this pipeline)

Elliptic's graph is used transductively: the full graph structure (all 203,769
nodes, all 234,355 edges) is visible to the model at all times. Only the
node-level loss and evaluation are restricted by train_mask/test_mask,
matching Weber et al. (2019)'s own protocol exactly. This is NOT a temporal-
leakage bug — the information being withheld from training is node labels,
not graph structure. Do not "tighten" this into hiding test-period edges
entirely; doing so would no longer replicate the paper this project targets.

### Visual inspection note

A search across all 4,545 illicit-labeled nodes found the densest 2-hop
neighborhood contains only 15 nodes (node 169304), with most illicit nodes'
2-hop neighborhoods far smaller (single digits) — see
results/figures/elliptic_densest_illicit_ego.html and
elliptic_top8_illicit_combined.html. This confirms Elliptic is a genuinely
sparse graph (consistent with Weber et al.'s reported average node degree of
~2), not a visualization artifact. This is a plausible contributing factor to
why Random Forest outperformed GCN in both the original paper and this
project's Phase 1/3 results: limited local neighborhood structure around
individual illicit nodes constrains how much a message-passing GNN can
exploit graph topology at the per-node level.

## Reproducibility

- Graph construction environment: experiments/_phase2_graph_construction/environment.txt
- PyTorch weights_only note: torch>=2.6 defaults torch.load(weights_only=True),
  which blocks loading torch_geometric.data.Data objects. All scripts loading
  elliptic_graph.pt must pass weights_only=False explicitly (safe here since
  these are self-generated files, not downloaded from an untrusted source).
