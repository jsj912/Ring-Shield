# Pre-registration — method track M1 / M2 / M3 (2026-11-15)

Repository: `E:\JSJ\RS-react`, branch `integrate/main`. Written before any M-track run. Frozen once
its sha256 is recorded in `paper/METHOD_PROGRESS.md`; never edited afterwards; changes go in a
dated amendment file. Like `paper/PREREG_2026-11-14.md`, these analyses use a test window that has
been examined many times; they are labelled follow-up method analyses, not confirmatory tests.

## 0. Fixed protocol (all parts)

- AMLworld HI-Small. Train days 0–5, validation 6–7, test 8–17. Primary window test days 8–9
  (174 truth rings). Scope `test_visible`; one-to-one greedy matching, Jaccard ≥ 0.5; minimum
  ring size 3. Detector Multi-GINe causal (`experiments/R1_gine_causal`, read from
  `../RS-e2e/experiments/R1_gine_causal` where missing), detector seeds 1–5.
- Scoring: `evaluation/score_external.py`, default (weighted) intervals, all four conventions,
  τ ∈ {0.3, 0.5, 0.7}. Paired: `score_external.py --compare A B` (10,000 draws, seed 20261114).
  Test labels are read by the scorer only.
- Reference (comparator) arm **REF** = ring-folded full pipeline at 0.1 % global seed budget,
  `experiments/R4_partition_ringfold/average/seed{1..5}`.
- Reference checks, done before this file was written (2026-11-15,
  `experiments/M1_verifier/refcheck/`): B0 0.5213 (= 0.5213), full 0.5894 (= 0.5894),
  ring-folded full 0.5893 (= 0.5893), test_visible τ 0.5. All pass.
- Seed budgets are fixed here, never chosen on validation: M1 0.2 % global; M2 and M3 0.1 %
  global (the same quantile rule as `evaluation/window_budget.seed_mask(rule="global")`).
- Anything trained uses train-period labels only, with the ring-folded cross-scores
  (`experiments/R3_ringfold/cross_scores`) as the detector score on train days. Anything tuned is
  tuned on the validation window (`--split val --window val`) from the grid fixed below. Ties on
  validation ring-F1 are broken toward the first cell in the grid order written below.
- Compute: CPU only, at most 18 processes/threads; any job projected over 6 hours stops for a
  decision.

## 1. Primary comparison, decision rule and readings (identical for every part)

Primary metric: ring-F1, test_visible, τ 0.5, primary window, 5 seeds; paired difference
Δ = part − REF from `--compare`. Family: the three parts M1, M2, M3, **Holm-corrected with
m = 3 fixed**. A part that does not reach test (gate stop, time-box stop, not run) enters the
Holm step with p = 1.

Secondary guard: **added-member precision** (AMP) = share of in-window expanded edges of the
part's rings that are truth ring edges, computed by `ringshield.expand.run_expand.expansion_vs_truth`
against the seed-only (B0) rings of the **same seed set** (0.2 % for M1, 0.1 % for M2/M3), pooled
over 5 seeds — the definition behind `results/figures/r9_quiet_vs_precision.csv` and T-P8.

Readings — evaluated in this order; the first that applies is the reading, so every outcome has
exactly one:

| # | Condition | Reading |
|---|---|---|
| R0 | Part stopped before test (validation gate failed, time box, a stop-and-ask not resolved in favour of continuing, or not run) | **NOT TESTED** — reported with the validation numbers that stopped it |
| R1 | unadjusted 95 % CI lies entirely above 0 **and** p_Holm < 0.05 **and** AMP ≥ 0.80 | **SUCCESS** |
| R2 | CI entirely above 0 and p_Holm < 0.05 and AMP < 0.80 | **GAIN AT A PRECISION COST** — never called an improvement |
| R3 | CI entirely above 0 and p_Holm ≥ 0.05 | **NOMINAL GAIN, NOT SURVIVING HOLM** — not claimed |
| R4 | CI entirely below 0 | **WORSE THAN REF** (p_Holm reported) |
| R5 | CI contains 0 and lies inside [−0.02, +0.02] | **NO DETECTABLE EFFECT** (equivalence at ±0.02) |
| R6 | CI contains 0 and has an end outside [−0.02, +0.02] | **INCONCLUSIVE** |

Always reported beside the reading, per part and for REF: ring precision, ring recall, quiet-member
recall (r9 definition), rings output per seed and accounts output per seed (analyst workload),
per-pattern recall, the other three conventions and τ 0.3 / 0.7 (descriptive only).

Prior expectation recorded for honesty: B13/B16 bound the in-window addressable under-coverage at
~19 % (mostly GATHER-SCATTER at one hop), and B14/C7 say most extra reach needs extra budget. So
R5/R6 are the expected readings for M2 and M3; M1 is the part with a mechanism (C7: 0.2 % reaches
~152 rings) and a known cost (T-P8: GINe full at 0.2 % falls to 0.542 with AMP < 0.85).

## 2. Part M1 — over-generate at 0.2 % and verify

**Hypothesis.** Running the ring-folded full pipeline at 0.2 % reaches more truth rings; a
ring-level classifier trained on train-period candidates can reject enough false candidates that
ring-F1 exceeds REF.

**Candidate generator (fixed).** The route of `evaluation/budget_sweep.py::run_detector` for
`gine_causal`, `rule = global`, `k = 0.20`, with the ring-folded expansion policy
(`experiments/R3_ringfold/expansion/policy_proposed`) and the ring-folded fixed cell
(`experiments/R3_ringfold/runs/proposed/seed{S}/config.yaml`), the R4 affinity and the average-linkage
cut from `experiments/R4_partition_ringfold/average/seed{S}/config.yaml`. Precondition: the same
code with the shipped (day-fold) inputs reproduces the v42 row `gine_causal | global | 0.20 | seed 1`
(B0 and full ring-F1 to 1e-4); otherwise stop and ask.

**Training set.** The same generator run on the **train split** (days 0–5) with the ring-folded
cross-scores (`cross_scores_train.parquet`, owner-fold `score_raw`) as the edge score, 0.2 % of
train edges. Label 1 if the candidate's train-visible account set matches a train truth ring at
Jaccard ≥ 0.5 (one-to-one greedy), else 0. No validation- or test-period ring contributes a label
or a feature statistic (no normalisation fitted outside train). A unit test
(`tests/test_m1_verifier.py`) asserts: every training candidate's edges have day ≤ 5; every label
ring id is a train ring; feature scaling statistics come from the train frame only; a validation
or test truth ring injected into the inputs changes no training label.
Known caveat (stated, not fixed): the expansion policy and the affinity model were themselves fit
on train-period labels, so policy-probability and affinity features are partly in-sample on the
training candidates; the validation-chosen threshold is the guard.
Stop-and-ask if the training set has fewer than 50 positive candidates.

**Features (no ids).** n_members, n_edges, density, seed-edge count and seed share, detector score
of member edges (mean, max, min, std), expansion probability of expanded edges (mean, min, count;
0 when none), duration_hours, amount statistics of member edges (log mean, log std, max/min ratio),
confidence, max_edge_prob, conservation_closure, topology_probs (8 values), counts of source /
sink / mule accounts, n_currencies.

**Model (fixed).** LightGBM 4.7.0 `LGBMClassifier(n_estimators=200, learning_rate=0.05,
num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
reg_lambda=1.0, random_state=S, deterministic=True, force_row_wise=True, n_jobs=8)`; one model per
detector seed S (training candidates are shared across seeds — the ring-folded cross-scores exist
for one fold set — so seeds differ by `random_state` and by their own test/val candidates).

**Variants.** M1-V (primary): keep candidates with classifier probability ≥ t. Baselines in the
same table (not in the Holm family): REF; full at 0.2 % unverified; score-only filter M1-S (keep
candidates whose mean member-edge detector score ≥ c).

**Validation grid.** t ∈ {0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9} (9 cells). M1-S: c = the
q-quantile of mean detector score over that seed's validation candidates, q ∈ {0, 0.1, …, 0.8}
(9 cells). Chosen per seed on validation ring-F1 (val window, test_visible, τ 0.5).

**Gate (seed 1).** Proceed to seeds 2–5 and test only if seed-1 validation ring-F1 of M1-V at its
chosen t is strictly greater than REF seed 1's validation ring-F1 at its chosen cut (from its
`config.yaml grid_results_val`). Otherwise R0.

**Also reported:** the score-only comparison M1-V − M1-S (paired, descriptive, not in the family):
if M1-V does not beat M1-S on test, the paper says the classifier adds nothing over a score filter,
whatever M1's reading.

## 3. Part M2 — temporal motif search from seeds

**Hypothesis.** Searching the window's transaction multigraph outward from 0.1 % seed edges for the
ground-truth pattern shapes recovers members the expansion policy misses, raising ring-F1 over REF.

**Search.** From each seed edge, enumerate time-ordered instances containing the seed of:
CYCLE (length 3 … L), FAN-IN and FAN-OUT (degree ≥ f), SCATTER-GATHER, GATHER-SCATTER,
BIPARTITE (≥ 2 × 2), STACK (two chained bipartite layers), all edges within a span T of the seed.
Edge visibility: the scored split's edges that the expansion step's `candidates()` could reach
(same split, same causal rule); a unit test asserts M2 never uses an edge outside it.
Caps fixed now: at most 50 instances per seed (highest mean detector rank first); accounts with
in-window total degree > 100 are not traversed. Cap-binding rates are logged.
Rings: seed-only CC rings plus instances; instances and rings sharing ≥ 2 accounts are merged
(union-find); min size 3.

**Variants.** M2-S structure-only; M2-G score-gated (non-seed edges need a detector score rank
in the top g of the split).

**Validation grid (24 cells).** T ∈ {24 h, 72 h} × f ∈ {3, 5} × L ∈ {4, 6} = 8 cells for M2-S;
the same 8 × g ∈ {1 %, 5 %} = 16 cells for M2-G. The single primary arm for the family is the
variant-and-cell with the best validation ring-F1 on seed 1 (grid order: M2-S then M2-G, T, f, L,
g ascending); seeds 2–5 re-choose the cell within that variant.

**Unit tests.** Hand-built graphs for each of the seven shapes, a time-order violation that must
not match, a span violation, both caps, and the visibility guard.

**Gate.** As M1, against REF seed 1 validation ring-F1.

## 4. Part M3 — flow-following expansion (only if M1 or M2 finished inside its time box)

**Hypothesis.** Following money (an account's outgoing amount matching an earlier incoming amount)
from seed-only rings recovers pass-through members and raises ring-F1 over REF.

**Method.** Start from B0 rings at 0.1 %. Repeatedly, for a ring account a with incoming edge
(u → a, amount x, time t), add outgoing edges (a → v, amount y, time t′) with
t < t′ ≤ t + D and |y − x| / x ≤ ε (amounts in the transaction's paid currency when currencies
match, else in USD via the repository's FX table); and symmetrically backwards for incoming edges
into ring accounts. Up to H hops. Same edge visibility and hub cap (degree > 100) as M2. Rings
sharing ≥ 2 accounts are merged; min size 3.

**Validation grid (18 cells).** ε ∈ {0.01, 0.05, 0.10} × D ∈ {6 h, 24 h, 72 h} × H ∈ {1, 2}.
Gate as M1.

## 5. Outputs and stopping

Per part: `results/tables/m<N>_*.csv/.json`, a section in `results/notes/m_track.md`, progress in
`paper/METHOD_PROGRESS.md`. Any SUCCESS (R1) stops the track for the author's decision on HI-Medium
replication. Stop and ask on: a failed reproduction, a result that fits none of R0–R6 (should be
impossible; would mean a defect here), a job projected over 6 hours, or a need to touch a file not
owned by this track. Time boxes: M1 2 days, M2 1.5 days, M3 1 day; a part that runs out of time is
R0.
