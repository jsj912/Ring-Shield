# Part A: rank-averaged ensemble as the seed source (2026-11-16, post hoc). GATE FAILED, no test read

Pre-registration: paper/PREREG_RECOVERY_2026-11-16.md (sha256 a265194c…), Part A.
Each ensemble is one run, not five seeds. Ensemble scores are the mean percentile rank within each split
(evaluation/build_rank_ensembles.py) → experiments/R16_ensemble/<name>/. Isotonic calibration was fit on
validation, the budget was fixed at 0.1 %, and the full arm uses the no-embedding policy and affinity.
E-All15 includes the shipped GINe scores, which were scored at batch 8192 (look-ahead median 600 s,
against 180 s at 2048).

## Validation ring-F1 (validation only)
| run | B0 (val) | full, no-embedding (val) |
|---|---|---|
| E-GenAgg5 (5 GenAgg seeds) | 0.5704 | 0.5623 |
| E-2048 (5 GenAgg + 5 MEGA-GIN) | 0.5588 | 0.5668 |
| **E-All15** (+ 5 shipped GINe) | 0.5509 | **0.5753** (selected) |
| GINe full, five-seed mean | | **0.5927** (gate bar) |
| MEGA-GIN full, five-seed mean | | 0.5438 |
| GenAgg full without embeddings, five-seed mean | | 0.5448 |

Sources: `chosen.val_ring_f1` in each run's config.yaml (run_rings for B0, run_partition for full).

## Verdict
**The gate fails:** the selected ensemble's 0.5753 is below the best single detector's 0.5927 (GINe full).

Part A stops as pre-registered:
- **Test:** the runners wrote test outputs, as they always do, but no test number of any ensemble was read or reported.
- **Not run:** the descriptive test edge F1 and AP (step 5) and the paired test.

Averaging detectors' ranks does not beat Multi-GINe's own full pipeline on validation. It does beat the
two MEGA-family single-detector means (0.544 and 0.545).
