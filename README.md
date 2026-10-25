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
| L3c roles / typing | account roles (source / sink / mule / holder / peripheral), ring confidence, topology head | `ringshield/roles.py`, `ringshield/typing/` | `experiments/R5_typing` |
| **L4 explainability** | **L4 explains rings, not edges.** Edge weights combine the calibrated score, leave-one-out ring contribution via `rerun_ring`, and flow share; account weights and roles come from conservation; feature weights are SHAP on GFP+XGBoost over the seed edges; narratives are fixed templates whose every number traces to a stored value. **No attention weights, no language model.** Its measured claims are explanation fidelity@k (k = 3, 5, 10) against ground-truth ring edges versus random and score-only controls with bootstrap CIs; typology and role accuracy on matched rings; p95 latency under 2 s; and a 30-explanation internal review with Fleiss' κ, labelled internal rather than an analyst study. The results are in L4's own report (`explainability/report/xai_chapter.md`), not in `docs/FINDINGS.md`. | `explainability/` (branch `explainability-l4`) | `results/xai/`, `contract/out/xai/` |
| Contract | `scored_edges` and `rings` v1 parquets for the platform side | `contract/` | `contract/out/` |
| CLI | `run` / `train` / `eval` / `export-model` | `python -m ringshield` | `docs/CLI.md` |

### Experiments behind the reported tables

| ID | What | Result |
|---|---|---|
| **R1** | detector, 5 seeds, causal | primary-window edge F1 0.495 ± 0.027 (whole test split 0.596 ± 0.069, inflated by the tail: C1/C2) |
| **R2** | B0 ring baseline, 3 detectors | gine 0.521 ± 0.045, gfpxgb 0.343, density 0.014 |
| **R3** | expansion: policy vs rule baselines vs ablations | proposed 0.582; **quiet-member recall 0.005 → 0.21** |
| **R4** | partition: 5 methods + CSGM | full 0.589; the stage is **not** significant on this detector |
| **R5** | roles and topology typing | head **0.599** [0.549, 0.648] vs rule 0.551 [0.499, 0.601] on the primary window (401 matched rings); 0.594 on `whole`: typing is not window-bounded (~~0.219~~ corrected 2026-10-22, found by Ruhani (L4 Week 5 check): the old lookup typed the wrong ring; B10, C3 withdrawn) |
| **R6** | detector swap: MEGA-GNN and GFP-XGBoost | **+9.4 edge-F1 points buys 0.000 ring-F1** |
| **R7** | held-out pattern types (3 arms) + LI-Small | transfer holds on CYCLE at undiminished precision |
| **R9** | statistics: bootstrap CIs, permutation tests, Holm | every table carries an interval |
| **R10** | tenant vs pooled: a pooled model applied to one bank's view (banks 1, 20, 11, 118, 12; 68 tenant-ring pairs) | pooled − (b) = **0.271 [0.154, 0.407]** ring recall; includes distribution shift (`docs/TENANT_SIZES.md`, `results/tables/r10_registered.md`) |
| **R11b/c** | seed-budget reallocation (ensemble, per-account) | allocation is **not** the binding constraint |

### Headline findings

1. **Edge F1 is not a proxy for ring recovery.** MEGA-GNN beats our detector by 9.4 edge-F1 points
   and produces the same rings (0.5208 vs 0.5213). The two disagree on *which* edges to seed
   (Jaccard 0.415) and agree on how many rings a 0.1 % budget reaches (128.8 vs 129.6 of 174).
2. **Expansion recovers quiet members** — 0.5 % → 21 % — but a two-line rule matches it; the learned
   policy buys *purity* (0.926 vs 0.518 added-member precision), not recall.
3. **Most of the remaining loss is structural, but there is no `min_size` cap on recall.** 34 % of
   rings (60 of 174) have < 3 visible members, yet 11.4 of them per seed are still matched
   (~~"28 % below `min_size`, recall capped at 0.72"~~, retracted 2026-09-30: B7/B9). 19 % are
   untouched by the shipped pipeline (13.8 % with MEGA-GNN: B8), and **80.7 %** of the largest
   residual class is in a piece of the ring that is *disconnected inside the evaluation window* —
   99.6 % for STACK even across the whole test split.
4. **One bank's view loses most of its rings (R10).** A pooled model applied to one bank's view
   recovers 0.088 of that bank's tenant-ring pairs against 0.359 pooled: pooled − (b) = **0.271
   [0.154, 0.407]**. This includes distribution shift (the model meets a graph unlike the one it was
   trained on), so it is not only the cost of seeing fewer edges.
5. **Both ends of the AMLworld timeline are generator artefacts**, reproduced in two releases: day 0
   holds ~34 % of training edges at 10× density, and the test tail collapses to a ~60 % base rate on
   ≤ 0.13 % of edges.

### Deliberately not done

* **Step 12 (structuring stress test)** — premise weakened by findings B13/B15; see `docs/REPRODUCE.md`.
* **LI-Small method numbers** — 38 matchable rings cannot separate any method; its scope, tail and
  day-0 analyses are the reported result.
* **`rings_full` for mega / gfpxgb** — the contract builder is pinned to the shipped detector and
  asserts it reproduces the R4 run. Those detectors are research comparisons under
  `experiments/R6_full/`, not contract deliveries.
* **SHAP over the expansion policy** — specified in the roadmap's XAI layer, not built. Leave-one-out answers the analyst's actual question ("what happens to this ring if this transaction is not real?") at 25 ms, whereas SHAP would explain a per-candidate probability the analyst never sees. That is a reframing of the scope, not a completion of it, and it is stated here rather than glossed.
* **The XAI layer is not in `docs/FINDINGS.md`** (see the L4 row). Its measurements are L4's own and there is no analyst study, so it is a delivered capability, not a validated explanation. The contract fields should not be read as evidence.
* Elliptic, EvolveGCN, GATv2, the escalation cascade, attention-based XAI — out of scope (Step 1).

Seeds come from `configs/seeds.yaml` (`[1, 2, 3, 4, 5]`), paths from `configs/paths.yaml`
(`$RINGSHIELD_PATHS` selects a per-dataset file). Pre-R1 runs used the seeds in their own
`config.yaml`.

## Setup

Windows 11, PowerShell. Install these yourself first:

| Tool | Version | Used for |
|---|---|---|
| Python | 3.12 (research), 3.11+ (platform) | everything |
| Node.js + npm | 18+ | the React dashboard |
| Docker Desktop | with Compose v2 | the demo and test Postgres |
| NVIDIA GPU + CUDA 12.1 | optional | retraining detectors (R1, R6); not needed for the demo or the tables |

Two virtual environments, one for the research code and one for the platform (the platform pins
different versions):

```bash
py -3.12 -m venv .venv312
.\.venv312\Scripts\python.exe -m pip install -r requirements.txt
py -3.12 -m venv ..\venv-platform
..\venv-platform\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Then install the front end's packages:

```bash
npm ci --prefix platform/frontend
```

## Data

Nothing in `data/`, `contract/out/*.parquet` or `experiments/**/*.parquet` is committed.

1. **Raw data.** Download *IBM Transactions for Anti Money Laundering (AML)* from Kaggle
   (https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml). Put
   `HI-Small_Trans.csv`, `HI-Small_accounts.csv` and `HI-Small_Patterns.txt` in `data/raw/`.
2. **Preprocess** (about 45 minutes). This writes `data/processed/`:

   ```bash
   .\.venv312\Scripts\python.exe scripts/format_kaggle_files.py data/raw/HI-Small_Trans.csv
   .\.venv312\Scripts\python.exe -m preprocessing.amlworld_loader --dataset HI-Small
   .\.venv312\Scripts\python.exe graph/motif_features.py
   .\.venv312\Scripts\python.exe preprocessing/account_bank.py
   ```

3. **Check the data.** This must print `data manifest OK`. If it doesn't, every downstream score is
   keyed to the wrong `edge_id` (`docs/PITFALLS.md` §1):

   ```bash
   .\.venv312\Scripts\python.exe scripts/data_manifest.py --check
   ```

4. **Demo inputs.** `scripts/demo.ps1` reads five sets of files:
   - `contract/out/scored_edges_gine_causal_1.parquet` (with its `.log.json`)
   - each bank's rings, edge ids and explanations, in `data/platform_tenant_runs/gine_causal_seed1/`

   These are produced by R1 seed 1 → `contract/make_scored_edges.py` → the tenant ring build
   (`docs/TENANT_SIZES.md`) → L4 (`explainability/`, branch `explainability-l4`). They come from
   the handoff, not from a download. The script lists any file that is missing.

## Running the demo

One command, from the repository root:

```bash
.\scripts\demo.ps1
```

The script does the following, in order:
1. Checks for Python, Node/npm and Docker (the demo Postgres runs in Docker), plus every input file. It prints everything that is missing and stops.
2. Starts an empty demo Postgres on `127.0.0.1:55433` and runs the migrations.
3. Loads the seed-1 rings and explanations for banks 12 and 20.
4. Creates the logins: analysts at banks 12 and 20, a supervisor at bank 12, and an administrator.
5. Starts the API (`127.0.0.1:8000`) and the worker supervisor.
6. Builds the React app and serves the production build.

At the end it prints the URL, **http://localhost:5173**, and the logins. Open the page at
`localhost`, not `127.0.0.1`: the API accepts only that origin. Every run starts from an empty
database. Stop everything with:

```bash
.\scripts\run-demo.ps1 -Down
```

Other banks, a different detector seed, or the frozen Streamlit dashboard: call
`scripts/run-demo.ps1` directly (`-Tenants`, `-PlatformConfig`, and without `-SkipStreamlit`).
To run the dashboard on fixtures, without the API, see `platform/frontend/README.md`. The
screen-by-screen walk-through is in `docs/dashboard_checklist.md`.

## Reproducing each table

Commands assume `$PY=.venv312/Scripts/python.exe` and `PYTHONIOENCODING=utf-8`, run from the
repository root. `docs/REPRODUCE.md` has every training command with measured runtimes. The
right-hand column is the slow part: the training that produces the run artefacts. The middle column
rebuilds the table from artefacts already in `experiments/`.

| Table | Rebuild the table | Runs it needs (`docs/REPRODUCE.md`) |
|---|---|---|
| `results/tables/r1_edge_metrics.csv` | `$PY evaluation/edge_metrics.py --table` | §2: R1 training, about 15 h |
| `results/tables/r2_ring_b0.csv` | `$PY evaluation/aggregate_results.py` | §3: `ringshield.run_rings`, 5 seeds |
| `results/tables/r3_expansion.csv` | `$PY evaluation/aggregate_expansion.py` | §4: cross-scoring (about 8 h), policy, `run_expand` |
| `results/tables/r4_partition.csv`, `r4_unmatched.csv` | `$PY evaluation/aggregate_partition.py`; `$PY evaluation/unmatched_rings.py` | §5: affinity, `run_partition` |
| `results/tables/r5_typing.csv` | `$PY evaluation/typing_eval.py` | §6: typing head |
| `r2_ci`, `r3_ci`, `r4_ci`, `r5_typing_ci`, `r9_*`, `*_pvalues` | `$PY -u evaluation/step9_tables.py`; `$PY evaluation/r9_robustness.py` | §7 (about 45 min) |
| `results/tables/r6_detector_swap.csv` | `$PY -u evaluation/r6_detector_swap.py` | §8: MEGA-GNN (about 18 h), GFP-XGBoost |
| `results/tables/r7_heldout.csv` | `$PY -u evaluation/r7_heldout.py` | §9: held-out policies |
| `results/tables/r_under_covered*.csv` | `$PY -u evaluation/under_covered.py` | §10 |
| `results/tables/r10_registered.{json,md}` | `$PY evaluation/r10_registered.py` | tenant ring builds (`docs/TENANT_SIZES.md`) |
| `results/platform/r11/five_seeds/` | `.\scripts\run-r11-seeds.ps1` (about 2 h; a fresh demo database per run) | `docs/R11.md` |
| `results/platform/r12/registered/`, `diagnosis/`, `amended/` | from `platform/`: `python -m experiments.r12_injected_shift --pattern CYCLE`, `python -m experiments.r12_diagnose`, `python -m experiments.r12_amended` | `docs/R12.md` |
| `results/figures/f1..f5` | `$PY evaluation/make_figures.py` | — |

Two checks tie the numbers to their sources:
- `$PY evaluation/audit_tables.py` re-derives the ring tables from the per-seed `metrics.json`.
- `results/FROZEN.json` holds every headline number in this README and its source. `tests/test_frozen.py` fails if any of them changes.

## Tests

```bash
.\.venv312\Scripts\python.exe -m pytest tests contract/tests -q
.\scripts\test-db.ps1      # with ..\venv-platform activated
```

The second command runs the platform suite, including the row-level-security tests, against a
throwaway Postgres.

For the front end:

```bash
npm --prefix platform/frontend run typecheck
npm --prefix platform/frontend test
npm --prefix platform/frontend run test:e2e
```

The front-end tests are typecheck, unit tests and Playwright, all on fixtures.

Research tests that need `data/processed/` skip when it is absent. A changed skip count matters
(`docs/PITFALLS.md` §8b).

## Hardware

All runs so far: Intel Xeon W-2295 (18C/36T, 3.0 GHz), 128 GB RAM, NVIDIA RTX A5000
(24 GB), Windows 11 Pro, Python 3.12.10, PyTorch 2.5.1+cu121, PyG 2.8.0, XGBoost 3.4.1.
