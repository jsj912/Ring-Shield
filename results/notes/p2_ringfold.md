# T-P2 — ring-folded cross-scores: the quantities promised beside B17 (2026-11-14)

Status: **ring-F1 INCONCLUSIVE** (paper/PREREG_AMENDMENT_2026-11-14.md, sha256 4f10b6e2…). B17 not
closed. Analysis in docs/deep-analysis.md §15. FINDINGS not edited; proposed notes below.

Step 1 (reproduction): all ten per-seed primary ring-F1 values match `metrics.json` to 4 decimals
(shipped 0.5985 0.5940 0.5649 0.6204 0.5318; ring folds 0.6074 0.5950 0.5768 0.6075 0.5371).
Shipped metrics.json are byte-identical in experiments/ and ../RS-e2e/experiments (rings read from
the latter). Leak-free assertion re-run from parquet: 220 rings, 1,406 ring edges, 0 violations.

`evaluation/ringfold_report.py` → `results/tables/v39_ringfold_report.{csv,json}` (a7b659fa…,
11442a20…). Primary window, 5 seeds, τ 0.5, ring-unit paired bootstrap (174 truth rings + off-ring
clusters), 10,000 draws, seed 20261114. Ring folds minus shipped:

| Metric | Shipped | Ring folds | Δ | 95 % CI | p |
|---|---|---|---|---|---|
| ring-F1 | 0.5819 | 0.5848 | **+0.0028** | [−0.0137, +0.0211] | 0.77 |
| ring precision | 0.8382 | 0.7835 | −0.0546 | [−0.0885, −0.0265] | 0.0002 |
| ring recall | 0.4460 | 0.4678 | +0.0218 | [+0.0068, +0.0395] | 0.003 |
| added-member precision | 0.9263 | 0.8190 | −0.1073 | [−0.1669, −0.0594] | 0.0002 |

- Point Δ = +0.0028 equals the §8 value (unit-test bar met).
- Overlap with the shipped rings (in-window account sets, pooled over 463 shipped rings): 79.7 %
  reproduced exactly; 97.2 % matched one-to-one at Jaccard ≥ 0.5 (per seed 67.7–86.0 % and
  91.4–100 %).
- Fold models, train ring edges as positives (AP / ROC-AUC per fold 0–4; denominators below):
  day folds 0.101 0.366 0.698 0.777 0.769 / 0.991 0.984 0.991 0.997 0.996;
  ring folds 0.097 0.011 0.083 0.511 0.167 / 0.947 0.968 0.976 0.998 0.992.
  Ring-edge AP falls sharply once a fold model no longer sees the ring's other days: the day-fold
  scores did carry ring information.
- Fold record: 137 of 220 train rings span day folds; 597 edges moved.

**Reading (author, round 4).** The three registered readings left a gap, a pre-registration
defect found after the result was seen. Ring-F1: **INCONCLUSIVE**, +0.0028 [−0.0137, +0.0211],
p 0.77. Not distinguishable from zero; the ±0.02 equivalence reading is not met; no equivalence
claim anywhere. Everything below is **post hoc and exploratory**.

## What the fold-2 AP drop is measured on (the denominator of "the leak was real")

- Population: the train edges a fold model held out and scored (`cross_scores_train.parquet`, one
  row per train edge, scored by its owner fold). Positives are ring edges (`ring_id > 0`). Score is
  `score_raw`.
- Fold 2, day folds: 414,812 edges, **485 ring edges**, AP 0.698. Fold 2, ring folds: 415,014
  edges, **687 ring edges**, AP 0.083. The positive sets differ, because ring folds move a ring's
  minority-day edges into its plurality fold.
- Same edges, same positives: on the 414,699 edges both arms put in fold 2 (**372 ring edges**),
  AP is 0.678 (day) vs 0.104 (ring).
- All folds pooled, identical denominator: 3,248,921 train edges, **1,406 ring edges**. AP 0.434
  (day) vs 0.088 (ring); ROC-AUC 0.993 vs 0.979.

## Post hoc follow-up with the ring-folded policy (same tests and seeds as the shipped tables)

| Quantity | Shipped value (day folds) | Ring-folded value | Test |
|---|---|---|---|
| added-member precision vs B1b | 0.926 vs 0.518, **+0.408 [+0.342, +0.481]** (v35: [+0.342, +0.479]) | 0.819 vs 0.518, **+0.301 [+0.235, +0.366]**, p 0.0002 | precision_paired, 10,000 draws, seed 20261111 |
| quiet-member recall | 0.2092 [0.142, 0.290] (B0 0.0052) | **0.2510 [0.179, 0.344]** | step9_tables, 1,000 resamples, seed 0 |
| ring-F1 vs B1b (paired unit bootstrap) | +0.027 [+0.001, +0.052], p 0.047 (v35: p 0.042) | **+0.030 [+0.010, +0.050]**, p 0.003 | precision_paired |
| ring-matched indicator vs B1b (r9 sign-flip) | −0.017 [−0.041, +0.005], p 0.18 | +0.005 [−0.013, +0.022], p 0.69 | step9_tables, 10,000 permutations |

Files: `results/tables/v39_ringfold_{precision_paired.csv,precision_paired.json,quiet_members.csv,significance.csv,ring_ci.csv}`
(sha256 4fdd968a…, a5fb330c…, b6f21ca0…, 85a98cc8…, a3405362…). Shipped B0, B1b and proposed
rows reproduce r9 exactly. The shipped "vs B1b" rows differ from v35 in the third decimal,
because the off-ring units are built over the methods in each run.

Supports / weakens: *weakens* "the leak does not change the reported rings". Ring-F1 is
inconclusive, and the precision advantage over B1b shrinks from +0.41 to +0.30 (it is still large
and significant). *Supports* the quiet-member result, which grows (0.209 → 0.251).

## Proposed dated FINDINGS notes (for the author to approve; FINDINGS.md not edited)

> *B17 (2026-11-14, post hoc; docs/deep-analysis.md §15, paper/PREREG_AMENDMENT_2026-11-14.md):*
> The ring-folded re-run (§8) leaves ring-F1 **inconclusive**: +0.0028 [−0.0137, +0.0211], p 0.77,
> 5 seeds. That is not distinguishable from zero, and the ±0.02 equivalence reading is not met.
> The leak did inflate precision. Ring precision 0.838 → 0.784 (Δ −0.055 [−0.089, −0.027]);
> added-member precision 0.926 → 0.819 (Δ −0.107 [−0.167, −0.059]); ring recall +0.022
> [+0.007, +0.040]. Fold models' ring-edge AP is 0.434 → 0.088 over all 1,406 train ring edges.
> **B17 is not closed.** The row's "small in effect" holds for ring-F1 only, not for precision.

> *A5 (2026-11-14, post hoc; §15):* Under leak-free (ring-folded) cross-scores, added-member
> precision is **0.819** vs B1b 0.518, Δ **+0.301 [+0.235, +0.366]**. The shipped 0.926 /
> +0.408 was measured under day folds, which leak ring labels into the policy's inputs. The
> purity claim holds, at a smaller size; the paper reports the leak-free value first.
