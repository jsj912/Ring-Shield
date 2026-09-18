# The test-period tail (Step 3b-w, 2026-09-17)

Read-only analysis. Day = (Timestamp − 10) // 86400 in the loader basis (day 0 = first calendar
day; train = days 0–5, val = 6–7, test = 8–17). "Tail" = test edges on **days ≥ 10**.
Script: `evaluation/test_tail.py [--neighbourhood]`; artefact: `docs/test_tail.json`.
Scores in §3 are the legacy-feature causal R1, seed 1 (`experiments/R1_gine_causal_legacyfeat`),
the only 5-seed scores that existed when this was run; the shape of the result does not
depend on the feature set. Nothing in the scope files or metrics was changed by this step.

**Headline.** The last eight days of the test period hold 1,108 edges (0.13 % of the split)
and **655 of the 1,611 test positives (40.7 %)** at a **59 % base rate**: the generator's
pattern injection outlives the licit background. Half of the GNN's true positives on the
whole split are tail edges, a trivial "flag the tail" rule reaches F1 0.48 on the whole
split, and the val split has no comparable regime. The whole-split test numbers are not
measuring what val thresholds were tuned for.

## 1. Volume per day

| day | split | edges | illicit | base rate | cumulative share of positives |
|---|---|---|---|---|---|
| 6 | val | 482,751 | 497 | 0.103 % | 48.0 % |
| 7 | val | 482,773 | 539 | 0.112 % | 100.0 % |
| 8 | test | 654,467 | 514 | 0.079 % | 31.9 % |
| 9 | test | 208,325 | 442 | 0.212 % | 59.3 % |
| 10 | test | 396 | 232 | 58.6 % | 73.7 % |
| 11 | test | 281 | 170 | 60.5 % | 84.3 % |
| 12 | test | 184 | 106 | 57.6 % | 90.9 % |
| 13 | test | 121 | 70 | 57.9 % | 95.2 % |
| 14 | test | 46 | 28 | 60.9 % | 97.0 % |
| 15 | test | 46 | 26 | 56.5 % | 98.6 % |
| 16 | test | 23 | 15 | 65.2 % | 99.5 % |
| 17 | test | 11 | 8 | 72.7 % | 100.0 % |

Test positives on days ≥ 10: **655 / 1,611 = 40.7 %**, on 1,108 edges (0.13 % of the split).
Days 8–9 alone: 862,792 edges, 956 positives, base rate 0.111 % — the same regime as val
(0.107 %). Val has no tail: both of its days are full days.

## 2. Test-visible rings and the tail

183 `test_visible` rings, 1,240 visible edges, **655 of them in the tail** (every tail positive
is a ring edge). Rings with ≥ 1 tail edge: **109 / 183**; rings with *all* visible edges in the
tail: **9**. Tail fraction of a ring's visible edges: mean 0.35, median 0.25; histogram
0: 74 rings, (0, 0.25]: 18, (0.25, 0.5]: 29, (0.5, 0.75]: 29, (0.75, 1): 24, 1: 9.

| pattern | rings | ≥ 1 tail edge | all in tail | mean tail fraction | visible edges | tail edges |
|---|---|---|---|---|---|---|
| BIPARTITE | 20 | 9 | 4 | 0.32 | 66 | 22 |
| CYCLE | 22 | 11 | 0 | 0.28 | 99 | 44 |
| FAN-IN | 19 | 13 | 1 | 0.40 | 123 | 66 |
| FAN-OUT | 21 | 12 | 1 | 0.35 | 131 | 66 |
| GATHER-SCATTER | 37 | 27 | 0 | 0.46 | 381 | 254 |
| RANDOM | 17 | 9 | 0 | 0.32 | 84 | 41 |
| SCATTER-GATHER | 22 | 16 | 0 | 0.38 | 239 | 129 |
| STACK | 25 | 12 | 3 | 0.25 | 117 | 33 |

Restricting to days 8–9 removes the 9 all-tail rings from what can be found and truncates
100 others; GATHER-SCATTER loses two thirds of its visible edges.

## 3. Detectability (legacy-feature causal R1, seed 1; val-chosen threshold 0.62)

| window | edges | illicit | base rate | AP | AP / prevalence | P @ R = 0.5 | F1 @ thr | P @ thr | R @ thr | share above thr | licit above thr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| days 8–9 | 862,792 | 956 | 0.111 % | **0.431** | 389 | **0.338** | **0.493** | 0.559 | 0.440 | 0.09 % | 0.04 % |
| days ≥ 10 | 1,108 | 655 | 59.1 % | 0.914 | 1.5 | 0.945 | 0.761 | 0.911 | 0.653 | 42.4 % | 9.3 % |
| whole split | 863,900 | 1,611 | 0.186 % | 0.549 | 294 | 0.743 | 0.599 | 0.694 | 0.527 | 0.14 % | 0.04 % |

The GNN predicts 1,223 positives on the whole split, **470 of them in the tail**; of its 849
true positives, **428 (50 %)** are tail edges. Trivial baseline, score = 1 on days ≥ 10 and 0
elsewhere, whole split: **F1 0.482, precision 0.591, recall 0.407, AP 0.241**. The GNN's
whole-split F1 (0.599) is 0.12 above a rule that reads the calendar; on the comparable
days it is 0.493. A model that learned "the tail is illicit" on top of the GNN would reach
F1 0.620 on the whole split (GNN + tail rule). So yes: on whole-split numbers the trivial
baseline is competitive with the GNN, and the whole-split AP / P@R=0.5 (0.549 / 0.743) are
dominated by a regime where ranking is nearly trivial (AP/prevalence 1.5).

## 4. Neighbourhood sparsity (causal test loader, W = 1,800 s, hop 1, both stores)

| window | seeds | hop-1 sampled neighbours: mean | median | p10 | illicit seeds mean | licit seeds mean | hop-2 mean | seeds per batch |
|---|---|---|---|---|---|---|---|---|
| days 8–9 | 862,792 | 1,271 | 153 | 45 | 1,662 | 1,271 | 5,394 | 7,303 |
| days ≥ 10 | 1,108 | **121** | 90 | 14 | 152 | 77 | 482 | 12 |

Per day, hop-1 mean: d8 1,362 · d9 987 · d10 108 · d11 116 · d12 122 · d13 122 · d14 159 ·
d15 184 · d16 168 · d17 161. Tail seeds see a tenth of the neighbourhood (mean) and their
batches hold 12 seeds instead of 7,303 — there is no licit background for the sampler to
draw from, so a tail edge is scored almost entirely from its own ring's edges and its
features (a fan-in of pattern transactions, a `closes_cycle` flag), which is why the tail is
easy: 91 % precision at the val threshold with 42 % of all tail edges flagged.

## Recommendation

**(a) Primary evaluation window = days 8–9; the tail reported separately, always.**

Reasons, in order of weight: (i) val has no tail, so every threshold, quantile and grid
cell is chosen on a 0.1 % regime and then scored on a split where 41 % of the positives sit
in a 59 % regime the model never saw at tuning time — whole-split numbers are not the
quantity that was optimised; (ii) a calendar rule gets 80 % of the GNN's whole-split F1,
which makes whole-split comparisons between detectors nearly uninformative (every detector
gets the tail for free, and the differences that matter are diluted 1:1); (iii) the tail is
an artefact of the generator (pattern injection with no background), not an operating regime
any deployment would see; (iv) ring-level metrics inherit the same problem — 109 of 183
rings touch the tail and the 9 all-tail rings are found by the sampler's isolation, not by
detection. (b) would keep those artefacts in every headline number and only annotate them.

What (a) costs, and how the ring side is handled: edge metrics on days 8–9 have 956
positives instead of 1,611 (still 5× the val count per seed, CIs widen ~20 %); ring truth
under `test_visible` keeps its window definition, but Ring-Recall's denominator on the
primary window becomes the rings with ≥ 1 visible edge on days 8–9 (174 = 183 − 9), the
9 all-tail rings and the tail-only edges of the 100 partial rings go to the tail block. The
tail block reports the same edge and ring metrics on days ≥ 10 so nothing is hidden; the
whole-split number is kept as a third column for continuity with 3b numbers, labelled.

**Apply step (done the same day, 3b-w apply):** `configs/eval_window.yaml` (`primary`
= test days [8, 9], `tail` = days [10, 17] written out in full, `whole` = [8, 17], `val` =
[6, 7]); `ringshield/windows.py` (day ↔ loader-basis bounds, masks);
`evaluation/edge_metrics.py` reports every metric per block (`val`, `primary`, `tail`,
`whole`; the val threshold is unchanged) and `results/tables/r1_edge_metrics.csv` carries one
column group per block; `ringshield/run_rings.py` evaluates rings per window with truth and
predicted rings restricted the same way (`ringshield/evaluate.py`; ground-truth doc §4a:
primary denominator 174 = 183 − 9 all-tail rings, tail block 109 rings; `tests/test_eval_window.py`
asserts 174 / 109 / 183 and the 100 / 9 / 74 straddling split). Nothing in
`docs/ring_scope.json` or the ground-truth parquet changed. Legacy-feature R1 under the
windows (5 seeds, mean): primary F1 0.494 / AP 0.436 / AP-over-prevalence 394 / P@R=0.5 0.33
vs whole 0.611 / 0.563 / 302 / 0.79; tail F1 0.79.
