# Elliptic baselines — Phase 0–3 (E1–E3)

Ruhani Kumar's first phases of the project, on the Elliptic Bitcoin dataset: data checks and
splits (Phase 0–1), tabular baselines (Phase 1), the Elliptic graph object and its
visualisations (Phase 2), and static GNN baselines (Phase 3). These are experiments E1–E3.

They are **not part of the ring pipeline**: Elliptic labels transactions, not rings, so nothing
here feeds L1–L6. The AMLworld edge-level experiments start at E5, and the ring-level ones are
R1–R12 (`docs/FINDINGS.md`).

## Results (test split, illicit class)

Every number is read from `experiments/<run>/metrics.json`. Threshold and class weight were
chosen on a validation window carved from the training timesteps, never on test.

| Run | Model | Illicit F1 | Precision | Recall | ROC-AUC |
|---|---|---|---|---|---|
| E1 | Logistic regression, untuned | 0.314 | 0.192 | 0.867 | 0.885 |
| E1b | Logistic regression, tuned | 0.489 | 0.470 | 0.510 | 0.894 |
| E2a | Random forest | **0.822** | 0.948 | 0.726 | 0.927 |
| E2b | XGBoost | 0.759 | 0.785 | 0.734 | 0.938 |
| E3a | GCN | 0.495 | 0.492 | 0.499 | 0.842 |
| E3b | GraphSAGE | 0.557 | 0.491 | 0.644 | 0.887 |

**Key finding** (`results/phase3_summary.md`): both GNNs substantially underperform the random
forest and XGBoost. Graph structure alone, without temporal or ring-level modelling, does not
beat tabular baselines on Elliptic, and the GNNs show a much larger validation-to-test gap
(~38 % relative) than the tree ensembles (15–19 %).

## Running it

From the repository root, with the pins in `elliptic/requirements.txt` (Python 3.11 in the
original runs):

```bash
python -m pip install -r elliptic/requirements.txt
```

Put `elliptic_txs_features.csv`, `elliptic_txs_classes.csv` and `elliptic_txs_edgelist.csv`
(Kaggle, *Elliptic Data Set*) in `elliptic/data/raw/elliptic/`. Everything this folder writes
goes under `elliptic/`; `elliptic/data/` is gitignored.

```bash
python -m elliptic.scripts.prepare_elliptic          # tabular splits -> elliptic/data/processed/
python elliptic/tests/test_split_no_leakage.py       # train and test timesteps do not overlap
python -m elliptic.baselines.logistic_regression     # E1b
python -m elliptic.baselines.random_forest           # E2a
python -m elliptic.baselines.xgboost_baseline        # E2b
python -m elliptic.graph.build_elliptic_graph        # graph object for E3
python -m elliptic.baselines.gcn                     # E3a
python -m elliptic.baselines.graphsage               # E3b
```

Each run overwrites its `elliptic/experiments/<run>/` files. The visualisations:
`python -m elliptic.graph.viz_elliptic` writes the two PNGs in `results/figures/`; the
`viz_*_interactive` scripts write HTML into `elliptic/graph/`, next to the vendored
`elliptic/graph/lib/` (vis-network, tom-select) that the HTML loads.

## Layout

| Path | What |
|---|---|
| `preprocessing/elliptic_loader.py` | loads the CSVs, applies `configs/elliptic_split.yaml` |
| `baselines/` | E1–E3 training scripts |
| `baselines/_ieee_cis_scratch/` | **scratch**: an early logistic-regression try on IEEE-CIS, not one of E1–E3 |
| `graph/` | graph builders (Elliptic, an early AMLworld graph) and visualisations |
| `evaluations/classification_metrics.py` | the metrics every run writes |
| `experiments/` | each run's config, environment, metrics and predictions |
| `results/` | phase summaries and the two figures |
| `docs/`, `handoffs/` | experiment registry, split and data manifests, phase handoffs |

`graph/motif_features.py` and `graph/build_amlworld_graph.py` are Phase 2's early AMLworld
tooling; the pipeline's own versions are `graph/` and `preprocessing/` at the repository root.
