# Action plan — from review to implementation (2026-11-14)

Written against repo `E:\JSJ\RS-react`, branch `integrate/main` at `aeab2be`
("deep-analysis #7 and #8: HI-Medium close-out verdicts, ring-folded cross-scores").

**That commit changes the plan.** Two items from my review are already done, and one result
changes the paper's story:

- Ring-folded cross-scores: **success**, mean Δ ring-F1 +0.0028 (0.58476 vs 0.58192), inside
  the registered ±0.008. Four reported-beside items are still "not yet computed".
- HI-Medium close-out (2,187 rings, detector seeds 1–2): P1 fail (recall 0.187 vs 0.4609),
  P2 fail, **P3 pass** — `full` vs b2 +0.015 [+0.010, +0.020] and **policy vs B1b +0.047
  [+0.037, +0.057], both p_Holm 0.0003**. At 12× the rings, the two comparisons that were null
  on HI-Small resolve in the method's favour. "A rule matches the policy" and "partition is a
  null" are now *power-limited HI-Small statements*, not general ones.
- A new audit finding fell out of it: a strict quantile cut on saturated scores (780,093 test
  scores exactly 1.0 on seed 3) selects zero seeds.

The LaTeX draft (v3) predates this commit and is stale on all three points (prompt P5 fixes it).

---

## Questions for Jooo (answer before running the prompts)

1. **Where will Opus find the paper?** The LaTeX lives in `E:\JSJ\Ring-Shield\paper_draft\`,
   outside the repo. The writing prompts assume you copy that folder to
   `E:\JSJ\RS-react\paper_draft\` (untracked) or attach it. Which?
2. **Venue, template, page limit, anonymity.** ICAIF uses ACM `sigconf`; a workshop may differ.
   P10 cannot be finalised without this.
3. **Run artefacts.** `deep-analysis.md` says R1 checkpoints and the R3/R6 run directories are
   in `../RS-e2e/experiments`, and v2 rings in `../RS-ccy-valrings`. Are those still the
   canonical roots, and will they exist on the machine Opus runs on?
4. **Current test baselines.** REPRODUCE §13 records 258 passed / 47 skipped / 1 xfailed
   (research) and 563 passed (platform) on 2026-10-26. New tests have landed since. Every prompt
   tells Opus to record the baseline first, but tell me if a different number is expected.
5. **MEGA-GenAgg.** `docs/FUTURE_IMPLEMENTATIONS.md` (F4) names it as the strongest published
   HI-Small detector (74.88 ± 0.38). Is the `genagg` code present in your
   `third_party/mega_gnn` clone at commit `ef60a71`, and does it run on Windows? P7 assumes yes
   and stops if not.
6. **Internet access for Opus.** P6 (related work) needs to read papers. If Claude Code has no
   web access on your machine, P6 becomes a checklist for you.
7. **Numbering in `docs/deep-analysis.md`.** Sections 1–11 and 14 exist; are 12 and 13
   reserved? The prompts say "use the next unused number ≥ 15" to be safe.
8. **HI-Medium seed 3.** Excluded as degenerate under Amendment 15. Keep it excluded for the
   audit replication (P4)? The prompt assumes yes.
9. **Authorship** (Ruhani; supervisor). Not an Opus task, but P5 and P10 need the answer.
10. **Will the repo be public or anonymised at submission?** The abstract says "we release".

---

## Part A — Improvement plan, ordered by impact ÷ effort

| # | Improvement | Fixes which criticism | Effort (GPU-h + dev-days) | Risk | Depends on | Call |
|---|---|---|---|---|---|---|
| P1 | **Standalone protocol scorer** `evaluation/score_external.py`: any rings file → ring P/R/F1 + CIs under all four scope conventions and three thresholds, plus observability counts | "Is this a protocol or just your scripts?"; needed to score any baseline | 0 + 1.5 | Low | — | **MUST** |
| P2 | **Close the ring-fold item**: paired bootstrap CI, P/R deltas, ring overlap, fold-model AP | "A leak in a paper about leaks" | 0 + 0.5 | Low | — | **MUST** |
| P3 | **Classical external baselines under the protocol**: CSGM at 5 bank seeds; Louvain/Leiden and label propagation on the flagged-edge graph | "No external ring-level baseline" (R1, R2) | 0–2 + 2 | Low | P1 | **MUST** |
| P4 | **Replicate the audit on HI-Medium** using the close-out rings: scope gap, component observability, threshold sweep, tail, budget capture | "One dataset" (R1, R2) | 0 + 1.5 | Low–med | P1 | **MUST** |
| P5 | **Sync and reframe the paper** for `aeab2be`: ring-fold result, HI-Medium P1–P3, the saturated-score cut, softened null claims | Stale draft; "is the method really a null?" | 0 + 1.5 | Low | P2, P4 (numbers) | **MUST** |
| P6 | **Related work verified against PDFs + comparison table** of units/metrics/splits across group-level AML papers; ~35 references | "Missing prior work" (R1); weak positioning | 0 + 2 | Low | web access | **MUST** |
| P7 | **Third, stronger detector: MEGA-GenAgg** under causal sampling, B0 + full | "Edge-F1 claim rests on a weak detector" | ~25–35 + 2 | Medium (Windows, VRAM) | — | **SHOULD** |
| P8 | **Budget sweep for every detector** (0.05–0.30 %, global and in-window) | "C6/C7 are single-budget claims" | 0 (CPU ~6 h) + 1 | Low | P7 optional | **SHOULD** |
| P9 | **TAML extractor scored under your protocol**, and your rings under its metric | "Compare with learned sub-network SOTA"; shows the protocol re-ranks others | ~15–25 + 4 | **High** (external code, Linux deps) | P1 | **SHOULD** (time-boxed 3 days) |
| P10 | **Submission packaging**: venue template, page fit, STACK-ring example figure, compile, anonymise | Presentation | 0 + 2 | Low | Q2, P5 | **SHOULD** |

### Skips

| Item | Why skip |
|---|---|
| FraudGT as the stronger detector | MEGA-GenAgg gives the same argument through an adapter you already have; FraudGT is a new codebase on Windows for ~the same edge-F1 level. |
| Account-level ring-membership model; two-stage budget; per-day budget with per-day cut | Method work. With the audit framing they do not move acceptance, and HI-Medium already shows the policy beats the rule at power. Revisit after submission. |
| Cross-window linking / ring-identity fine-tuning | Research bets your own results argue against (0 of 140 STACK edges via history; frozen head AUC 0.62 vs 0.75 bar). |
| AMLGenteX / Tide as a third generator | 20–40 h with uncertain attempt-level labels; HI-Medium + LI-Small is enough for ICAIF/workshop. Needed only for NeurIPS D&B. |
| External analyst study | People-bound, weeks, and L4 is now appendix-only. |
| HI-Medium seed 3 rescue and P4 arms | Detector-side cleanup of a release where the detector failed its gate; no reviewer will ask. |
| FlowScope | Unsupervised dense-flow on amounts; no maintained Windows build. Named in P3 as optional and time-boxed to half a day. |

---

## Part B — Implementation prompts

Each block is self-contained. Common facts are repeated in every prompt on purpose.

### P1 — Standalone protocol scorer

```text
ROLE: You are working in the repository E:\JSJ\RS-react (branch integrate/main), a research
codebase for ring-level money-laundering detection on IBM AMLworld. Do not commit or push; leave
changes in the working tree and list them at the end.

1. GOAL
Build one command-line scorer, evaluation/score_external.py, that takes ANY file of predicted
rings (ours or an external method's) and reports ring-level metrics under every evaluation
convention the paper discusses. The paper is being reframed as an evaluation-protocol and
benchmark-audit paper, and a reviewer will ask whether "the protocol" is a reusable artefact or
a pile of our own scripts. This tool is that artefact, and prompts for external baselines
depend on it.

2. CONTEXT
- Dataset: AMLworld HI-Small, day split train 0-5 / val 6-7 / test 8-17. Primary window = test
  days 8-9 (174 in-scope truth rings). Windows are defined in configs/eval_window.yaml.
- A truth ring = one laundering-attempt block of the pattern file; members = accounts of its
  transactions. Ground truth: data/processed/amlworld_ring_ground_truth.parquet.
- Scope conventions (all already implemented somewhere; reuse, do not rewrite):
  test_visible (reported): ring in scope if >=1 transaction in window; members = accounts of
  in-window transactions. full_membership: same rings, members = all accounts
  (evaluation/scope_sensitivity.py). component / component_ge3: each in-window connected piece
  of a ring is a target; ge3 keeps pieces with >=3 accounts (evaluation/component_scope.py).
- Matching: greedy one-to-one by descending Jaccard on account sets, threshold 0.5; also report
  0.3 and 0.7. min_size 3 applies to the unrestricted prediction; matching is on the
  window-restricted prediction.
- Statistics live in evaluation/ring_stats.py (bootstrap over truth rings, 1,000 resamples,
  seeds averaged inside a resample; paired_permutation; paired_unit_bootstrap).
- Existing entry point for our own rings: `python -m ringshield eval`. Run artefacts for the
  shipped pipeline are under experiments/R4_partition/runs/average/seed{1..5}/ (rings.parquet,
  metrics.json); if a directory is missing locally, the same tree exists at
  ../RS-e2e/experiments.
- Numbers you must reproduce before adding anything (5 seeds, primary window):
  results/tables/r14_scope_sensitivity.csv -> gine_causal full: test_visible ring_f1 0.5894
  [0.5234, 0.6529], full_membership 0.2428; b0 0.5213 / 0.1437.
  results/tables/v36_component_scope.csv -> gine full: component 0.515, component_ge3 0.740;
  targets 254 and 108.
- Environment: Windows 11, PY=.venv312/Scripts/python.exe, set PYTHONIOENCODING=utf-8, invoke
  package code as modules (python -m ...); ringshield/typing shadows the stdlib otherwise.

3. HARD CONSTRAINTS
- Read-only with respect to results/FROZEN.json, contract/out/, and every existing
  experiments/**/rings.parquet and metrics.json.
- No parameter is chosen inside this tool. It scores what it is given.
- Do not duplicate matching or bootstrap logic: import it. If two existing implementations
  disagree, stop and report (see 8).
- Record the test baseline first: `$PY -m pytest tests contract/tests preprocessing/tests -q`
  (last recorded: 258 passed, 47 skipped, 1 xfailed). It must not get worse. Do not touch
  platform/.

4. STEPS
a. Read evaluation/scope_sensitivity.py, evaluation/component_scope.py,
   evaluation/ring_stats.py, evaluation/unmatched_rings.py and the `eval` subcommand in
   ringshield/. Write a 10-line note (in your final report) of which function provides what.
b. Create evaluation/score_external.py with:
   --rings PATH [PATH ...]   one file per seed/run; accept the repo's rings.parquet schema AND a
                             minimal schema (ring_id, members:list[int]) in parquet or JSONL
   --split {val,test} --window {primary,tail,whole} --paths (default: load_paths())
   --min-size 3 --thresholds 0.3 0.5 0.7 --n-boot 1000 --out DIR
   Output DIR/metrics.json and DIR/summary.csv with, per convention x threshold: n_targets,
   ring_precision, ring_recall, ring_f1 with 95% CI, ring_recall_ge3, member_coverage,
   per-pattern recall; plus an "observability" block: rings with <3 visible members, rings with
   no in-window piece of >=3 accounts, pieces recovered on rings that have one.
   Also write DIR/config.json (git commit, input sha256, arguments).
c. Add --compare PATH_A PATH_B to run evaluation.ring_stats.paired_unit_bootstrap between two
   sets of runs (10,000 draws) on ring_f1.
d. Add a short docs/PROTOCOL.md: definitions, the command, the output schema, and the reporting
   checklist (scope rule, split, window, budget allocation, threshold sweep, observability).
e. Runtime: a few minutes per call on CPU.

5. TESTS & SANITY CHECKS
- tests/test_score_external.py with a hand-built fixture (3 truth rings, one split into two
  in-window pieces, one with 2 visible members; 4 predictions): assert exact Jaccard values,
  one-to-one matching, target counts per convention, and that a prediction spanning two pieces
  matches only one.
- Reproduction: scoring experiments/R4_partition/runs/average/seed1..5 must return, to 4
  decimals, the r14 and v36 values listed in section 2. Same check for R2_b0/gine_causal.
- Minimal-schema input and full-schema input of the same rings give identical metrics.

6. ACCEPTANCE CRITERIA
Done when the reproduction check passes for both `full` and `b0`, the new tests pass, the
research suite is no worse than baseline, and docs/PROTOCOL.md exists. This is tooling, so the
pre-registered bar is the reproduction itself: any deviation > 1e-4 from r14/v36 is a failure.

7. DELIVERABLES
evaluation/score_external.py, tests/test_score_external.py, docs/PROTOCOL.md, and a results
note results/notes/p1_scorer.md in the form: "result, CI, p-value, what it means for the
claim" (here: reproduced values and the max absolute deviation). Feeds: every baseline table
in the paper and the "we release the protocol" claim.

8. STOP CONDITIONS
Stop and report instead of improvising if: the reproduction differs by more than 1e-4 and you
cannot find why within an hour; two existing implementations of matching or scoping give
different answers on the same input; a required run directory exists in neither experiments/
nor ../RS-e2e/experiments; any pre-existing test fails before you change anything.
```

### P2 — Close the ring-folded cross-score item

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on AMLworld HI-Small. Do not commit or push; list your changes at the end.

1. GOAL
A known weakness is recorded in docs/FINDINGS.md (row B17): the expansion policy was trained on
cross-scores folded by DAY, but rings span days, so a fold model saw labels from rings it then
scored. A ring-folded re-run was registered (docs/deep-analysis.md, section 8) and has finished:
mean delta ring-F1 = +0.0028 (ring folds 0.58476 vs shipped 0.58192), inside the registered
+/-0.008, verdict SUCCESS. Four quantities the registration promised to report beside the
verdict are marked "Not yet computed". Compute them, so the paper can close the leak with a
measurement and an interval instead of an ablation bound.

2. CONTEXT
- Pipeline stage: L3a expansion. Policy = LightGBM over 70 causal features, trained on
  cross-scored train data (ringshield/expand/cross_score.py, make_training_set.py, policy.py,
  run_expand.py).
- Shipped runs: experiments/R3_expansion/runs/proposed/seed{1..5} (also under
  ../RS-e2e/experiments). Ring-folded runs: experiments/R3_ringfold/runs/proposed/seed{1..5},
  with cross_scores/, expansion/ and chain.log beside them. Both use the fixed shipped cell
  (delta_t 24 h, p_min 0.7).
- Per-seed ring-F1, shipped -> ring folds: 0.5985->0.6074, 0.5940->0.5950, 0.5649->0.5768,
  0.6204->0.6075, 0.5318->0.5371. Reproduce these from the metrics.json files first.
- Evaluation: primary window (test days 8-9, 174 truth rings), test_visible scope, Jaccard 0.5.
- Tools: evaluation/ring_stats.py::paired_unit_bootstrap (ring-level paired bootstrap, 392
  units on shipped runs, 10,000 draws) and its driver evaluation/precision_paired.py.
- PY=.venv312/Scripts/python.exe; PYTHONIOENCODING=utf-8; run package code with python -m.

3. HARD CONSTRAINTS
- Nothing is re-trained and nothing is re-chosen. This is analysis of existing runs.
- Do not modify results/FROZEN.json, contract/out/, the shipped rings, or any existing
  metrics.json. The shipped rings stay final whatever you find (this is in the registration).
- Research test suite must stay at its baseline (record it first).

4. STEPS
a. Reproduce the ten per-seed ring-F1 values above from metrics.json. If any differs at the
   4th decimal, stop.
b. Write evaluation/ringfold_report.py that computes, primary window, 5 seeds:
   (i)   paired ring-unit bootstrap CI and p-value for ring-F1 and for added-member precision,
         ring folds minus shipped (10,000 draws, RNG seed 20261114);
   (ii)  ring precision and ring recall per arm and their paired differences;
   (iii) share of shipped rings reproduced exactly (same account set) and share matched at
         Jaccard >= 0.5, per seed and mean;
   (iv)  held-out AP and ROC-AUC of the ring-folded fold models on ring edges versus the
         day-folded ones, per fold, from cross_scores_train.parquet in each directory; state the
         number of ring edges per fold;
   (v)   from experiments/R3_ringfold/cross_scores/*/fold.json: how many rings span day folds
         and how many edges moved.
   Output results/tables/v39_ringfold_report.csv and .json.
c. Append the numbers to docs/deep-analysis.md section 8 under "Result", replacing the "Not yet
   computed" bullet, and add a dated note to FINDINGS section G naming row B17. Do not edit the
   B17 row text itself.
d. Runtime: under 15 minutes, CPU only.

5. TESTS & SANITY CHECKS
- tests/test_ringfold_report.py: on a 3-ring fixture, exact-reproduction share and Jaccard
  overlap equal hand-computed values.
- The paired difference in ring-F1 computed by the bootstrap's point estimate equals +0.0028
  (to 4 decimals) — the same number as the per-seed mean.
- Assert from the fold records that no ring-folded model was supervised on an edge of a ring
  it scores (the run's own assertion; re-check it from the parquet).

6. ACCEPTANCE CRITERIA
The registered verdict is already fixed (|mean delta| <= 0.008 -> success) and must not be
re-litigated. Pre-registered reading of the new items, written here before they are computed:
- If the paired CI for delta ring-F1 lies inside [-0.02, +0.02]: report "no detectable effect
  of the ring-level leak on the reported rings".
- If the CI excludes 0: report the direction and size plainly, and state that the shipped rings
  carry that caveat.
- Exact-reproduction share is descriptive; no bar.

7. DELIVERABLES
evaluation/ringfold_report.py, results/tables/v39_ringfold_report.{csv,json}, the two doc
edits, and results/notes/p2_ringfold.md in the form "result, CI, p-value, what it means for
the claim". Feeds the paper's Limitations paragraph on the leak (one sentence + one number).

8. STOP CONDITIONS
Stop and report if: per-seed values do not reproduce; a ring-folded seed directory is
incomplete; the leak-free assertion fails; the paired CI is wider than +/-0.05 (then the test
has no power and the note must say so rather than claim closure).
```

### P3 — Classical external baselines under the protocol

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on AMLworld HI-Small. Do not commit or push; list your changes at the end.

1. GOAL
Reviewers' first objection to the paper is "no external ring-level baseline". Add simple,
reproducible group-detection baselines and score them with the same protocol as our pipeline,
under every scope convention. The paper's claim is about evaluation: we need to show (a) where
standard community detection sits relative to our seeds-plus-components baseline, and (b)
whether method rankings move when the scope convention changes.

2. CONTEXT
- Data/split: HI-Small; train days 0-5, val 6-7, test 8-17; primary window = test days 8-9,
  174 truth rings; scope test_visible; Jaccard 0.5 one-to-one matching; min_size 3.
- Detector scores (causal Multi-GINe, seeds 1-5): experiments/R1_gine_causal/
  scores_{val,test}_seed{S}.parquet (also ../RS-e2e/experiments/R1_gine_causal). Seeds come
  from configs/seeds.yaml = [1,2,3,4,5].
- Our baseline B0: connected components of the top-k% raw-score edges, k and min_size
  grid-searched on VALIDATION (python -m ringshield.run_rings --aggregator cc ...). Every seed
  chose k = 0.1 %, min_size 3. B0 primary ring-F1 = 0.521 [0.429, 0.607] (5 seeds).
  B1b rule = 0.555; learned expansion = 0.582; full pipeline = 0.589 [0.502, 0.675].
- An external method already has an adapter: evaluation/csgm_baseline.py (collaborative
  scatter-gather mining, Tian et al. WWW 2025; upstream cloned to external/, git-ignored). It
  uses no detector; it splits accounts into two institutions at random (--bank-seed, default
  0). One run exists: ring precision 0.545, recall 0.069, ring-F1 0.122.
- A scorer that handles all conventions: evaluation/score_external.py (see docs/PROTOCOL.md).
  If it does not exist yet, stop: it is a prerequisite.
- Louvain is available as networkx.community.louvain_communities (networkx 3.6.1 is pinned).
- PY=.venv312/Scripts/python.exe; PYTHONIOENCODING=utf-8; python -m for package code.

3. HARD CONSTRAINTS
- Every free parameter of a baseline (k, min_size, resolution, len/sim thresholds) is chosen
  on the validation split by ring-F1 and frozen; record the grid and the chosen cell in the
  run's config. Test is scored once.
- Use only causal inputs (the stored scores; no label-derived inputs).
- Do not modify results/FROZEN.json, shipped rings, or existing run directories. New runs go
  under experiments/R13_baselines/<method>/seed{S}/ with rings.parquet + metrics.json +
  config.yaml in the repo's usual schema.
- Adding a dependency: prefer what is installed. If you need leidenalg/python-igraph, check it
  installs on Windows into .venv312, record the exact versions in the run config, and do NOT
  edit requirements-lock.txt; report it instead.
- Record research-test baseline first; it must not get worse.

4. STEPS
a. Write the registration into docs/deep-analysis.md as a new numbered section (next unused
   number >= 15) BEFORE running anything: question, methods, grids, bars from section 6 below.
b. Reproduce B0: re-run run_rings for seed 1 into a temp dir and confirm primary ring-F1
   matches experiments/R2_b0/gine_causal/seed1/metrics.json exactly.
c. Implement evaluation/community_baselines.py with three aggregators over the "flagged-edge
   graph" (accounts as nodes, edges = top-k% raw-score transactions of the split):
   louvain (resolution in {0.5, 1, 2}; weight = max score between the two accounts),
   leiden (same grid; skip with a logged reason if it cannot be installed),
   label_propagation (networkx asyn_lpa_communities, seed fixed).
   k grid = the B0 grid; min_size in {3}. RNG seed 20261114.
   Also run each on the EXPANDED subgraph of the learned policy
   (experiments/R3_expansion/runs/proposed/seed{S}) as a partition alternative.
d. CSGM: run evaluation/csgm_baseline.py for --bank-seed 0..4 (it is detector-free, so the
   five runs differ only by the institution split).
e. Score everything with evaluation/score_external.py on the primary window, all four scope
   conventions, thresholds 0.3/0.5/0.7. Add our B0, B1b, proposed and full from their existing
   run directories to the same table.
f. Optional, time-boxed to half a day: FlowScope (github.com/aplaceof/FlowScope). If it does
   not build on Windows in that time, log why and move on.
g. Expected runtime: community methods ~2-5 min per seed per cell on CPU; CSGM ~10 min per
   run; total under 4 hours.

5. TESTS & SANITY CHECKS
- tests/test_community_baselines.py: on a toy graph of two cliques joined by one edge, louvain
  returns two rings; output schema validates against the rings schema used by ringshield eval.
- Louvain at resolution -> 0 on the flagged-edge graph must reproduce B0's components
  (sanity: with a single community per component, ring-F1 equals B0's on that seed).
- CSGM --bank-seed 0 reproduces 0.122 ring-F1 before the other seeds are run.

6. ACCEPTANCE CRITERIA (pre-registered bars; write them into the registration first)
- Descriptive result: a table of ring P/R/F1 with CIs for every method x convention.
- Bar A ("protocol matters"): SUCCESS if at least one pair of methods changes order between
  test_visible and any other convention, with the reversal visible in point estimates;
  FAILURE if the full ordering is identical under all four. Either outcome is reported.
- Bar B ("baselines are not strawmen"): a community baseline is called competitive if its
  ring-F1 point estimate is >= B0's 0.521 under test_visible. If any external or community
  baseline's ring-F1 exceeds the full pipeline's 0.589, flag it prominently: the paper then
  drops every remaining method-superiority sentence.
- Paired tests (paired_unit_bootstrap, Holm across the comparisons listed in the
  registration): best community baseline vs B0; best community baseline vs full.

7. DELIVERABLES
evaluation/community_baselines.py, experiments/R13_baselines/**, results/tables/
v40_external_baselines.csv/.json, the deep-analysis section with registration and result, and
results/notes/p3_baselines.md in the form "result, CI, p-value, what it means for the claim".
Feeds: the main results table (new rows) and the scope-convention figure.

8. STOP CONDITIONS
Stop and report if: B0 does not reproduce; score_external.py is missing; any baseline needs a
parameter you would have to choose on test; total runtime passes 8 hours; a baseline beats the
full pipeline (finish the table, then stop before touching any doc beyond the registration and
result — the framing decision is the author's).
```

### P4 — Replicate the audit on HI-Medium

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on IBM AMLworld. Do not commit or push; list your changes at the end.

1. GOAL
The paper's strongest contributions are audit findings about the benchmark: (i) the scope
convention moves ring-F1 by 0.35-0.38 on HI-Small, about five times the method effect;
(ii) 44 % of in-scope rings (77 of 174) have no connected in-window piece of >=3 accounts;
(iii) a partition gain that shrinks as the matching threshold tightens; (iv) a degenerate test
tail; (v) a global score quantile that hands most of the seed budget to one day. All but (iv)
and (v) are shown on ONE release with 174 rings. HI-Medium close-out rings now exist with
2,187 truth rings. Re-measure every audit finding there, with no new training, so the paper
can say "reproduced on a second release at 12x the rings" or say honestly where it does not.

2. CONTEXT
- HI-Medium split: train days 0-3, val 4-5, test 6-27. Under Amendment 15 of
  docs/V3_HIMEDIUM_PREREG.md the primary window is days 6-14 (2,187 truth rings) and the seed
  cut is tie-safe. Detector: C1' (experiments_hi_medium/R1_gine_causal_c1prime), seeds 1-2
  usable; seed 3 excluded as degenerate (saturated scores).
- Close-out rings: experiments_hi_medium/closeout_a15/ (per window, rule [global | per-day],
  method [b0, b1b, proposed(b2), full], seed). Scripts: evaluation/hm_closeout.py,
  evaluation/hm_closeout_report.py. Tables: results/tables/v3_closeout_{p1,p2,p3,blocks}.csv,
  v3_closeout_verdicts.json.
- Numbers to reproduce first (global rule, seeds 1-2): full ring recall 0.187 [0.174, 0.200];
  Ring-Recall>=3 0.264; untouched share 28.7 %; full vs b2 matched-rate delta +0.015
  [+0.010, +0.020]; policy vs b1b +0.047 [+0.037, +0.057].
- HI-Small reference values: scope gap -0.347 to -0.383 (results/tables/
  r14_scope_sensitivity.csv); component targets 254 / 108, 77 of 174 with no >=3 piece
  (v36_component_scope.csv); partition recall gain +0.024 / +0.015 / +0.001 at Jaccard
  0.3 / 0.5 / 0.7; tail days 10-17 = 1,108 edges at 59 % base rate; HI-Medium tail days 16-27
  = 6,987 edges at ~58 % (results/tables/v3_day_profile_HI-Medium.csv); day 15 takes 87.5 % of
  seeds (v33_seed_by_day.csv).
- Per-dataset paths: set RINGSHIELD_PATHS=configs/paths_hi_medium.yaml (verify the filename in
  configs/). Scorers: evaluation/score_external.py, scope_sensitivity.py, component_scope.py.
- PY=.venv312/Scripts/python.exe; PYTHONIOENCODING=utf-8; python -m for package code.

3. HARD CONSTRAINTS
- No training, no re-selection, no new rings. Re-score existing close-out rings only.
- HI-Medium numbers are never merged with HI-Small numbers into one figure or average.
- The detector failed its 0.45 validation-AP adequacy gate; every HI-Medium number you report
  must carry that caveat in the table caption and the note.
- Do not touch results/FROZEN.json or any HI-Small artefact. Research tests stay at baseline.

4. STEPS
a. Registration first: add a numbered section (next unused >= 15) to docs/deep-analysis.md
   with the question, inputs, and the bars in section 6, BEFORE computing anything.
b. Reproduce the five close-out numbers in section 2 from the rings.
c. Scope sensitivity: for b0, b1b, proposed, full x {global, per-day}: ring P/R/F1 with CIs
   under test_visible and full_membership; report the gap and median member-set size.
d. Component scope: number of targets, rings with <3 visible members, rings with no in-window
   piece of >=3 accounts, pieces recovered by `full` on rings that have one; ring-F1 under
   component and component_ge3; whether the b0 < b1b < proposed < full ordering holds.
e. Threshold sweep: full-minus-b2 recall and F1 at Jaccard 0.3 / 0.5 / 0.7.
f. Tail and budget: reproduce the day profile (edges, base rate per test day) and the share of
   global-quantile seeds per day for seeds 1-2; one table.
g. In-window disconnection, if feasible in under 2 hours: run evaluation/
   in_window_connectivity.py logic on under-covered rings of the HI-Medium `full` runs; else
   record it as not done.
h. Output results/tables/v41_hm_audit_{scope,component,threshold,tail}.csv and one JSON.
   Expected total runtime: 1-3 hours CPU (2,187 rings, bootstrap 1,000).

5. TESTS & SANITY CHECKS
- The test_visible rows of your scope table equal the close-out report's numbers exactly.
- Target partition check: pieces partition each ring's visible member set (assert).
- Run the same code path once on HI-Small `full` and confirm it returns 77 of 174 and the r14
  gap, to prove the HI-Medium numbers come from the same definitions.

6. ACCEPTANCE CRITERIA (pre-registered; write into the registration before running)
- Scope: REPRODUCED if the full_membership gap is negative for every method and its absolute
  size exceeds the largest method effect on HI-Medium (full minus b0 ring-F1); NOT REPRODUCED
  otherwise.
- Observability: REPRODUCED if the share of rings with no >=3 piece is within 15 percentage
  points of HI-Small's 44 %; report the number either way.
- Threshold dependence: REPRODUCED if the partition recall gain at Jaccard 0.7 is less than
  half its value at 0.3.
- Ordering: report whether proposed > full under component_ge3 again (HI-Small: yes).
- A "not reproduced" is a result and goes in the paper as such.

7. DELIVERABLES
evaluation/hm_audit.py, the v41 tables, the deep-analysis section (registration + result), a
dated note in docs/FINDINGS.md section G, and results/notes/p4_hm_audit.md in the form
"result, CI, p-value, what it means for the claim". Feeds a new "second release" subsection and
one two-panel figure (scope gap and observability, HI-Small vs HI-Medium side by side, never
pooled).

8. STOP CONDITIONS
Stop and report if: the close-out numbers do not reproduce; the HI-Medium paths file or ground
truth is missing; runtime exceeds 6 hours; the HI-Small cross-check does not return 77/174; a
finding flips sign (finish the tables, then stop before editing FINDINGS).
```

### P5 — Sync and reframe the paper for the new results

```text
ROLE: You are editing a LaTeX paper draft about ring-level money-laundering detection on IBM
AMLworld. The draft is in paper_draft/latex/ (main.tex, sections/*.tex, tables/*.tex,
figures/, references.bib) with paper_draft/CLAIMS_CHECK.md, OPEN_QUESTIONS.md and REVIEW.md
beside it. The research repository is E:\JSJ\RS-react (branch integrate/main). You may READ
the repository; you may WRITE only inside paper_draft/. Do not commit or push.

1. GOAL
The draft (v3, titled "Rings, Not Edges: What AMLworld Can and Cannot Tell Us About Recovering
Money-Laundering Attempts") is framed as an evaluation-protocol and benchmark-audit paper. It
predates repository commit aeab2be, which added two results that change three of its claims.
Bring the paper in line with the repository, soften the claims the new data no longer support,
and keep the audit framing.

2. CONTEXT — what changed, with the numbers to use
(a) Ring-level leak, now measured (docs/deep-analysis.md section 8): an expansion policy
    trained on ring-folded cross-scores gives primary-window ring-F1 0.58476 against the
    shipped 0.58192, mean delta +0.0028, inside the pre-registered +/-0.008; per-seed deltas
    range from -0.013 to +0.012. If results/tables/v39_ringfold_report.csv exists, also use its
    paired CI; if not, say the interval is pending.
(b) HI-Medium close-out (deep-analysis section 7; results/tables/v3_closeout_*.csv,
    v3_closeout_verdicts.json): primary window days 6-14, 2,187 truth rings, detector seeds
    1-2, tie-safe seed cut. Full-pipeline ring recall 0.187 [0.174, 0.200] against HI-Small's
    0.461 (pre-registered containment test failed; the detector also failed its adequacy
    gate, and ring-F1 decays with distance from training: 0.408 on days 6-7 to 0.065 on days
    14-15 for seed 1). Untouched rings 28.7 %, partially recovered 8.6 % (both worse than
    HI-Small). But: full vs expansion-only matched-rate delta +0.015 [+0.010, +0.020],
    p_Holm 0.0003; learned policy vs the two-line rule +0.047 [+0.037, +0.057], p_Holm 0.0003.
(c) A new benchmark-audit finding: on HI-Medium seed 3, 780,093 of 18.9 M test scores are
    exactly 1.0, so a strict 99.9 % quantile equals 1.0 and the strict rule "score > q"
    selects ZERO seeds; saturation grows with test day (124 edges on day 6, 221,909 on day 15).
(d) If results/tables/v40_external_baselines.csv or v41_hm_audit_*.csv exist, integrate them
    (new rows in the main results table; a "second release" subsection). If not, leave clearly
    marked TODO comments, not prose placeholders.
Current draft statements that are now too strong:
- "partitioning is a null result" -> null at 174 rings on HI-Small; a small positive effect
  resolved at 2,187 rings on HI-Medium (same size, +0.015).
- "a two-line rule matches the policy" -> matches its recall on HI-Small, where the policy's
  advantage is purity (+0.408 added-member precision, p_Holm 0.0008); on HI-Medium the policy
  also matches more rings than the rule.
- Limitations says the ring-folded result "is not in this draft".
- Findings C10/B17 wording in FINDINGS may lag; the paper follows deep-analysis where they
  differ, and CLAIMS_CHECK must say so.

3. HARD CONSTRAINTS
- Every number carries a LaTeX comment `% source: <repo path> (<row/column>)`. If you cannot
  find a source file for a number, write [NO SOURCE] and do not estimate.
- Headline numbers are the HI-Small primary window (test days 8-9). HI-Medium numbers are
  never averaged or plotted together with HI-Small's, and each carries the caveat "detector
  failed its adequacy gate; 2 seeds".
- No internal codes in prose (B17, C6, R6, P1-P3, "Amendment 15", "close-out"). Describe the
  thing. Codes may appear only in % source comments.
- No hype words. Do not upgrade "not significant" to "promising". Do not present the HI-Medium
  P3 result as overturning the HI-Small nulls: both are reported, with their ring counts.
- Only standard Overleaf packages already in main.tex. Relative paths. Keep \ci{x}{lo}{hi}.
- Do not invent citations.

4. STEPS
a. Read all of paper_draft/latex and CLAIMS_CHECK.md; read deep-analysis sections 7 and 8,
   V3_HIMEDIUM_PREREG.md (Amendments 13-15), and the v3_closeout tables.
b. Abstract, introduction, results (expansion and partition subsections), conclusion and the
   recommendations list: revise the two softened claims. Add recommendation: "state the
   tie-handling rule of any quantile cut".
c. Benchmark-audit section: add a short subsection on score saturation and strict quantile
   cuts; extend the "second release" subsection with the HI-Medium results above and the
   temporal-decay row.
d. Limitations: replace the leak paragraph's last sentences with the measured result; add that
   HI-Medium rests on 2 seeds and a detector below its gate.
e. Add tables/hm_closeout.tex (booktabs) with the P1-P3 rows in plain language.
f. Update CLAIMS_CHECK.md with a dated section: every new or changed number -> source -> value
   -> match. Update OPEN_QUESTIONS.md.
g. Run a static check: balanced environments, every \input and figure exists, every \ref and
   \cite resolves. If pdflatex is available, compile and list warnings; if not, say so.

5. TESTS & SANITY CHECKS
- grep the prose for stale phrases: "is a null result", "not in this draft", "one significant
  link", any [A-C][0-9]+ / R[0-9]+ code outside comments. Zero hits expected.
- Every number you add appears in CLAIMS_CHECK.md with its CSV value.

6. ACCEPTANCE CRITERIA
Done when the three softened claims read consistently in abstract, intro, results, conclusion
and recommendations; the leak paragraph cites the measured delta; the HI-Medium table exists;
the static check passes; CLAIMS_CHECK has no row marked mismatch. No experimental bar applies:
this is writing.

7. DELIVERABLES
Edited .tex files, tables/hm_closeout.tex, updated CLAIMS_CHECK.md and OPEN_QUESTIONS.md, a
rebuilt zip paper_draft/RingShield-paper-latex.zip with main.tex at top level, and a change
summary: one line per edited claim (old wording -> new wording -> source).

8. STOP CONDITIONS
Stop and ask if: a number in the repository contradicts another repository file (list both);
integrating a result would require removing a headline claim entirely; the page count grows
by more than one page (propose cuts instead of making them).
```

### P6 — Related work: verify against PDFs, comparison table, references

```text
ROLE: You are improving the related-work section and bibliography of a LaTeX paper in
paper_draft/latex/ (sections/related.tex, references.bib). You need web access to read
papers. Write only inside paper_draft/. Do not commit or push.

1. GOAL
The paper audits how ring-level (group-level) money-laundering detection is evaluated on the
IBM AMLworld benchmark. Its central positioning claim is that group-level AML papers use
different units, ground truths, matching rules and splits, and none states how a group that
crosses the evaluation window is scored. That claim currently rests on a quick search. Verify
every sentence about another paper against the paper itself, build the comparison table that
makes the claim checkable, and bring the bibliography to about 35 entries with complete
metadata.

2. CONTEXT
- Our protocol, for comparison: unit = laundering attempt (one block of AMLworld's pattern
  file); members = accounts; one-to-one greedy Jaccard >= 0.5 on account sets; scope rule
  "members are the accounts of the ring's in-window transactions"; IBM day split 60/20/20 with
  a reported primary window of test days 8-9; bootstrap CIs over rings.
- Papers already cited and characterised from a partial read (VERIFY EACH):
  Chai et al., AAAI 2023 (AMAP; private Alipay data; DOI 10.1609/aaai.v37i12.26656).
  Rico et al., IJCAI 2026 (TAML; DOI 10.24963/ijcai.2026/723; believed: HI-Small, ego
  sub-network per account, node-wise precision/recall, 70/15/15 temporal split, baselines
  AMAP, Diga, DenseFlow; how ground-truth sub-networks are built is in its supplement).
  Tian et al., WWW 2025 (CSGM; arXiv 2502.19952). Tariq, Kaja, Hassani 2026 (arXiv
  2604.01315; "refined evaluation metric"). Tariq & Hassani, SAC 2026 (ExSTraQt; arXiv
  2604.02899). Lin et al., ICAIF 2024 (FraudGT). Bilgi, Chen, Atasu (MEGA-GNN; arXiv
  2412.00241; venue unknown). Li et al., AAAI 2020 (FlowScope). Bellei et al. 2024
  (Elliptic2). Altman et al., NeurIPS 2023 (AMLworld). Egressy et al., AAAI 2024. Blanusa et
  al., ICAIF 2024 (GFP).
- Candidates to add after verification: DenseFlow (Lin et al. 2024), Diga (Li et al. 2023),
  SMURF (TU Delft thesis extending CSGM), RevTrack/RevClassify (arXiv 2410.08394), LAS-GNN
  (ICAIF 2025), SALT-GNN (arXiv id unverified), Elliptic++ (Elmougy & Liu, KDD 2023), SAML-D
  (Oztas et al. 2023), AMLSim, Tide (arXiv 2603.01863), GARG-AML (arXiv 2506.04292), Tab-AML,
  plus methodology: Efron bootstrap, Holm 1979, Khosla et al. 2020, Ke et al. 2017.
- Three bib entries have "and others" author lists: chai2023, tian2025, khosla2020.

3. HARD CONSTRAINTS
- Never characterise a paper from an abstract or a search snippet. Read the method and
  evaluation sections (and the supplement where the detail lives). If you cannot access a
  paper, mark the cell "not verified" and do not cite a claim about it.
- No invented metadata. Every bib entry: full author list, title, venue, year, pages or
  arXiv id, DOI where one exists. If a field cannot be confirmed, leave it out and list it.
- Do not claim "first" anything. The positioning is: the task exists; the conventions are
  unstated and incompatible; we make them explicit and measure them.
- Be fair to other papers: if one of them DOES state a scope rule or handle the test tail,
  say so and adjust our claim.

4. STEPS
a. For each paper above, extract into a working sheet: dataset(s) and release; split; unit of
   prediction; how ground-truth groups are built; matching rule / metric; whether evaluation
   is restricted to a window; whether cross-boundary groups are discussed; whether the last
   days of AMLworld's test period are treated specially; headline numbers on HI-Small.
b. Write tables/related_comparison.tex (booktabs, fits one column-width or one page-width):
   rows = papers with group-level evaluation; columns = unit, ground truth, metric, split,
   scope rule stated (yes/no), tail handled (yes/no).
c. Rewrite sections/related.tex (about 0.8 page) around that table. Keep the four
   paragraphs: edge-level detection; group-level detection; benchmark artefacts; statistics.
d. Search for any published (peer-reviewed or arXiv) statement of AMLworld's test-tail base
   rate jump or day-0 warm-up. If found, cite it and soften "we are not aware of".
e. Complete references.bib; target about 35 entries, none uncited.
f. Write paper_draft/RELATED_WORK_AUDIT.md: per paper, the page/section where each claim was
   verified, and a list of anything you could not verify.

5. TESTS & SANITY CHECKS
- Every \cite key resolves; no bib entry is uncited; no "and others" remains unless the list
  is genuinely unavailable (then listed in the audit file).
- Every sentence in related.tex that describes another paper has a row in
  RELATED_WORK_AUDIT.md.

6. ACCEPTANCE CRITERIA
Done when the comparison table exists with no unverified cell silently filled, the audit file
covers every characterising sentence, and the bibliography is complete. Pre-registered
reading: if two or more group-level papers turn out to state an explicit scope rule for
cross-window groups, the paper's positioning sentence must be rewritten and you report that
before rewriting anything else.

7. DELIVERABLES
sections/related.tex, tables/related_comparison.tex, references.bib,
RELATED_WORK_AUDIT.md, and a short note: "what changed in our positioning and why".

8. STOP CONDITIONS
Stop and report if: a paper already does what we claim as a contribution (scope-rule
sensitivity, tail quantification, edge-vs-ring decoupling); more than a third of the papers
are inaccessible; you have no web access (then deliver only the checklist of what to verify).
```

### P7 — Third, stronger detector: MEGA-GenAgg

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on AMLworld HI-Small. One NVIDIA RTX A5000 (24 GB), Windows 11, Python
3.12, PyTorch 2.5.1+cu121, PyG 2.8.0. Do not commit or push; list your changes at the end.

1. GOAL
The paper claims that edge F1 is not a proxy for ring recovery: MEGA-GNN beats our Multi-GINe
by 9.4 points of test edge F1 (0.6893 vs 0.5957) and produces the same baseline rings (B0
ring-F1 0.5208 vs 0.5213). A reviewer will say this rests on two detectors about 9 points
apart and a weak reference. Add a third, stronger point: MEGA-GNN with the GenAgg aggregator,
which docs/FUTURE_IMPLEMENTATIONS.md (item F4) records as the strongest published HI-Small
detector at 74.88 +/- 0.38 edge F1. Train it under OUR causal sampler and run it through the
ring layer.

2. CONTEXT
- Split: train days 0-5, val 6-7, test 8-17. Ring metrics on the primary window (test days
  8-9, 174 truth rings), scope test_visible, Jaccard 0.5, 5 seeds [1,2,3,4,5].
- Existing swap: models/mega_adapter.py drives the unmodified upstream code in
  third_party/mega_gnn (github.com/hcagri/MEGA-GNN, commit ef60a71, git-ignored) through
  shims in third_party/shims/ (pure-python stand-ins for two Linux-only modules and wandb).
  Outputs: experiments/R6_mega/ (scores, calibrators, config.yaml). Measured: about 238 s per
  epoch, about 18 h for 5 seeds.
- Downstream per detector (as done for MEGA): calibrate (models/calibrate.py), B0
  (python -m ringshield.run_rings --aggregator cc), detector-specific expansion policy and
  affinity, run_expand, run_partition; table by evaluation/r6_detector_swap.py ->
  results/tables/r6_detector_swap.csv. Read docs/REPRODUCE.md sections 3-5 and 8 for the exact
  commands.
- Reference numbers (5 seeds): gine B0 0.5213 (seed SD 0.045), full 0.5894; mega B0 0.5208,
  full 0.6074; gfpxgb B0 0.3435; rings touched 129.6 (gine) / 128.8 (mega) of 174; every seed
  of every detector chose k* = 0.1 %, min_size 3 on validation.
- PY=.venv312/Scripts/python.exe; PYTHONIOENCODING=utf-8; python -m for package code.

3. HARD CONSTRAINTS
- Upstream model code is not edited; anything needed goes into the adapter or shims.
- Causal neighbour sampling exactly as the MEGA run used it. Checkpoint chosen by validation
  F1. Every downstream parameter re-chosen on VALIDATION per detector per seed
  (--choose-on val is the only accepted value).
- Do not modify results/FROZEN.json, contract/out/, or any existing run directory. New runs
  go to experiments/R6_megagenagg/ and experiments/R6_full/megagenagg/.
- Research tests stay at baseline (record first).

4. STEPS
a. Registration: write a numbered section (next unused >= 15) in docs/deep-analysis.md with
   the question, the arm, and the bars in section 6, BEFORE training.
b. Verify the GenAgg variant exists in the clone and how upstream selects it (flag or config).
   Run a smoke test: 1 % sample, 1 epoch, seed 1. Record peak VRAM and seconds per epoch.
c. Train seed 1 fully. Gate (pre-registered): continue to seeds 2-5 only if seed-1 test edge
   F1 >= 0.70 (clearly above MEGA's 0.689 mean) or validation AP exceeds MEGA seed 1's.
   Otherwise stop: the arm does not provide a stronger point.
d. Train seeds 2-5; score val and test; calibrate.
e. B0 for each seed. Then the full chain (policy, affinity, expand, partition) as for MEGA.
f. Extend evaluation/r6_detector_swap.py to include the new detector; regenerate the table to
   a NEW file results/tables/r6_detector_swap_v2.csv (do not overwrite the old one).
g. Compute seed-set Jaccard and rings-touched overlap against gine and mega.
h. Estimated runtime: 25-35 GPU-hours training, about 2 h CPU downstream.

5. TESTS & SANITY CHECKS
- Before training: re-run the existing table builder and confirm it reproduces
  r6_detector_swap.csv for gine and mega exactly.
- Causality check used for the MEGA run passes on the new run (no sampled neighbour later than
  the batch's latest seed; within-batch window recorded).
- Calibrator fitted on validation rows only (assert row counts).

6. ACCEPTANCE CRITERIA (pre-registered)
Let d = B0 ring-F1(new) - 0.5213.
- "Edge F1 is not a proxy" EXTENDS if |d| <= 0.045 (gine's seed SD) while test edge F1 is at
  least 5 points above gine's.
- It is CONTRADICTED if d > 0.090 (two SDs): then ring recovery does respond to detector
  quality above MEGA's level, and the paper's claim becomes "a plateau between about 0.60 and
  0.69 edge F1".
- Between the two: "inconclusive at 5 seeds"; report it as such.
Report also the paired ring-level test (evaluation.ring_stats.paired_unit_bootstrap) for new
full vs gine full, ring-F1 and added-member precision.

7. DELIVERABLES
experiments/R6_megagenagg/**, the v2 table, the deep-analysis section (registration + result),
a dated note in FINDINGS section G naming row C6, and results/notes/p7_genagg.md in the form
"result, CI, p-value, what it means for the claim". Feeds the edge-F1-versus-ring-F1 figure
(a fourth point) and the detector table.

8. STOP CONDITIONS
Stop and report if: the GenAgg variant is absent or needs upstream edits; it does not fit in
24 GB at the published batch size (report the largest that fits, do not silently shrink the
model); seconds per epoch exceed 2x MEGA's 238 s; the seed-1 gate fails; the existing table
does not reproduce; any downstream stage chooses a parameter at the edge of its validation
grid on 3 or more seeds.
```

### P8 — Budget sweep for every detector

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on AMLworld HI-Small. CPU only. Do not commit or push; list your changes.

1. GOAL
Two paper claims are stated at a single seed budget (top 0.1 % of scores): "a stronger edge
detector buys no rings" and "the seed budget, not the ranking, binds". Show whether they hold
across budgets and under both ways of counting the budget (over the whole test split, or
inside the two-day reporting window), for every detector we have scores for.

2. CONTEXT
- Split: train 0-5 / val 6-7 / test 8-17. Primary window = test days 8-9, 174 truth rings,
  scope test_visible, Jaccard 0.5, seeds [1..5].
- The shipped rule takes a strict global quantile over the WHOLE test split: 864 seeds, of
  which only 463.0 (379-567 per seed) land in the primary window. Validation chose 0.1 % /
  min_size 3 on every seed of every detector.
- Existing scripts to extend rather than rewrite: evaluation/window_budget.py (global /
  in_window / per_day masks, B0 and full with shipped cells, classes and added-member
  precision; table v34_window_budget.csv) and evaluation/r9_robustness.py (0.05 / 0.15 %).
- Scores: gine in experiments/R1_gine_causal, mega in experiments/R6_mega, gfpxgb in
  experiments/R2_b0/gfpxgb_scores, and experiments/R6_megagenagg if it exists. Policies and
  affinity models per detector under experiments/R3_expansion, R4_partition, R6_full. Missing
  directories may be under ../RS-e2e/experiments.
- Reference values at 0.1 % global (gine): rings touched 129.6, B0 ring-F1 0.521, full 0.589,
  added-member precision 0.926; in-window rule: 148.2 / 0.503 / 0.546 / 0.700. At 0.15 %
  global, full 0.606 +/- 0.033 with precision 0.782.
- PY=.venv312/Scripts/python.exe; PYTHONIOENCODING=utf-8; python -m for package code.

3. HARD CONSTRAINTS
- This is a SENSITIVITY analysis. The operating point stays the validation-chosen 0.1 %;
  nothing here changes a shipped or reported number, and no cell is re-tuned per budget (each
  detector keeps its own validation-chosen expansion and partition cells).
- Only the seed mask changes between rows.
- Do not modify results/FROZEN.json or existing run directories; write per-row outputs under
  experiments/R14_budget_sweep/ with metrics.json per (detector, rule, k, seed).

4. STEPS
a. Registration in docs/deep-analysis.md (next unused number >= 15) with the bars below,
   before running.
b. Reproduce v34_window_budget.csv's global and in_window rows for gine.
c. Sweep k in {0.05, 0.10, 0.15, 0.20, 0.30} % x rule in {global, in_window} x detector x
   seed: rings touched, seeds in window, B0 and full ring P/R/F1, untouched count,
   added-member precision, matched rings.
d. Also compute, per k, the seed-set Jaccard and touched-ring union between gine and mega (the
   0.2 % row tests the earlier statement that their union of 150.8 rings is "a 0.2 %-budget
   number").
e. Output results/tables/v42_budget_sweep.csv/.json and a figure script that draws ring-F1
   against seeds-in-window, one line per detector, B0 and full as separate panels.
f. Runtime: about 4 minutes per (detector, rule, k) per seed for the full pipeline; about
   6-8 hours total on CPU. Run detectors in sequence.

5. TESTS & SANITY CHECKS
- k = 0.10 %, rule = global reproduces the published row for each detector to 4 decimals.
- Seeds-in-window is monotone in k for every seed.
- Added-member precision is computed on in-window expanded edges only (same definition as
  results/figures/r9_quiet_vs_precision.csv); assert the 0.926 value at the shipped row.

6. ACCEPTANCE CRITERIA (pre-registered)
- "Budget binds, not ranking" HOLDS ACROSS BUDGETS if, at every k and rule, |B0 ring-F1(mega)
  - B0 ring-F1(gine)| <= the larger of the two seed SDs at that row.
- It FAILS if the gap exceeds two seed SDs at any k >= 0.15 %.
- Union check: at k = 0.20 % global, one detector alone touches >= 140 rings -> "the union
  figure largely materialises at double budget" is supported; < 135 -> not supported.
- Precision veto, as in the earlier analysis: any row whose added-member precision is below
  0.85 is reported as "reach gained at a precision cost", never as an improvement.

7. DELIVERABLES
The v42 table, the figure script and PNG, the deep-analysis section, a FINDINGS section-G
note, and results/notes/p8_budget.md in the form "result, CI, p-value, what it means for the
claim". Feeds one figure and one sentence qualifying the edge-versus-ring claim.

8. STOP CONDITIONS
Stop and report if: the shipped rows do not reproduce; a detector's policy or affinity model
is missing; runtime passes 16 hours; any row would require re-choosing a cell on test.
```

### P9 — A learned sub-network baseline (TAML) under the protocol

```text
ROLE: You are working in E:\JSJ\RS-react (branch integrate/main), a ring-level money-laundering
detection codebase on AMLworld HI-Small. One RTX A5000 (24 GB), Windows 11, Python 3.12.
Do not commit or push. THIS TASK IS TIME-BOXED TO 3 WORKING DAYS.

1. GOAL
The closest published work is Rico et al., "Translating Latent Representations for Money
Laundering Detection" (IJCAI 2026; method TAML; code github.com/rricocuevas1/taml), which does
joint account classification and sub-network discovery and evaluates on HI-Small. Their unit
is the sub-network around each account, scored by node-wise precision and recall; ours is the
laundering attempt, scored by one-to-one Jaccard matching under an explicit scope rule. Run
their extractor on our split and score it with our protocol, and score our rings with their
metric. The point is not to win: it is to show whether the two evaluations rank methods the
same way.

2. CONTEXT
- Our split: train days 0-5, val 6-7, test 8-17; primary window = test days 8-9 (174 truth
  rings); scope test_visible; Jaccard 0.5; min_size 3. Their paper uses a 70/15/15 temporal
  split and account-level labels ("an account is 1 if it participates in at least one
  laundering transaction"), with test accounts removed from training.
- Our scorer: evaluation/score_external.py (minimal input schema: ring_id, members). Our runs:
  experiments/R2_b0/gine_causal (B0, 0.521), R3_expansion/runs/b1b (0.555),
  R3_expansion/runs/proposed (0.582), R4_partition/runs/average (full, 0.589); seeds 1-5.
- Ground truth: data/processed/amlworld_ring_ground_truth.parquet; splits in
  data/processed/amlworld_{train,val,test}.parquet.
- External code goes in external/taml (git-ignored), like external/Collaborative-AML.
- PY=.venv312/Scripts/python.exe for our code; create a SEPARATE venv for theirs if its pins
  conflict, and record it.

3. HARD CONSTRAINTS
- Their model code is not edited beyond what is needed to read our split files; every change
  is recorded as a patch file under experiments/R15_taml/patches/.
- Train on our train days only; choose every threshold (risk cut, hop count K, dedup rule
  parameters) on our validation days; score test once.
- The conversion from per-account sub-networks to a set of predicted rings is fixed BEFORE any
  test number is seen (step c) and written into the registration.
- Do not modify results/FROZEN.json or existing runs. Research tests stay at baseline.

4. STEPS
a. Day 1 feasibility: clone, install, run their own HI-Small example for one epoch. If it does
   not run on Windows natively, try WSL2 with the same GPU. Decide go/no-go by end of day 1.
b. Registration in docs/deep-analysis.md (next unused number >= 15): question, the conversion
   rule, bars. Written before any test scoring.
c. Conversion rule (fixed): take the predicted sub-network of every test-window account whose
   risk score is above a validation-chosen threshold; drop sub-networks with < 3 accounts;
   sort by risk; greedily keep a sub-network unless its Jaccard with an already-kept one is
   >= 0.5 (non-maximum suppression); the kept sets are the predicted rings.
d. Train with their best encoder for 3 seeds (1, 2, 3); produce predictions on val and test.
e. Score with evaluation/score_external.py: four scope conventions, thresholds 0.3/0.5/0.7.
f. Their metric on our rings: for each account in a predicted ring, compute node-wise
   precision and recall of the ring against the account's true sub-network as their Problem 1
   defines it; implement in evaluation/taml_metric.py with a unit test from the paper's
   definition; apply to B0, B1b, proposed, full and to TAML's own output.
g. Output results/tables/v43_taml_under_protocol.csv/.json.
h. Estimated: 15-25 GPU-hours if it runs natively.

5. TESTS & SANITY CHECKS
- Reproduce one headline number from their paper on their own split within a reasonable
  tolerance before using our split (record the number and the gap; if their setup cannot be
  reproduced, say so in the note).
- tests/test_taml_metric.py: hand-built 5-node example.
- NMS conversion is deterministic (same input -> same rings) and unit-tested.

6. ACCEPTANCE CRITERIA (pre-registered)
- Descriptive: ring-F1 with CI for TAML under each convention; node-wise P/R for all methods.
- "The two evaluations disagree" is SUPPORTED if the ranking of {B0, B1b, proposed, full,
  TAML} by their node-wise F-measure differs from the ranking by ring-F1 under test_visible in
  at least one adjacent pair; NOT SUPPORTED if identical.
- If TAML's ring-F1 exceeds the full pipeline's 0.589 under test_visible: report prominently;
  the paper keeps the audit framing and drops any remaining method-comparison language.
- If the task is abandoned at the day-1 gate, the deliverable is a one-page note on why, which
  the paper cites as a limitation.

7. DELIVERABLES
experiments/R15_taml/** (patches, configs, predictions, metrics.json), evaluation/
taml_metric.py with tests, the v43 table, the deep-analysis section, and results/notes/
p9_taml.md in the form "result, CI, p-value, what it means for the claim". Feeds one row
group in the results table and one paragraph in related work.

8. STOP CONDITIONS
Stop and report if: day-1 feasibility fails; their code needs model edits to accept our split;
training exceeds 2x the estimate; their own number cannot be approximately reproduced AND you
cannot find why; the conversion rule would need changing after seeing validation results more
than once (one revision allowed, recorded).
```

### P10 — Submission packaging

```text
ROLE: You are preparing a LaTeX paper for submission. The project is paper_draft/latex/
(main.tex, sections/, tables/, figures/, references.bib). You may read the repository
E:\JSJ\RS-react; write only inside paper_draft/. Do not commit or push.

1. GOAL
Turn the draft into a submission candidate for the venue the author names: correct template,
within the page limit, compiling cleanly, anonymised if required, with one missing figure
added.

2. CONTEXT
- The author will give you: VENUE, TEMPLATE (e.g. ACM sigconf for ICAIF), PAGE LIMIT, and
  whether review is double-blind. If any of these is missing, ask before starting.
- The paper: an evaluation-protocol and benchmark-audit paper on ring-level money-laundering
  detection on IBM AMLworld. Current class: article, 11pt, natbib numeric. Figures are PNGs in
  figures/ (four built by paper_draft/make_figs.py from repository tables). The pipeline
  diagram is TikZ in sections/method.tex.
- Missing figure: an example of one STACK laundering attempt whose transactions fall in two
  or more disconnected pieces inside the reporting window (test days 8-9) — the paper's
  observability argument in one picture. Source data: data/processed/
  amlworld_ring_ground_truth.parquet and amlworld_test.parquet; windows in
  configs/eval_window.yaml. results/tables/r_under_covered.csv lists the 13 partially
  recovered rings (pick a STACK one with about 14-17 members).
- Every number in the .tex has a `% source:` comment; paper_draft/CLAIMS_CHECK.md audits them.

3. HARD CONSTRAINTS
- Do not change any number, claim or citation. This task is layout, cuts and one figure.
- Cuts are proposed first (a list with the lines saved), applied only after the author
  agrees, and moved to the appendix rather than deleted wherever the venue allows one.
- Standard packages only; relative paths; the zip must compile on Overleaf as-is with main.tex
  at the top level.
- If double-blind: remove author block, acknowledgements, repository URLs and the footnote
  URL to a third-party GitHub repository only if it could identify the authors (it cannot;
  keep it); replace "our repository" with "the supplementary material".

4. STEPS
a. Port main.tex to the venue class; fix natbib/biblatex style to the venue's.
b. Compile (pdflatex + bibtex) if a compiler is available; otherwise say so and stop after the
   static checks. Fix every error and every overfull box wider than 5pt; list remaining
   warnings.
c. Build the STACK example: paper_draft/make_fig_stack.py reading the two parquet files;
   draw accounts as nodes, in-window transactions as solid edges, out-of-window transactions
   of the same attempt as dashed grey edges, each connected in-window piece in one colour, the
   recovered fragment outlined. Save figures/fig_stack_example.png at 300 dpi; add it to the
   "where ring recovery stops" section with a two-line caption. Account ids must be relabelled
   A, B, C...
d. Page fit: measure overflow; propose cuts in this order — per-day budget-capture detail,
   the reallocation paragraph, the held-out-pattern paragraph, the second screenshot, the
   explanation/platform appendix.
e. Rebuild paper_draft/RingShield-paper-latex.zip.

5. TESTS & SANITY CHECKS
- Static: balanced environments, all \input and figures exist, all \ref and \cite resolve.
- The figure's ring id, member count and piece count are printed by the script and match
  r_under_covered.csv / the connectivity table.
- A grep for author names, institution, and the repository URL returns nothing in the
  anonymised build.

6. ACCEPTANCE CRITERIA
Compiles with zero errors on the venue class (or, without a compiler, passes static checks
with that stated), is within the page limit or comes with an agreed cut list, contains the
STACK figure, and the zip opens on Overleaf. No experimental bar: this is packaging.

7. DELIVERABLES
The ported project, make_fig_stack.py, the new figure, the zip, a warnings list, and a cut
list with lines saved per cut.

8. STOP CONDITIONS
Stop and ask if: venue details are missing; fitting the limit would require cutting a
contribution or a pre-registered negative result; no STACK ring in the table has a clean
two-piece example; the venue forbids an appendix.
```

---

## Part C — Execution order

```
Day 0        Answer the Questions. Copy paper_draft/ where Opus can see it.

Week 1       GPU track                       CPU / writing track (parallel)
  d1         P7 smoke + seed 1 (gate)        P1 scorer            | P6 related work (start)
  d2         P7 seeds 2-5 (≈25-35 h)         P2 ring-fold report  | P6 continues
  d3-4       (training)                      P3 classical baselines
  d4-5       (training)                      P4 HI-Medium audit
  ── CHECKPOINT A (end of week 1): review P1 reproduction, P2 CI, P3 table, P4 verdicts ──

Week 2
  d6         P7 downstream (CPU)             P5 paper sync (needs P2, P3, P4 numbers)
  d7-8       P9 TAML feasibility + train     P8 budget sweep (CPU, after P7 scores exist)
  ── CHECKPOINT B: P7 verdict; P9 go/no-go ──

Week 3       P9 finishes or is abandoned     P5 second pass with P7/P8/P9; figures
Week 4       —                               P10 packaging; your full read; submit
```

Only one GPU job at a time: P7 first (it is the cheapest strong result), P9 second. P1 blocks
P3, P4 and P9. P6 is independent and should start on day 1.

### Results that change the plan

| If… | Then… |
|---|---|
| P1 cannot reproduce `r14`/`v36` to 4 decimals | Stop everything. Two code paths disagree on the protocol; that is a paper-level bug. |
| P3: a community baseline ≥ full pipeline (0.589) | Keep the audit framing, remove every method-superiority sentence, and **skip P7's downstream `full` chain** (B0 only). |
| P3: orderings identical under all four conventions | The "convention re-ranks methods" claim rests on the partition swap alone; say so, and P9 becomes more important. |
| P4: scope gap or observability **not** reproduced on HI-Medium | Audit claims are HI-Small-specific. Target a workshop, not ICAIF main track; say it plainly in the abstract. |
| P4: reproduced | Promote HI-Medium to a full "second release" subsection and add it to the abstract. |
| P2: paired CI excludes 0 | The leak is real and small; add the caveat to the main results table caption. |
| P7 seed-1 gate fails | Drop P7; state the edge-vs-ring claim as "between 0.60 and 0.69 edge F1". P8 becomes MUST (it is then the only robustness evidence). |
| P7: B0 ring-F1 rises by > 0.09 | The headline "edge F1 is not a proxy" becomes "a plateau". Rewrite abstract and figure caption; P8 becomes MUST. |
| P9 fails its day-1 gate | Skip it; one limitation sentence. Do not spend week 3 on it. |
| P9: TAML beats the pipeline | Good for an audit paper: it becomes the example of a method whose rank depends on the evaluation. Lead the results with the comparison table. |
| P6 finds a paper that states a scope rule or quantifies the tail | Rewrite the positioning before anything else in P5. |
