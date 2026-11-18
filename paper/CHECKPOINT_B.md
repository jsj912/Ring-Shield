# Checkpoint B (2026-11-18): STOP, waiting for the author

Nothing has been committed or pushed. paper/sections and paper/tables have not been edited, per the standing stop.
Every number here comes from results/notes/final_numbers.md. The earlier draft is kept as paper/CHECKPOINT_B_draft_2026-11-16.md.bak.

## Pending author approvals (unchanged from the draft, not applied)
1. **FINDINGS note on intervals:** proposed text in results/notes/interval_consistency.md.
2. **FINDINGS note on loader look-ahead:** proposed text in results/notes/p7_genagg.md.
3. **open_items #5:** r7 held-out intervals still use the collapsed bootstrap, kept via the legacy flag.

## 1. T-P7 verdict: EXTENDS
- **Strength condition: met.**
  - MEGA-GenAgg test edge F1 is 0.7153 ± 0.0486 (five seeds).
  - That is 11.96 points above Multi-GINe's 0.5957; the bar asks for at least 5.
- **d = B0 ring-F1(GenAgg) − 0.5213 = 0.5511 − 0.5213 = +0.030,** within |d| ≤ 0.045.
  - Paired comparison (exploratory family, Holm over 4):
    - GenAgg B0 − GINe B0: +0.030 [−0.011, +0.072];
    - GenAgg full − GINe full: +0.002 [−0.030, +0.034];
    - none significant.
- **v2 table:**

| Detector | Edge F1 | B0 ring-F1 | Full ring-F1 |
|---|---|---|---|
| Multi-GINe | 0.596 ± 0.071 | 0.521 [0.429, 0.607] | 0.589 [0.502, 0.675] |
| MEGA-GNN, batch 2048 | 0.686 ± 0.045 | 0.518 [0.429, 0.604] | 0.602 [0.517, 0.683] |
| MEGA-GenAgg | 0.715 ± 0.049 | 0.551 [0.458, 0.634] | 0.591 [0.508, 0.673] |

  Sources: r6_detector_swap_sb2048.csv and r6_genagg_5seed.csv.
- **Conclusion:** the claim extends, with a third point on the edge-against-ring figure. Ring-F1 stays flat while edge F1 rises by 12 points.

## 2. T-P8 bars
- **Gap bar: HOLDS in 10 of 10 rows.** The largest gap is −0.041, against a seed SD of 0.052. The failure bar (more than 2 SD at k ≥ 0.15) is not met anywhere.
- **Union bar: SUPPORTED.**
  - At k = 0.20 %, a single detector touches 152.0 to 156.2 rings, against a bar of 140.
  - The two-detector union touches 150.8, so the union is reachable with one detector given double budget.
- Source: results/notes/p8_budget.md.

## 3. T-P9 result: GO, run, three seeds
TAML was converted to rings with all its labels:
- its features are aggregated over all ten days, test days included;
- about 42 % of in-window ring transactions are missing from its graphs;
- its ceiling is 63 of the 97 matchable rings.

Results (HI-Small primary window, test days 8–9, 174 rings, Jaccard 0.5, test_visible, 10,000 draws):

| Row | Seeds | Ring-F1 [interval] | Precision | Recall |
|---|---|---|---|---|
| TAML joined | 3 | **0.327** [0.254, 0.403] | 0.379 | 0.287 |
| TAML per step | 3 | 0.323 [0.249, 0.399] | | |

- **Recall on the 63 representable rings:** 0.788.
- **Exploratory paired comparison, GenAgg B0 (five seeds) − TAML joined (three seeds):** +0.224 [+0.146, +0.304]. This was not pre-registered as a superiority test.
- **Framing:** TAML solves account flagging; converted to rings, it loses mainly through what its graphs omit.
- Details are in results/notes/p9_taml.md.

## 4. Flags

| Flag | Value | Basis |
|---|---|---|
| METHOD_SUPERIORITY | **ON** | T-P3: no baseline reaches 0.5894. The paper is framed as an audit, so no method claim is in the contribution list. |
| HM_AUDIT | **NOT_REPRODUCED** | T-P4: the scope gap keeps its direction but not its size. Unchanged. |
| EDGE_RING_CLAIM | **FULL** (not RESTRICTED) | T-P7 extends, and the T-P8 gap bar holds at every k. |

## 5. Proposed abstract (≈175 words; every number from final_numbers.md, with its window and seed count)
> Anti-money-laundering detectors are scored per transaction, but investigators act on rings. We give a ring-level evaluation protocol for AMLworld (a ring metric, a matching rule with a deterministic tie-break, a ring bootstrap that keeps multiplicities, and ring-folded cross-fitting) and use it to audit the benchmark. On HI-Small (test days 8–9, 174 rings, five seeds), ring recovery is bounded by what the window lets one observe, not by the detector or by reassembly. Three detectors spanning test edge F1 0.596 to 0.715 give seeds-only ring-F1 0.518 to 0.551, and eight recovery attempts after the detector leave ring-F1 flat. On HI-Medium (test days 6–14, 2,187 rings), a detector trained only on HI-Small, applied without retraining, gives seeds-only ring-F1 0.396 ± 0.015 (five seeds). An earlier in-domain detector, which differs in architecture and training data, gives 0.090 (two seeds). Most of the gain is ranking, not budget allocation. TAML, an account-flagging method converted to rings, reaches 0.327 [0.254, 0.403] (three seeds); it loses mainly through transactions its graphs omit. We list the evaluation defects we found.

**Check before use:** results.tex ("What did not help") currently lists **five** recovery approaches, but the author's framing says **eight**. The count must be reconciled with the recovery family (m_track, q_track, recovery_history) before "eight" is printed.

## 6. Contribution list (author order)
- **(a) Protocol.**
  - Ring-level metric.
  - Greedy one-to-one Jaccard matching with a deterministic tie-break.
  - Ring bootstrap with multiplicities kept.
  - Ring-folded cross-fitting.
- **(b) HI-Small bound.**
  - Ring recovery is bounded by observability: three detectors and the recovery attempts all stay flat.
  - Loss buckets: 83.4 matched, 51.8 with fewer than 3 visible members, 24.0 untouched, 7.6 over-merged, 7.2 under-covered (MEGA).
  - Overlap ceiling: the union of touched rings is 150.8.
- **(c) Transfer.**
  - 0.396 ± 0.015 against 0.090, labelled as above.
  - Allocation across days explains at most about 0.06 of the 0.24 per-day gap, so most of the gain is ranking.
- **(d) External baseline:** TAML converted to rings, with its labels.
- **(e) Defects list**, as a short methodological contribution:
  - silent multiplicity collapse in the bootstrap;
  - matcher tie order;
  - scoring-batch dependence of causal-loader scores;
  - loader look-ahead;
  - day-15 budget capture by a global quantile;
  - saturated scores and strict quantile cuts.

**Excluded claims:**
- transfer beats in-domain training;
- "beats TAML";
- the expansion policy helps on HI-Medium (not evaluated under transfer).

## 7. Cut list for 8 pages (ICAIF, no supplementary material; the draft is about 8,600 body words against a budget of about 5,500 to 6,000)
Ranked from least to most support for (a)–(e). The first rows are cut first; items moved go to the released repository. Lines are estimated at about 13 words per line.

| Rank | What | Supports | Saves | Action |
|---|---|---|---|---|
| 1 | Typing results (typing.tex and its prose) | none | part of row 2 | Repository |
| 2 | Whole appendix (typing, held-out cycle, per-pattern, tenant, robustness, windows, val–test gap, dashboards) | (b) and (e), marginally | ~980 words, 8 tables, 4 figures (~75 lines plus floats) | Repository |
| 3 | B0-against-B1b exploratory row; it never enters the paper | none | 0 (not in the draft) | results/notes only |
| 4 | Per-seed tables (keep mean ± SD and intervals only) | none | ~1 table (~15 lines) | Repository |
| 5 | Per-method recovery tables beyond one summary (precision_paired, significance, ring_methods detail); keep one table of B0 / B1b / proposed / full | (b) | ~450 words, 2 tables (~35 lines) | Repository |
| 6 | HI-Medium close-out table (hm_closeout) and its old-detector prose, replaced by one transfer paragraph and a 3-row table (B0 five-seed, old detector, paired Δ) | (c), the old version superseded | ~350 words out, ~120 in (~18 lines net) | Repository |
| 7 | HI-Medium audit table (hm_audit); keep one sentence | (e), weakly | ~200 words, 1 table (~15 lines) | Repository |
| 8 | Global-quantile subsection, shortened to one paragraph; keep the tail table or the tail figure, not both | (e) | ~400 words, 1 float (~30 lines) | Repository |
| 9 | Related-comparison table; related-work prose compressed to about 350 words | context | ~250 words, 1 table (~20 lines) | Repository |
| 10 | Where-recovery-stops: keep the decomposition figure, move the window-budget table | (b) | ~300 words, 1 table (~23 lines) | Repository |
| 11 | "What did not help" compressed to one paragraph | (b) | ~250 words (~19 lines) | Stays, shortened |
| 12 | Protocol window and statistics detail moved to docs/PROTOCOL.md; definitions kept | (a), definitions stay | ~400 words (~30 lines) | docs/PROTOCOL.md |
| 13 | Method: platform paragraph and long pipeline caption | none | ~150 words (~12 lines) | Repository |

**Total:** about 3,400 words and about 14 floats, which covers the 2,600–3,100-word gap plus the new transfer and TAML paragraphs (about 250 words). The page count must be measured on Overleaf, because this machine has no LaTeX toolchain.

## 8. Draft numbers that final_numbers.md no longer supports (not edited, per the stop)

| Where | Draft | Final |
|---|---|---|
| abstract.tex:18, results.tex:161, scope_sensitivity.tex:18 | MEGA B0 "0.5208 vs 0.5213" | **0.5179** at scoring batch 2048 |
| abstract.tex:18, results.tex:139, val_test_gap.tex:29 | MEGA edge F1 0.6893 | **0.6856 ± 0.0447** at 2048 (0.6893 only as the 8192 footnote) |
| tables/detector_swap.tex:20 | GenAgg row [TBD] | 0.7153 ± 0.0486 / 0.551 / 0.591 (section 1) |
| intro and results: seed-set Jaccard, rings reached, touched overlap | 0.415 / 128.8 / 71.5 % | **0.409 / 127.4 / 70.6 %** |
| results §7: MEGA loss buckets | 83.6 / 51.6 / 24.0 / 8.2 / 6.6 | **83.4 / 51.8 / 24.0 / 7.6 / 7.2** |
| results §7: "6.4 of the 9.2 newly reached rings" | 6.4 | **not recomputed at 2048 (open)**; drop the clause or recompute |
| abstract.tex:10, findings.tex §137 (HI-Medium) | old detector only; no transfer | add the transfer result; old close-out numbers serve only as the 0.090 side |
| results.tex:122 | 0.408 / 0.066 by block (old detector, full arm, per-day) | supported as an old-detector number, but its arm is policy-transfer-confounded; cut with rank 6 |

The 0.926, +0.408 and 0.2092 occurrences are intended comparisons of the shipped version against the leak-free one (with 0.819, +0.301 and 0.251), so they are not flagged.

## 9. Files changed since Checkpoint A (2026-11-14)
- **New evaluation code:** hm_transfer_{score,closeout,intervals,paired}.py, hm_proposed_diag.py, hm_vocab_remap.py, chunk_check_hs.py, taml_convert.py, taml_representability.py, genagg_paired{,_v2}.py, genagg_provisional_4seed.py, genagg_touch_overlap.py, r6_detector_swap_sb2048.py, seed_overlap_sb2048.py, ring_decomposition_sb2048.py, scope_rows_sb2048.py, make_figs_sb2048.py, rescore_weighted_intervals.py, matcher_tiebreak_audit.py, check_multiplicity_fix.py, scoring_noise.py, budget_sweep.py, recovery_history.py, history_seeds.py, build_rank_ensembles.py, q0/q2/q3/q6/q7 scripts, m1/m2/m3 scripts, p7_genagg_seed_spread.py, r9_style_ci.py, ringfold_full_paired.py, b2_test_read.py.
- **Changed evaluation code:**
  - ring_stats.py: multiplicity fix plus legacy flag;
  - ring_metrics.py: deterministic tie-break;
  - score_external.py, scope_sensitivity.py, r6_detector_swap.py, r7_heldout.py, baselines_table.py.
- **Models:** models/mega_adapter.py, models/score.py.
- **Pre-registrations and addenda:** PREREG_AMENDMENT_2026-11-14, PREREG_GENAGG_ADDENDUM_2026-11-16, PREREG_METHOD (+2 amendments), PREREG_Q (+2), PREREG_RECOVERY (+ amendment with addenda 5 and 6), PREREG_TP9_ADDENDUM, PREREG_TP9_ADDENDUM2.
- **Paper (before the stop):** 11 sections, 9 tables, 3 figures, main.tex, refs.bib, PAGE_BUDGET.md, CLAIMS_CHECK.md, RELATED_WORK_AUDIT.md, progress logs.
- **Docs:** FINDINGS.md (appended), PROTOCOL.md, deep-analysis.md.
- **Notes and tables:** 36 files in results/notes, 146 in results/tables (all new; frozen tables untouched).
- **This round:**
  - final_numbers.md (two sections appended);
  - p9_taml.md (three-seed section);
  - hm_transfer_old_checkout_inputs.md;
  - hm_transfer_paired_addendum5.csv, hm_transfer_paired_b0_vs_b1b_exploratory.csv;
  - hm_transfer_closeout_seed{1..5}_{ci,budget_shares}.csv;
  - experiments/R15_taml/{scored_3seed_10k, scored_seed*_10k, genagg_b0_ref_10k, paired_genagg_b0_vs_taml_joined}.

## 10. Decisions needed
1. Approve or edit the abstract, and settle "eight" against "five" recovery attempts.
2. Approve or reorder the cut list.
3. Lift the paper-writing stop, so the section 8 corrections and the transfer and TAML paragraphs can go in.
4. FINDINGS notes 1–2 and open_items #5.
