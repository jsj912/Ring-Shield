# Why `full` has two intervals: r9 [0.502, 0.675] vs r14 / v40 [0.523, 0.653] (2026-11-14)

**Finding: the two bootstraps resample the same unit (truth rings, seeds averaged inside each draw),
but the r14 one silently drops the multiplicities. It is a subsample, not a bootstrap, and its
intervals are about 25 % too narrow.**

## The code

- `evaluation.ring_stats.bootstrap_over_rings` (r9_ring_ci.csv, FINDINGS A3, the close-out report):
  draws |T| ring ids with replacement and passes their counts as `weights` to
  `metrics_from_evidence(ev, sub, w)`. A ring drawn three times counts three times.
- `evaluation.scope_sensitivity.boot` (r14_scope_sensitivity.csv, v36_component_scope.csv, and
  through it `evaluation/score_external.py`, so v40 and v41): draws |T| ids with replacement and
  passes the list with repeats as `truth_ids`, with **no weights**.
- `metrics_from_evidence` sets `w = {i: 1}` when no weights are given and sums over `set(ids)`, so
  repeats collapse. Each r14 "resample" is the set of distinct rings drawn, each counted once: on
  average 63.4 % of the 174 rings. That is a without-replacement subsample of about 0.63 n.
- The variance of a without-replacement subsample of fraction f = 0.632 is (1 − f) / (f n) ≈ 0.58 / n,
  against 1 / n for the bootstrap. The expected SD ratio is √0.58 ≈ 0.76. Observed width ratio:
  0.130 / 0.173 = 0.75.

## The check (same evidence, `full`, 5 seeds, primary, test_visible, τ 0.5, seed 0, 1,000 draws)

| Procedure | ring-F1 | 95 % interval |
|---|---|---|
| `scope_sensitivity.boot` as shipped (r14) | 0.5894 | [0.5234, 0.6529] |
| the same draws, with the counts passed as weights | 0.5894 | [0.5023, 0.6747] |
| `ring_stats.bootstrap_over_rings` (r9) | 0.5894 | [0.5023, 0.6747] (r9_ring_ci.csv: 0.50226, 0.67469) |

Adding the weights reproduces r9 exactly. Point estimates are unaffected (they use every ring once).

Script: scratchpad `interval_check.py`. It imports the repository functions and changes no file.

## Consequences

- **Correct:** r9_ring_ci.csv and every table built on `bootstrap_over_rings` (FINDINGS A3, the
  HI-Medium close-out), and the paired tests (`paired_unit_bootstrap` builds count matrices with
  `np.bincount`, so multiplicities are kept; v35, v39).
- **Too narrow:** the intervals in r14_scope_sensitivity.csv, v36_component_scope.csv, and
  everything scored with `evaluation/score_external.py`: T-P1's reproduction, v40 (T-P3) and v41
  (T-P4). r14 and v36 are frozen and stay as they are.
- `score_external --compare` uses `paired_unit_bootstrap`, so its paired intervals and p-values
  (T-P3 bar B) are unaffected.
- T-P1's gate (reproduce r14 / v36 to 1e-4) was met *because* the scorer copies this behaviour.

## Paper rule (author, Checkpoint A, decision 7)

The headline interval is the FINDINGS one (r9). Any table using the r14-style interval says so in
its caption; no table mixes the two.

## Recommendation (needs the author's decision)

Give `score_external.py` weighted resampling by default (a correct bootstrap, equal to r9). Keep a
`--legacy-subsample-intervals` flag that reproduces r14 / v36, so the T-P1 reproduction still runs.
Then rescore v40 and v41 into new files (`_v2`); point estimates and paired tests do not change.
Until then the v40 / v41 intervals are the r14-style ones and must be captioned as such.

## Resolution (2026-11-15, author decisions 2–6)

- `score_external.py` now uses weighted resampling by default (= r9). `--legacy-subsample-intervals` reproduces r14/v36, and T-P1 re-run with it gives 90 cells, max deviation 0.0.
- Corrected tables (new files; frozen originals untouched; every point estimate bit-identical):
  `r14_scope_sensitivity_wci`, `v36_component_scope_wci`, `v40_external_baselines_v2`, `v41_hm_audit_*_v2`.
- Every interval in the paper now comes from the weighted bootstrap. The captions that distinguished two interval types are removed.
- `ring_stats.metrics_from_evidence` and `scope_sensitivity.boot` are unchanged. The collapse is logged as an open defect, with a proposed fix, in `paper/RUNBOOK_PROGRESS.md`.

## Proposed FINDINGS note (for the author to approve; NOT added to docs/FINDINGS.md)

> **Dated note — 2026-11-15 (intervals of r14 / v36).** The 95 % intervals in
> `r14_scope_sensitivity.csv` and `v36_component_scope.csv` are too narrow, by about a quarter.
> Their bootstrap passed resampled ring ids without counts, and `metrics_from_evidence` counts each
> distinct id once, so each resample was a ~63 % subsample rather than a bootstrap. Point estimates
> are unaffected. Corrected intervals, using the same draws with counts as weights (the procedure
> behind r9 and A3), are in `r14_scope_sensitivity_wci.csv` and `v36_component_scope_wci.csv`.
> For example, the full pipeline's test_visible ring-F1 is 0.5894 [0.5023, 0.6747] rather than
> [0.5234, 0.6529]. Corrected widths are ×1.30–1.41 (r14) and ×1.24–1.39 (v36). No claim in this
> file rests on those intervals' width; the verdict rechecks are in `results/notes/interval_consistency.md`.

## Verdict recheck with corrected intervals (2026-11-15, author decision 4)

Every gate or bar decided so far, and whether it used an r14-style interval:

| Gate / bar | Used an r14-style interval? | Recheck | Result |
|---|---|---|---|
| T-P1 reproduction (r14/v36 to 1e-4) | yes: it reproduces them | re-run with `--legacy-subsample-intervals`: 90 cells, max deviation 0.0 | **unchanged** (PASS) |
| T-P2 ring-F1 equivalence and follow-ups | no (`paired_unit_bootstrap`; r9-style ring CIs via step9_tables) | — | **unchanged** (INCONCLUSIVE) |
| T-P3 bar A (adjacent swaps across conventions) | no: point orderings | v40_v2 `bar_A` identical | **unchanged** (met, narrowly) |
| T-P3 bar B (best community vs B0 / full) | no: `score_external --compare` = `paired_unit_bootstrap` | v40_v2 `bar_B` identical | **unchanged** (not competitive) |
| T-P3 gate (any baseline ≥ 0.5894) | no: points | v40_v2 `gate` identical | **unchanged** (METHOD_SUPERIORITY=ON) |
| T-P4 scope bar | no: point gaps vs point full−B0 | v41_v2 `verdicts.scope` identical | **unchanged** (NOT_REPRODUCED) |
| T-P4 observability band | no: counts | identical | **unchanged** (in band) |
| T-P4 threshold dependence | no: point gains | identical | **unchanged** (reproduced) |
| Checkpoint A §5 table (test_visible [CI] column) | yes: displayed intervals only, no verdict | corrected values in v40_external_baselines_v2.csv (e.g. full [0.502, 0.675], B0 [0.429, 0.607]) | display only; no verdict depends on it |

No verdict changed, so no Addendum B to the amendment file is needed (sha256 stays 705e2ccc…).
All point columns of r14_wci, v36_wci, v40_v2 and v41_*_v2 are bit-identical to the frozen originals.
Corrected/legacy width ratios: r14 ×1.30–1.41, v36 ×1.24–1.39, v40 ×1.19–1.49 (median 1.33).
