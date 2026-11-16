# T-P1 — standalone protocol scorer (2026-11-14)

Gate: **PASS** (bar: max abs deviation ≤ 1e-4 on every cell).

`evaluation/score_external.py`, run on the five shipped `full` runs
(`experiments/R4_partition/runs/average/seed1..5`) and the five B0 runs
(`../RS-e2e/experiments/R2_b0/gine_causal/seed1..5`; not present under `experiments/` in this
checkout), HI-Small primary window, τ = 0.5:

| Convention | Targets | full ring-F1 [95 % CI] | B0 ring-F1 | Reference |
|---|---|---|---|---|
| test_visible | 174 | 0.5894 [0.5234, 0.6529] | 0.5213 | r14, v36 |
| full_membership | 174 | 0.2428 | 0.1437 | r14 |
| component | 254 | 0.5145 | 0.4436 | v36 |
| component_ge3 | 108 (in 97 rings) | 0.7397 | 0.6731 | v36 |

Observability: 174 in-scope rings; 60 with < 3 visible members; **77 with no in-window piece
of ≥ 3 accounts**; 28 split into ≥ 2 pieces; 70.6 % of ≥ 3-account pieces recovered by `full`.

90 cells compared against `r14_scope_sensitivity.csv` (sha256 cc26b9cb…) and
`v36_component_scope.csv` (2f787847…), columns ring precision, recall (+CI), F1 (+CI),
recall ≥ 3, member coverage, plus target counts: **maximum absolute deviation 0.0**
(`results/notes/p1_reproduction_cells.csv`). Ground truth sha256 cd6d207b….

Meaning: the protocol is a single tool, not a set of scripts that agree by luck; the paper may
say it is released as a scorer. Unit tests: `tests/test_score_external.py`, 12 tests on a
hand-built fixture (exact Jaccard, one-to-one matching, target counts per convention, a
prediction spanning two pieces matching only one, minimal = full schema).
