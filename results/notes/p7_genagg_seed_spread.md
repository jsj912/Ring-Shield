# MEGA-GenAgg seed spread: why seeds 4 and 5 score lower (2026-11-16)

This uses existing score files only. Nothing was retrained or rescored. Script:
`evaluation/p7_genagg_seed_spread.py`; table: `results/tables/p7_genagg_seed_spread.csv`.

**Method.** The threshold is tuned on validation exactly as in `r6_detector_swap.edge_f1`: `score_raw`, 400 quantiles
in [0.90, 0.99999], ties broken to the larger threshold. The test F1 values reproduce the reported
per-seed edge F1 exactly (0.7557 / 0.7516 / 0.7442 / 0.6552 / 0.6700). The test-optimal F1 is a
**diagnostic only** and is never reported as a result. Days are `timestamp // 86400`: test days 8–9 are
the two ordinary-traffic days, and days 10–17 are the tail.

## MEGA-GenAgg, per seed
| seed | val F1 @ thr | thr | test F1 @ thr | test F1, test-optimal (diag.) | test AP | test ROC-AUC | test F1 d8–9 | test F1 d10–17 | val AP |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.666 | 0.553 | 0.756 | 0.758 | 0.745 | 0.989 | 0.633 | 0.910 | 0.626 |
| 2 | 0.664 | 0.524 | 0.752 | 0.760 | 0.748 | 0.989 | 0.613 | 0.931 | 0.621 |
| 3 | 0.652 | 0.472 | 0.744 | 0.751 | 0.742 | 0.988 | 0.620 | 0.900 | 0.617 |
| **4** | 0.639 | 0.429 | **0.655** | 0.685 | **0.679** | 0.991 | 0.531 | 0.856 | 0.611 |
| **5** | 0.646 | 0.653 | **0.670** | 0.675 | **0.681** | 0.988 | 0.560 | 0.837 | 0.600 |

## Reading
- **The main cause is ranking quality, not the threshold.**
  - Even at the test-optimal threshold, seeds 4 and 5 reach only 0.685 and 0.675, against 0.75–0.76 for seeds 1–3.
  - Test AP drops by the same amount: 0.679 and 0.681, against 0.742–0.748.
  - ROC-AUC barely moves (0.988–0.991), so the difference is at the top of the ranking, where F1 and AP are decided.
- **Threshold transfer adds a little for seed 4 only.** Its val-tuned threshold loses 0.030 of F1 against the test optimum (0.655 against 0.685). Seed 5 loses 0.005, and seeds 1–3 lose 0.002–0.008.
- **It is not the tail alone.** Seeds 4 and 5 are lower in both periods:
  - days 8–9: F1 0.531 / 0.560 against 0.61–0.63, AP 0.552 / 0.550 against about 0.58;
  - days 10–17: F1 0.856 / 0.837 against 0.90–0.93.
- **It was partly visible on validation.** Validation F1 (0.639 / 0.646 against 0.652–0.666) and validation AP (0.611 / 0.600 against 0.617–0.626) are the lowest of the five seeds. Validation understates the test gap.
- **The spread is not peculiar to GenAgg.**
  - MEGA-GIN at batch 2048 ranges from 0.631 (seed 1) to 0.751 (seed 4).
  - Shipped Multi-GINe ranges from 0.481 (seed 5) to 0.658 (seed 3).
  - GenAgg's five-seed SD of 0.049 is like MEGA-GIN's 0.045, and smaller than Multi-GINe's 0.071.

**Conclusion.** Seeds 4 and 5 are weaker rankers: training-seed variance that shows on both test periods
and partly on validation. Seed 4 also loses about 0.03 to threshold transfer. All five seeds are reported
as they are (author decision); the reported value is 0.715 ± 0.049.
