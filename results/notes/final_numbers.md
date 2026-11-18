# Final numbers: what the paper quotes now → final value (2026-11-16)

Data only. No prose was edited (paper/sections and paper/tables are frozen until the author says
otherwise). "Changed" means the final value differs from the value the paper currently prints.
Final MEGA-family numbers use scoring batch 2048 and the fixed 0.1 % budget, five seeds, primary
window, test_visible, Jaccard 0.5. The headline interval convention is the weighted (r9) bootstrap.

## Detector-level
| Paper quotes (where) | Now in paper | Final | Changed | Source |
|---|---|---|---|---|
| MEGA-GNN − Multi-GINe edge-F1 gap (abstract, intro, results ×2, conclusion: "9.4 points") | 9.4 | **9.0** (0.6856 − 0.5957) | yes | results/tables/r6_detector_swap_sb2048.csv |
| MEGA-GNN test edge F1 (results, detector-swap table) | 0.6856 ± 0.0447 | 0.6856 ± 0.0447 | no | r6_detector_swap_sb2048.csv |
| MEGA-GNN edge F1 at 8192 (results, val_test_gap table) | 0.6893 | keep only as the 8192 footnote value | — | r6_detector_swap.csv (frozen) |
| MEGA-GenAgg test edge F1 (detector-swap table placeholder) | [TBD] | **0.7153 ± 0.0486** (per seed 0.7557, 0.7516, 0.7442, 0.6552, 0.6700); published 74.48 ± 0.84 | yes | results/tables/r6_genagg_5seed.csv |
| MEGA-GenAgg − Multi-GINe edge-F1 gap | — | 12.0 points (0.7153 − 0.5957) | new | r6_genagg_5seed.csv |
| GenAgg seed spread | — | seeds 4–5 are weaker rankers (test AP 0.68 vs 0.74–0.75), not threshold or tail | new | results/notes/p7_genagg_seed_spread.md |

## Ring-level, detector swap (fixed 0.1 %)
| Paper quotes (where) | Now in paper | Final | Changed | Source |
|---|---|---|---|---|
| MEGA B0 ring-F1 (abstract comment, results "0.5208 vs 0.5213", scope_sensitivity table) | 0.5208 | **0.5179** [0.429, 0.604] | yes | r6_detector_swap_sb2048.csv |
| MEGA full ring-F1 (detector-swap table; scope_sensitivity table "0.6074") | table 0.602; scope table 0.6074 | **0.6023** [0.517, 0.683] | scope table yes | r6_detector_swap_sb2048.csv; r14_scope_sensitivity_sb2048.csv |
| MEGA full quiet recall / added precision (detector-swap table) | 0.234 / 0.915 | 0.234 / 0.915 | no | r6_detector_swap_sb2048.csv |
| MEGA no-embeddings full (detector-swap table) | 0.578 [0.493, 0.659], 0.200, 0.787 | same | no | r6_detector_swap_sb2048.csv |
| GenAgg B0 / full / full-no-emb ring-F1 (table placeholder) | [TBD] | **0.5511** [0.458, 0.634] / **0.5910** [0.508, 0.673] / **0.5989** [0.516, 0.685] | yes | r6_genagg_5seed.csv |
| GenAgg full quiet recall / added precision | [TBD] | 0.226 / 0.943 (no-emb: 0.209 / 0.857) | yes | r6_genagg_5seed.csv |
| GenAgg ring precision / recall (full) | — | 0.757 / 0.486 (no-emb 0.776 / 0.489; B0 0.846 / 0.409) | new | r6_genagg_5seed.csv |
| GenAgg paired family (exploratory; Holm over 4) | — | (i) vs GINe full +0.002 [−0.030, +0.034]; (ii) vs MEGA full −0.011 [−0.037, +0.014]; (iii) B0 vs GINe B0 +0.030 [−0.011, +0.072]; (iv) full − no-emb −0.008 [−0.022, +0.006]; none significant; (iv) → no retraining | new | results/tables/r6_genagg_paired.csv |
| Val-picked sensitivity, MEGA (method.tex, caption) | 0.414 / 0.510 | 0.4137 / 0.5098 | no | r6_detector_swap_sb2048_valpicked.csv |
| Val-picked sensitivity, GenAgg | — | identical to fixed 0.1 %: every seed picks 0.1 % (B0 0.5511, full 0.5910, no-emb 0.5989) | new | r6_genagg_5seed_valpicked.csv |

## Seeds and reach (C6 / C7)
| Paper quotes (where) | Now in paper | Final (MEGA-GIN @2048) | GenAgg @2048 | Changed | Source |
|---|---|---|---|---|---|
| Seed-set Jaccard vs GINe (intro, results) | 0.415 | **0.409** (primary window; whole test split 0.454) | 0.468 (0.505) | yes | results/tables/r6_seed_overlap_sb2048.csv (8192 check reproduces 0.415) |
| Rings reached by seeds (results "128.8 and 129.6") | 128.8 vs 129.6 | **127.4** vs 129.6 | 135.2 | yes | r6_seed_overlap_sb2048.csv |
| Touched-set overlap (results "71.5 %") | 71.5 % | **70.6 %** | 73.0 % | yes | r6_seed_overlap_sb2048.csv |
| Union of touched rings (results "150.8") | 150.8 | 150.8 | 153.0 (with GINe) | no | r6_seed_overlap_sb2048.csv |
| GenAgg vs GINe touched, per seed | — | both 111.8, GenAgg only 23.4, GINe only 17.8 | | new | results/tables/r6_genagg_touch_overlap.csv |

## Where recovery stops (Figure 3, results §7)
| Paper quotes | Now | Final MEGA @2048 | GenAgg @2048 | Changed | Source |
|---|---|---|---|---|---|
| MEGA matched / <3 visible / untouched / over-merged / under-covered | 83.6 / 51.6 / 24.0 / 8.2 / 6.6 | **83.4 / 51.8 / 24.0 / 7.6 / 7.2** | 84.6 / 49.6 / 23.6 / 8.0 / 8.2 | yes | results/tables/r6_ring_decomposition_sb2048.csv (8192 check reproduces) |
| "matched rises only from 80.2 to 83.6" | 83.6 | **83.4** | 84.6 | yes | same |
| "6.4 of the 9.2 newly reached rings become matches" | 6.4 of 9.2 | 9.2 newly reached is unchanged (33.2 − 24.0); **6.4 not recomputed** (needs a per-ring cross-detector comparison) | | open | evaluation/unmatched_rings.py at 2048 (not run) |
| Figures | fig_edge_vs_ring.png, fig_ring_decomposition.png (8192) | fig_edge_vs_ring_sb2048.png, fig_ring_decomposition_sb2048.png (GenAgg added) | | yes | evaluation/make_figs_sb2048.py |
| fig_budget_sweep | already batch 2048 | no change | | no | v42_budget_sweep.json |

## Scope tables (corrected intervals)
| Row (table) | Now in paper | Final @2048 | Source |
|---|---|---|---|
| MEGA B0, test_visible / full_membership (scope_sensitivity) | 0.5208 / 0.1595 | **0.5179 / 0.1576** | r14_scope_sensitivity_sb2048.csv |
| MEGA full, test_visible / full_membership | 0.6074 / 0.2252 | **0.6023 / 0.2195** | same |
| MEGA proposed (test_visible / full_membership) | 0.5976 / 0.2150 | 0.5941 / 0.2128 | same |
| MEGA full, component / component_ge3 (component_scope) | 0.530 / 0.774 | **0.5276 / 0.7658** | v36_component_scope_sb2048.csv |
| MEGA B0, component / component_ge3 | 0.4405 / 0.6742 | 0.4383 / 0.6652 | same |
| GenAgg (new rows): B0 / proposed / full, test_visible | — | 0.5511 / 0.6017 / 0.5910 | same files |
| GenAgg full, full_membership / component / component_ge3 | — | 0.2360 / 0.5337 / 0.7500 | same files |
| GINe rows | as printed (from _wci) | unchanged (= r14_wci / v36_wci) | same files |

## Leak-free values (Section 6.1, conclusion; already applied in pass 2)
| Quantity | Paper | Final | Source |
|---|---|---|---|
| Quiet-member recall, policy | 0.251 [0.179, 0.344] | same | v39_ringfold_quiet_members.csv |
| Added-member precision, policy vs B1b | 0.819 vs 0.518, +0.301 [+0.235, +0.366] | same | v39_ringfold_precision_paired.csv |

## Matching
| Quantity | Paper | Final | Source |
|---|---|---|---|
| Tie-break effect | stated in data.tex | no headline match count changes; largest five-seed-mean shift 0.0032 | results/notes/matcher_tiebreak.md |

## HI-Medium transfer (added 2026-11-18; addendum 5 + close-out). Every number: trained on HI-Small, zero-shot on HI-Medium
Wording: "a detector trained only on HI-Small, applied without retraining to HI-Medium, gives seeds-only ring-F1 0.396 ± 0.015" (primary window, test days 6–14, 2,187 truth rings, five seeds, Jaccard 0.5, test_visible). The old-detector comparison differs in architecture and training data; old side two seeds. Never "transfer beats in-domain training". Proposed / Full are not evaluated under transfer (policy trained on HI-Medium on the old detector; two features missing) and appear in no table.

| Quantity | Final | Source |
|---|---|---|
| B0 ring-F1, global rule, 5 seeds | **0.396 ± 0.015** (per seed 0.409, 0.399, 0.398, 0.369, 0.403); P 0.444 ± 0.028, R 0.357 ± 0.008 | results/tables/hm_transfer_closeout_seed{1..5}_ci.csv |
| B0 ring-F1, per-day rule, 5 seeds | 0.387 ± 0.015; P 0.431 ± 0.030, R 0.352 ± 0.005 | same |
| B1b ring-F1, global / per-day (descriptive) | 0.301 ± 0.013 / 0.291 ± 0.012 | same |
| Validation AP, HI-Medium | 0.5445, 0.5404, 0.5205, 0.5445, 0.5308 | genagg_seed{S}/scores_val + processed labels |
| Largest per-day share of the seed budget | ≤ 16.5 % in every seed and rule (no day > 25 %) | ..._budget_shares.csv |
| Addendum 5 primary: GenAgg B0 (5 seeds) − old HM detector B0 (2 seeds), global, days 6–14 | **+0.306 [0.286, 0.326]**, p 0.0002 (0.396 vs 0.090); ΔP +0.318 [0.295, 0.341], ΔR +0.283 [0.266, 0.301]; paired unit bootstrap over 2,187 rings, 10,000 draws, rng 20261117, seeds averaged per draw | results/tables/hm_transfer_paired_addendum5.csv |
| Old HM detector B0 (the 0.0898 bar) | global 0.1035 / 0.0761 (mean 0.090); per-day 0.1193 / 0.1757 (mean 0.148) | experiments_hi_medium/closeout_a15/log_seed{1,2}.json |
| Jump decomposition, five seeds | per-day rule: old 0.148 (2 seeds) vs new 0.387 (5 seeds), gap 0.24; allocation across days explains at most ≈ 0.06 (old per-day − old global); the rest is ranking | as above |
| Hash check (seed 1, val, rescored) | scores reproduce to 6.3e-7; seed set identical (3,857 = 3,857, Jaccard 1.0) | experiments/R18_hm_transfer/hashcheck_seed1 |
| B0 − B1b, exploratory | HI-Medium GenAgg +0.094 [0.084, 0.105]; HI-Small **GINe** (no GenAgg B1b exists) −0.034 [−0.076, +0.004]; ordering flips; no claim | hm_transfer_paired_b0_vs_b1b_exploratory.csv; R13_baselines/scored/compare_b0_vs_b1b_exploratory |

## TAML external baseline (added 2026-11-18). Labels: features over all ten days incl. test; ~42 % of in-window ring transactions absent from its graphs; ceiling 63/97 matchable rings
| Quantity | Final | Source |
|---|---|---|
| TAML joined ring-F1, HI-Small primary (days 8–9), 3 seeds, 10k | **0.327 [0.254, 0.403]** (P 0.379, R 0.287; mean ± SD over seeds 0.327 ± 0.030) | experiments/R15_taml/scored_3seed_10k/joined |
| TAML per-step ring-F1, 3 seeds | 0.323 [0.249, 0.399] | scored_3seed_10k/per_step |
| Recall on the 63 representable rings (joined) | 0.788 (0.730 / 0.841 / 0.794) | scored_seed*/convert_info.json |
| Exploratory paired: GenAgg B0 (5) − TAML joined (3) | +0.224 [+0.146, +0.304], p 0.0002 | paired_genagg_b0_vs_taml_joined/compare.csv |

## Recovery attempts and loss buckets (added 2026-11-18, author items 2 and 4)
| Quantity | Final | Source |
|---|---|---|
| Post-detector recovery attempts, HI-Small | 9: five read on test (fusion, per-account budget, Q2, M1, B2), four stopped at validation (Q6, M2, M3, rank-averaged ensemble); none raised ring-F1 | results/notes/recovery_attempts.md |
| Loss buckets, **Multi-GINe full** (the one detector used for buckets throughout the paper) | a 77.0 (11.4 matched) / b 11.0 / c1 14.4 / c2 1.0 / c3 1.8 / d 68.8; matched 80.2; unmatched in a 65.6 of 93.8 | q_track.md Q0, q0_buckets.csv |
| Figure-3 view, same detector (B11) | 80.2 matched / 48.6 under three visible members / 33.2 untouched / 5.2 merged / 6.8 partial | FINDINGS B11 (GINe, unaffected by the MEGA batch change) |
