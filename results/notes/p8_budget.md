# T-P8 — budget sweep for every detector (2026-11-15)

Table: results/tables/v42_budget_sweep.{csv,json} and v42_budget_sweep_pairs.csv (builder: evaluation/budget_sweep.py).
Cells: experiments/R14_budget_sweep/<det>/<rule>/k<pct>/seed<S>. MEGA uses scoring batch 2048 with ring configs from
R6_full_sb2048_k010: the seed budget is fixed at 0.1 % because the pre-registration fixes it (T-P7 and the T-P8 reference cell; decision D-1). The old val-picked MEGA sweep is in experiments/R14_budget_sweep/_superseded_mega_valpicked_k/ (kept, not used).
Consistency checks: GINe global k = 0.10 seed 1 reproduces v34 (402 / 123 / 0.5391 / 0.6045 / 0.9189). MEGA global k = 0.10 equals
the r6_detector_swap_sb2048 rows (B0 0.5179, full 0.6023).

## Bars (pre-registered, deep-analysis §19)
- **Gap bar: HOLDS.** |B0 ring-F1(MEGA) − B0 ring-F1(Multi-GINe)| ≤ the larger seed SD in all 10 rows. Largest gaps: global 0.30 −0.041 (SD 0.052), global 0.05 −0.037 (SD 0.067). The failure bar (> 2 SD at k ≥ 0.15) is not met anywhere.
- **Union bar: SUPPORTED.** At k = 0.20 % global, one detector alone touches 152.0 (GINe), 156.2 (MEGA) or 152.8 (GFP+XGB) rings (bar ≥ 140), so the two-detector union of 150.8 is reachable with a single detector given double budget.
- **Veto:** added-member precision falls below 0.85 for GINe at global k ≥ 0.15 (0.849 at 0.15) and in-window k ≥ 0.10, for MEGA at global k ≥ 0.15 and in-window k ≥ 0.10, and for GFP+XGB in every row. Those rows are "reach gained at a precision cost", never an improvement.

## B0 / full ring-F1 by budget (global, mean of 5 seeds)
| k % | GINe B0 | GINe full | MEGA B0 | MEGA full | GFP+XGB B0 | GFP+XGB full |
|---|---|---|---|---|---|---|
| 0.05 | 0.330 | 0.429 | 0.293 | 0.396 | 0.200 | 0.422 |
| 0.10 | 0.521 | 0.557 | 0.518 | 0.602 | 0.344 | 0.451 |
| 0.15 | 0.552 | 0.574 | 0.572 | 0.599 | 0.378 | 0.383 |
| 0.20 | 0.538 | 0.542 | 0.542 | 0.548 | 0.362 | 0.310 |
| 0.30 | 0.487 | 0.481 | 0.447 | 0.450 | 0.308 | 0.216 |

## FINDING (decision D-3): validation-chosen budgets are unstable, MEGA batch 2048 — not used in any paired test
File: results/notes/p8_mega_valpicked_sensitivity.csv. Val ring-F1 is the best val cell at that k (ring configs R6_b0_sb2048/mega); test values are the T-P8 global cells.

| seed | val chose k | val F1 @0.05 | val F1 @0.10 | test B0 @0.05 | test B0 @0.10 | test full @0.05 | test full @0.10 |
|---|---|---|---|---|---|---|---|
| 1 | 0.10 | 0.481 | 0.498 | 0.353 | 0.506 | 0.504 | 0.598 |
| 2 | 0.10 | 0.477 | 0.513 | 0.221 | 0.508 | 0.329 | 0.567 |
| 3 | 0.10 | 0.490 | 0.530 | 0.319 | 0.482 | 0.398 | 0.607 |
| 4 | 0.05 | 0.549 | 0.539 | 0.289 | 0.522 | 0.361 | 0.614 |
| 5 | 0.05 | 0.552 | 0.530 | 0.284 | 0.571 | 0.389 | 0.626 |

Reading: on validation the best cells at 0.05 % and 0.1 % differ by at most 0.04 ring-F1, and the choice between them flips across seeds (seeds 4–5 pick 0.05 %). On test, the two budgets differ by 0.15–0.29 seed-only ring-F1 in every seed. A budget chosen on validation is therefore unstable: a near-tie on validation corresponds to a large difference on test. This is a finding about validation-chosen budgets only. It is not used in any paired test, and it plays no part in the budget used elsewhere, which the pre-registration fixes.

GenAgg ring rows: pending (GPU chain, seeds 2–5 training).
