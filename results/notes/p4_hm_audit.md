# T-P4 — the audit on HI-Medium (2026-11-14)

Flag: **HM_AUDIT=NOT_REPRODUCED**. The scope gap is negative for every method under both rules,
but its size does not exceed the largest method effect.

Inputs:
- Amendment-15 close-out rings (`experiments_hi_medium/closeout_a15`), seeds 1–2, primary window
  = test days 6–14. 2,187 in-scope rings.
- Ground truth and splits from `E:/JSJ/RS-e2e/data/processed_hi_medium`. That folder is absent
  in RS-react. Its ground truth and test split are byte-identical to Ring-Shield's
  (sha256 8fca50f7…, b0c0130e…).
- Test scores from `E:/JSJ/Ring-Shield/experiments_hi_medium/R1_gine_causal_c1prime`, read only.
  They exist only there.
- No new training.

Checks (all pass):
- Step 2: `hm_closeout_report.py` rerun into scratch reproduces `v3_closeout_{p1,p2,p3,blocks}.csv`
  byte for byte. That covers full ring recall 0.187 [0.174, 0.200], Ring-Recall≥3 0.264
  [0.246, 0.280], untouched share 28.7 %, and the P3 rows.
- `test_visible` rows of the new audit equal the close-out report exactly (P/R/F1, max deviation 0).
- Step 8: the same code path on HI-Small `full` gives 77 of 174 and gap −0.3467 (r14: −0.347).
- Pieces partition each ring's visible members (asserted in `build_targets`).
- `tests/test_hm_audit.py` (2) passes.

Every table carries the invariant-11 note: seeds 1–2 only, and the detector missed the adequacy
bar, so this is an audit replication, not a method comparison.

## Bar 1 — scope gap (full_membership − test_visible ring-F1): NOT reproduced

| Rule | Method | test_visible | full_membership | gap |
|---|---|---|---|---|
| global | B0 | 0.0898 | 0.0519 | −0.038 |
| global | B1b | 0.0974 | 0.0542 | −0.043 |
| global | proposed | 0.1804 | 0.1214 | −0.059 |
| global | full | 0.1822 | 0.1257 | −0.057 |
| per day | B0 | 0.1475 | 0.0867 | −0.061 |
| per day | B1b | 0.1408 | 0.0818 | −0.059 |
| per day | proposed | 0.2327 | 0.1597 | −0.073 |
| per day | full | 0.2338 | 0.1648 | −0.069 |

- Every gap is negative, so the sign reproduces and no finding flips.
- The bar fails on size. Global: smallest |gap| 0.038 < full − B0 0.092. Per day: 0.059 < 0.086.
  On HI-Small the gap (−0.347 for full) dwarfed every method effect. On HI-Medium it is the same
  order as the method effects.
- Median target size: 4 accounts under test_visible, 8 under full_membership.
- Hypothesis, not tested: a 9-day window holds far more of each ring than HI-Small's 2-day
  window, so cutting to visible members costs less.

## Bar 2 — observability: within band

- 875 of 2,187 in-scope rings (**40.0 %**) have no in-window piece of ≥ 3 accounts, against
  HI-Small's 44.3 % (77/174). That is −4.2 points, inside ±15.
- 669 rings have < 3 visible members; 343 split into ≥ 2 pieces; 1,912 pieces have ≥ 3 accounts.
- `full` recovers 26.8 % of ≥ 3-account pieces (global) and 35.9 % (per day). HI-Small: 70.6 %.

## Bar 3 — threshold: reproduced

| Rule | Gain at 0.3 | 0.5 | 0.7 | 0.7 < ½ × 0.3? |
|---|---|---|---|---|
| global | +0.0194 | +0.0149 | +0.0089 | yes |
| per day | +0.0279 | +0.0194 | +0.0098 | yes |

The gain is full − expansion-only ring recall. The gain in ring-F1 is near zero at every τ:
global +0.004 / +0.002 / +0.0003, per day +0.006 / +0.001 / −0.003.

## Component orderings

- `component` keeps B0 < B1b < proposed < full under both rules.
- **proposed > full under `component_ge3` again, under both rules**: 0.2434 vs 0.2430 global,
  0.3274 vs 0.3237 per day. Tiny, but in the same direction as HI-Small.
- Per day, B1b < B0 under test_visible and component_ge3.

## Tail and budget (step 6): as expected

- Days 16–27 hold 6,987 edges at a base rate of about 58 %.
- Day 15 holds 3.02 M edges at a 0.08 % base rate and takes **87.5 %** (seed 1) and 87.1 % (seed 2)
  of the global-quantile seeds.
- Step 7 (in-window disconnection of missing members): **not done**, so T-P4 stays inside budget.

Supports / weakens / kills: "the audit findings hold on a second release".
- *Supports*: observability, the threshold dependence, proposed > full under component_ge3, and
  the sign of the scope gap.
- *Weakens*: the scope gap's size. It is no longer larger than the method effects, so the
  abstract cannot say the scope effect "reproduces on two releases" in the registered sense.

Proposed FINDINGS section-G note (for the author; FINDINGS.md not edited):
> *(2026-11-14, T-P4; docs/deep-analysis.md §17)* On HI-Medium (seeds 1–2, days 6–14), the
> full_membership − test_visible gap is negative for every method. Under the global rule it
> ranges −0.038 to −0.059; across all eight cells (both rules) it ranges −0.038 to −0.073. It is
> smaller than full − B0 (0.092 global, 0.086 per day), so the registered scope bar is not met
> (HM_AUDIT=NOT_REPRODUCED). The observability share (40.0 % vs 44.3 %) and the threshold
> dependence (gain at 0.7 < half the gain at 0.3) reproduce.

Outputs: `results/tables/v41_hm_audit_{scope,component,threshold,tail}.csv` and `v41_hm_audit.json`
(9bd8f2af…, 1f136d43…, 08503abc…, 887736de…, 885f86a7…). Code: `evaluation/hm_audit.py`.
