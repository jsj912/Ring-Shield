# Checkpoint A — 2026-11-14

Runbook sha256 1307cedc…; PREREG 568a296f… (frozen); amendment `paper/PREREG_AMENDMENT_2026-11-14.md`
4f10b6e2…. Nothing committed or pushed.

## 1. Status

| Task | Status | Gate / bar result |
|---|---|---|
| Phase 0 | DONE | PASS (after author-approved env repairs 1–3) |
| PREREG + amendment | DONE | frozen; amendment for the T-P2 gap |
| T-P6 related work | DONE | PASS |
| T-P1 scorer | DONE | PASS, max deviation 0.0 |
| T-P7a GenAgg seed 1 | RUNNING | seed-1 gate pending |
| T-P2 ring-fold report | DONE | ring-F1 INCONCLUSIVE (amendment); B17 not closed |
| T-P3 baselines | DONE | METHOD_SUPERIORITY=ON; bar A met narrowly; bar B not competitive |
| T-P4 HI-Medium audit | DONE | HM_AUDIT=NOT_REPRODUCED; observability in band; threshold reproduced |

Research suite (runbook 0.7 command): **282 passed, 44 skipped, 1 xfailed**, 0 failures (baseline 261/44/1; +21 new tests).

## 2. T-P6
No paper makes our four claims. None of the group-level papers states how a group that crosses the
window is scored. The closest prior work is Malik (arXiv 2604.23494): transaction- vs actor-level
queues on Elliptic++, actor level, not rings, not AMLworld. It is now cited with that
characterisation. MEGA-GenAgg is 74.48 ± 0.84 (TMLR 2026); FUTURE_IMPLEMENTATIONS has a dated
correction note.

## 3. T-P1
90 cells against r14/v36: maximum absolute deviation **0.0**.

## 4. T-P2
- Δ ring-F1 (ring folds − shipped) = **+0.0028 [−0.0137, +0.0211], p 0.77**: INCONCLUSIVE, no
  equivalence claim.
- Post hoc: the leak inflated precision. Ring precision Δ −0.055 [−0.089, −0.027]; added-member
  precision 0.926 → 0.819.
- Gain over B1b: +0.408 → **+0.301 [+0.235, +0.366]**.
- Quiet-member recall: 0.2092 → 0.2510 [0.179, 0.344].
- Ring-F1 vs B1b: +0.030 [+0.010, +0.050].
- Ring-edge AP of the fold models: 0.434 → 0.088 over 1,406 train ring edges.
  Fold 2: 0.678 → 0.104 on the 372 ring edges both arms share.

## 5. T-P3 (ring-F1, τ 0.5, primary, 5 runs)

| Method | test_visible [CI] | full_membership | component | component_ge3 |
|---|---|---|---|---|
| full | 0.5894 [0.523, 0.653] | 0.2428 | 0.5145 | 0.7397 |
| proposed | 0.5819 [0.513, 0.646] | 0.2297 | 0.5041 | 0.7656 |
| B1b | 0.5553 [0.493, 0.613] | 0.2073 | 0.4878 | 0.7001 |
| LPA on expansion (partition alt.) | 0.5550 [0.486, 0.620] | 0.1762 | 0.5001 | 0.7483 |
| Louvain r1 on expansion (partition alt.) | 0.5292 [0.466, 0.590] | 0.1555 | 0.4833 | 0.7349 |
| B0 | 0.5213 [0.454, 0.586] | 0.1437 | 0.4436 | 0.6731 |
| Louvain r0.5 | 0.5151 [0.451, 0.578] | 0.1289 | 0.4451 | 0.6738 |
| LPA | 0.5091 [0.443, 0.572] | 0.1258 | 0.4428 | 0.6659 |
| Louvain r1 | 0.4830 [0.418, 0.543] | 0.1055 | 0.4298 | 0.6560 |
| Louvain r2 | 0.1066 [0.075, 0.136] | 0.0162 | 0.1021 | 0.1819 |
| CSGM (bank seeds 0–4) | 0.0834 [0.050, 0.113] | 0.0477 | 0.0597 | 0.0855 |

- **Bar (A): met, narrowly.** Beyond full ↔ proposed under component_ge3, the new swaps are
  B0 ↔ Louvain r0.5 (by 0.0015 / 0.0007) and Louvain r2 ↔ CSGM. Conventions re-rank near-ties.
- **Bar (B): not competitive.** The best community baseline by validation (Louvain r0.5) vs B0:
  Δ −0.006 [−0.014, +0.000], p_Holm 0.072. Vs full: Δ −0.074 [−0.118, −0.035], p_Holm 0.0004.
- **METHOD_SUPERIORITY=ON.** Leiden was not run (the install was refused in this session).

## 6. T-P4
- **Scope bar NOT reproduced.** Gaps are negative everywhere (global −0.038 to −0.059), but
  smaller than full − B0 (0.092). **HM_AUDIT=NOT_REPRODUCED.**
- **Observability:** 40.0 % vs 44.3 %, within band.
- **Threshold:** gain 0.019 at 0.3 → 0.009 at 0.7. Reproduced.
- proposed > full under component_ge3 again. Day 15 takes 87.5 % of global seeds.

## 7. T-P7
- Seed 1 has been training since 09:28 UTC: batch 4096, ~550 s per epoch, peak 21,627 MiB, no
  watchdog trip.
- At epoch 42, best val F1 is 0.665. The seed-1 gate uses **test** edge F1 ≥ 0.70, which is not
  known until scoring.
- Early-stopping patience is 20, so training ends between about epoch 62 and 80, followed by test
  scoring. ETA ≈ 19:00–22:00 UTC, inside the 15 h cap (00:28 UTC).

## 8. Decisions needed
1. **Abstract with HM_AUDIT=NOT_REPRODUCED.** *Recommendation:* say the scope effect's direction
   reproduces on HI-Medium but its size is HI-Small-specific (window length 2 vs 9 days). Also say
   observability and threshold dependence reproduce on both. (Venue: the author decides at
   Checkpoint B.)
2. **Bar (A) wording.** *Recommendation:* "conventions re-rank methods that are close; the partition
   step's sign flips under component_ge3 on both releases". Not "conventions re-rank methods".
3. **Run T-P9 (TAML)?** *Recommendation:* yes, with the day-1 go/no-go. The three code findings in
   `results/notes/p9_taml.md` (day ≤ 10 horizon, per-day 2-hop truth, 10-day feature aggregation)
   decide feasibility.
4. **Proposed FINDINGS notes** (B17, A5 in `results/notes/p2_ringfold.md`; HI-Medium in
   `results/notes/p4_hm_audit.md`): approve as written?
5. **Leak-free `full`.** No ring-folded `full` run exists, so full's precision stays a day-fold
   value. Approve a ring-folded full run (CPU, about 1 h), or state the caveat in T-P5?
6. **Deviations to note:**
   - HI-Medium processed data was read from RS-e2e and its test scores from Ring-Shield, read only
     (hashes verified).
   - CSGM was imported from `Ring-Shield/external` through PYTHONPATH.
   - Leiden was skipped.
   - T-P4 step 7 was not done.
   - FlowScope was not attempted.

## 9. Files changed since Phase 0 (for you to commit)
- Modified:
  - `docs/FUTURE_IMPLEMENTATIONS.md`
  - `docs/deep-analysis.md` (§15–§17)
  - `evaluation/r6_detector_swap.py` (`--pvalues-out`)
  - The typing head files (line endings only; leave per decision 8 of round 3).
- New, code:
  - `evaluation/{score_external,ringfold_report,ringfold_followup,community_baselines,baselines_table,hm_audit}.py`
- New, tests:
  - `tests/test_{score_external,r6_pvalues_out,ringfold_report,community_baselines,hm_audit}.py`
- New, docs and paper:
  - `docs/PROTOCOL.md`
  - `paper/` (whole folder, including PREREG, amendment, progress log, related work, this file)
  - `results/notes/`
- New, tables:
  - `results/tables/v39_ringfold_*`
  - `results/tables/v40_external_baselines.*`
  - `results/tables/v41_hm_audit*`
- New, artefact repairs:
  - `models/artifacts/full_gine_causal_seed1/version.json`
  - `models/artifacts/full_gine_causal_seed1/typing/lf_backup/`
- Run outputs (git-ignored):
  - `experiments/R13_baselines/`
  - `experiments/R6_megagenagg/`
