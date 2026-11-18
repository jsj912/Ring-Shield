# Post-detector recovery attempts on HI-Small (2026-11-18, author item 2 after Checkpoint B)

Confirmed against q_track.md, m_track.md, recovery_ensemble.md, recovery_history.md and docs/FINDINGS.md (B14, 11b/11c). **Nine attempts: five read on test, four stopped at their validation gate.** The author's list is confirmed with no change.

| # | Attempt | Source | Reference | Outcome |
|---|---|---|---|---|
| 1 | Best-rank seed fusion of two detectors (11b) | FINDINGS B14 / C7, v37_realloc_full.csv | shipped GINe full | **test**: +0.021 ± 0.038, inside seed spread |
| 2 | Per-account seed budget (11c) | FINDINGS B14, v37_realloc_full.csv | shipped GINe full | **test**: 0.575 vs 0.590; fewer rings reached (116.2 vs 129.6) |
| 3 | Account-level seeding (Q2) | q_track.md Q2, q_family_holm.csv | shipped GINe full | **test**: −0.138 [−0.184, −0.093], WORSE |
| 4 | Over-generate at 0.2 % and verify (M1) | m_track.md M1, m1_primary.json | leak-free GINe full | **test**: +0.004 [−0.041, +0.046], inconclusive (precision +0.098, recall −0.029) |
| 5 | History-reserved seeds (B2, r25_both) | recovery_history.md B2, b2_test_r25_both_paired.csv | shipped GINe full | **test**: +0.003 [−0.022, +0.030], p 0.84 |
| 6 | Undersized-group rescue (Q6) | q_track.md Q6 | shipped GINe full | **validation**: no relaxed cell beat shipped; not applied |
| 7 | Temporal motif search (M2) | m_track.md M2, m2_gate.json | leak-free GINe full | **validation**: gate failed, 0.569 < 0.585 |
| 8 | Flow-following expansion (M3) | m_track.md M3, m3_gate.json | leak-free GINe full | **validation**: gate failed, 0.569 < 0.585 |
| 9 | Rank-averaged detector ensemble as seed source (Part A) | recovery_ensemble.md | GINe full (validation 0.5927) | **validation**: gate failed, 0.5753 < 0.5927 |

Not counted as recovery attempts:
- Q1 score-saturation tie handling: stopped before any test run because 0 edges tie at the cut. It is a check, not a recovery method.
- Q4 merge/split consensus: dropped before running.
- Q5 ring-balanced training: plan only.
- Part B history count: a count; its build is B2, row 5.
- T-P3 community baselines: partition alternatives, reported separately.

Loss buckets used in the paper (author item 4): Multi-GINe full pipeline, Q0, five seeds, primary window, per seed:
- a: 77.0 rings with no in-window piece of three or more accounts (11.4 of them still matched);
- b: 11.0 untouched but matchable;
- c1: 14.4 too few recovered;
- c2: 1.0 merged;
- c3: 1.8 split;
- d: 68.8 matched.
- In total, 80.2 matched and 93.8 unmatched per seed, of which 65.6 are in bucket a.
