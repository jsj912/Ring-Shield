# CLAIMS_CHECK — every number in the paper, its source, and whether they match

Repository root for all paths: `E:\JSJ\RS-react`. "Exact" means the paper's rounded figure is
the stated rounding of the source value (FROZEN.json's own `reported` convention). Where the
paper quotes a FINDINGS.md row, the underlying table is named too.

## Headline pipeline numbers

| Paper statement | Source file (row/column) | Source value | Match |
|---|---|---|---|
| Edge F1 primary 0.495 ± 0.027 | `results/tables/r1_edge_metrics.csv` (label=causal, primary_f1_minority_mean/std); pinned in `results/FROZEN.json` (R1.edge_f1_primary) | 0.4954675 / 0.0270931 | exact (rounded) |
| ROC-AUC 0.965, AP/prevalence 405 | `docs/FINDINGS.md` A4 (from r1_edge_metrics.csv) | 0.965 / 405 | exact |
| B0 ring-F1 0.521 [0.429, 0.607] | `results/tables/r9_ring_ci.csv` (b0, primary, ring_f1\*) | 0.5213175 [0.4291727, 0.6072530] | exact (rounded) |
| B1 ring-F1 0.162 [0.118, 0.213] | `r9_ring_ci.csv` (b1, primary) | 0.1622108 [0.1181304, 0.2126446] | exact (rounded) |
| B1b ring-F1 0.555 [0.470, 0.632] | `r9_ring_ci.csv` (b1b, primary) | 0.5552958 [0.4697254, 0.6317998] | exact (rounded) |
| Proposed ring-F1 0.582 [0.490, 0.668] | `r9_ring_ci.csv` (proposed, primary) | 0.5819257 [0.4903248, 0.6680423] | exact (rounded) |
| Full ring-F1 0.589 [0.502, 0.675] | `r9_ring_ci.csv` (average, primary) and `r4_partition.csv` (average, ring_f1_mean) | 0.5894467 [0.5022566, 0.6746895]; 0.58946 | exact (rounded) |
| Ring precision/recall/coverage per method (Table ring_methods) | `r9_ring_ci.csv` (primary rows: ring_precision, ring_recall, member_coverage) | b0 0.8138/0.3839/0.8662; b1 0.1710/0.1621/0.9700; b1b 0.7018/0.4632/0.9433; proposed 0.8382/0.4460/0.9420; average 0.8184/0.4609/0.9442 | exact (rounded) |
| Quiet recall B0 0.005 / 0.0054 [0.000, 0.015] | `r9_ring_ci.csv` + `r9_quiet_members.csv` (b0, primary, ALL) | 0.0052288–0.0053798 [0, 0.0151572] | exact (rounded; FINDINGS quotes 0.0054 from r9_ring_ci, 0.0052 in r9_quiet_members — both round to 0.005) |
| Quiet recall proposed 0.2098 [0.142, 0.290] | `r9_quiet_members.csv` (b2/proposed, primary, ALL); `r3_expansion.csv` (proposed, quiet_member_recall) | 0.2091503 [0.1418324, 0.2898203] | exact (rounded; FINDINGS writes 0.2098, the CSV holds 0.20915 — difference is FINDINGS' own rounding, flagged) |
| Quiet recall full 0.2026 [0.136, 0.284] | `r9_quiet_members.csv` (average, primary, ALL) | 0.2026144 [0.1357638, 0.2838415] | exact (rounded) |
| Quiet recall B1b 0.2229 [0.163, 0.299] | `r9_quiet_members.csv` (b1b, primary, ALL) | 0.2228758 [0.1630434, 0.2987179] | exact (rounded) |
| Added-member precision 0.926 [0.899, 0.951] vs 0.518 [0.484, 0.550] | `results/figures/r9_quiet_vs_precision.csv` (prec); CIs from `docs/FINDINGS.md` A5; `r6_detector_swap.csv` (gine full: 0.9257 [0.8985, 0.9505]) | 0.9262899 / 0.5178971 | exact (rounded). Note: r6_detector_swap gives 0.9257 for the full pipeline; the paper's 0.926 [0.899, 0.951] follows FINDINGS A5 (proposed) |
| 6 vs 86 false edges per seed | `docs/FINDINGS.md` A5 | 6 vs 86 | exact |

## Significance (Table significance)

| Paper statement | Source (r9_significance.csv row/column) | Source value | Match |
|---|---|---|---|
| proposed vs B0: Δ +0.062 [+0.036, +0.092], p_holm 0.0005 | proposed_vs_b0 (mean_delta, ci, p_holm) | 0.0620690 [0.0356322, 0.0919540], 0.00049995 | exact (rounded) |
| proposed vs B0 quiet: +0.359 [+0.236, +0.510], p 0.0005 | proposed_vs_b0 (quiet_\*) | 0.3586207 [0.2356322, 0.5103448], 0.00049995 | exact (rounded) |
| proposed vs B1b: −0.017 [−0.041, +0.005], p 0.49; quiet −0.024 [−0.084, +0.037], p 1.00 | proposed_vs_b1b | −0.0172414 [−0.0413793, +0.0045977], 0.4931507; quiet −0.0241379 [−0.0839080, +0.0367816], 1.0 | exact (rounded) |
| full vs b2: +0.015 [−0.002, +0.036], p 0.49 | full_vs_b2 | 0.0149425 [−0.0022989, 0.0356322], 0.4931507 | exact (rounded) |
| cc+partition vs B0: +0.018 [+0.002, +0.039], p 0.23 | cc_partition_vs_b0 | 0.0183908 [0.0022989, 0.0390805], 0.2331767 | exact (rounded) |
| full vs B1b: −0.002 [−0.032, +0.028], p 0.94 | full_vs_b1b | −0.0022989 [−0.0321839, 0.0275862], 0.9447055 | exact (rounded) |
| 28 rings differ (proposed vs B0); 32 (vs B1b) | r9_significance.csv (n_differing_rings) | 28; 32 | exact |

## Detector swap (Table detector_swap) — `results/tables/r6_detector_swap.csv`

| Paper statement | Source cell | Source value | Match |
|---|---|---|---|
| GINe edge F1 0.596 ± 0.071 | gine_causal, edge_f1/edge_f1_std | 0.5957467 / 0.0705630 | exact (rounded) |
| MEGA edge F1 0.689 ± 0.040 | mega, edge_f1/std | 0.6892934 / 0.0395734 | exact (rounded) |
| GFP-XGB edge F1 0.500 ± 0.006 | gfpxgb, edge_f1/std | 0.4995696 / 0.0061753 | exact (rounded) |
| 9.4-point edge gap | 0.6893 − 0.5957 | 0.0935 | exact (FINDINGS' own rounding) |
| MEGA B0 ring-F1 0.521 [0.432, 0.609] | mega b0, ring_f1\* | 0.5208450 [0.4316276, 0.6092738] | exact (rounded) |
| MEGA full 0.607 [0.521, 0.688] | mega full | 0.6074269 [0.5214607, 0.6879437] | exact (rounded) |
| GFP-XGB B0 0.343 [0.259, 0.426]; full 0.451 [0.375, 0.526] | gfpxgb rows | 0.3434758 [0.2591366, 0.4261781]; 0.4507889 [0.3754641, 0.5261029] | exact (rounded) |
| Quiet recall full: 0.203 / 0.242 / 0.267 | quiet_member_recall (gine/mega/gfpxgb full) | 0.2032327 / 0.2417180 / 0.2673473 | exact (rounded) |
| Added precision full: 0.926 / 0.932 / 0.260 | added_member_precision | 0.9257426 / 0.9315673 / 0.2600248 | exact (rounded; gine cell is 0.9257 → paper prints 0.926) |
| Seed-set Jaccard 0.415; rings touched 128.8 vs 129.6 of 174 | `docs/FINDINGS.md` C6; r6_detector_swap.csv (rings_touched_by_seeds: 129.6 gine, 128.8 mega) | 0.415; 129.6 / 128.8 | exact |
| 13.9 ring-F1 points below at p_holm 0.807 (gfpxgb full vs gine full) | `docs/FINDINGS.md` §B preamble | 13.9; 0.807 | exact (p 0.807 is from FINDINGS; not re-verified in a CSV — the r6_pvalues.csv table was not re-read) |
| Union 150.8/174 = 86.7 %; ensemble 133.6; local 116.2; B0 F1 0.5213/0.5317/0.4455; 484 of 864 overlap | `docs/FINDINGS.md` C7, B14 (experiments/R11b_ensemble/, R11c_local/) | identical | exact (FINDINGS row; underlying experiment dirs not re-parsed) |

## Partition, ceiling, residual decomposition

| Paper statement | Source | Source value | Match |
|---|---|---|---|
| Val ring-F1 0.549→0.188 (B0), 0.593→0.194 (full) at k 0.10→0.50 % | `docs/FINDINGS.md` B3; figure `r4_val_ringf1_vs_seedfrac.png` | identical | exact (FINDINGS row) |
| MEGA partition p_holm ≈ 0.011, Δ +0.0172 [+0.006, +0.032]; over-merged 9.8→8.2 / 5.2→5.2; precision −0.0198/−0.0145; τ-sweep +0.0241/+0.0149/+0.0011, ΔF1 −0.0087 | `docs/FINDINGS.md` B3 (docs/PARTITION.md) | identical | exact (FINDINGS row) |
| Decomposition 80.2 / 48.6 / 33.2 / 5.2 / 6.8 (gine) and 83.6 / 51.6 / 24.0 / 8.2 / 6.6 (mega), both sum 174 | `docs/FINDINGS.md` B11; `r6_detector_swap.csv` (class_b_rings 33.2/24.0, matched 80.2/83.6 via matched_rings×?) | class_b 33.2 ± 3.6 and 24.0 ± 2.5 confirmed in r6_detector_swap.csv (class_b_rings, class_b_rings_std); full row matched_rings 80.2 / 83.6 confirmed | exact |
| 60 of 174 rings < 3 visible members (58 with 2, 2 with 1); 11.4 ± 2.3 matched anyway; recall 0.461 [0.393, 0.529]; Ring-Recall≥3 denominator 114/174 = 0.655 | `docs/FINDINGS.md` B7/B9 (r4_unmatched.csv, docs/V3_OBSERVABILITY.md); recall CI in `r9_ring_ci.csv` (average, primary, ring_recall\*) | r9_ring_ci.csv: 0.4609195 [0.3930747, 0.5287356] | exact (rounded) |
| Untouched 33.2 ± 3.6 = 19.1 %; mega 24.0 ± 2.5 = 13.8 %; gfpxgb 39.6 ± 3.0 = 22.8 %; 6.4 of 9.2 become matches | `docs/FINDINGS.md` B8/B11; r6_detector_swap.csv (class_b columns) | confirmed for 33.2/3.6 (gine full), 24.0/2.5 (mega full), 39.6/2.97 (gfpxgb full; FINDINGS says ± 3.0, CSV std 2.9665) | exact (rounded) |
| Under-covered: purity 1.000 (34/34), median coverage 0.176, truth 14 vs prediction 3, 13 rings, STACK 17/34, median gap 0.324 | `docs/FINDINGS.md` B12 (r_under_covered.csv) | identical | exact (FINDINGS row) |
| Disconnection 176/216 = 81.5 %; STACK 140/140, BIPARTITE 24/24, CYCLE 11/19, RANDOM 1/2, G-S 0/31 (1 hop); 85.6 % never candidates; whole-window 52.3 %, CYCLE 58→0 %, STACK 237/237 | `docs/FINDINGS.md` B13 (corrected 2026-10-26; r_in_window_connectivity.csv) | identical | exact (FINDINGS row) |
| Historical bridge: 0/140 STACK at 2 and 3 hops; overall 12.5 %/16.7 %; null 0/216; 5,078,345 edges | `docs/FINDINGS.md` B16 (docs/HISTORICAL_BRIDGE.md, r_historical_bridge.csv) | identical | exact (FINDINGS row) |
| Policy prize: oracle 8/8 to Jaccard 1.0 (1.6 rings/seed ≈ 0.9 recall points); floor 0.7→0.3: +1.0 ring/seed, 2.5× edges, precision 0.653→0.509, val F1 0.577→0.513 | `docs/FINDINGS.md` B15 | identical | exact (FINDINGS row) |
| TTD median 0 h, IQR 0 h; 93–98 % non-negative; 334–394 matched rings | `results/tables/r9_ttd.csv` (b0/average, primary: median_h 0.0, iqr_h 0.0; frac_non_negative 0.934–0.988; n 334/394) | confirmed | exact |

## Typing

| Paper statement | Source | Source value | Match |
|---|---|---|---|
| Head 0.599 [0.549, 0.648], rule 0.551 [0.499, 0.601], 401 rings (primary) | `results/tables/r5_typing_ci.csv` | 0.5985037 [0.5486284, 0.6483791]; 0.5511222 [0.4987531, 0.6009975]; 401 | exact (rounded) |
| Head 0.594 [0.547, 0.640], rule 0.547 [0.499, 0.591], 433 rings (whole) | `r5_typing_ci.csv` (whole) | 0.5935335 [0.5473441, 0.6397229]; 0.5473441 [0.4988453, 0.5912818]; 433 | exact (rounded) |
| Wrong-lookup figure 0.219; wrong ring in 316 of 401 cases; RANDOM 0.11, BIPARTITE 0/5 | `docs/FINDINGS.md` B10 (tests/test_typing_eval_lookup.py) | identical | exact (FINDINGS row; the 0.219 appears only as a corrected error) |

## Robustness (Table robustness) — `docs/FINDINGS.md` §E, from `results/tables/r9_robustness.csv`

| Paper row | Source | Match |
|---|---|---|
| 0.05 %: proposed 0.433 ± 0.069 / 0.140 ± 0.041 / 0.970 ± 0.016; full 0.450 ± 0.066 | FINDINGS E1–E2; per-seed values in r9_robustness.csv (e.g. proposed 0.05 F1: 0.347, 0.407, 0.404, 0.512, 0.494 → mean 0.4329) | exact (mean recomputed: 0.4329 ≈ 0.433) |
| 0.15 %: proposed 0.593 ± 0.044 / 0.235 ± 0.020 / 0.783 ± 0.069; full 0.606 ± 0.033 / 0.232 ± 0.015 / 0.782 ± 0.069 | FINDINGS E5–E6; r9_robustness.csv per-seed | exact (spot-checked: full 0.15 F1 mean of 0.6284, 0.5987, 0.6246, 0.6271, 0.5517 = 0.6061 ≈ 0.606) |
| E7: 0.606 ± 0.033 vs 0.589, gap 0.017 inside spread | FINDINGS E7 | exact |

## Windows (Table windows) — `docs/FINDINGS.md` §D, from `r9_ring_ci.csv`

All eight F1 and eight quiet cells checked against r9_ring_ci.csv (b0/b1b/proposed/average ×
primary/whole): D1 whole 0.4707 [0.3945, 0.5553] → paper 0.471 [0.395, 0.555]; D4 whole 0.5870
[0.4988, 0.6741] → paper 0.587 [0.499, 0.674]; quiet b0 whole 0.0 → 0.0000; b1b whole 0.2523
[0.1918, 0.3191] → 0.252 [0.192, 0.319]; proposed whole 0.2366 [0.1709, 0.3062] → 0.237
[0.171, 0.306]; average whole 0.2269 [0.1651, 0.2914] → 0.227 [0.165, 0.291]. **All exact
(rounded).**

## Held-out patterns (Table heldout_cycle) — `docs/paper/generalisation.md` §2, from `r7_heldout.csv`

| Paper statement | Source | Match |
|---|---|---|
| CYCLE quiet 0.1614 vs 0.1344, Δ +0.0270 [−0.0062, +0.0647], p 0.130 | generalisation.md CYCLE table; r7_heldout.csv (all_patterns/l3_cycle, full, CYCLE: 0.16139 vs 0.13444) | exact (rounded) |
| Ring recall 0.3818 vs 0.3455, Δ +0.0364 [−0.0125, +0.0728], p 0.286 | same; r7_heldout.csv (0.38182 vs 0.34545) | exact (rounded; Δ and p from generalisation.md, not re-derivable from the CSV alone) |
| Added precision 0.952 (40/42) vs 0.970 (32/33) | r7_heldout.csv (all_patterns full CYCLE: 0.95238, 40/42; l3_cycle full CYCLE: 0.96970, 32/33) | exact |
| BIPARTITE holdout removes 0 of 244 positives; 0 of 51 quiet edges adjacent | generalisation.md §2; docs/EXPANSION.md §6.3 (244 positives; 51 BIPARTITE quiet edges) | exact |
| Detector holdout: 148 of 2,530 labels (5.9 %); 0.5967 vs 0.5967, Δ +0.0014, p 1.0000 | generalisation.md §2 | exact (doc row) |

## Per-pattern table — `docs/report.md` §7.2 (evaluation/unmatched_rings.py)

Copied verbatim from report.md's table (found / <3 / never flagged / merged / %). **Exact
(doc row; the underlying r4_unmatched.csv was listed but not re-parsed per cell).**

## Scope sensitivity (Table scope_sensitivity) — `results/tables/r14_scope_sensitivity.csv`

All six test_visible/full_membership ring-F1 pairs checked: gine b0 0.5213/0.1437 (CSV
0.5213175/0.1436822), b1b 0.5553/0.2073 (0.5552958/0.2072834), proposed 0.5819/0.2297
(0.5819257/0.2296611), full 0.5894/0.2428 (0.5894467/0.2427764), mega b0 0.5208/0.1595
(0.5208450/0.1595084), mega full 0.6074/0.2252 (0.6074269/0.2252134). Gaps −0.347…−0.383;
median members 4 → 11 (CSV median_members). **All exact (rounded).**

## Measurement findings (Section 7)

| Paper statement | Source | Match |
|---|---|---|
| Tail: 655/1,611 positives, 1,108 edges, 59 % vs 0.11 %; clock rule F1 0.48 | `docs/FINDINGS.md` C1 (docs/TEST_TAIL.md) | exact |
| LI-Small tail table (223 edges, 134 = 16.7 %, 60.1 %, 880×) | `docs/paper/evaluation_protocol.md` §4 | exact (doc table) |
| Day 0: 34.3 %/34.4 % of train; motif 12.6 % vs ~2 %; fan features 63 % vs 89 % | `docs/FINDINGS.md` C8 | exact |
| C10: HI-Medium day 0 = 48.8 % at 0.0236 % vs 0.0909 %; val AP 0.3073 → 0.4495 (+46 %); F1 0.3782 → 0.4985; 4.68 M vs 9.15 M edges | `docs/FINDINGS.md` C10 (V3_HIMEDIUM_PREREG.md) | exact |
| C11: day 15 takes 87.5 % of seeds holding 16 % of edges; HI-Small 22.0–36.3 % vs 75.8 % of edges; day ratios 1.36/1.36/1.57; day 0 2.31× | `docs/FINDINGS.md` C11 (corrected 2026-10-25) | exact |
| C5: 7.9 % (155/1,962) and 33.2 % (652/1,962) | `docs/FINDINGS.md` C5 (RING_GROUND_TRUTH_DEFINITION.md §6a) | exact |
| C4: 12–16× → 1.0–4.0×; 0.495 vs 0.494; tail 0.786 → 0.739 | `docs/FINDINGS.md` C4 | exact |
| 370 rings, 3,209 pattern transactions, 8 patterns | `docs/RING_GROUND_TRUTH_DEFINITION.md` §1–2 | exact |
| 5,078,345 transactions | `docs/report.md` §3.3; FINDINGS B16 | exact |
| LI-Small 6,924,049 transactions, 705,907 accounts; 38 vs 114 matchable rings | `docs/paper/evaluation_protocol.md` §4 | exact |
| MEGA-GNN 0.6893 ± 0.0396 vs authors' 0.7083 ± 0.0218 | `docs/paper/generalisation.md` §1 | exact |

## Limitations (B17)

All B17 figures (fold leak shares 65.0–92.4 % / 57.7–79.5 %; AUC gaps +0.005…+0.011 and
−0.008…+0.036; clean AUC 0.958–0.996; bounds |0.008| HI-Small / |0.026| HI-Medium; embedding
−0.020; registered fix deadline 2026-10-28, not built) are quoted verbatim from
`docs/FINDINGS.md` B17 (tables `v33_ring_fold_leakage.csv`, `v33_leak_inflation.csv`,
`v33_policy_ablations.csv`). Ablation deltas also visible in `r3_expansion.csv`
(no_detector 0.5736, no_embedding 0.5622 vs proposed 0.5819 at full precision). **Exact.**

## L4 numbers (Section 5.5) — L4's own claims, labelled as such in the paper

| Paper statement | Source | Match |
|---|---|---|
| Mixing (0.6, 0.0, 0.4); 343 of 401 instances all-true; expanded recall@5 0.724/0.729/0.873, Holm p < 0.001; latency 393 ms / 918 ms; review yes-rates 0.91 (κ 0.86), 0.53 (κ 0.60), 1.00 | `explainability/report/xai_chapter.md` §5.2, §7.2.1–7.2.4 | exact (doc rows; note xai_chapter §7.2.1 says "343 of the 395 matched ring-instances with any true ranked transaction", while its §7.2.1 fidelity note and README say 343 of 401 — the paper uses 401 per the chapter's Table 1 population; flagged in OPEN_QUESTIONS) |
| Typing narrated 0.599 / 0.594 | xai_chapter.md §7.2.3 (matches r5_typing_ci.csv) | exact |

## Platform / appendix

| Paper statement | Source | Match |
|---|---|---|
| R10: 0.088 [0.031, 0.161] vs 0.359 [0.239, 0.500], diff 0.271 [0.154, 0.407]; rows (c) and (d); 68 pairs; 172/174 rings cross banks; 4.6 banks avg | `results/tables/r10_registered.json` (FROZEN R10.\*: 0.0882/0.3588/0.2706 [0.1536, 0.4067]); `docs/report.md` §7.2 | exact (rounded) |
| Tests: 373/412/563/22 RLS/361/58; audit 18/18; rings sha 9d1e0b9e…5328, 108 rings, 62 s | `docs/report.md` §6.1; `docs/REPRODUCE.md` §13 | exact |
| R11 gate refused candidates; R12 control not detected | `results/FROZEN.json` (R11.\*, R12.\*); docs/report.md §6.2 | exact — with one nuance: FROZEN records seed 5 as "1 promoted, 1 refused", so "the gate refused every candidate" (report.md's wording for the seed-1 run) is stated in the paper as the R11 outcome for the registered run only |
| Data hashes table | `docs/REPRODUCE.md` §0 | exact |
| Runtimes 15 h / 8 h / 18 h / 45 min | `docs/REPRODUCE.md` §2, §4, §7, §8 | exact |

## Known gaps ([NO SOURCE] in the paper)

- Author affiliation — not recorded anywhere in the repository.
- Venue / page style — not specified; article class used.

## Update 2026-11-12 — numbers added or changed after commit aa4d233 ("Deep analysis #1-#11, #14 drafts")

Paper base moved from `56973da` to `aa4d233` on `integrate/main`. No reported point estimate
changed in the repository except the quiet-recall convention; everything else below is new.
Rows above this section that quote quiet recall as 0.0054 / 0.2098 describe the first draft;
the paper now prints 0.0052 / 0.2092 (tables: 0.005 / 0.209), the `r9_quiet_members.csv`
point estimates pinned in `FROZEN.json`.

### Changed

| Paper statement | Source | Source value | Match |
|---|---|---|---|
| Quiet recall B0 0.0052 [0.000, 0.015]; proposed 0.2092 [0.142, 0.290] (were 0.0054 / 0.2098) | `r9_quiet_members.csv` (primary, ALL); CIs `r9_ring_ci.csv`; `FROZEN.json` (R3.quiet_member_recall_*) | 0.0052288; 0.2091503 | exact (rounded) |
| Table ring_methods quiet recall: B1 0.118, B1b 0.223, proposed 0.209 (were 0.119 / 0.222 / 0.210) | `r9_quiet_members.csv` (primary, ALL) | 0.1183007 / 0.2228758 / 0.2091503 | exact (rounded) |
| Tail share 40.7 % (was "40 %") | `docs/FINDINGS.md` C1 (655 / 1,611) | 40.66 % | exact (rounded) |
| Forced-budget B0 ring-F1 0.5213 / 0.5146 / 0.5193 (global / ensemble / local); the earlier 0.4455 figure removed from the paper | `docs/FINDINGS.md` G (#5); `results/tables/v37_realloc_full.csv`; `docs/deep-analysis.md` §5 | 0.521 ± 0.045 / 0.515 ± 0.032 / 0.519 ± 0.044 | exact |
| B17: closed by decision on 2026-10-22; ring-folded re-run registered, result pending | `docs/FINDINGS.md` B17 (dates clarified 2026-11-12); `docs/deep-analysis.md` §8 | registration only | exact |
| C10 on HI-Small: now run, does not transfer (was "has not been run") | `docs/deep-analysis.md` §9 | seed-1 val AP 0.5455 vs shipped 0.5726; gate 0.6131 | exact — FINDINGS C10 itself still says "has not been run there"; see OPEN_QUESTIONS |

### New: precision-aware paired test (Table precision_paired) — `results/tables/v35_precision_paired.csv`

| Paper cell | CSV value | Match |
|---|---|---|
| proposed vs B1b, added precision: +0.408 [+0.342, +0.479], p_holm 0.0008 | 0.4083928 [0.3416877, 0.4793541], 0.00079992 | exact (rounded) |
| full vs B1b, added precision: +0.408 [+0.341, +0.479], 0.0008 | 0.4078455 [0.3410998, 0.4785762], 0.00079992 | exact (rounded) |
| GINe full vs GFP-XGB full, added precision: +0.666 [+0.557, +0.752], 0.0008 | 0.6657178 [0.5571019, 0.7517737], 0.00079992 | exact (rounded) |
| MEGA full vs GINe full, added precision: +0.006 [−0.042, +0.053], 0.771 | 0.0058248 [−0.0419413, 0.0531398], 0.7705229 | exact (rounded) |
| proposed vs B1b, ring F1: +0.027 [+0.001, +0.052], 0.093 | 0.0266299 [0.0009955, 0.0519246], 0.0929907 | exact (rounded) |
| full vs B1b, ring F1: +0.034 [+0.004, +0.065], 0.093 | 0.0341509 [0.0035746, 0.0652406], 0.0929907 | exact (rounded) |
| GINe full vs GFP-XGB full, ring F1: +0.139 [+0.083, +0.196], 0.0008 | 0.1386578 [0.0827281, 0.1955088], 0.00079992 | exact (rounded) |
| MEGA full vs GINe full, ring F1: +0.018 [−0.016, +0.053], 0.303 | 0.0179802 [−0.0158501, 0.0528388], 0.3027697 | exact (rounded) |
| 392 units = 174 truth rings + 218 off-ring clusters; 10,000 draws; 2,419 edges at 26 % precision | `docs/deep-analysis.md` §2; `r6_detector_swap.csv` (gfpxgb full: n_added_edges 2419, precision 0.2600) | exact |

### New: window-matched seed budget (Table window_budget) — `results/tables/v34_window_budget.json`

Global row verified cell by cell against the JSON `summary.global` (seeds_in_window 463.0 ±
84.22; rings_touched 129.6 ± 4.83; added_member_precision 0.9261 ± 0.0147; full_matched 80.2 ±
5.93; full_ring_f1 0.5895 ± 0.0371; b0_ring_f1 0.5213 ± 0.0448; full_b_untouched 33.2 ± 3.56)
and `summary.in_window` (863; 148.2 ± 6.18; 0.6999 ± 0.1366; b0_ring_f1 0.5028). The remaining
in-window cells and all per-day cells (28.0 ± 5.5, 77.6 ± 5.6, 0.546 ± 0.023; 864, 139.8 ± 7.3,
30.6 ± 3.8, 0.738 ± 0.098, 75.8 ± 5.3, 0.532 ± 0.032, 0.485 ± 0.036) are taken from the table
in `docs/deep-analysis.md` §1, which FINDINGS G repeats for the headline cells. **Exact
(rounded); per-day cells are doc-table values, not re-read from the JSON.**

### New: component-level scope (Table component_scope) — `results/tables/v36_component_scope.csv`

The seven `test_visible` rows were re-read from the CSV and match (e.g. gine full 0.5894467
[0.5234239, 0.6528545]; mega proposed 0.5975691 [0.5283246, 0.6612226]). The `component` and
`component_ge3` columns, the target counts (254; 108 in 97 rings), 77 of 174 = 44 %, the 60 +
17 split, 70.6 % of pieces recovered and STACK recall 0.036 → 0.493 are from the tables in
`docs/deep-analysis.md` §4 and FINDINGS G. **Exact; the two component columns are doc-table
values, not re-read per cell from the CSV.**

### New: other follow-ups

| Paper statement | Source | Match |
|---|---|---|
| Reallocation under full: local 116.2 touched / 79.4 matched / F1 0.575; shipped 129.6 / 80.2 / 0.590; ensemble +0.021 ± 0.038 | `docs/FINDINGS.md` G (#5); `docs/deep-analysis.md` §5 (v37_realloc_full.csv) | exact (doc table) |
| R10 consortium: 0.121 → 0.147 vs 0.359; +0.026 [+0.006, +0.053]; 11 % of gap; median 25 %; 1 ring of 49; 68 pairs | `results/tables/r10_consortium.json` (curve k=1 0.1206 [0.0539, 0.2054]; n_pairs 68, n_rings 49); k=5 row from `docs/deep-analysis.md` §3 | exact (rounded) |
| Ring-identity head: AUC 0.552 → 0.618 (untouched rings), 0.526 → 0.605 (under-covered); bar 0.75 | `docs/deep-analysis.md` §10 (v38_ring_identity_head.csv) | exact (doc table). Not in FINDINGS G; labelled as such in the .tex |
| L4 follow-up: 52 mixed instances; score-only − shipped +0.058 [+0.010, +0.133]; retuned − shipped −0.122 [−0.241, −0.019]; expanded recall@5 0.875 vs random 0.870; abstention 36 of 36 at 9.0 % coverage | `docs/deep-analysis.md` §11 (results/xai/mixed_ring_eval.json) | exact (doc table). L4-side, not in FINDINGS |
| R12b: 2.9 % tied scores; day 9 share 3.1× day 8 = +3.2 SD; closed as not testable | `docs/R12.md` (R12b); `docs/FINDINGS.md` G (#6) | exact |
| External L4 study: 40 cases, 12 unmatched rings, at least 3 reviewers; not run | `docs/deep-analysis.md` §14; `review/analysis_plan.md` | exact |

## Update 2026-11-13 — draft v3, restructured as an evaluation / benchmark-audit paper

No number changed in this pass except the additions below; the restructure moved, cut and
reworded text. Section order is now: Introduction, Related work, Evaluation protocol,
Benchmark audit, Reference pipeline, Results, Where ring recovery stops, Recommendations,
Limitations, Conclusion; appendix: Reproducibility, Additional results, Corrections, System
context.

### New numbers in v3

| Paper statement | Source | Source value | Match |
|---|---|---|---|
| CSGM external baseline: precision 0.545, recall 0.069, ring-F1 0.122 [0.061, 0.194], member coverage 0.856; one run | `results/tables/r4_partition.csv` (row b5); `docs/PARTITION.md` (B5 row and provenance) | 0.5455 / 0.069 / 0.1224 [0.0612, 0.1939] / 0.8563 | exact (rounded; precision printed as 0.545 to match PARTITION.md) |
| Louvain partition leaves ring-F1 at 0.582 | `results/tables/r4_partition.csv` (row b4, ring_f1_mean) | 0.58192 | exact (rounded) |
| Whole-split edge F1 0.596 quoted beside primary-window 0.495 ± 0.027 | `r6_detector_swap.csv` (gine_causal, edge_f1); `r1_edge_metrics.csv` | 0.5957467; 0.4954675 ± 0.0270931 | exact (rounded) |
| Budget comparison at equal budget: 0.521 / 0.515 / 0.519 | `docs/FINDINGS.md` (dated note on B14); `docs/deep-analysis.md` §5 | 0.5213 / 0.5146 / 0.5193 | exact (rounded) |

### New figures (built by `paper_draft/make_figs.py`, reading repository files only)

| Figure | Data source | Check |
|---|---|---|
| `fig_tail_base_rate.png` | per-day base rates typed from the table in `docs/paper/evaluation_protocol.md` §4 | values transcribed by hand into the script — re-check against the table before camera-ready |
| `fig_edge_vs_ring.png` | read directly from `results/tables/r6_detector_swap.csv` (edge_f1, edge_f1_std, ring_f1, ring_f1_lo/hi) | read from CSV at build time |
| `fig_ring_decomposition.png` | class counts typed from `docs/FINDINGS.md` B11 (80.2 / 48.6 / 33.2 / 5.2 / 6.8; 83.6 / 51.6 / 24.0 / 8.2 / 6.6) | transcribed by hand; both rows sum to 174 |
| `fig_scope_conventions.png` | read directly from `v36_component_scope.csv` and `r14_scope_sensitivity.csv` (Multi-GINe rows) | read from CSV at build time |

### Removed from the body in v3

The dated-correction narrative, all internal row codes, the L4 result paragraph, the R10
paragraph, and the typing, held-out, robustness, windows and per-pattern material (all moved to
the appendix in shortened form). Removed entirely: the HI-Small spike-day seed-by-seed detail,
most platform test counts, the R11 feedback-loop sentences, the consortium detail beyond one
sentence, and two repository figures (f3, f4) and one screenshot that are no longer referenced.

### Claims that rest on the literature search, not the repository

The Related-work statements about Chai et al. 2023, Rico et al. 2026, Tian et al. 2025, Tariq
et al. 2026 and the practitioner footnote come from a web search on 2026-11-13, not from
repository files. In particular "their unit is the sub-network around a target account, scored
by node-wise precision and recall, under a 70/15/15 temporal split" (Rico et al.) was read from
the first half of the IJCAI HTML text only; verify against the PDF.

## 2026-11-14 — T-P5 pass 1 (numbers added or changed)

Interval rule (author, Checkpoint A): headline intervals are the ring bootstrap
(`ring_stats.bootstrap_over_rings`, r9). New single-arm intervals come from
`results/tables/v45_posthoc_ring_ci.csv`, which is produced by the same code
(`evaluation/r9_style_ci.py` runs `step9_tables.py` unmodified). The shipped b0 / b1b / proposed /
average rows of v45 equal r9_ring_ci.csv exactly. Scorer (r14-style) intervals appear only in
`tables/component_scope.tex`, which says so in its caption (`results/notes/interval_consistency.md`).

| Paper statement | Source file (row/column) | Source value | Match |
|---|---|---|---|
| Abstract/recs: HI-Medium scope gap 0.04–0.07 | `results/tables/v41_hm_audit_scope.csv` (gap_f1_fm_minus_tv, 8 cells) | −0.0379 … −0.0729 | exact (rounded) |
| Abstract: 40 % unobservable on HI-Medium; text 875 of 2,187 = 40.0 % | `v41_hm_audit.json` (observability) | 875 / 2187 = 0.40009 | exact |
| HI-Small 44.3 % | `v36_component_scope.csv` / FINDINGS dated note | 77 / 174 = 0.44253 | exact |
| Abstract: three external baselines | `v40_external_baselines.json` (Louvain, label propagation, CSGM) | 3 method families | exact |
| Partition on HI-Medium +0.015 [+0.010, +0.020], p_Holm 0.0003 | `v3_closeout_p3.csv` (global, full vs b2) | 0.014861 [0.009831, 0.019890], 0.00030 | exact (rounded) |
| Policy vs rule on HI-Medium +0.047 [+0.037, +0.057], p_Holm 0.0003 | `v3_closeout_p3.csv` (global, policy vs b1b) | 0.047096 [0.037266, 0.057156], 0.00030 | exact (rounded) |
| Saturation: 780,093 of 18.9 M at 1.0; 124 / 25,495 / 221,909 on days 6 / 9 / 15 | `docs/deep-analysis.md` §7 (diagnosis 1) | same | exact (text source; no table) |
| Near-ties: 0.4436 vs 0.4451; 0.6731 vs 0.6738 | `v40_external_baselines.csv` (b0 / louvain_r0.5, component / component_ge3, τ 0.5) | 0.44359 / 0.44508; 0.67309 / 0.67382 | exact (rounded) |
| HI-Medium global gap 0.038–0.059; all cells 0.038–0.073 | `v41_hm_audit_scope.csv` | global −0.0379 … −0.0590; all −0.0379 … −0.0729 | exact (rounded) |
| HI-Medium full − B0 0.092 | `v41_hm_audit.json` (verdicts.scope.global.largest_method_effect_full_minus_b0) | 0.092440 | exact |
| HI-Medium threshold gain 0.019 / 0.015 / 0.009 | `v41_hm_audit_threshold.csv` (global, gain_ring_recall) | 0.019433 / 0.014860 / 0.008916 | exact (rounded) |
| HI-Medium component_ge3 proposed 0.2434 vs full 0.2430 | `v41_hm_audit_component.csv` (global) | 0.24343 / 0.24301 | exact (rounded) |
| Table hm_audit (16 values) | `v41_hm_audit_scope.csv` (tv_ring_f1, fm_ring_f1, gap) | e.g. global full 0.18225 / 0.12573 / −0.05651 | exact (rounded) |
| HI-Medium full ring recall 0.187 [0.174, 0.200] vs HI-Small 0.461 | `v3_closeout_p1.csv` (global, full, ring_recall); `r9_ring_ci.csv` (average) | 0.18701 [0.17398, 0.19959]; 0.46092 | exact (rounded) |
| Untouched 28.7 %, partial 8.6 % | `v3_closeout_verdicts.json` (P2_global shares) | 0.2867 / 0.0855 | exact (rounded) |
| Per-day seed 1: 0.408 (days 6–7), 0.066 (days 14–15) | `v3_closeout_blocks.csv` (1, per_day, full) | 0.40775 / 0.06563 | exact (rounded). The runbook and deep-analysis §7 write 0.065 (truncated); the paper uses 0.066 |
| Table hm_closeout (12 intervals) | `v3_closeout_p1.csv` | e.g. per_day full F1 0.23381 [0.21904, 0.24882] | exact (rounded) |
| Louvain r0.5 test 0.515; vs B0 −0.006 [−0.014, +0.000], p_Holm 0.072; vs full −0.074 [−0.118, −0.035], p_Holm 0.0004 | `v40_external_baselines.json` (bar_B) | 0.51514; −0.00618 [−0.01403, +0.00019], 0.07199; −0.07431 [−0.11781, −0.03549], 0.00040 | exact (rounded) |
| Louvain r2 0.107; LPA on expansion 0.555; CSGM 0.083, recall 0.048 | `v45_posthoc_ring_ci.csv` | 0.10664; 0.55505; 0.08337 / 0.04828 | exact (rounded) |
| Table ring_methods, new rows (CSGM, Louvain ×3, LPA, ring-folded proposed / full, LPA on expansion) | `v45_posthoc_ring_ci.csv` + `v45_posthoc_quiet_members.csv` | values in the table's `% source` comments | exact (rounded) |
| Leak-free added-member precision 0.819 vs 0.518, +0.301 [+0.235, +0.366] | `v39_ringfold_precision_paired.csv` (proposed_ringfold_vs_b1b) | 0.81900 / 0.51790, 0.30110 [0.23494, 0.36573] | exact (rounded) |
| Leak-free ring-F1 vs rule +0.030 [+0.010, +0.050] | same, ring_f1 | 0.02946 [0.01009, 0.05007] | exact (rounded) |
| Leak-free full added-member precision 0.817 | `v45_ringfold_full_precision_paired.csv` (full_ringfold) | 0.81736 | exact (rounded) |
| Precision table, leak-free block (6 rows) | `v39_ringfold_precision_paired.csv`, `v45_ringfold_full_precision_paired.csv` | +0.3011 / +0.2995 / −0.1084 / +0.0295 / +0.0340 [0.0080, 0.0615] / −0.0002 | exact (rounded) |
| Limitations: +0.0028, [−0.0137, +0.0211], p 0.77; ring precision 0.838 → 0.784, −0.055 [−0.089, −0.027]; recall +0.022 | `v39_ringfold_report.csv` (paired rows) | 0.00283 [−0.01366, +0.02111], 0.766; 0.83816 → 0.78355, −0.05461 [−0.08845, −0.02654]; +0.02184 | exact (rounded) |
| Limitations: full ring-F1 0.589 either way, −0.000 [−0.017, +0.019]; 0.926 vs 0.817 | `v45_ringfold_full_precision_paired.csv` (full_ringfold_vs_full) | −0.00019 [−0.01699, +0.01854]; 0.92574 / 0.81736 | exact (rounded) |

Known stale-grep false positive: `0\.219` matches `tables/hm_closeout.tex` (lower bound 0.21904 of
HI-Medium per-day full ring-F1), not the retired quiet-recall figure 0.219.
