# RUNBOOK_OPUS — from reviewed draft to submission candidate

Written 2026-11-14 against repository commit `aeab2be` on branch `integrate/main`
("deep-analysis #7 and #8: HI-Medium close-out verdicts, ring-folded cross-scores").
Target: ACM ICAIF 2027 (backup: a KDD 2027 finance/graph workshop). Double-blind, ACM
`sigconf`, 8-page body + references + unlimited appendix.

---

## 0. How to use this runbook

### 0.1 Your role

You are the implementing engineer and co-writer for a research paper. The project detects
money-laundering **rings** (groups of accounts executing one laundering attempt) on the IBM
AMLworld benchmark, and the paper is an **evaluation-protocol and benchmark-audit paper**:
its strongest results are about how ring-level detection is measured, not about a new method.
You will run a fixed set of analyses and experiments, each with a bar written down before it
runs, then update the paper. You do not see the conversation that produced this plan;
everything you need is in this file, in `paper/`, and in the repository.

The author is Joan ("Jooo"). She commits between phases. **You never commit, push, amend,
rebase, stash-drop or reset.** Leave every change in the working tree and list it in the
progress log.

### 0.2 Repository layout (verified at `aeab2be`)

Repository root: `E:\JSJ\RS-react`.

| Path | What |
|---|---|
| `preprocessing/`, `graph/` | L0: splits, ring ground truth, GFP motif features |
| `models/` | L1: detector (`tgn.py`), scoring (`score.py`), calibration (`calibrate.py`), `mega_adapter.py` |
| `baselines/` | GFP-XGBoost and other comparison detectors |
| `ringshield/` | L2–L3: seeds, `expand/`, `partition/`, roles, `typing/`, CLI (`python -m ringshield`), `run_rings.py`, `aggregators/` |
| `evaluation/` | ring metrics, statistics, every table and figure builder |
| `contract/` | the `scored_edges` / `rings` parquet contract; `contract/out/` holds shipped rings |
| `explainability/` | L4 explanations (not part of this runbook's experiments) |
| `platform/` | L5/L6 API, database, dashboard (touched only by the platform test suite) |
| `configs/` | `paths.yaml`, `paths_hi_medium.yaml`, `paths_li_small.yaml`, `seeds.yaml`, `eval_window.yaml`, `eval_window_hi_medium.yaml`, `threshold_rule.yaml`, `detector_choice.yaml`, `roles.yaml`, `holdout_manifest.json` |
| `experiments/` | HI-Small run records (configs, metrics, logs) |
| `experiments_hi_medium/` | HI-Medium run records, including `closeout_a15/` |
| `results/tables/`, `results/figures/`, `results/FROZEN.json` | reported tables; frozen headline numbers |
| `docs/` | `FINDINGS.md` (single source of claims), `deep-analysis.md` (registered follow-ups), `REPRODUCE.md`, `PITFALLS.md`, `PARTITION.md`, `EXPANSION.md`, `V3_HIMEDIUM_PREREG.md`, `FUTURE_IMPLEMENTATIONS.md`, `R12.md` |
| `third_party/mega_gnn/` | upstream MEGA-GNN clone (git-ignored), with `genagg/`; `third_party/shims/` |
| `external/` | git-ignored external code (e.g. `Collaborative-AML`) |
| `tests/`, `contract/tests/`, `preprocessing/tests/` | research tests |
| `paper/` | **this runbook, the LaTeX paper, and everything you write for it** (created in Phase 0) |

Sibling directories that hold run artefacts the repository does not carry:

- `..\RS-e2e\experiments` — detector checkpoints, scores, embeddings, and the R2/R3/R4/R6 run
  directories.
- `..\RS-ccy-valrings` — schema-v2 rings and scored edges (`contract/out`) and validation
  rings (`experiments_valrings`).
- `E:\JSJ\Ring-Shield\paper_draft\` — the current paper draft (copied into `paper/` in Phase 0).

### 0.3 Environment

Windows 11 Pro; Intel Xeon W-2295 (18C/36T); 128 GB RAM; NVIDIA RTX A5000 24 GB.
Research env: `.venv312` (Python 3.12, PyTorch 2.5.1+cu121, PyG 2.8.0, XGBoost 3.4.1,
LightGBM, pandas 3.0.5, NetworkX 3.6.1). Platform env: `..\venv-platform` (needs Docker
Desktop for the database tests).

Commands in this runbook are written for **Git Bash**, as in `docs/REPRODUCE.md`:

```bash
cd /e/JSJ/RS-react
PY=.venv312/Scripts/python.exe
export PYTHONIOENCODING=utf-8      # required: several scripts print ± and →
```

**Invoke package scripts as modules** (`$PY -m ringshield.run_rings`, not
`$PY ringshield/run_rings.py`): `ringshield/typing/` shadows the standard library otherwise
(`docs/PITFALLS.md` §9). Scripts under `evaluation/` and `models/` are run by path, as
`REPRODUCE.md` does.

### 0.4 Working rules

1. **Work through the phases in the order of §4.0. Never skip a gate.** A gate marked STOP
   means: write the result to the progress log, write the checkpoint or failure summary, and
   end your turn. Do not start the next task.
2. **Before running any script, read its `argparse` block (or `--help`).** Never guess a
   flag. Where this runbook names a flag, it was read from the source at `aeab2be`; if the
   source disagrees, the source wins and you log the difference.
3. **Progress log.** Keep `paper/RUNBOOK_PROGRESS.md` (template in §0.5). Update it after
   every task and every gate: status, start/end timestamps, exact commands, output paths, key
   numbers, deviations. Write it so a fresh session with no memory can resume.
4. **Resume rule.** At the start of every session: read `paper/RUNBOOK_OPUS.md` §0–§1, then
   `paper/RUNBOOK_PROGRESS.md`, and continue from the first task whose status is not DONE.
   If a task is RUNNING with a background job, check the job's log first.
5. **Long GPU jobs run in the background** with stdout/stderr to a log file under the run's
   output directory. Record in the progress log the PID, the log path, and the command to
   watch it, in this form:
   `tail -f experiments/<run>/train.log` (Git Bash) or
   `Get-Content experiments\<run>\train.log -Wait -Tail 20` (PowerShell).
   Only one GPU job at a time.
6. **Deviations.** Anything you do differently from this runbook gets a row in the progress
   log's Deviations table with the reason, before you do it. A deviation that touches a
   pre-registered bar, a test-set choice, or a frozen file is not a deviation; it is a STOP.
7. **Stop-and-ask is cheap.** If a result contradicts an assumption in this file, a needed
   file is missing, a test fails and you cannot explain it within about an hour, or a runtime
   exceeds twice its estimate: stop and report. Do not improvise around it.
8. **Internal codes.** The repository uses row codes (A1–A6, B1–B17, C1–C11, R1–R12, E1–E7,
   P1–P4 of the HI-Medium pre-registration). They are fine in code, logs and docs. They must
   **never appear in the paper's prose**; see §6. Note that this runbook's task IDs are also
   called P1–P11: in the progress log write them as `T-P1` … `T-P11` to avoid confusion with
   the HI-Medium pre-registration's P1–P4.

### 0.5 Progress-log template

Create `paper/RUNBOOK_PROGRESS.md` in Phase 0 with exactly these sections:

```markdown
# RUNBOOK_PROGRESS

Runbook: paper/RUNBOOK_OPUS.md (sha256: <fill>)   Repo HEAD at start: <git rev-parse HEAD>
PREREG file: <path> (sha256: <fill>, frozen at <timestamp>)

## Status
| Task | Status | Started | Finished | Gate result | Notes |
|---|---|---|---|---|---|
| Phase 0 | TODO | | | | |
| PREREG | TODO | | | | |
| T-P6 related work | TODO | | | | |
| T-P1 scorer | TODO | | | | |
| T-P7a GenAgg seed 1 | TODO | | | | |
| T-P2 ring-fold report | TODO | | | | |
| T-P3 classical baselines | TODO | | | | |
| T-P4 HI-Medium audit | TODO | | | | |
| T-P7b GenAgg seeds 2-5 | TODO | | | | |
| CHECKPOINT A | TODO | | | | |
| T-P5 paper sync (pass 1) | TODO | | | | |
| T-P7c GenAgg downstream | TODO | | | | |
| T-P8 budget sweep | TODO | | | | |
| T-P9 TAML | TODO | | | | |
| CHECKPOINT B | TODO | | | | |
| T-P5 paper update (pass 2) | TODO | | | | |
| T-P10 packaging | TODO | | | | |
| T-P11 anonymised snapshot | TODO | | | | |
| Final verification | TODO | | | | |

Status values: TODO / RUNNING / DONE / FAILED / BLOCKED.

## Phase 0 checks (PASS/FAIL, one line each)
## Baselines recorded (test counts, audit rows)
## Task log (one subsection per task: commands, outputs, numbers, runtime)
## Background jobs (PID, log path, watch command, state)
## Deviations (what, why, when; approved by author? y/n)
## Open questions for the author
```

---

## 1. Global invariants (apply to every task)

1. **Nothing is chosen on test.** Every free parameter is selected on the validation split
   and frozen; `--choose-on val` is the only accepted value in `ringshield.run_rings`. A
   sensitivity analysis may *vary* a parameter on test but may never *select* one from it.
2. **Causal inputs only.** No feature, score or sample may use a transaction later than the
   one being scored. Do not introduce label-derived inputs into any baseline.
3. **Frozen artefacts are read-only:** `results/FROZEN.json`, everything under
   `contract/out/`, every existing `experiments/**` and `experiments_hi_medium/**` run
   directory (their `rings.parquet`, `metrics.json`, `config.yaml`), and every existing file in
   `results/tables/`. New results go to **new** files and directories named in each task.
4. **Every new number regenerates from a run's `metrics.json`** (or, for pure re-scoring, from
   an output JSON written by a committed script with its inputs' sha256 recorded). No number
   enters the paper from a terminal printout.
5. **Tests must not regress** from the baselines recorded in Phase 0. A change in the *skip*
   count matters as much as a failure (`docs/PITFALLS.md` §8b).
6. **All new code gets unit tests** in `tests/`, including one hand-computed case.
7. **Fixed seeds.** Detector seeds are `configs/seeds.yaml` = `[1, 2, 3, 4, 5]`. Any new RNG
   (bootstrap, community detection, sampling) uses seed `20261114` unless a script already
   fixes one.
8. **Every result carries an interval; every registered comparison carries a
   Holm-corrected p.** Intervals: 2.5/97.5 percentile bootstrap over truth rings, 1,000
   resamples, seeds averaged inside each resample (`evaluation/ring_stats.py`). Paired
   precision-aware comparisons: `evaluation.ring_stats.paired_unit_bootstrap`, 10,000 draws.
   Holm is applied within the family named in the pre-registration, never across families
   after the fact.
9. **Datasets are never pooled.** HI-Small and HI-Medium numbers are reported side by side,
   never averaged or drawn on one axis as one series.
10. **HI-Small conventions** unless a task says otherwise: split train days 0–5 / val 6–7 /
    test 8–17; **primary window = test days 8–9 (174 in-scope truth rings)**; scope
    `test_visible`; one-to-one greedy matching at Jaccard ≥ 0.5 on account sets; `min_size` 3;
    5 seeds.
11. **HI-Medium conventions:** `RINGSHIELD_PATHS=configs/paths_hi_medium.yaml`; split train
    0–3 / val 4–5 / test 6–27; primary window days 6–14 (2,187 truth rings) under Amendment 15
    of `docs/V3_HIMEDIUM_PREREG.md`; tie-safe seed cut; detector `R1_gine_causal_c1prime`,
    **seeds 1–2 only — seed 3 is excluded as degenerate (saturated scores)**. Every HI-Medium
    table carries the footnote: "Detector seeds 1–2; seed 3 excluded (saturated scores, zero
    seeds under a strict quantile). The detector did not meet its pre-set validation-AP
    adequacy bar."
12. **New analysis sections in `docs/deep-analysis.md` start at §15.** Sections 12–13 are
    reserved and §14 is taken (external L4 study). Do not renumber anything.
13. **`docs/FINDINGS.md` rows are not rewritten.** New facts go in as dated notes in its
    section G, naming the row they qualify.

### Reference numbers (HI-Small, primary window, 5 seeds) — used by the reproduction checks

| Quantity | Value | Source |
|---|---|---|
| Edge F1, primary window | 0.495 ± 0.027 | `results/tables/r1_edge_metrics.csv` (label=causal) |
| Edge F1, whole test split: Multi-GINe / MEGA-GNN / GFP-XGBoost | 0.5957 ± 0.0706 / 0.6893 ± 0.0396 / 0.4996 ± 0.0062 | `r6_detector_swap.csv` |
| B0 (seeds + connected components) ring-F1 | 0.5213 [0.429, 0.607]; precision 0.814, recall 0.384 | `r9_ring_ci.csv`, `r2_ring_b0.csv` |
| B1b rule ring-F1 | 0.5553 [0.470, 0.632] | `r9_ring_ci.csv` |
| Learned expansion ("proposed") ring-F1 | 0.5819 [0.490, 0.668] | `r9_ring_ci.csv`, `r3_expansion.csv` |
| Full pipeline (`average` partition) ring-F1 | 0.5894 [0.502, 0.675]; recall 0.461 [0.393, 0.529] | `r9_ring_ci.csv`, `r4_partition.csv` |
| Same row under `scope_sensitivity.boot` | 0.5894 [0.5234, 0.6529] | `r14_scope_sensitivity.csv` |
| `full_membership` ring-F1: B0 / full | 0.1437 / 0.2428 | `r14_scope_sensitivity.csv` |
| Component scope: targets / ring-F1 full | 254 / 0.515; ≥3-account pieces: 108 in 97 rings / 0.740 (proposed 0.766) | `v36_component_scope.csv` |
| Rings with no in-window piece of ≥ 3 accounts | 77 of 174 | `v36_component_scope.csv`, `deep-analysis.md` §4 |
| Quiet-member recall: B0 / proposed / full / B1b | 0.0052 / 0.2092 / 0.2026 / 0.2229 | `r9_quiet_members.csv` |
| Added-member precision: proposed / B1b | 0.9263 / 0.5179 | `results/figures/r9_quiet_vs_precision.csv` |
| Paired precision test, proposed − B1b | +0.408 [0.342, 0.479], p_Holm 0.0008 | `v35_precision_paired.csv` |
| MEGA-GNN ring-F1: B0 / full | 0.5208 / 0.6074 [0.521, 0.688] | `r6_detector_swap.csv` |
| GFP-XGBoost ring-F1: B0 / full | 0.3435 / 0.4508 | `r6_detector_swap.csv` |
| Rings touched by seeds: Multi-GINe / MEGA | 129.6 / 128.8 of 174; seed-set Jaccard 0.415 | `r6_detector_swap.csv`, FINDINGS C6 |
| Seeds in window under the global 0.1 % rule | 463.0 ± 84.2 of 864 | `v34_window_budget.json` |
| CSGM external baseline (1 run) | precision 0.545, recall 0.069, ring-F1 0.122 | `r4_partition.csv` (row `b5`) |
| Ring-folded vs day-folded expansion policy | 0.58476 vs 0.58192, Δ +0.0028 | `deep-analysis.md` §8 |
| Validation-chosen operating point | k* = 0.1 %, `min_size` 3, every seed, every detector | `r4_partition.csv` (chosen_cells) |

---

## 2. Phase 0 — setup and verification

Every check gets one PASS/FAIL line in the progress log. **Any FAIL = STOP and report.**

| # | Check | Command / action | PASS when |
|---|---|---|---|
| 0.1 | Repository state | `git rev-parse HEAD`; `git status --short`; `git branch --show-current` | branch `integrate/main`; HEAD is `aeab2be` or a descendant (record it); untracked files listed in the log, none deleted |
| 0.2 | Copy the paper in | Copy `E:\JSJ\Ring-Shield\paper_draft\latex\*` into `paper/` so that `paper/main.tex`, `paper/sections/`, `paper/tables/`, `paper/figures/` exist. Rename `references.bib` → `paper/refs.bib` and change `\bibliography{references}` to `\bibliography{refs}`. Copy `latex/README.md` to `paper/README_LATEX.md`. Copy `paper_draft\{CLAIMS_CHECK.md, OPEN_QUESTIONS.md, REVIEW.md, ACTION_PLAN.md, make_figs.py}` into `paper/`. **Do not overwrite `paper/RUNBOOK_OPUS.md`.** | all files present; the static check of §6.6 passes on the copy |
| 0.3 | Environment | `$PY -c "import torch, torch_geometric, lightgbm, xgboost, networkx, pandas; print(torch.__version__, torch_geometric.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"` | PyTorch 2.5.1+cu121, PyG 2.8.0, CUDA available, RTX A5000 |
| 0.4 | Data manifest | `$PY scripts/data_manifest.py --check` | prints `data manifest OK` |
| 0.5 | Artefact roots exist | `ls ../RS-e2e/experiments ../RS-ccy-valrings/contract/out ../RS-ccy-valrings/experiments_valrings` | all three exist; `../RS-e2e/experiments` contains `R1_gine_causal`, `R2_b0`, `R3_expansion`, `R4_partition`, `R6_mega`, `R6_full` |
| 0.6 | Artefact roots match the frozen numbers | (a) `$PY -m pytest tests/test_frozen.py -q`. (b) For each of `R1_gine_causal/scores_test_seed1.parquet`, `R1_gine_causal/embeddings_test_seed1.parquet`, `R4_partition/runs/average/seed1/rings.parquet`: sha256 in `../RS-e2e/experiments` equals sha256 in `experiments/` (these three were recorded as byte-identical in `deep-analysis.md` §1–§2). (c) seed-1 `full` rings in `../RS-ccy-valrings/contract/out` have sha256 starting `9d1e0b9e` (`docs/REPRODUCE.md` §13 row 7). | all equal |
| 0.7 | Research test baseline | `$PY -m pytest tests contract/tests preprocessing/tests -q` | no failures. Record passed / skipped / xfailed. Last recorded 2026-10-26: 258 passed, 47 skipped, 1 xfailed; newer commits added tests, so a higher pass count is expected. **The numbers you record now are the no-regression baseline.** If passed < 258, STOP. |
| 0.8 | Platform test baseline | Read `scripts/test-db.ps1`, then run it with `..\venv-platform` activated (it needs Docker Desktop). | no failures. Record the count (last recorded: 563 passed, 2 skipped, 22 row-level-security tests). If Docker is unavailable, mark BLOCKED, record why, and continue: no task in this runbook edits `platform/`, and the final verification will need it. |
| 0.9 | Audit of headline rows | `$PY evaluation/audit_tables.py` | `traceable: 18, mismatched: 0` (or more traceable rows; never a mismatch) |
| 0.10 | Reference numbers | From the existing tables, confirm five values in §1's reference table to 4 decimals: B0 0.5213, proposed 0.5819, full 0.5894, MEGA B0 0.5208, CSGM 0.1224 | all match |
| 0.11 | GenAgg smoke test | Read `models/mega_adapter.py` lines ~130–145, ~330–350 and ~470–480 (it documents the variant flags and a known GenAgg caveat about a forward hook). Run a dry run of MEGA-GenAgg: `$PY -u models/mega_adapter.py --seeds 1 --edge-agg-type genagg --node-agg-type genagg --epochs 1 --dry-run --out-dir experiments/_smoke_megagenagg` (confirm what `--dry-run` does from the source first). Record seconds per epoch, peak VRAM (`nvidia-smi`), and any warning. | completes 1 epoch without error and without exceeding 24 GB. **On FAIL do not stop:** record the failure, then try in order (i) `--edge-agg-type genagg --node-agg-type sum`, (ii) `--edge-agg-type pna --node-agg-type sum`. Record which variant runs; this decides T-P7's arm (see T-P7 gate). If none runs, T-P7 is BLOCKED and T-P8 becomes mandatory. Delete `experiments/_smoke_megagenagg` afterwards. |
| 0.12 | LaTeX toolchain | `which pdflatex bibtex latexmk tectonic` | record the result. Not a failure if absent: then the paper is statically checked only, compiled by the author on Overleaf, and you say so in every paper task. |
| 0.13 | Web access | Fetch `https://arxiv.org/abs/2502.19952` | readable. If not, T-P6 delivers a verification checklist instead of verified text, and that is a STOP at the T-P6 gate. |

After 0.1–0.13: create `paper/RUNBOOK_PROGRESS.md`, fill the Phase 0 lines, record the sha256
of this runbook, and continue to §3.

---

## 3. Pre-registration block

Before **any** experiment or analysis in §4 runs, write `paper/PREREG_2026-11-14.md` (use the
actual date) containing the table below **verbatim**, plus for each row one sentence on the
inputs and the exact script that will compute it. Then:

1. compute its sha256 and write it, with a timestamp, into the progress log;
2. copy each row's text into `docs/deep-analysis.md` as the "Registration" subsection of that
   task's new section (§15 onward) at the moment the task starts, not before;
3. **never edit the PREREG file after the first run starts.** If a bar turns out to be
   ill-defined, that is a STOP: describe the problem, propose an amendment, and wait. An
   amendment is a new dated file, never an edit.

These analyses run on a test window that has been examined many times. They are
pre-registered to fix the reading of each outcome, and the paper will label them as
sensitivity or follow-up analyses, not as confirmatory tests.

| Task | Hypothesis / question | Metric and comparison | Success bar | Failure bar | What each outcome means for the paper |
|---|---|---|---|---|---|
| T-P1 | The protocol is implementable as one tool that reproduces existing tables | ring-F1 and CI per scope convention for shipped `full` and B0, against `r14_scope_sensitivity.csv` and `v36_component_scope.csv` | max abs deviation ≤ 1e-4 on every cell | any cell deviates by more | Success: "we release the protocol as a scorer". Failure: two code paths disagree on the protocol — a paper-level bug; everything stops. |
| T-P2 | Folding cross-scores by ring instead of by day does not change the reported rings materially | paired ring-unit bootstrap of ring-F1, ring-folded minus shipped expansion policy, 5 seeds | (already fixed by `deep-analysis.md` §8: \|mean Δ\| ≤ 0.008 → met, Δ = +0.0028.) New reading: paired 95 % CI inside [−0.02, +0.02] → "no detectable effect" | CI excludes 0 → report direction and size; CI wider than ±0.05 → "under-powered, not closed" | Success: the leak paragraph cites a measurement and an interval. CI excludes 0: the main results table caption carries the caveat. |
| T-P3 (A) | Scope conventions can change the ranking of methods | ordering of {CSGM, Louvain, Leiden, label propagation, B0, B1b, proposed, full} by ring-F1 point estimate under `test_visible`, `full_membership`, `component`, `component_ge3` | at least one adjacent pair changes order between `test_visible` and another convention | identical ordering under all four | Success: a concrete example beyond the partition step. Failure: the "re-ranks methods" claim rests on the partition swap alone, and the paper says so. |
| T-P3 (B) | Simple community detection on flagged edges is a non-trivial baseline | ring-F1 of the best community baseline vs B0 (0.5213) and vs full (0.5894); paired unit bootstrap, Holm across these two comparisons | descriptive; "competitive" if point estimate ≥ 0.5213 | — | **If any external or community baseline ≥ 0.5894: the paper drops every method-superiority sentence and T-P7 runs B0 only.** |
| T-P4 (scope) | The scope-convention gap reproduces on HI-Medium | `full_membership` minus `test_visible` ring-F1, each method, global rule | gap negative for every method **and** its absolute size exceeds the largest method effect on HI-Medium (full − B0 ring-F1) | otherwise | Reproduced: the abstract says "on two releases". Not reproduced: the audit is HI-Small-specific and the paper says so in the abstract. |
| T-P4 (observability) | A comparable share of rings has no matchable in-window piece | share of in-scope rings with no connected in-window piece of ≥ 3 accounts | within 15 percentage points of HI-Small's 44.3 % (77/174) | outside that band | Either way the number is reported; outside the band, the paper explains the difference (window length 9 days vs 2). |
| T-P4 (threshold) | The partition gain shrinks as the matching threshold tightens | full − expansion-only ring recall at Jaccard 0.3 / 0.5 / 0.7 | gain at 0.7 is less than half the gain at 0.3 | otherwise | Reproduced: the threshold-sweep recommendation stands on two releases. Not: it is stated for HI-Small only. |
| T-P7 | Ring recovery does not respond to a stronger edge detector at a fixed 0.1 % budget | d = B0 ring-F1(new detector) − 0.5213, 5 seeds; plus paired unit bootstrap new-full vs Multi-GINe-full on ring-F1 and added-member precision | **extends** if \|d\| ≤ 0.045 while test edge F1 is ≥ 5 points above Multi-GINe's 0.5957 | **contradicted** if d > 0.090; between the two: "inconclusive at 5 seeds" | Extends: a third point on the edge-vs-ring figure, claim stands. Contradicted: the claim becomes "a plateau between about 0.60 and 0.69 edge F1" and T-P8 is mandatory. |
| T-P7 seed-1 gate | The new detector is actually stronger | seed-1 test edge F1 of the new detector | ≥ 0.70 → train seeds 2–5 | < 0.70 → stop T-P7 | Gate failed: no stronger point is available; the claim is stated as bounded and T-P8 is mandatory. |
| T-P8 | "The budget binds, not the ranking" holds across budgets | \|B0 ring-F1(MEGA) − B0 ring-F1(Multi-GINe)\| at k ∈ {0.05, 0.10, 0.15, 0.20, 0.30} %, global and in-window rules | at every k and rule, the gap ≤ the larger of the two seed SDs at that row | gap > 2 seed SDs at any k ≥ 0.15 % | Holds: one sentence and one figure. Fails: the claim is restricted to k ≤ 0.10 %. |
| T-P8 (union) | Two detectors' union of touched rings (150.8) is a double-budget number | rings touched by one detector at k = 0.20 % global | ≥ 140 → supported | < 135 → not supported | Supported or not, one sentence. |
| T-P8 (veto) | — | added-member precision | any row below 0.85 is reported as "reach gained at a precision cost", never as an improvement | — | Guards against reading a larger budget as better. |
| T-P9 | A node-wise sub-network metric and attempt-level ring-F1 rank methods differently | ranking of {B0, B1b, proposed, full, TAML} by TAML's node-wise F-measure vs by ring-F1 under `test_visible` | at least one adjacent pair differs | identical | Supported: the comparison table leads the results. Not supported: one sentence. **If TAML ring-F1 > 0.5894: reported prominently; audit framing kept.** |

T-P5, T-P6, T-P10 and T-P11 are writing, verification and packaging tasks; their "bars" are
the acceptance criteria in their sections, and the PREREG file lists them as such.

---

## 4. Phases 1–N — tasks in run order

### 4.0 Run order

```
Phase 0 → PREREG → T-P6 (GATE) → T-P1 (GATE) → start T-P7a in background (GPU)
        → T-P2 → T-P3 → T-P4            (CPU, while the GPU trains)
        → T-P7b if the seed-1 gate passed (GPU, background)
        → CHECKPOINT A  ── STOP, wait for the author ──
        → T-P5 pass 1 → T-P7c → T-P8 → T-P9 (3 days, day-1 gate)
        → CHECKPOINT B  ── STOP, wait for the author ──
        → T-P5 pass 2 (§6) → T-P10 → T-P11 → Final verification (§7)
```

One GPU job at a time: T-P7 first, T-P9 second. T-P1 blocks T-P3, T-P4 and T-P9.

---

### T-P6 — Related work verified against the papers (day-1 gate)

**Goal and why.** The paper's positioning is: group-level money-laundering detection on
AMLworld already exists, but each paper uses its own unit, ground truth, matching rule and
split, and none states how a group that crosses the evaluation window is scored. A reviewer
who finds one counter-example sinks the paper. This task verifies every sentence about another
paper against the paper itself, builds the comparison table that makes the claim checkable,
and completes the bibliography. It runs first because a negative finding changes everything
downstream.

**Inputs.** `paper/sections/related.tex`, `paper/refs.bib`, the reference list in §8.3.
**Outputs.** `paper/sections/related.tex`, `paper/tables/related_comparison.tex`,
`paper/refs.bib`, `paper/RELATED_WORK_AUDIT.md`.

**Steps.**
1. For each paper in §8.3 group A (group-level) and group B (edge-level detectors on
   AMLworld), read the method and evaluation sections — and the supplement where the detail
   lives. Never characterise a paper from an abstract or a search snippet. Extract: dataset
   and release; split; unit of prediction; how ground-truth groups are built; metric and
   matching rule; whether evaluation is restricted to a window; whether groups crossing a
   split or window boundary are discussed; whether the last days of AMLworld's test period are
   treated specially; headline HI-Small numbers.
2. Specific facts to verify (each was taken from a partial read and may be wrong):
   - Rico et al. (IJCAI 2026): evaluates on HI-Small with a 70/15/15 temporal split; unit is
     the sub-network around a target account; metric is node-wise precision/recall; baselines
     AMAP, Diga, DenseFlow; how true sub-networks are built from the data (in the supplement).
   - Tian et al. (WWW 2025): what its group-level ground truth and metric are on AMLworld.
   - Tariq, Kaja, Hassani (2026): what the "refined evaluation metric" measures and on what.
   - Bilgi, Chen, Atasu: the reported HI-Small edge F1 for MEGA-GIN (0.7083 ± 0.0218 is
     recorded in `docs/paper/generalisation.md`) and MEGA-GenAgg (74.88 ± 0.38 is recorded in
     `docs/FUTURE_IMPLEMENTATIONS.md`), and the paper's publication venue.
   - Tariq & Hassani (SAC 2026): its HI-Small minority F1.
3. Search for any peer-reviewed or arXiv statement of (a) the jump in AMLworld's laundering
   base rate in the last days of the test period, (b) the day-0 volume burst, (c) sensitivity
   of group-level scores to a scope convention, (d) edge-level and group-level metrics
   disagreeing. A practitioner repository (github.com/Kluey/AML-Transaction-Detection) notes
   (a) informally; that is already footnoted.
4. Write `paper/tables/related_comparison.tex` (booktabs; one row per group-level paper;
   columns: unit, ground truth, metric / matching, split, scope rule stated, tail handled).
   A cell you could not verify says "n.v." and is listed in the audit file.
5. Rewrite `paper/sections/related.tex` to about 0.7 page (ACM two-column) around that table,
   keeping four paragraphs: edge-level detection; group-level detection; benchmark artefacts;
   statistics. No sentence claims "first". Be fair: if a paper states a scope rule or handles
   the tail, say so.
6. Complete `paper/refs.bib`: full author lists, venue, year, pages or arXiv id, DOI where one
   exists. Three entries currently have "and others" (`chai2023`, `tian2025`, `khosla2020`).
   Target about 35 entries, none uncited.
7. Write `paper/RELATED_WORK_AUDIT.md`: for every sentence in `related.tex` that describes
   another paper, the paper, the section/page where it was verified, and the quote or number.

**Tests / checks.** Every `\cite` key resolves; no uncited entry; no "and others" unless the
list is genuinely unavailable (then listed); every characterising sentence has an audit row.

**Acceptance.** Comparison table exists with no silently filled cell; audit file complete;
bibliography complete.

**GATE (hard).**
- **PASS** — no paper already does what this paper claims as a contribution (scope-rule
  sensitivity of ring-level scores; a quantified test-tail artefact with a ring-level or
  seed-budget consequence; edge-level and ring-level metrics decoupling under a detector
  swap; a count of unobservable targets). Continue to T-P1.
- **FAIL / STOP** — any one of those is already published, or two or more group-level papers
  state an explicit scope rule for cross-window groups, or more than a third of the papers
  were inaccessible. Write a one-page summary (what was found, where, which of our claims it
  touches, and a proposed re-positioning) and wait for the author.

**Stop-and-ask.** No web access; a paper's supplement is unobtainable and the claim depends on
it; conflicting versions of a paper.

**Results note** → `results/notes/p6_related_work.md`: "finding; where verified; which
positioning sentence it supports / weakens / kills."

**Paper hook.** Related work (Section 2), the new comparison table, `refs.bib`; the
introduction's first paragraph cites the same works.

---

### T-P1 — Standalone protocol scorer (gate for T-P3, T-P4, T-P9)

**Goal and why.** One command that takes any file of predicted rings — ours or an external
method's — and reports ring-level metrics under every convention the paper discusses. It
answers "is the protocol a reusable artefact or your own scripts?" and every baseline task
depends on it.

**Inputs.** `evaluation/scope_sensitivity.py`, `evaluation/component_scope.py`,
`evaluation/ring_stats.py`, `evaluation/ring_metrics.py`, `evaluation/unmatched_rings.py`,
the `eval` subcommand of `python -m ringshield`, `configs/eval_window.yaml`,
`data/processed/amlworld_ring_ground_truth.parquet`; run directories
`experiments/R4_partition/runs/average/seed{1..5}` and `experiments/R2_b0/gine_causal/seed{1..5}`
(or the same under `../RS-e2e/experiments`).
**Outputs.** `evaluation/score_external.py`, `tests/test_score_external.py`,
`docs/PROTOCOL.md`, `results/notes/p1_scorer.md`.

**Definitions it must implement by importing existing code, not rewriting it.**
- `test_visible`: a ring is in scope if it has ≥ 1 transaction in the window; members = the
  accounts of its in-window transactions.
- `full_membership`: same rings; members = all the ring's accounts.
- `component`: each in-window connected piece of a `test_visible` ring (its in-window truth
  edges joined when they share an account) is its own target.
- `component_ge3`: the same, keeping pieces with ≥ 3 accounts.
- Matching: greedy one-to-one by descending Jaccard on account sets, threshold 0.5; also 0.3
  and 0.7. `min_size` 3 applies to the unrestricted prediction; matching uses the prediction
  restricted to the window.

**Steps.**
1. Read the five evaluation modules and the `eval` subcommand. Note in the task log which
   function provides which piece, and whether any two disagree.
2. Create `evaluation/score_external.py`:
   - `--rings PATH [PATH ...]` one file per seed/run; accepts the repository's `rings.parquet`
     schema and a minimal schema (`ring_id`, `members: list[int]`) in parquet or JSONL;
   - `--split {val,test}`, `--window {primary,tail,whole}`, dataset paths via `load_paths()`
     (so `RINGSHIELD_PATHS` selects HI-Medium), `--eval-window` defaulting to the dataset's
     window file, `--min-size 3`, `--thresholds 0.3 0.5 0.7`, `--n-boot 1000`, `--out DIR`;
   - writes `DIR/metrics.json` and `DIR/summary.csv`: per convention × threshold — n_targets,
     ring precision, recall, F1 with 95 % CI, `ring_recall_ge3`, member coverage, per-pattern
     recall; an `observability` block — rings with < 3 visible members, rings with no
     in-window piece of ≥ 3 accounts, share of pieces recovered on rings that have one;
   - writes `DIR/config.json` (git commit, input sha256s, arguments);
   - `--compare DIR_A DIR_B` runs `ring_stats.paired_unit_bootstrap` (10,000 draws) on ring-F1.
3. Write `docs/PROTOCOL.md`: the definitions above, the command, the output schema, and the
   reporting checklist (scope rule, split, window, budget allocation across days, tie-handling
   of quantile cuts, threshold sweep, observability, precision beside recall).
4. Runtime: minutes on CPU.

**Unit tests.** `tests/test_score_external.py` with a hand-built fixture — three truth rings
(one split into two in-window pieces, one with two visible members) and four predictions:
assert exact Jaccard values, one-to-one matching, target counts per convention, and that a
prediction spanning two pieces matches only one. Minimal-schema and full-schema inputs of the
same rings give identical metrics.

**Reproduction check (tolerance 1e-4).** Scoring the five shipped `full` runs returns
`test_visible` 0.5894 [0.5234, 0.6529], `full_membership` 0.2428, `component` 0.515,
`component_ge3` 0.740, targets 174 / 174 / 254 / 108, and 77 rings with no ≥ 3 piece. Scoring
the five B0 runs returns 0.5213 and 0.1437.

**Acceptance.** Reproduction passes for `full` and B0; tests pass; research suite at baseline.

**GATE (hard).** PASS → continue. **FAIL → STOP everything:** the protocol has two code paths
that disagree. Report both values, both call sites, and the input.

**Stop-and-ask.** A run directory exists in neither `experiments/` nor `../RS-e2e/experiments`;
a pre-existing test fails before you change anything.

**Results note** → `results/notes/p1_scorer.md`: reproduced values, max absolute deviation,
what it means ("the protocol is a single tool; the paper may say it is released").

**Paper hook.** Evaluation-protocol section (one sentence + footnote to the anonymised
repository), Reproducibility appendix.

---

### T-P7 — A third, stronger detector: MEGA-GNN with GenAgg aggregation (GPU, background)

**Goal and why.** The paper claims edge F1 is not a proxy for ring recovery: MEGA-GNN beats the
reference Multi-GINe by 9.4 points of test edge F1 and yields the same baseline rings. A
reviewer will say the claim rests on two detectors nine points apart and a weak reference.
`docs/FUTURE_IMPLEMENTATIONS.md` (F4) records MEGA-GenAgg as the strongest published HI-Small
detector (74.88 ± 0.38). Train it under our causal sampler and run it through the ring layer.

**Inputs.** `models/mega_adapter.py` (flags read at `aeab2be`: `--seeds`, `--out-dir`,
`--epochs` default 80, `--patience` default 20, `--batch-size` default 8192, `--num-neighs`,
`--window-s`, `--splits`, `--embeddings-for`, `--non-causal`, `--dry-run`,
`--edge-agg-type {gin,genagg,pna,sum}`, `--node-agg-type {sum,genagg}`),
`third_party/mega_gnn` (upstream commit `ef60a71`), `third_party/shims/`,
`experiments/R6_mega/config.yaml` (the MEGA-GIN run to mirror), `docs/REPRODUCE.md` §3–§5, §8.
**Outputs.** `experiments/R6_megagenagg/` (scores, embeddings, calibrators, logs,
`config.yaml`), `experiments/R6_b0/megagenagg/seed{S}`, `experiments/R6_full/megagenagg/`,
`results/tables/r6_detector_swap_v2.csv`, `deep-analysis.md` §15+, `results/notes/p7_genagg.md`.

**T-P7a — seed 1 (≈ 4–8 GPU-hours; measure in the smoke test).**
1. Arm: the variant that passed Phase 0 check 0.11, in the order genagg/genagg →
   genagg/sum → pna/sum. Log any variant other than genagg/genagg as a deviation, and name
   the detector accordingly in every table.
2. Read lines ~470–480 of the adapter: it documents a caveat about GenAgg as published
   (an inverse-objective forward hook that never fires). Record that caveat verbatim in the
   run's `config.yaml` notes and in the results note.
3. Re-run the existing table builder first: `$PY -u evaluation/r6_detector_swap.py` into a
   scratch output (read its arguments; do **not** overwrite `r6_detector_swap.csv`) and confirm
   it reproduces the Multi-GINe and MEGA rows exactly.
4. Launch in the background, mirroring `R6_mega/config.yaml` for every other setting:
   `nohup $PY -u models/mega_adapter.py --seeds 1 --edge-agg-type genagg --node-agg-type genagg --out-dir experiments/R6_megagenagg > experiments/R6_megagenagg/train_seed1.log 2>&1 &`
   Record PID and the watch command.
5. When it finishes: record best validation F1, validation AP, test edge F1 at the
   validation-chosen threshold, epochs, seconds per epoch.

**GATE — seed 1.** Test edge F1 ≥ 0.70 → PASS, start T-P7b. Below 0.70 → **T-P7 ends here**:
mark T-P7b/c SKIPPED, write the note, and mark T-P8 as mandatory in the progress log.

**T-P7b — seeds 2–5 (background; ≈ 4× seed 1).** Same command with `--seeds 2 3 4 5`. Then
score validation and test and calibrate as `REPRODUCE.md` §8 does for MEGA
(`$PY models/calibrate.py --scores-dir experiments/R6_megagenagg --seeds 1 2 3 4 5`; read its
arguments first).

**T-P7c — downstream (CPU, ≈ 2–3 h).**
1. B0 per seed: `$PY -m ringshield.run_rings --aggregator cc --scores-val … --scores-test … --model-id megagenagg --seed S --out experiments/R6_b0/megagenagg/seedS`.
2. **Unless the T-P3 (B) gate fired** (a baseline ≥ 0.5894, in which case stop at B0): build
   the detector-specific expansion policy and affinity model and run `run_expand` and
   `run_partition` exactly as was done for MEGA (`experiments/R6_full/mega/` shows the
   layout; follow its `config.yaml` files).
3. Extend `evaluation/r6_detector_swap.py` to include the new detector and write
   `results/tables/r6_detector_swap_v2.csv`. Compute seed-set Jaccard and touched-ring overlap
   against Multi-GINe and MEGA.
4. Paired unit bootstrap: new-full vs Multi-GINe-full, ring-F1 and added-member precision.

**Unit tests / checks.** The causality check used for the MEGA run passes on the new run (no
sampled neighbour later than the batch's latest seed; within-batch window recorded). The
calibrator is fitted on validation rows only (assert counts). The v2 table's Multi-GINe and
MEGA rows equal the v1 table's.

**Acceptance and bar.** As in §3 (T-P7): extends / contradicted / inconclusive.

**Stop-and-ask.** Out of memory at the published batch size (report the largest that fits; do
not shrink the model silently); seconds per epoch > 2× MEGA's 238 s after the smoke-test
estimate; the existing table does not reproduce; a downstream stage picks a validation cell
at the edge of its grid on three or more seeds; d > 0.090 (finish the table, then stop before
editing FINDINGS).

**Results note** → `results/notes/p7_genagg.md`: edge F1 (mean ± SD, vs published 74.88);
B0 and full ring-F1 with CIs; d; paired Δ, CI, p; verdict against the bar; "supports /
weakens / kills: edge F1 is not a proxy for ring recovery".

**Paper hook.** The edge-F1-vs-ring-F1 figure (`paper/make_figs.py`, a fourth point), the
detector table, one sentence in Limitations.

---

### T-P2 — Close the ring-folded cross-score item

**Goal and why.** `docs/FINDINGS.md` row B17: the expansion policy's training inputs were
cross-scored with folds that hold out a day, but rings span days, so a fold model saw labels
from rings it then scored. A ring-folded re-run (`deep-analysis.md` §8) finished with mean Δ
ring-F1 +0.0028, inside the registered ±0.008. Four quantities promised beside the verdict
are still "not yet computed". Computing them lets the paper close the leak with an interval.

**Inputs.** `experiments/R3_ringfold/runs/proposed/seed{1..5}` (+ `cross_scores/`,
`expansion/`, `chain.log`), `experiments/R3_expansion/runs/proposed/seed{1..5}` (or under
`../RS-e2e/experiments`), `experiments/R3_cross_scores/`, `evaluation/ring_stats.py`,
`evaluation/precision_paired.py`.
**Outputs.** `evaluation/ringfold_report.py`, `tests/test_ringfold_report.py`,
`results/tables/v39_ringfold_report.{csv,json}`, edits to `deep-analysis.md` §8 and FINDINGS
section G, `results/notes/p2_ringfold.md`.

**Steps (CPU, < 15 min).**
1. Reproduce from `metrics.json` the ten per-seed ring-F1 values:
   shipped → ring folds: 0.5985→0.6074, 0.5940→0.5950, 0.5649→0.5768, 0.6204→0.6075,
   0.5318→0.5371. Any 4th-decimal mismatch is a STOP.
2. `evaluation/ringfold_report.py` computes, primary window, 5 seeds:
   (i) paired ring-unit bootstrap CI and p for ring-F1 and for added-member precision,
   ring-folded minus shipped (10,000 draws, seed 20261114);
   (ii) ring precision and recall per arm and their paired differences;
   (iii) share of shipped rings reproduced exactly (same account set) and share matched at
   Jaccard ≥ 0.5;
   (iv) held-out AP and ROC-AUC of the ring-folded fold models on ring edges against the
   day-folded ones, per fold, with the number of ring edges per fold;
   (v) from the fold records: rings spanning day folds, and edges moved.
3. Replace the "Not yet computed" bullet in `deep-analysis.md` §8 with the numbers; add a
   dated note in FINDINGS section G naming row B17. Do not edit the row itself.

**Unit tests / checks.** On a three-ring fixture, exact-reproduction share and Jaccard overlap
equal hand-computed values. The bootstrap's point estimate of Δ ring-F1 equals +0.0028 to 4
decimals. Re-assert from the parquet that no ring-folded model was supervised on an edge of a
ring it scores.

**Acceptance and bar.** §3 (T-P2). The registered verdict (success) is not re-opened.

**Gate.** CI inside [−0.02, +0.02] → note says "no detectable effect". CI excludes 0 → flag
for T-P5 (table-caption caveat). CI wider than ±0.05 → note says "under-powered; not closed".
All three continue.

**Stop-and-ask.** Per-seed values do not reproduce; a seed directory is incomplete; the
leak-free assertion fails.

**Results note** → "Δ ring-F1, CI, p; share of rings reproduced; supports / weakens: 'the
ring-level leak does not change the reported rings'."

**Paper hook.** Limitations paragraph on the leak (two sentences, one number, one interval).

---

### T-P3 — Classical external baselines under the protocol

**Goal and why.** The first reviewer objection is "no external ring-level baseline". Score
simple, reproducible group-detection baselines with T-P1's scorer under every convention.
The paper needs to show where standard community detection sits relative to seeds-plus-
components, and whether rankings move with the scope convention.

**Inputs.** `experiments/R1_gine_causal/scores_{val,test}_seed{S}.parquet`,
`experiments/R2_b0/gine_causal/seed{S}` (B0), `experiments/R3_expansion/runs/{b1b,proposed}/seed{S}`,
`experiments/R4_partition/runs/average/seed{S}` (full), `evaluation/csgm_baseline.py`
(flags read at `aeab2be`: `--out`, `--seed`, `--bank-seed` default 0, `--min-size`, `--scope`,
`--eval-window`), `external/Collaborative-AML` (upstream commit `2db6537`, git-ignored),
`configs/threshold_rule.yaml` (the B0 grid), `evaluation/score_external.py`.
**Outputs.** `evaluation/community_baselines.py`, `tests/test_community_baselines.py`,
`experiments/R13_baselines/<method>/seed{S}/{rings.parquet,metrics.json,config.yaml}`,
`results/tables/v40_external_baselines.{csv,json}`, `deep-analysis.md` §15+,
`results/notes/p3_baselines.md`.

**Steps (CPU, ≈ 3–4 h).**
1. Copy the T-P3 registration rows into a new `deep-analysis.md` section before running.
2. Reproduce B0 for seed 1 into a scratch directory with
   `$PY -m ringshield.run_rings --aggregator cc --scores-val … --scores-test … --model-id gine_causal --seed 1 --out <scratch>`
   and confirm primary ring-F1 equals `experiments/R2_b0/gine_causal/seed1/metrics.json`.
3. `evaluation/community_baselines.py` builds the **flagged-edge graph** of a split —
   accounts as nodes, an edge for every top-k % raw-score transaction, weight = the maximum
   raw score between the two accounts — and runs:
   - `louvain` (`networkx.community.louvain_communities`, resolution ∈ {0.5, 1, 2});
   - `leiden` (same grid) if `leidenalg` + `python-igraph` install cleanly into `.venv312`;
     record versions in the run config; **do not edit `requirements-lock.txt`**; if it does not
     install, skip it with a logged reason;
   - `label_propagation` (`networkx.community.asyn_lpa_communities`, seeded).
   k grid = the B0 grid in `configs/threshold_rule.yaml`; `min_size` 3; all choices on
   validation ring-F1, recorded with the full grid in `config.yaml`.
   Also run each method as a *partition alternative* on the learned policy's expanded subgraph
   (`R3_expansion/runs/proposed/seed{S}`); note `r4_partition.csv` row `b4` already records a
   Louvain partition with mean-affinity weights at ring-F1 0.582.
4. CSGM: confirm `--bank-seed 0` reproduces ring-F1 0.1224, then run bank seeds 1–4. CSGM
   uses no detector, so its five runs differ only by the random two-institution split.
5. Score all runs and our four methods with `evaluation/score_external.py`: primary window,
   four conventions, thresholds 0.3 / 0.5 / 0.7.
6. Paired unit bootstrap, Holm across two comparisons: best community baseline vs B0; best
   community baseline vs full.
7. Optional, half a day at most: FlowScope (github.com/aplaceof/FlowScope). If it does not run
   on Windows in that time, log why and move on.

**Unit tests / checks.** Two cliques joined by one edge → Louvain returns two rings; output
validates against the rings schema `ringshield eval` reads. With every component forced into
one community, ring-F1 equals B0's on that seed.

**Acceptance and bars.** §3, T-P3 (A) and (B).

**GATE.**
- Any baseline ring-F1 ≥ 0.5894 under `test_visible` → finish the table, write the note, set
  the flag `METHOD_SUPERIORITY=OFF` in the progress log (T-P5 removes every
  method-superiority sentence; T-P7c stops at B0), and **raise it at Checkpoint A**.
- Otherwise continue.

**Stop-and-ask.** B0 does not reproduce; a baseline needs a parameter that could only be
chosen on test; total runtime > 8 h.

**Results note** → per method: ring-F1, CI under each convention; the two paired Δ with CI and
p_Holm; bar (A) verdict; "supports / weakens: 'conventions re-rank methods' and 'the reference
pipeline is not a strawman's opponent'".

**Paper hook.** Main results table (new rows above B0), the scope-convention figure
(`paper/make_figs.py`), one paragraph in Results.

---

### T-P4 — Replicate the audit on HI-Medium

**Goal and why.** The audit findings — scope gap, unobservable targets, threshold-dependent
partition gain — are shown on one release with 174 rings. HI-Medium close-out rings exist
with 2,187 truth rings. Re-measure every audit finding there with **no new training**, so the
paper can say "reproduced on a second release" or say exactly where it is not.

**Inputs.** `experiments_hi_medium/closeout_a15/` (rings per window, rule [global, per-day],
method, seed; `log_seed{1,2}.json`), `evaluation/hm_closeout.py`,
`evaluation/hm_closeout_report.py`, `results/tables/v3_closeout_{p1,p2,p3,blocks}.csv`,
`v3_closeout_verdicts.json`, `v3_day_profile_HI-Medium.csv`, `v33_seed_by_day.csv`,
`configs/paths_hi_medium.yaml`, `configs/eval_window_hi_medium.yaml`,
`evaluation/in_window_connectivity.py`, `docs/V3_HIMEDIUM_PREREG.md` (Amendments 13–15).
**Outputs.** `evaluation/hm_audit.py`, `tests/test_hm_audit.py`,
`results/tables/v41_hm_audit_{scope,component,threshold,tail}.csv` and one JSON,
`deep-analysis.md` §15+, FINDINGS section-G note, `results/notes/p4_hm_audit.md`.

**Steps (CPU, ≈ 1–3 h).**
1. Registration rows into `deep-analysis.md` first.
2. With `RINGSHIELD_PATHS=configs/paths_hi_medium.yaml`, reproduce from the rings (global
   rule, seeds 1–2): full ring recall 0.187 [0.174, 0.200]; Ring-Recall≥3 0.264
   [0.246, 0.280]; untouched share 28.7 %; full − expansion-only matched rate +0.015
   [+0.010, +0.020]; policy − rule +0.047 [+0.037, +0.057].
3. Scope: for B0, B1b, proposed (expansion-only), full × {global, per-day}: ring
   precision / recall / F1 with CIs under `test_visible` and `full_membership`; the gap;
   median member-set size under each.
4. Component: number of targets; rings with < 3 visible members; rings with no in-window
   piece of ≥ 3 accounts; pieces recovered by full on rings that have one; ring-F1 under
   `component` and `component_ge3`; whether B0 < B1b < proposed < full holds, and whether
   proposed > full under `component_ge3` again.
5. Threshold: full − expansion-only ring recall and ring-F1 at Jaccard 0.3 / 0.5 / 0.7.
6. Tail and budget: per test day — edges, base rate, share of global-quantile seeds
   (seeds 1–2). Expected from existing tables: days 16–27 hold 6,987 edges at about 58 %;
   day 15 takes about 87.5 % of global seeds on seed 1.
7. If it takes under 2 hours: in-window disconnection of the missing members of
   under-covered rings, as `evaluation/in_window_connectivity.py` does for HI-Small
   (HI-Small: 176 of 216 = 81.5 %). Otherwise record "not done".
8. Cross-check: run the same code path on HI-Small `full` and confirm 77 of 174 and the
   `r14` gap (−0.347 for full).

**Unit tests / checks.** Pieces partition each ring's visible member set (assert). The
`test_visible` rows equal the close-out report exactly. Every output table carries the
seed-3 / adequacy-bar footnote text of invariant 11 in a `note` column or header comment.

**Acceptance and bars.** §3, three T-P4 rows. "Not reproduced" is a result.

**GATE.** Set `HM_AUDIT=REPRODUCED` if the scope bar passes (the other two are reported
either way); else `HM_AUDIT=NOT_REPRODUCED`. Both continue; the flag drives the abstract in
T-P5 and is **raised at Checkpoint A**. If any finding flips sign, finish the tables and stop
before editing FINDINGS.

**Stop-and-ask.** Close-out numbers do not reproduce; HI-Medium ground truth or paths file
missing; runtime > 6 h; the HI-Small cross-check does not return 77/174.

**Results note** → per finding: HI-Small value, HI-Medium value with CI, bar verdict;
"supports / weakens / kills: 'the audit findings hold on a second release'".

**Paper hook.** A "second release" subsection of the benchmark-audit section;
`paper/tables/hm_audit.tex`; a two-panel figure (scope gap; observability), HI-Small and
HI-Medium side by side, never pooled.

---

### CHECKPOINT A — STOP

Write `paper/CHECKPOINT_A.md` and end your turn. Contents:

1. Status table of every task so far, with gate results.
2. T-P6: positioning verdict; any paper that touches a claim.
3. T-P1: max deviation.
4. T-P2: Δ, CI, reading.
5. T-P3: the full baseline table; bar (A) verdict; `METHOD_SUPERIORITY` flag.
6. T-P4: three bars; `HM_AUDIT` flag.
7. T-P7: seed-1 gate result; training status; ETA.
8. Decisions needed from the author, each with your recommendation:
   - framing if `METHOD_SUPERIORITY=OFF`;
   - abstract wording if `HM_AUDIT=NOT_REPRODUCED` (and whether to retarget the workshop);
   - whether to run T-P9;
   - anything in Deviations.
9. The list of files changed since Phase 0, for her to commit.

Resume only when the author replies. Record her decisions in the progress log.

---

### T-P5 pass 1 — Sync the paper with the repository

**Goal and why.** The draft in `paper/` predates `aeab2be`. Bring every claim in line with the
repository and with T-P2/T-P3/T-P4, keeping the audit framing. Full instructions are in §6;
pass 1 does §6.1–§6.3 (content). Pass 2, after Checkpoint B, does the rest.

**Gate.** The stale-phrase grep of §6.6 returns nothing; `paper/CLAIMS_CHECK.md` has a row for
every new number and no mismatch.

---

### T-P8 — Budget sweep for every detector

**Goal and why.** Two claims are stated at one seed budget (top 0.1 % of scores): "a stronger
edge detector buys no rings" and "the budget, not the ranking, binds". Show whether they hold
across budgets and under both ways of counting the budget. **Mandatory if T-P7 was skipped,
failed its gate, or was contradicted.**

**Inputs.** `evaluation/window_budget.py` (global / in_window / per_day masks; B0 and full at
shipped cells), `evaluation/r9_robustness.py`, `evaluation/realloc_full.py`; scores in
`experiments/R1_gine_causal`, `experiments/R6_mega`, `experiments/R2_b0/gfpxgb_scores`, and
`experiments/R6_megagenagg` if it exists; per-detector policies and affinity models under
`R3_expansion`, `R4_partition`, `R6_full`, `R6_gfpxgb_*` (or under `../RS-e2e/experiments`).
**Outputs.** `evaluation/budget_sweep.py`, `tests/test_budget_sweep.py`,
`experiments/R14_budget_sweep/<detector>/<rule>/k<pct>/seed{S}/metrics.json`,
`results/tables/v42_budget_sweep.{csv,json}`, a figure via `paper/make_figs.py`,
`deep-analysis.md` §15+, `results/notes/p8_budget.md`.

**Steps (CPU, ≈ 6–8 h; about 4 minutes per detector × rule × k × seed for the full pipeline).**
1. Registration rows into `deep-analysis.md`.
2. Reproduce `v34_window_budget.csv`'s global and in-window rows for Multi-GINe
   (129.6 / 0.521 / 0.589 / 0.926 and 148.2 / 0.503 / 0.546 / 0.700).
3. Sweep k ∈ {0.05, 0.10, 0.15, 0.20, 0.30} % × rule ∈ {global, in_window} × detector × seed.
   **Only the seed mask changes.** Each detector keeps its own validation-chosen expansion and
   partition cells; nothing is re-tuned per budget. Record: seeds in window, rings touched,
   B0 and full ring precision / recall / F1, untouched count, matched rings, added-member
   precision (in-window expanded edges only — the definition behind
   `results/figures/r9_quiet_vs_precision.csv`).
4. Per k: seed-set Jaccard and touched-ring union between Multi-GINe and MEGA.

**Unit tests / checks.** k = 0.10 % global reproduces each detector's published row to 4
decimals; seeds-in-window is monotone in k for every seed; the shipped row's added-member
precision is 0.926.

**Acceptance and bars.** §3, three T-P8 rows. This is a sensitivity analysis: the operating
point stays the validation-chosen 0.1 % and no reported number changes.

**Gate.** Bars reported; continue either way. If the "fails" bar triggers, set
`EDGE_RING_CLAIM=RESTRICTED` for T-P5 pass 2.

**Stop-and-ask.** Shipped rows do not reproduce; a detector's policy or affinity model is
missing; runtime > 16 h; any row would need a cell re-chosen on test.

**Results note** → per k and rule: MEGA − Multi-GINe B0 ring-F1 with both SDs; union result;
vetoed rows; "supports / weakens: 'the budget binds'".

**Paper hook.** One figure (ring-F1 against seeds-in-window, one line per detector), one
sentence qualifying the edge-vs-ring claim; table in the appendix.

---

### T-P9 — A learned sub-network baseline (TAML) under the protocol — 3 days, day-1 gate

**Goal and why.** The closest published work is Rico et al., "Translating Latent
Representations for Money Laundering Detection" (IJCAI 2026; code
github.com/rricocuevas1/taml), which does joint account classification and sub-network
discovery and evaluates on HI-Small with a node-wise metric on the sub-network around each
account. Run its extractor on our split and score it with our protocol; score our rings with
its metric. The point is not to win: it is to show whether the two evaluations rank methods
the same way.

**Inputs.** The TAML repository (clone to `external/taml`, git-ignored),
`data/processed/amlworld_{train,val,test}.parquet`,
`data/processed/amlworld_ring_ground_truth.parquet`, `evaluation/score_external.py`, our four
methods' run directories.
**Outputs.** `experiments/R15_taml/` (patches, configs, environment record, predictions,
`metrics.json`), `evaluation/taml_metric.py`, `tests/test_taml_metric.py`,
`results/tables/v43_taml_under_protocol.{csv,json}`, `deep-analysis.md` §15+,
`results/notes/p9_taml.md`.

**Day 1 — feasibility.** Clone; create a **separate** virtual environment if its pins conflict
with `.venv312` and record it; run its own HI-Small example for one epoch. If it does not run
natively on Windows, try WSL2 with the same GPU. Attempt to reproduce one headline number
from the paper on its own split (record the number and the gap).

**GATE — end of day 1.** GO if the code trains for an epoch on HI-Small and you can see how to
feed it our split without editing model code. **NO-GO otherwise: stop T-P9**, write a one-page
note on why (the paper cites it as a limitation), and go to Checkpoint B.

**Days 2–3.**
1. Registration into `deep-analysis.md`, including the conversion rule below, **before any
   test scoring**.
2. Train on our train days 0–5 only; choose every threshold on validation days 6–7; three
   seeds (1, 2, 3).
3. **Conversion rule (fixed):** take the predicted sub-network of every test-window account
   whose risk score exceeds a validation-chosen threshold; drop sub-networks with fewer than
   three accounts; sort by risk; greedily keep a sub-network unless its Jaccard with an
   already-kept one is ≥ 0.5; the kept sets are the predicted rings. One revision of this rule
   is allowed after seeing validation results, recorded as an amendment file.
4. Score with `evaluation/score_external.py` (four conventions, three thresholds).
5. `evaluation/taml_metric.py`: their node-wise precision and recall as their problem
   definition states it; apply to B0, B1b, proposed, full and to TAML's output.

**Unit tests / checks.** A hand-built five-node example for the metric; the conversion is
deterministic and unit-tested.

**Acceptance and bar.** §3 (T-P9).

**Stop-and-ask.** The code needs model edits to accept our split; training > 2× its estimate;
its own number cannot be approximately reproduced and you cannot find why; a second revision
of the conversion rule would be needed; end of day 3 reached with no test result (stop, report
what exists).

**Results note** → TAML ring-F1 with CI per convention; node-wise P/R for all five methods;
both rankings; bar verdict; "supports / weakens: 'evaluations of group-level AML are not
interchangeable'".

**Paper hook.** One row group in the results table, one paragraph in Related work or Results,
or one limitation sentence if NO-GO.

---

### CHECKPOINT B — STOP

Write `paper/CHECKPOINT_B.md` and end your turn: T-P7 verdict against its bar with the v2
table; T-P8 bars; T-P9 result or NO-GO note; the flags `METHOD_SUPERIORITY`, `HM_AUDIT`,
`EDGE_RING_CLAIM`; a proposed final abstract (≤ 180 words) and contribution list reflecting
all of them; a proposed cut list for the 8-page limit with lines saved per cut; files changed
since Checkpoint A. Resume when the author replies.

---

### T-P5 pass 2, T-P10, T-P11

See §6 (paper update and packaging) and §7 (final verification, including the anonymised
snapshot).

---

## 5. Decision gates and checkpoints — summary

| Gate | Where | Condition | PASS → | FAIL → |
|---|---|---|---|---|
| Phase 0 | §2 | every check PASS (0.8 may be BLOCKED; 0.11 has fallbacks; 0.12 may be absent) | continue | STOP, report |
| PREREG frozen | §3 | file written, sha256 logged before any run | continue | no experiment may start |
| Prior work | T-P6 | no paper already makes one of our four contribution claims; papers accessible | continue | STOP, one-page re-positioning proposal |
| Protocol reproduction | T-P1 | all cells within 1e-4 of `r14` / `v36` | continue | **STOP everything** |
| Stronger detector | T-P7a | seed-1 test edge F1 ≥ 0.70 | train seeds 2–5 | end T-P7; T-P8 mandatory; claim stated as bounded |
| Baseline strength | T-P3 | no baseline ≥ 0.5894 | continue | `METHOD_SUPERIORITY=OFF`; T-P7c B0 only; raise at Checkpoint A |
| Audit replication | T-P4 | scope bar met | `HM_AUDIT=REPRODUCED` | `HM_AUDIT=NOT_REPRODUCED`; raise at Checkpoint A |
| **Checkpoint A** | after T-P4 | — | **STOP and wait** | — |
| Edge-vs-ring | T-P7c | \|d\| ≤ 0.045 | claim extends | d > 0.090: STOP before FINDINGS; claim becomes "plateau"; T-P8 mandatory |
| Budget | T-P8 | gap ≤ seed SD at every k | one sentence | `EDGE_RING_CLAIM=RESTRICTED` |
| TAML feasibility | T-P9 day 1 | trains one epoch; our split feedable without model edits | days 2–3 | NO-GO note; skip |
| **Checkpoint B** | after T-P9 | — | **STOP and wait** | — |
| Page limit | T-P10 | body ≤ 8 pages | continue | propose cuts; apply only with approval |
| Anonymity | T-P11 | grep of the snapshot and the blind PDF source returns nothing | continue | fix and re-grep; never ship a dirty snapshot |

---

## 6. Paper update phase (T-P5 pass 1 and 2, T-P10)

The paper lives in `paper/`: `main.tex`, `sections/{abstract,introduction,related,data,findings,method,results,recommendations,limitations,conclusion,appendix}.tex`,
`tables/*.tex`, `figures/`, `refs.bib`, `make_figs.py`, `CLAIMS_CHECK.md`,
`OPEN_QUESTIONS.md`. Current title: *Rings, Not Edges: What AMLworld Can and Cannot Tell Us
About Recovering Money-Laundering Attempts*. Section order: Introduction, Related work,
Evaluation protocol, Benchmark audit, Reference pipeline, Results, Where ring recovery stops,
Recommendations, Limitations, Conclusion; appendix: Reproducibility, Additional results,
Corrections, System context.

### 6.0 Rules for every edit

- Every number in a `.tex` file is followed by a comment `% source: <repo path> (<row/column>)`.
  No source file → write `[NO SOURCE]` and do not estimate.
- Headline numbers are HI-Small, primary window. HI-Medium numbers carry the invariant-11
  footnote and are never pooled with HI-Small's.
- Plain, precise English. No "novel", "state-of-the-art", "groundbreaking". Never upgrade
  "not significant" to "promising". Negative results are stated as results.
- **No internal codes in prose.** Describe the thing. Codes may appear only in `% source`
  comments. This includes: A/B/C/E row codes, R1–R12 and R12b, P1–P4, "Amendment 15",
  "close-out", "Step 6", "V3", "11b/11c", "L0–L6", `b0`/`b2`/`b5` as bare codes (write "seeds
  and connected components", "expansion only", "CSGM"), `gine_causal`, `megagenagg`.
- No dated-correction narrative in the body. Corrections live in one short appendix
  paragraph.
- Only packages the venue class allows; relative paths; `\ci{x}{lo}{hi}` for intervals.
- Do not invent citations. Every citation is in `RELATED_WORK_AUDIT.md`.

### 6.1 Claims to change because of commit `aeab2be` (pass 1)

| Current statement in the draft | Replace with | Numbers and sources |
|---|---|---|
| "partitioning is a null result" (abstract, introduction, Results, conclusion, recommendations) | Not significant at 174 rings on HI-Small; on HI-Medium, with 2,187 rings, the same-sized effect is resolved. | HI-Small: +0.015 [−0.002, +0.036], p_Holm 0.49 (`r9_significance.csv`). HI-Medium: +0.015 [+0.010, +0.020], p_Holm 0.0003 (`v3_closeout_p3.csv`). Keep: the gain shrinks with the matching threshold and reverses under one scope convention. |
| "a two-line rule matches the learned policy" | On HI-Small the rule matches the policy's *recall* of undetected members and the policy's advantage is purity; on HI-Medium the policy also matches more rings than the rule. | HI-Small: quiet-accounts Δ −0.024 [−0.084, +0.037], p_Holm 1.00; added-member precision +0.408 [0.342, 0.479], p_Holm 0.0008 (`v35_precision_paired.csv`). HI-Medium: matched rate +0.047 [+0.037, +0.057], p_Holm 0.0003. |
| Limitations: "a ring-folded re-run is registered; its result is not in this draft" | The measured result. | 0.58476 vs 0.58192, Δ +0.0028; per-seed −0.013 to +0.012; plus the paired CI from `v39_ringfold_report.csv`. |
| "One generator family … reproduced on LI-Small and, for the warm-up and budget capture, on HI-Medium" | Add the HI-Medium ring-level results and their limits. | Full-pipeline ring recall 0.187 [0.174, 0.200] against HI-Small's 0.461; untouched 28.7 %; partially recovered 8.6 %; ring-F1 falls with distance from training (seed 1: 0.408 on days 6–7 to 0.065 on days 14–15) (`deep-analysis.md` §7; `v3_closeout_blocks.csv`). State plainly: the detector did not meet its adequacy bar, two seeds. |
| (absent) | New audit finding: score saturation breaks strict quantile cuts. | On one HI-Medium detector seed, 780,093 of 18.9 M test scores are exactly 1.0, so the 99.9 % quantile is 1.0 and a strict "score > q" rule selects zero seeds; saturated edges grow from 124 on day 6 to 221,909 on day 15 (`deep-analysis.md` §7 diagnosis). New recommendation: "state the tie-handling rule of any quantile cut". |
| HI-Small day-0 label exclusion "does not help" | keep; confirm the wording against `deep-analysis.md` §9 (seed-1 validation AP 0.5455 vs 0.5726; gate 0.6131; one seed) | — |

### 6.2 New material from this runbook's tasks (pass 1 for T-P2–T-P4; pass 2 for T-P7–T-P9)

| Result | Where it goes | Form |
|---|---|---|
| T-P1 scorer | Evaluation protocol, last paragraph; Reproducibility appendix | one sentence + anonymised link |
| T-P2 ring-fold interval | Limitations, leak paragraph | two sentences |
| T-P3 baselines | Main results table (rows above "seeds + components"); Results, first subsection; scope figure | `tables/ring_methods.tex` extended; `make_figs.py` updated |
| T-P4 HI-Medium audit | Benchmark audit, "A second release" subsection | `tables/hm_audit.tex`; two-panel figure `fig_hm_audit.png` |
| HI-Medium method results (already in repo) | Results, after the HI-Small tests | `tables/hm_closeout.tex` (plain-language rows; footnote of invariant 11) |
| T-P6 comparison | Related work | `tables/related_comparison.tex` |
| T-P7 detector | edge-vs-ring figure and detector table | fourth point; one sentence |
| T-P8 sweep | Results, budget paragraph; appendix table | one figure, one sentence |
| T-P9 TAML | Results or Related work | one row group or one limitation sentence |

### 6.3 Abstract and contributions (pass 1 draft; final at pass 2)

Write the abstract (≤ 180 words) from this skeleton, filling in only numbers that exist in
the repository or in this runbook's result tables, and choosing each bracketed variant by the
flags in the progress log:

> Money-laundering detection on AMLworld is reported per transaction, while group-level
> results are appearing under definitions that cannot be compared. We audit what the benchmark
> supports when the unit is the laundering attempt. We define attempt-level recovery with
> one-to-one matching, an explicit scope rule and intervals over rings, and release it as a
> scorer. Three unstated choices dominate reported numbers: the day split's tail (40.7 % of
> test positives in 0.13 % of edges) inflates edge metrics and absorbs half of a global seed
> budget; the scope convention moves ring-F1 by 0.35–0.38, five times our method's effect
> [HM_AUDIT=REPRODUCED: ", on two releases" | NOT_REPRODUCED: "on HI-Small; the effect on a
> larger release is <value>"]; and 44 % of in-scope rings have no connected in-window piece
> any method could match. With a reference pipeline and <n> external baselines we find that
> [T-P7 extends: "edge-F1 gains of up to <x> points buy no rings at a fixed budget" |
> otherwise: "a 9.4-point edge-F1 gain buys no rings at a fixed budget"], and that effects
> too small to resolve at 174 rings are resolved at 2,187. We close with reporting
> recommendations.

Contribution list (four items): (1) an attempt-level evaluation protocol and scorer;
(2) a benchmark audit — tail, day-0 warm-up, budget capture, score saturation, scope
sensitivity, in-window disconnection — [on two releases | on HI-Small with partial
replication]; (3) a reference pipeline, external baselines, and a decomposition of where ring
recovery is lost, including results against our own method; (4) reporting recommendations.
If `METHOD_SUPERIORITY=OFF`, item 3 reads "a comparison of a reference pipeline and external
baselines under the protocol" and no sentence anywhere says the pipeline is better than a
baseline.

### 6.4 Body, appendix and cuts for 8 pages (pass 2 and T-P10)

Target body budget in ACM two-column pages: Introduction 0.9; Related work 0.7 (with the
comparison table); Evaluation protocol 1.0; Benchmark audit 1.6 (Figure: base rate by day;
Figure: scope conventions; second-release subsection); Reference pipeline 0.5; Results 1.6
(main table with baselines; tests; edge-vs-ring figure); Where ring recovery stops 0.9
(decomposition figure; STACK example figure); Recommendations 0.3; Limitations 0.4;
Conclusion 0.2.

Move to the appendix if not already there: the window-budget table; the precision-paired
table's ring-F1 block (keep the added-precision block in the body); the detector table (the
figure carries it); the seed-budget reallocation paragraph; HI-Medium temporal-decay rows;
the budget-sweep table; everything about explanations and the platform.

Cut order if the body is still over 8 pages — **propose, do not apply without approval**:
(1) the budget-capture subsection to three sentences; (2) the day-0 HI-Medium detector detail;
(3) the reallocation paragraph entirely; (4) the pipeline diagram (replace with one sentence);
(5) Recommendations merged into the Conclusion as a compact list. Never cut a pre-registered
negative result or a limitation to make space.

### 6.5 Template, authors, anonymity (T-P10)

1. Port `main.tex` to `\documentclass[sigconf,review,anonymous]{acmart}`. Remove `geometry`;
   keep `booktabs`, `graphicx`, `amsmath`, `tikz`, `subcaption`, `siunitx` only if the class
   accepts them without clashes (acmart loads `natbib`, `hyperref` and `caption`-like
   machinery itself — remove our explicit loads of `natbib`, `hyperref`, `caption`, `xcolor`
   if they clash). Bibliography style `ACM-Reference-Format`; `\bibliography{refs}`.
   Add CCS concepts and keywords (placeholders marked for the author).
2. Create `paper/authors.tex` with a toggle:

   ```latex
   % \anonymoustrue for review; \anonymousfalse for camera-ready
   \newif\ifanonymous \anonymoustrue
   \ifanonymous
     \author{Anonymous Author(s)}
     \affiliation{\institution{Anonymous Institution}\country{}}
   \else
     \author{Joan Sara Joe}
     \author{Ruhani Kumar}
     \author{Kashish Mittal}
     \author{Lakshmishree}
     \author{[SUPERVISOR NAME]}   % last author, corresponding — to be supplied by the author
     \affiliation{\institution{BMS College of Engineering}\city{Bengaluru}\country{India}}
   \fi
   ```

   Use the class's own `anonymous` option as well; emails, the corresponding-author mark and
   ORCIDs are placeholders for the author to fill. **All five are co-authors: delete the
   Acknowledgements paragraph that credits three of them.**
3. Add, inside `\ifanonymous … \else … \fi`, a CRediT contributions statement for camera-ready
   only, drafted from `CONTRIBUTORS.md`: Joan Sara Joe — conceptualisation, methodology,
   software (data, detector, ring layer, evaluation), formal analysis, writing; Ruhani Kumar —
   software (explanation layer, Elliptic baselines), validation (found the typing-evaluation
   defect); Kashish Mittal — software (platform); Lakshmishree — visualisation (dashboard
   mockup); supervisor — supervision. Mark it "draft — authors to confirm".
4. Blind build: replace repository URLs with the anonymised mirror placeholder
   `https://anonymous.4open.science/r/<ID>` (the author supplies the ID); remove "our
   repository" phrasing that names it; the Corrections appendix must not name a person.
5. Add the missing figure: one STACK laundering attempt whose in-window transactions fall in
   two or more disconnected pieces. `paper/make_fig_stack.py` reads
   `data/processed/amlworld_ring_ground_truth.parquet` and `amlworld_test.parquet`; pick a
   STACK ring from `results/tables/r_under_covered.csv` with about 14–17 members; in-window
   transactions solid, the same attempt's out-of-window transactions dashed grey, each
   connected in-window piece one colour, the recovered fragment outlined; accounts relabelled
   A, B, C…; 300 dpi. The script prints ring id, member count and piece count, which must
   match the connectivity table.
6. Regenerate all figures with `paper/make_figs.py` using `.venv312`. Two of its figures
   currently use hand-typed numbers (per-day base rates from
   `docs/paper/evaluation_protocol.md` §4; ring classes from FINDINGS B11): change them to
   read `results/tables/v3_day_profile_HI-Small.csv` (and the LI-Small profile if present)
   and `results/tables/r6_detector_swap.csv` / `r4_unmatched.csv`, and assert the values equal
   the typed ones before removing them.

### 6.6 Checks (run after every paper task)

- **Static:** balanced environments and braces per file; every `\input` and
  `\includegraphics` target exists; every `\ref` has a `\label`; every `\cite` key is in
  `refs.bib`; no uncited entry.
- **Stale phrases (must return nothing in non-comment text):** `is a null result`,
  `not in this draft`, `one significant link`, `CITATION NEEDED`, `NO SOURCE` (unless listed
  in `OPEN_QUESTIONS.md`), `0\.4455`, `0\.219`, `0\.2098`, `0\.0054`, `RingShield` (the system
  name is not used in the blind paper), and the regex
  `\b(B1[0-9]|B[2-9]|C[0-9]{1,2}|R[0-9]{1,2}[a-z]?|E[0-9]|11[bcd]|L[0-6]|P[1-4])\b`.
- **Numbers:** every number added or changed has a row in `paper/CLAIMS_CHECK.md` under a new
  dated heading: statement → source file (row/column) → source value → match.
- **Compile:** if a LaTeX toolchain exists, `pdflatex` + `bibtex` + `pdflatex` ×2 with zero
  errors; list every warning; fix overfull boxes wider than 5 pt. If none exists, say so in
  the progress log and in the final report: the author compiles on Overleaf.

### 6.7 Final paper checklist (must all be ticked in the progress log)

- [ ] Compiles on the ACM class with no errors and no unresolved references (or: static
      checks pass and "not compiled locally" is stated).
- [ ] Body ≤ 8 pages, or an approved cut list is applied.
- [ ] Every number traces to a `metrics.json` or a committed table, via its `% source`
      comment and its `CLAIMS_CHECK.md` row; zero mismatches.
- [ ] Every citation verified against its PDF or arXiv record; audit file complete.
- [ ] No internal code and no system name in the prose; no dated-correction narrative in the
      body.
- [ ] Blind build contains no author name, institution, city, email, GitHub handle,
      repository URL, or absolute local path (grep list in §7.4).
- [ ] HI-Medium tables carry the seed-3 / adequacy footnote; no pooled HI-Small/HI-Medium
      number or figure.
- [ ] Follow-up analyses are labelled as sensitivity analyses, not confirmatory tests.
- [ ] `paper/OPEN_QUESTIONS.md` lists everything the author must still supply (supervisor
      name, emails, ORCIDs, CCS concepts, mirror ID).

---

## 7. Final verification phase

### 7.1 Tests
Re-run the research suite and the platform suite exactly as in Phase 0. Passed counts must be
≥ the recorded baselines plus the tests you added; skipped counts must equal the baseline
unless a new test legitimately skips without data (list each). Any regression is a STOP.

### 7.2 Audit
`$PY evaluation/audit_tables.py` → all rows traceable, 0 mismatched.
`$PY -m pytest tests/test_frozen.py -q` → pass. `git diff --stat results/FROZEN.json contract/out`
→ empty. `git status --short` shows no modification under existing `experiments/**` run
directories or existing `results/tables/*` files (only additions).

### 7.3 Paper
Rebuild figures, run §6.6, tick §6.7, and rebuild `paper/RingShield-paper-latex.zip` with
`main.tex` at the top level (for Overleaf).

### 7.4 T-P11 — anonymised repository snapshot

**Goal.** A copy of the repository that can be mirrored for double-blind review
(anonymous.4open.science) without identifying the authors. You build and verify the snapshot;
**you do not upload anything.**

**Steps.**
1. Build to `..\RS-anon-snapshot\` (outside the repository) from tracked files only, with no
   git history: `git archive HEAD | tar -x -C ../RS-anon-snapshot`. Then copy in the new,
   still-untracked files this runbook created that the paper cites
   (`evaluation/score_external.py`, the new `evaluation/*.py`, their tests, `docs/PROTOCOL.md`,
   the new `results/tables/v39…v43*`, `results/notes/`), and the blind `paper/` sources.
2. Remove: `CONTRIBUTORS.md`; `docs/archive/`; `docs/HANDOFF_*.md`; `review/`; `LICENSE`
   copyright line if it names a person; `platform/demo-credentials.txt`; any
   `*.log`, `environment.txt` and `config.yaml` field that records a user name, host name or
   absolute path (rewrite the field to `<redacted>`, do not delete the file); `paper/`
   working files that name the author (`REVIEW.md`, `ACTION_PLAN.md`, `OPEN_QUESTIONS.md`,
   `CHECKPOINT_*.md`, `RUNBOOK_*.md`, `authors.tex`'s non-anonymous branch).
3. Replace, across all text files: absolute paths `E:\JSJ\…`, `E:/JSJ/…`, `/e/JSJ/…` →
   `<repo>`; the GitHub URL → `<anonymised>`; "found by Ruhani" style credits → "found by an
   independent check".
4. **Grep to prove it is clean** (case-insensitive, whole snapshot including the blind
   `paper/`): `Joan`, `Sara Joe`, `\bJSJ\b`, `jsj912`, `Jooo`, `Ruhani`, `Kashish`, `Mittal`,
   `kashishmittal`, `Lakshmishree`, `LakshmishreeKP`, `BMS College`, `Bengaluru`,
   `Bangalore`, `manjunath`, `@gmail`, `E:\\JSJ`, `E:/JSJ`, `/e/JSJ`, `C:\\Users`,
   `github.com/jsj`, the supervisor's name once supplied, and any e-mail address regex.
   Also list binary files (`.parquet`, `.pkl`, `.png`, `.docx`) and check metadata of the
   `.docx`/images for author fields; drop `docs/dashboard_requirements_v1.0.docx`.
   Write every hit, its file and the fix to `paper/ANON_SNAPSHOT_REPORT.md`; iterate until
   zero hits. Record the snapshot's file count and total size.
5. Sanity: in the snapshot, `python -m pytest tests/test_score_external.py -q` passes (using
   `.venv312` from the original repository), and `docs/PROTOCOL.md`'s command line runs
   `--help`.
6. Write `..\RS-anon-snapshot\README_REVIEWERS.md`: what is here, how to run the scorer on the
   included tables, what is omitted (raw data: download instructions for the Kaggle AMLworld
   files and the manifest hashes; model checkpoints).

**Gate.** Zero grep hits and the sanity test passes → DONE. Otherwise fix and repeat. Never
mark DONE with a known hit "to be fixed later".

### 7.5 Final report

Write `paper/FINAL_REPORT.md`:

1. What changed: files added (code, tests, tables, docs, paper), files modified, nothing
   deleted; the list for the author to commit.
2. Every new number with its CI (and p where registered), its source file, and the paper
   location that uses it.
3. Claim ledger: for each paper claim — stronger / unchanged / weaker / removed — with the
   task that moved it and the pre-registered bar verdict.
4. Gates and flags: every gate's result; final values of `METHOD_SUPERIORITY`, `HM_AUDIT`,
   `EDGE_RING_CLAIM`.
5. Deviations from this runbook, each with its reason and whether the author approved it.
6. Test and audit results against the Phase 0 baselines.
7. Open risks: anything not verified (uncompiled LaTeX, unverified citations, skipped tasks,
   two-seed HI-Medium results, post-hoc analyses), in order of how likely a reviewer is to
   raise it.
8. What the author must still do: supervisor name and e-mails, CCS concepts, mirror upload and
   ID, Overleaf compile if not done locally, final read.

---

## 8. Appendix

### 8.1 Paths, files and scripts referenced

| Path | Role in this runbook |
|---|---|
| `configs/seeds.yaml`, `eval_window.yaml`, `eval_window_hi_medium.yaml`, `paths.yaml`, `paths_hi_medium.yaml`, `threshold_rule.yaml`, `detector_choice.yaml` | seeds, windows, dataset paths, the validation grid, the detector-choice rule |
| `scripts/data_manifest.py`, `scripts/test-db.ps1` | Phase 0 checks |
| `models/tgn.py`, `models/score.py`, `models/calibrate.py`, `models/mega_adapter.py` | detector, scoring, calibration, MEGA adapter (T-P7) |
| `ringshield/run_rings.py`, `ringshield/aggregators/cc.py`, `ringshield/expand/{candidates,features,cross_score,make_training_set,policy,run_expand}.py`, `ringshield/partition/{make_pairs_training_set,affinity,run_partition}.py` | the ring layer |
| `evaluation/ring_stats.py`, `ring_metrics.py`, `scope_sensitivity.py`, `component_scope.py`, `unmatched_rings.py`, `precision_paired.py`, `window_budget.py`, `realloc_full.py`, `r9_robustness.py`, `r6_detector_swap.py`, `csgm_baseline.py`, `hm_closeout.py`, `hm_closeout_report.py`, `in_window_connectivity.py`, `under_covered.py`, `audit_tables.py`, `step9_tables.py`, `make_figures.py` | existing evaluation code to reuse |
| `evaluation/score_external.py`, `ringfold_report.py`, `community_baselines.py`, `hm_audit.py`, `budget_sweep.py`, `taml_metric.py` | **new**, created by T-P1, T-P2, T-P3, T-P4, T-P8, T-P9 |
| `experiments/R1_gine_causal`, `R2_b0`, `R3_cross_scores`, `R3_expansion`, `R3_ringfold`, `R4_partition`, `R6_mega`, `R6_b0`, `R6_full`, `R6_gfpxgb_*`, `R11b_ensemble`, `R11c_local` | existing HI-Small runs (read-only) |
| `experiments/R6_megagenagg`, `R13_baselines`, `R14_budget_sweep`, `R15_taml` | **new** run directories |
| `experiments_hi_medium/R1_gine_causal_c1prime`, `closeout_a15` | HI-Medium detector and close-out rings (read-only) |
| `results/tables/r1_edge_metrics.csv`, `r2_ring_b0.csv`, `r3_expansion.csv`, `r4_partition.csv`, `r4_unmatched.csv`, `r5_typing_ci.csv`, `r6_detector_swap.csv`, `r9_ring_ci.csv`, `r9_significance.csv`, `r9_quiet_members.csv`, `r14_scope_sensitivity.csv`, `r_under_covered.csv`, `r_in_window_connectivity.csv`, `v34_window_budget.{csv,json}`, `v35_precision_paired.csv`, `v36_component_scope.csv`, `v37_realloc_full.csv`, `v3_closeout_{p1,p2,p3,blocks}.csv`, `v3_closeout_verdicts.json`, `v3_day_profile_HI-{Small,Medium,Large}.csv`, `v33_seed_by_day.csv` | existing tables (read-only) |
| `results/tables/v39_ringfold_report.*`, `v40_external_baselines.*`, `v41_hm_audit_*`, `v42_budget_sweep.*`, `v43_taml_under_protocol.*`, `r6_detector_swap_v2.csv`; `results/notes/p*.md` | **new** tables and notes |
| `docs/FINDINGS.md`, `deep-analysis.md`, `REPRODUCE.md`, `PITFALLS.md`, `PARTITION.md`, `EXPANSION.md`, `V3_HIMEDIUM_PREREG.md`, `FUTURE_IMPLEMENTATIONS.md`; **new** `docs/PROTOCOL.md` | documentation |
| `paper/` | LaTeX, `CLAIMS_CHECK.md`, `OPEN_QUESTIONS.md`, `REVIEW.md`, `ACTION_PLAN.md`, `make_figs.py`; **new** `RUNBOOK_PROGRESS.md`, `PREREG_<date>.md`, `RELATED_WORK_AUDIT.md`, `CHECKPOINT_A.md`, `CHECKPOINT_B.md`, `ANON_SNAPSHOT_REPORT.md`, `FINAL_REPORT.md`, `authors.tex`, `make_fig_stack.py` |
| `..\RS-e2e\experiments`, `..\RS-ccy-valrings`, `..\venv-platform`, `..\RS-anon-snapshot` | sibling directories |

### 8.2 Glossary of internal terms

| Term | Meaning | How the paper says it |
|---|---|---|
| Ring | the accounts of one laundering attempt (one block of the generator's pattern file) | "ring" / "laundering attempt" |
| L0–L6 | pipeline layers: data, detector, calibration/seeds, ring layer, explanations, platform, feedback | never used; name the stage |
| Primary / tail / whole window | HI-Small test days 8–9 / 10–17 / 8–17 | "primary window", "tail", "whole test split" |
| `test_visible`, `full_membership`, `component`, `component_ge3` | scope conventions (§T-P1) | "in-window accounts", "all member accounts", "every in-window piece", "pieces of three or more accounts" |
| B0 | seeds grouped by connected components | "seeds and connected components" |
| B1 / B1b | rule: shared endpoint within Δt / plus score quantile > 0.99 | "the rule" (B1b); B1 only in the table |
| proposed / expand / b2 | learned expansion policy, no partition | "learned expansion", "expansion only" |
| full / average | expansion + average-linkage partition | "full pipeline" |
| b4 / b5 | Louvain partition / CSGM external baseline | "Louvain partition", "CSGM" |
| Quiet member | a ring member edge below the seed cut | "members the detector does not flag" (define "quiet member" once) |
| Added-member precision | share of expanded in-window edges that are true member edges | same |
| Class (a)/(b)/(c) | unmatched rings: < 3 visible members / untouched / touched (over-merged or under-covered) | "small", "untouched", "merged", "partially recovered" |
| k* | validation-chosen seed fraction (0.1 %) | "seed budget" |
| `gine_causal`, `mega`, `gfpxgb`, `megagenagg` | detectors | Multi-GINe, MEGA-GNN, GFP-XGBoost, MEGA-GenAgg |
| C1′ (`c1prime`) | HI-Medium detector trained without day-0 labels | "the HI-Medium detector (day-0 labels excluded)" |
| Close-out, Amendment 15, P1–P3 | HI-Medium pre-registered tests and their amended window / cut | "pre-registered tests on HI-Medium" |
| FINDINGS rows A/B/C/E, section G | the repository's claim ledger and dated notes | never cited by code in prose |
| R-numbers | experiment ids (R6 detector swap, R10 tenant view, R12 drift, …) | never used |

### 8.3 Reference list for T-P6 (verify every field; identifiers as currently known)

**A. Group- and sub-network-level AML**
1. Chai et al., "Towards Learning to Discover Money Laundering Sub-network in Massive
   Transaction Network", AAAI 2023, 37(12):14153–14160. DOI 10.1609/aaai.v37i12.26656.
   (arXiv 2302.11880 — verify.) Author list incomplete in `refs.bib`.
2. Rico, Hulpus, Leisink, Zhao, Velegrakis, "Translating Latent Representations for Money
   Laundering Detection", IJCAI 2026, pp. 6500–6508. DOI 10.24963/ijcai.2026/723.
   Code: github.com/rricocuevas1/taml.
3. Tian, Ding, et al., "Towards Collaborative Anti-Money Laundering Among Financial
   Institutions", The Web Conference 2025. arXiv 2502.19952. Author list incomplete.
   Code: github.com/zhihuat/Collaborative-AML.
4. Tariq, Kaja, Hassani, "Detecting Complex Money Laundering Patterns with Incremental and
   Distributed Graph Modeling", 2026. arXiv 2604.01315.
5. Li, Liu, Li, Han, Shi, Hooi, Huang, Cheng, "FlowScope: Spotting Money Laundering Based on
   Graphs", AAAI 2020, 34(04):4731–4738. DOI 10.1609/aaai.v34i04.5906.
6. Bellei, Xu, Phillips, Robinson, Weber, Kaler, Leiserson, Arvind, Chen, "The Shape of Money
   Laundering: Subgraph Representation Learning on the Blockchain with the Elliptic2
   Dataset", KDD MLF workshop 2024. arXiv 2404.19109.
7. "Identifying Money Laundering Subgraphs on the Blockchain" (RevTrack / RevClassify).
   arXiv 2410.08394. Authors and venue to find.
8. DenseFlow (cited by Rico et al. as "Lin et al. 2024a") — title, venue, id to find.
9. Diga (cited by Rico et al. as "Li et al. 2023") — title, venue, id to find.
10. SMURF: "Privacy-Preserving Multi-Party Graph Mining for AML", TU Delft thesis
    (repository.tudelft.nl, uuid 8e53ccf5-3cfa-4907-adc2-775846021e90) — verify.
11. Deprez, Baesens, Verdonck, Verbeke, "GARG-AML against Smurfing", 2025. arXiv 2506.04292.
12. Wang, Cao, "Clue-Guided Money Laundering Group Discovery", 2026. arXiv 2606.26189 — verify.

**B. Edge-level detection on AMLworld**
13. Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu, "Realistic Synthetic Financial
    Transactions for Anti-Money Laundering Models", NeurIPS 2023 Datasets and Benchmarks.
    arXiv 2306.16424.
14. Egressy, von Niederhäusern, Blanuša, Altman, Wattenhofer, Atasu, "Provably Powerful Graph
    Neural Networks for Directed Multigraphs", AAAI 2024, 38(10):11838–11846.
    DOI 10.1609/aaai.v38i10.29069. arXiv 2306.11586.
15. Blanuša, Cravero Baraja, Anghel, von Niederhäusern, Altman, Pozidis, Atasu, "Graph Feature
    Preprocessor: Real-time Subgraph-based Feature Extraction for Financial Crime Detection",
    ICAIF 2024, pp. 222–230. DOI 10.1145/3677052.3698674. arXiv 2402.08593.
16. Lin, Guo, Zhu, Mitchell, Altman, Shun, "FraudGT: A Simple, Effective, and Efficient Graph
    Transformer for Financial Fraud Detection", ICAIF 2024, pp. 292–300.
    DOI 10.1145/3677052.3698648.
17. Bilgi, Chen, Atasu, "Multigraph Message Passing with Bi-Directional Multi-Edge
    Aggregations" (MEGA-GNN). arXiv 2412.00241. Venue to verify.
    Code: github.com/hcagri/MEGA-GNN (commit ef60a71 used here).
18. Tariq, Hassani, "Extracting Money Laundering Transactions from Quasi-Temporal Graph
    Representation" (ExSTraQt), ACM SAC 2026. DOI 10.1145/3748522.3779790. arXiv 2604.02899.
19. Verlaan, Hulpuș, van Leeuwen, "LAS-GNN: A Graph Neural Network for Temporal Money
    Laundering Motif Detection", ICAIF 2025, pp. 256–264. DOI 10.1145/3768292.3770410 — verify.
20. "SALT-GNN: Handling Dense Neighborhoods in Anti-Money Laundering Graphs via
    Statistics-Aware Attention". arXiv 2607.10131 — **id unverified**; cite only if confirmed.
21. Tab-AML and PBAD (baselines in Rico et al.) — find and cite only if used in our text.

**C. Datasets and generators**
22. Weber, Domeniconi, Chen, Weidele, Bellei, Robinson, Leiserson, "Anti-Money Laundering in
    Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics", KDD
    Workshop on Anomaly Detection in Finance 2019. arXiv 1908.02591.
23. Elmougy, Liu, "Demystifying Fraudulent Transactions and Illicit Nodes in the Bitcoin
    Network for Financial Forensics" (Elliptic++), KDD 2023. arXiv 2306.06108.
24. Oztas et al., SAML-D, IEEE ICEBE 2023. DOI 10.1109/ICEBE59045.2023.00028.
25. van den Beukel, Rožanec, Varbanescu, "Tide: A Customisable Dataset Generator for
    Anti-Money Laundering Research", 2026. arXiv 2603.01863.
26. AMLSim (IBM) — find the canonical citation.
27. Jensen et al., SynthAML, Scientific Data 2023. DOI 10.1038/s41597-023-02569-2.

**D. Methods and statistics**
28. Holm, "A Simple Sequentially Rejective Multiple Test Procedure", Scandinavian Journal of
    Statistics 6(2):65–70, 1979.
29. Efron, Tibshirani, *An Introduction to the Bootstrap*, 1993 (or Efron 1979) — pick one.
30. Ke, Meng, Finley, Wang, Chen, Ma, Ye, Liu, "LightGBM: A Highly Efficient Gradient
    Boosting Decision Tree", NeurIPS 2017.
31. Chen, Guestrin, "XGBoost: A Scalable Tree Boosting System", KDD 2016.
32. Khosla et al., "Supervised Contrastive Learning", NeurIPS 2020. Author list incomplete.
33. Blondel, Guillaume, Lambiotte, Lefebvre, "Fast unfolding of communities in large
    networks", J. Stat. Mech. 2008 (Louvain).
34. Traag, Waltman, van Eck, "From Louvain to Leiden: guaranteeing well-connected
    communities", Scientific Reports 2019 (Leiden).
35. Zadrozny, Elkan, "Transforming classifier scores into accurate multiclass probability
    estimates", KDD 2002 (isotonic calibration) — or the reference the author prefers.
36. Lundberg & Lee, NeurIPS 2017; Lundberg et al., Nature Machine Intelligence 2020;
    Fleiss 1971; Landis & Koch 1977 — keep only if the explanation appendix stays.

Informal source, footnote only: github.com/Kluey/AML-Transaction-Detection (notes the high
laundering rate in AMLworld's last days).
