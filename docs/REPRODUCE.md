# REPRODUCE — every command, in order, with measured runtimes

Workstation: **NVIDIA RTX A5000**, 36 worker cores, Windows 11, Python 3.12 in `.venv312`.
Runtimes are measured on that machine and taken from the runs' own `metrics.json` /
`config.yaml`, not estimated.

Every command below is runnable as written from the repository root. Where a step is slow, the
elapsed time is stated so you can decide what to re-run and what to take from `experiments/`.

```bash
# every command in this file assumes:
cd E:/JSJ/Ring-Shield
PY=.venv312/Scripts/python.exe
export PYTHONIOENCODING=utf-8      # required: several scripts print ± and →
```

> **Invoke package scripts as modules.** `ringshield/typing/` shadows the standard library, so
> `python ringshield/run_rings.py` fails with `cannot import name 'Any' from 'typing'`. Always
> `python -m ringshield.run_rings`. See `docs/PITFALLS.md` §9.

---

## 0. Data integrity — run this first and after any preprocessing change

```bash
$PY scripts/data_manifest.py --check      # ~40 s; must print: data manifest OK
```

`edge_id` is a row position in `data/raw/formatted_transactions.csv` after a stable mergesort on
`Timestamp`. If that file changes, **every** score, embedding, calibrator and rings artefact in the
repository is silently re-keyed and still loads. The manifest is the only thing that catches it.

| file | sha256 (first 16) | bytes |
|---|---|---|
| `HI-Small_Trans.csv` | `b19d39f515523373` | 475,664,283 |
| `HI-Small_accounts.csv` | `786808526e33cfc4` | 34,053,187 |
| `HI-Small_Patterns.txt` | `2c546b5ce6009e73` | 323,844 |
| `formatted_transactions.csv` | `3b9678458eeece7e` | 266,605,148 |

---

## 1. Preprocessing (HI-Small)

```bash
$PY scripts/format_kaggle_files.py data/raw/HI-Small_Trans.csv          # ~6 min
$PY -m preprocessing.amlworld_loader --dataset HI-Small                 # ~12 min (rebuild_account_map dominates)
$PY graph/motif_features.py                                             # ~25 min on 36 workers
```

Produces `data/processed/amlworld_{train,val,test}.parquet`,
`amlworld_ring_ground_truth.parquet` and `amlworld_gfp_features_{split}.parquet`.

**A second dataset never shares these paths.** Use a per-dataset paths file, which every script
inherits through `load_paths()`:

```bash
$PY scripts/format_kaggle_files.py data/raw_li_small/LI-Small_Trans.csv \
      data/raw_li_small/formatted_transactions.csv                      # explicit output path!
RINGSHIELD_PATHS=configs/paths_li_small.yaml $PY -m preprocessing.amlworld_loader \
      --dataset LI-Small --raw-dir data/raw_li_small --out-dir data/processed_li_small
RINGSHIELD_PATHS=configs/paths_li_small.yaml $PY graph/motif_features.py \
      --data-dir data/processed_li_small --out-dir data/processed_li_small
```

Omitting the output path on the first command **overwrites HI-Small's formatted CSV** — see
`docs/PITFALLS.md` §1.

---

## 2. R1 — the detector (5 seeds)

```bash
$PY -u models/tgn.py --arch gine --emlps --ports --tds --reverse-mp --ego --gfp --causal \
    --epochs 100 --patience 20 --batch-size 8192 --lr 0.006 --n-hidden 66 --n-gnn-layers 2 \
    --w-ce1 1.0 --w-ce2 9.0 --num-neighs 100 100 --seeds 1 2 3 4 5 \
    --out-dir experiments/R1_gine_causal
```

**≈ 15 h** (255 s/epoch; 30–52 epochs per seed under patience 20). Then score and calibrate:

```bash
$PY -u models/score.py --run-dir experiments/R1_gine_causal --seeds 1 2 3 4 5 --splits val test
$PY models/calibrate.py --scores-dir experiments/R1_gine_causal --seeds 1 2 3 4 5   # ~3 min
```

Add `--hold-out-pattern BIPARTITE` to train as if a pattern type did not exist (Step 11 / R7); the
holdout is recorded in `config.yaml` and **inherited** by cross-scoring and re-scoring.

---

## 3. r2 — B0 ring baseline  ← *check 1 target*

```bash
for S in 1 2 3 4 5; do
  $PY -m ringshield.run_rings --aggregator cc \
      --scores-val  experiments/R1_gine_causal/scores_val_seed$S.parquet \
      --scores-test experiments/R1_gine_causal/scores_test_seed$S.parquet \
      --model-id gine_causal --seed $S --out experiments/R2_b0/gine_causal/seed$S
done
$PY evaluation/aggregate_results.py            # -> results/tables/r2_ring_b0.csv
```

**≈ 2 min per seed.** Each run grid-searches `seed_frac_pct × min_size` on **validation**, records
the whole grid and the chosen cell in its `config.yaml`, then scores the test window once.

The same three commands with `--scores-*` pointing at `experiments/R2_b0/gfpxgb_scores/` or
`experiments/R6_mega/` produce the gfpxgb and mega rows.

---

## 4. r3 — expansion  ← *check 1 target*

Cross-scored training data first — the policy is never trained on in-sample detector scores:

```bash
$PY -u -m ringshield.expand.cross_score --run-dir experiments/R1_gine_causal \
      --out-dir experiments/R3_cross_scores --epochs 30        # ≈ 8 h (5 fold models)
$PY -u -m ringshield.expand.make_training_set --out experiments/R3_expansion   # ≈ 2 min
$PY -u -m ringshield.expand.policy --training-set experiments/R3_expansion/training_set.parquet \
      --out experiments/R3_expansion/policy_proposed                            # ≈ 2 min
```

Then the runs (each grid-searches Δt × p_min on validation):

```bash
for S in 1 2 3 4 5; do
  $PY -m ringshield.expand.run_expand --seed $S --r1-dir experiments/R1_gine_causal \
      --policy-dir experiments/R3_expansion/policy_proposed \
      --b0-config experiments/R2_b0/gine_causal/seed$S/config.yaml \
      --model-id gine_causal --out experiments/R3_expansion/runs/proposed/seed$S
done
$PY evaluation/aggregate_expansion.py          # -> results/tables/r3_expansion.csv
```

**≈ 6 min per seed.** Baselines: `--policy rule` (B1) and `--policy rule_q` (B1b); ablations with
`--drop-feature-group` at the policy step and `--hop1-only`.

---

## 5. r4 — partition

```bash
$PY -u -m ringshield.partition.make_pairs_training_set --out experiments/R4_partition   # ≈ 3 min
$PY -u -m ringshield.partition.affinity --pairs experiments/R4_partition/pairs_train.parquet \
      --out experiments/R4_partition/affinity
for S in 1 2 3 4 5; do
  $PY -m ringshield.partition.run_partition --seed $S --method average \
      --r1-dir experiments/R1_gine_causal --policy-dir experiments/R3_expansion/policy_proposed \
      --affinity-dir experiments/R4_partition/affinity \
      --r3-config experiments/R3_expansion/runs/proposed/seed$S/config.yaml \
      --model-id gine_causal --out experiments/R4_partition/runs/average/seed$S
done
$PY evaluation/aggregate_partition.py          # -> results/tables/r4_partition.csv
$PY evaluation/unmatched_rings.py              # -> results/tables/r4_unmatched.csv (ceiling decomposition)
```

**≈ 13 min per seed.** `--method b2` is the no-partition control on the same expanded subgraph.

---

## 6. r5 — roles and typing

```bash
$PY -m ringshield.typing.head --out experiments/R5_typing/head       # ≈ 1 min
$PY evaluation/typing_eval.py                                        # -> results/tables/r5_typing.csv
```

---

## 7. r9 — statistics for every table

```bash
$PY -u evaluation/step9_tables.py        # ≈ 25 min: CIs, p-values, quiet members, TTD
$PY evaluation/r9_robustness.py          # ≈ 20 min: k* robustness (k* itself is NOT changed)
$PY evaluation/quiet_precision_figure.py
```

---

## 8. r6 — detector swap (Step 10)

```bash
git clone https://github.com/hcagri/MEGA-GNN third_party/mega_gnn   # commit ef60a71, Apache-2.0
$PY -u models/mega_adapter.py --seeds 1 2 3 4 5                     # ≈ 18 h (238 s/epoch)
$PY models/calibrate.py --scores-dir experiments/R6_mega --seeds 1 2 3 4 5
$PY -u baselines/gfp_xgboost_crossfit.py                            # ≈ 14 min
# ... policy/affinity per detector, then run_expand + run_partition as in §4-5 ...
$PY -u evaluation/r6_detector_swap.py                               # ≈ 12 min
```

Their model code is **not edited**; `third_party/shims/` supplies pure-python stand-ins for two
Linux-only compiled modules and for wandb. The clone is gitignored — its commit is recorded in
`experiments/R6_mega/config.yaml`.

---

## 9. r7 — held-out pattern (Step 11)

```bash
# L3-only: detector frozen, the ring layer never trained on the pattern  (≈ 2 h per pattern)
for PAT in BIPARTITE CYCLE; do
  low=$(echo $PAT | tr A-Z a-z)
  $PY -u -m ringshield.expand.make_training_set --hold-out-pattern $PAT --out experiments/R7_l3only_$low
  $PY -u -m ringshield.expand.policy --training-set experiments/R7_l3only_$low/training_set.parquet \
        --hold-out-pattern $PAT --out experiments/R7_l3only_$low/policy
  # ... pairs, affinity, typing head, then run_expand + run_partition per seed ...
done
$PY -u evaluation/r7_heldout.py                  # -> results/tables/r7_heldout.csv

# full (detector included) — calibration run only; ≈ 18 h
$PY -u models/tgn.py ... --hold-out-pattern BIPARTITE --out-dir experiments/R7_heldout_bipartite
```

---

## 10. Follow-ups that named where the ceiling lives

```bash
$PY -u evaluation/under_covered.py          # ≈ 8 min  -> r_under_covered.csv   (B12)
$PY -u evaluation/ensemble_seeds.py         # ≈ 2 min  -> R11b ensemble seeds   (C7 / B14)
$PY -u evaluation/local_budget_seeds.py     # ≈ 2 min  -> R11c local budget     (B14)
```

---

## 11. Figures and the traceability audit

```bash
$PY evaluation/make_figures.py              # ≈ 1 min -> results/figures/f1..f5
$PY evaluation/audit_tables.py              # every reported number traced to a metrics.json
```

---

## 12. Tests

```bash
$PY -m pytest tests/ contract/tests -q      # ≈ 4 min; expect 133 passed, 1 xfailed
```

A change in the **skip** count matters as much as a failure — 18 silent skips once hid a duplicated
config loader that broke dataset isolation (`docs/PITFALLS.md` §8b).

---

## What is *not* reproducible from here

* **Step 12 (R8 structuring)** was not run. Its premise is weakened by B13 (the residual is
  connectivity, not thresholds) and B15 (the floor prize is ≈ 1 ring/seed).
* **LI-Small method numbers** were deliberately not produced: 38 matchable rings in its primary
  window cannot separate any method from any other. Its preprocessing, scope table, tail and day-0
  analyses *are* reproducible with the §1 commands and are the reported result
  (`docs/ring_scope_li_small.json`).
* **Elliptic** is not part of the ring pipeline (it has no ring labels). Its baselines, E1–E3, are
  in `elliptic/` with their own commands (`elliptic/README.md`).

## 13. End-to-end check of the integrated `main` (2026-10-26)

Run on the development workstation (Windows 11, RTX A5000) on branch `integrate/main`, with
`$PY=.venv312/Scripts/python.exe`, `PYTHONIOENCODING=utf-8`, the data from the Kaggle download, and
the existing checkpoints and scores (nothing was retrained). Fixes made on the way are named by
commit.

| # | Command | Result |
|---|---|---|
| 1 | `$PY scripts/data_manifest.py --check` | `data manifest OK` |
| 2a | `$PY -m pytest tests contract/tests preprocessing/tests -q` | **258 passed**, 47 skipped, 1 xfailed (one test needs `experiments/R1_gine_causal/scores_val_seed1.parquet` on disk) |
| 2b | `..env-xai\Scripts\python.exe -m pytest explainability/tests -q` | **229 passed**, 35 failed, 6 errors, all environmental: L4 outputs not produced on this machine (`results/xai/explanations_week3_seed1.parquet`, `results/xai/review/answer_key.parquet`, `results/xai/explanations_converted_seed1.parquet`, `contract/out` seeds 2–5 and the v1 rings), `fastapi` not installed in the XAI environment, and the committed L4 tenant log recording tenant-ring inputs of 2026-10-17 (`eaa4f609…`) that predate the v2 rings now shipped (`d98cce48…`). One real test bug fixed: input fingerprints failed on an LF checkout (df4334f). |
| 3 | `make test-db` (no `make` here: its three `docker compose` commands) | **563 passed**, 2 skipped, **22 RLS tests** against PostgreSQL, after fixes 9ce7a92 (`git_commit` without git), 9260bdf (simulator URL), 0f8d5ef (`.dockerignore`), cd7ea1e (the summary's pass count) |
| 4 | `cd platform/frontend; npm ci; npm run build; npm run test; npm run test:e2e` | build OK; **361** unit tests passed; **58** Playwright tests passed |
| 5 | `powershell -File scripts/tests/run-demo-validation.tests.ps1` | **18 checks passed**. Under `Invoke-Pester` (Pester 3.4.0) the file runs but counts as 0 tests: it is a script of checks, not `It` blocks. |
| 6 | `$PY evaluation/audit_tables.py` | **traceable: 18, mismatched: 0** |
| 7 | `$PY -m ringshield run --scores contract/out/scored_edges_gine_causal_1.parquet --model-dir models/artifacts/full_gine_causal_seed1 --aggregator full --gfp data/processed/amlworld_gfp_features_test.parquet --embeddings experiments/R1_gine_causal/embeddings_test_seed1.parquet --out <tmp>/rings_full_gine_causal_1.parquet` | 108 rings in 62 s; sha256 **`9d1e0b9e…5328`**, 57,618 bytes, **identical** to `contract/out/rings_full_gine_causal_1.parquet` as listed in `docs/HANDOFF_XAI.md`. Needs the model's typing head, which the exported model lacked (0069718). |
| 8 | `.\scripts\demo.ps1 -FromProcessedData` (clean database) | banks 12 and 20: 5 rings each rebuilt from `data/processed/` (bank 12 byte-identical to the shipped tenant rings: `1e651963…`, edge ids `d98cce48…`); L4: 5/5 explained and reproduced per bank; demo ready at http://localhost:5173. Signed in as the bank-12 analyst: queue of 5 typed rings (FAN-OUT, FAN-IN, STACK ×3); `full-gine_causal-1-0` opens with its L4 narrative. |
| 9 | `python elliptic/tests/test_split_no_leakage.py`; `python -m elliptic.baselines.random_forest` (in `..env-xai`, which has E2a's recorded pandas 2.3.3 / scikit-learn 1.8.0) | no train/test overlap; **E2a illicit F1 0.8221757322175732**, identical to `elliptic/experiments/E2a_random_forest/metrics.json`. All 31 `elliptic/` modules compile and their imports resolve except `pyvis` (not installed here). |

Note: `demo.ps1 -FromProcessedData` regenerates L4's tenant explanations in `results/xai/tenant/`
and rewrites their committed `.log.json` run records there; restore them with
`git checkout -- results/xai/tenant/` after a run unless a new L4 handoff is intended.

