# FINDINGS — the single source for every claim in the report

**Rule: nothing in the report may cite a number that is not in this file.** Every row gives the
statement, the number with its 95 % CI, the comparison it rests on, the Holm-adjusted p where one
exists, and the file the number comes from. Negative results are claims here, not footnotes.

Unless a row says otherwise: AMLworld HI-Small, `test_visible` scope, Jaccard 0.5, the **primary
window** (test days 8–9), 5 detector seeds, CIs are 2.5 / 97.5 percentiles of 1,000 bootstrap
resamples over truth rings with the seeds averaged inside each resample
(`evaluation/ring_stats.py`). p-values are paired sign-flip permutation tests on per-ring matched
indicators, 10,000 permutations, Holm-corrected across the five pre-registered comparisons.

## A. What the pipeline achieves

| # | Claim | Number [95 % CI] | Rests on | p_holm | Source |
|---|---|---|---|---|---|
| **A1** | **Seed-adjacent expansion recovers ring members the detector never fires on.** Quiet-member recall rises from 0.5 % to 21 %. | B0 **0.0054** [0.000, 0.015] → proposed **0.2098** [0.142, 0.290]; full 0.2026 [0.136, 0.284] | proposed vs B0, quiet accounts per ring Δ **+0.359** [+0.236, +0.510] | **0.0005** | `results/tables/r9_quiet_members.csv`, `r9_ring_ci.csv`, `r9_significance.csv` |
| **A2** | The same comparison is significant on whole-ring matching, not only on accounts. | Δ matched rate **+0.062** [+0.036, +0.092] (28 of 174 rings differ) | proposed vs B0 | **0.0005** | `r9_significance.csv` |
| **A3** | Ring-F1 improves from B0 to the shipped pipeline, and the intervals overlap. | B0 **0.521** [0.429, 0.607] → full **0.589** [0.502, 0.675] | — | see A6 | `r9_ring_ci.csv`, `r4_partition.csv` |
| **A4** | The detector itself is strong at the edge level and the ring stage is what is hard. | edge F1 **0.495 ± 0.027**, AP/prevalence 405, AUC 0.965 (primary) | R1 causal, trailing features, 5 seeds | — | `results/tables/r1_edge_metrics.csv` |
| **A5** | What the learned policy buys is the **purity** of what it adds. | added-member precision **0.926** [0.899, 0.951] vs B1b **0.518** [0.484, 0.550]; 6 vs 86 false edges per seed | proposed vs B1b on added edges | — | `results/figures/r9_quiet_vs_precision.csv`, `r3_expansion.csv` |
| **A6** | Ring-level metrics have wide intervals on 174 rings: only one of five pre-registered comparisons survives Holm. | see the table in §B | five comparisons | — | `r9_significance.csv` |

## B. What the pipeline does **not** achieve (report these as claims)

| # | Claim | Number [95 % CI] | Rests on | p_holm | Source |
|---|---|---|---|---|---|
| **B1** | **The learned policy is not what produces the quiet-member recovery.** A two-line rule (shares an endpoint with a seed within Δt **and** its score quantile > 0.99) reaches the same recall. | B1b **0.2229** [0.163, 0.299] vs proposed **0.2098** [0.142, 0.290]; Δ quiet accounts/ring −0.024 [−0.084, +0.037] | proposed vs B1b | **1.00** | `r9_quiet_members.csv`, `r9_significance.csv` |
| **B2** | The policy's advantage over B1b on whole-ring matching is also not significant. | Δ matched rate −0.017 [−0.041, +0.005] (32 rings differ) | proposed vs B1b | 0.49 | `r9_significance.csv` |
| **B3** | **The partition stage is not significant** and its pre-registered hypothesis was rejected. | Δ matched rate **+0.015** [−0.002, +0.036]; val ring-F1 falls 0.549 → 0.188 (B0) and 0.593 → 0.194 (full) from k 0.10 % to 0.50 % | full vs B2; the pre-registered sweep | 0.49 | `r9_significance.csv`, `results/figures/r4_val_ringf1_vs_seedfrac.png`, `docs/PARTITION.md` |
| **B4** | Partitioning without expansion is not significant either. | Δ matched rate +0.018 [+0.002, +0.039]; quiet recall unchanged at 0.0054 | cc+partition vs B0 | 0.23 | `r9_significance.csv` |
| **B5** | **Time-to-detection is uninformative on this dataset** — a spike at zero, because the first in-window transaction of a ring is usually already a seed. | median **0 h**, IQR 0 h (B0, full); 93–98 % non-negative | 334–394 matched rings | — | `results/tables/r9_ttd.csv` |
| **B6** | **BIPARTITE rings are unreachable** by endpoint-adjacent expansion: their quiet edges share no endpoint with a seed of their own ring. | quiet recall **0.00** for every method; 0 of 51 train quiet edges adjacent to a seed | construction, all seeds | — | `r9_quiet_members.csv`, `docs/EXPANSION.md` |
| **B7** | **28 % of primary-window rings are below `min_size`** and no aggregator can match them. | **48.6 of 174** rings per seed have < 3 visible members (1,359 of 1,387 have exactly 2) | ceiling decomposition | — | `results/tables/r4_unmatched.csv`, `docs/RING_GROUND_TRUTH_DEFINITION.md` §6a |
| **B8** | **19 % of primary-window rings are untouched by any detector edge** — no seed and no expanded edge lands on them. | **33.2 of 174** per seed, mean size 5.8, median 4 | ceiling decomposition, `full` | — | `r4_unmatched.csv`, `docs/PARTITION.md` |
| **B9** | Ring recall on the primary window is therefore capped at ≈ 0.72 with `min_size` 3, against 0.46 achieved. | cap (174 − 48.6) / 174 = **0.72**; achieved 0.461 [0.393, 0.529] | B7 + `r9_ring_ci.csv` | — | `RING_GROUND_TRUTH_DEFINITION.md` §6a |
| **B10** | The typing head is not a working topology classifier on the reporting window. | head **0.219** [0.182, 0.259], rule 0.207 [0.170, 0.249] on 401 matched rings | head vs rule | — | `results/tables/r5_typing_ci.csv` |

## C. Measurement findings (independent of our method)

| # | Claim | Number | Rests on | Source |
|---|---|---|---|---|
| **C1** | **The day-based split's tail inflates every HI-Small ring/edge number published on it.** Test days 10–17 hold 1,611 → 655 positives in 1,108 edges at a **59 % base rate** (vs 0.11 % on days 8–9): 40 % of the test positives sit in 0.13 % of the edges. | 655 / 1,108 edges; a clock-reading rule ("after day 10 ⇒ illicit") scores **F1 0.48** there | tail analysis | `docs/TEST_TAIL.md`, `configs/eval_window.yaml` |
| **C2** | Because of C1 we report days 8–9 as the primary window and the tail separately; a single-number test F1 on HI-Small is not comparable across papers unless the split is stated. | primary 0.495 ± 0.027 vs whole-split edge F1 (inflated by the tail) | — | `docs/TEST_TAIL.md`, `results/tables/r1_edge_metrics.csv` |
| **C3** | **Pattern typing is window-bounded, not model-bounded.** The same rings and the same classifier are 2.7× more accurate over ten days than over two. | primary **0.219** [0.182, 0.259] → whole **0.594** [0.547, 0.640] (head); rule 0.207 → 0.547 | 401 vs 433 matched rings | `results/tables/r5_typing_ci.csv`, `docs/TYPING.md` |
| **C4** | A forward-looking feature inflated the detector until it was removed: the original `temporal_cycle` read edges after the scored transaction. | lift over base rate falls 12–16× → 1.0–4.0× once made trailing; primary edge F1 unchanged (0.495 vs 0.494), tail F1 falls 0.786 → 0.739 | causality audit | `docs/FEATURE_CAUSALITY.md` §7, `docs/CAUSAL_LEAK.md` |
| **C5** | Ring membership itself is only partly observable in one split: 7.9 % of members have no test-period transaction at all, 33.2 % none labelled illicit. | 155 / 1,962 and 652 / 1,962 | scope analysis | `docs/RING_GROUND_TRUTH_DEFINITION.md` §6a |

## D. Sensitivity — the same headline rows on the `whole` window (days 8–17, 183 rings)

Reported so a reader comparing against published HI-Small numbers can see both windows. **Every
number in the report must carry its window label.**

| # | Method | Ring-F1 primary [CI] | Ring-F1 **whole** [CI] | quiet recall primary [CI] | quiet recall **whole** [CI] |
|---|---|---|---|---|---|
| D1 | B0 (cc at k\*) | 0.521 [0.429, 0.607] | **0.471** [0.395, 0.555] | 0.0054 [0.000, 0.015] | **0.0000** [0.000, 0.000] |
| D2 | B1b (rule) | 0.555 [0.470, 0.632] | **0.552** [0.475, 0.634] | 0.2229 [0.163, 0.299] | **0.2523** [0.192, 0.319] |
| D3 | proposed (policy) | 0.582 [0.490, 0.668] | **0.577** [0.490, 0.667] | 0.2098 [0.142, 0.290] | **0.2366** [0.171, 0.306] |
| D4 | full (expand + partition) | 0.589 [0.502, 0.675] | **0.587** [0.499, 0.674] | 0.2026 [0.136, 0.284] | **0.2269** [0.165, 0.291] |
| D5 | typing (head) | 0.219 [0.182, 0.259] | **0.594** [0.547, 0.640] | — | — |

Ring-F1 is stable across the two windows (±0.01 for every method except B0, which loses 0.05);
quiet-member recall is 2–5 points *higher* on the longer window; typing is the one metric that
changes character. The tail's 59 % base rate (C1) inflates *edge*-level numbers, not these
ring-level ones.

## E. Robustness — does the quiet-member result depend on k\*?

k\* stays the validation-chosen **0.1 %** (`configs/threshold_rule.yaml`); this is a check, not a
re-selection. `proposed` and `full` re-run at 0.05 % and 0.15 % on the primary window, five seeds,
every other parameter unchanged.

| # | k (seeds) | method | ring-F1 | quiet-member recall | added-member precision |
|---|---|---|---|---|---|
| E1 | 0.05 % (432 seed edges) | proposed | 0.433 ± 0.069 | **0.140 ± 0.041** | 0.970 ± 0.016 |
| E2 | 0.05 % | full | 0.450 ± 0.066 | 0.140 ± 0.041 | 0.970 ± 0.016 |
| **E3** | **0.10 % (864) — shipped k\*** | **proposed** | **0.582** [0.490, 0.668] | **0.2098** [0.142, 0.290] | **0.926** [0.899, 0.951] |
| E4 | 0.10 % — shipped k\* | full | 0.589 [0.502, 0.675] | 0.2026 [0.136, 0.284] | 0.926 [0.899, 0.948] |
| E5 | 0.15 % (1,296) | proposed | 0.593 ± 0.044 | **0.235 ± 0.020** | 0.783 ± 0.069 |
| E6 | 0.15 % | full | 0.606 ± 0.033 | 0.232 ± 0.015 | 0.782 ± 0.069 |

**The quiet-member result does not depend on the operating point.** At every k the expansion
recovers 14–24 % of quiet members where B0 recovers 0.5 %, so A1 holds throughout; what k moves
is the familiar trade — a tighter cut adds fewer, purer edges (0.05 %: precision 0.97, recall
0.14) and a looser one adds more, dirtier ones (0.15 %: 0.78 / 0.24). Ring-F1 is *higher* at
0.15 % (0.606 vs 0.589) than at the shipped k\*, which was chosen on validation ring-F1 in Step 3c;
that gap is inside the seed spread (±0.033) and **k\* is not changed** — re-choosing it on a
test-window number is exactly what this project does not do. Numbers here are mean ± std over
five seeds (no bootstrap: this is a robustness check, not a headline row). Source:
`results/tables/r9_robustness.csv`, `evaluation/r9_robustness.py`.

## F. What the report should claim, in order

1. **A1 + A2** — seed-adjacent expansion recovers quiet members, 0.5 % → 21 %, p_holm 0.0005.
2. **B1** — but the learned policy is not what does it; a two-line rule matches it. Say this
   early and plainly: it is a negative result run on purpose and reported against our own method.
3. **A5** — what the policy buys is the purity of what it adds (93 % vs 52 % member precision,
   6 vs 86 false edges per seed). A trade, not a dominance: B1b's quiet recall is higher
   (`results/figures/r9_quiet_vs_precision.png`).
4. **B3 / B4** — the partition is a null result, and its pre-registered hypothesis was rejected.
5. **C1 + C3** — two measurement findings that hold independently of our method: the day-based
   split's tail inflates published HI-Small numbers, and pattern typing is window-bounded.
6. **B5** — time-to-detection is a dataset artefact; report and drop.
7. **B7 / B8 / B9** — the ceiling: 28 % of rings under `min_size`, 19 % untouched by any
   detector, recall capped at 0.72.
