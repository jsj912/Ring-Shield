# r6 — detector swap (Step 10), primary window, 174 truth rings, 5 seeds each

Built by `evaluation/r6_detector_swap.py`; p-values in `r6_pvalues.csv`; provenance, per-seed k\*
cells and the pre-registration in `r6_detector_swap.json`.

| detector | edge F1 | B0 ring-F1 | `full` ring-F1 | quiet recall | added-member P | class (b) |
|---|---|---|---|---|---|---|
| gine_causal (shipped) | 0.5957 | 0.5213 [0.429, 0.607] | 0.5894 [0.502, 0.675] | 0.2032 | 0.9257 (404 edges) | 33.2 ± 3.6 |
| **mega** | **0.6893** | 0.5208 [0.432, 0.609] | **0.6074** [0.522, 0.688] | 0.2417 | 0.9316 (453 edges) | **24.0 ± 2.5** |
| mega_noembed | 0.6893 | — | 0.5881 [0.503, 0.674] | 0.2014 | 0.8633 (395 edges) | 25.8 ± 3.4 |
| gfpxgb | 0.4996 | 0.3435 [0.259, 0.426] | 0.4508 [0.376, 0.526] | 0.2673 | **0.2600** (2,419 edges) | 39.6 ± 3.0 |

Every L3 parameter (k\*, min_size, Δt, p_min, linkage cut) was re-chosen on val per detector per
seed. All fifteen `full` runs chose k\* = 0.1 % / 3, Δt = 24 h, p_min = 0.7, cut = 0.5.

## What the table decides

**1. No detector row differs significantly from another at the ring level.** The four
pre-registered paired sign-flip tests (10,000 permutations, Holm across exactly these four):

| comparison | Δ matched rate [95 %] | p_raw | p_holm |
|---|---|---|---|
| mega/full vs gine/full | +0.0195 [−0.015, +0.055] | 0.307 | 0.807 |
| mega/b0 vs gine/b0 | −0.0011 [−0.039, +0.040] | 1.000 | 1.000 |
| gfpxgb/full vs gine/full | −0.0333 [−0.090, +0.023] | 0.269 | 0.807 |
| mega_noembed/full vs mega/full | −0.0149 [−0.029, −0.002] | 0.038 | 0.153 |

**2. The pre-registered alternative explanation did not trigger, and is not needed.** The rule
written before the table existed was: *if* `mega/full` beats `gine/full` by more than the seed
spread, test "MEGA's seeds are spread more evenly" before "MEGA is better for rings". The gap is
+0.018 ring-F1 against a seed spread of 0.037 (gine) / 0.018 (mega) — inside the noise — so the
question does not arise. The diagnostics agree with that reading: rings touched by seeds is
**128.8 (mega) vs 129.6 (gine)** and the seeds-per-touched-ring Gini is **0.384 vs 0.395**.
Neither the even-spread signature (lower Gini at equal reach) nor the genuine-reach signature
(higher reach at equal Gini) fires. **Report `mega/full` as indistinguishable from `gine/full`.**

**3. The embedding-space caveat is resolved, in the safe direction.** The shipped policy learned
its two cosine thresholds in gine's 198-dim head space and is applied here to MEGA's 192-dim one.
Dropping the embedding group entirely (`mega_noembed`) makes MEGA slightly *worse*, not better
(0.5881 vs 0.6074; added-member precision 0.863 vs 0.932), so the cross-space transfer is not
depressing MEGA's row and the `mega` row stands as the detector row. The effect is nominally
significant raw (p 0.038) but not after Holm (0.153), so it is reported as a direction, not a
result.

**4. class (b) is where the detectors actually differ**, and it is the one column that moves:
33.2 → **24.0** untouched rings when MEGA replaces our detector, against combined SDs of ~3.1.
Matched rings rise only 80.2 → 83.6, so roughly two thirds of the newly reached rings land in the
partially-covered classes rather than becoming matches. See `FINDINGS.md` B8 — the 19 % untouched
figure is a property of the detector, not of the dataset.

## Two cautions about reading this table

**The paired test only sees recall.** It compares per-ring matched indicators, so a difference
driven by *precision* is invisible to it. gfpxgb/full scores 13.9 ring-F1 points below gine/full
yet tests at p_holm 0.807, because it matches almost as many rings — while producing far more
rings to do it. Use ring-F1 with its CI for precision-side differences and the paired test only
for "does this method find different rings".

**gfpxgb's `full` gain is not the same mechanism as the others'.** Its ring-F1 does rise (0.3435
→ 0.4508) and it posts the highest quiet-member recall in the table (0.2673), but it gets there by
adding **2,419 edges at 0.260 precision**, against MEGA's 453 at 0.932 — five times the volume at
a quarter of the accuracy, with runs producing up to 153 rings and clusters of 53 members. Half
its seed edges (`seed_edges_off_ring_share` 0.499) are not on a truth-ring edge at all, against
0.214 for gine and 0.112 for MEGA. A weak detector's seeds chain through the expansion; the
headline quiet-recall number for gfpxgb should not be quoted without the precision beside it.

## Detector provenance

| detector | scores | sampling | policy | affinity |
|---|---|---|---|---|
| gine_causal | `R1_gine_causal` | ours_causal (fallback, W = 1,800 s) | R3 `policy_proposed` | R4 `affinity` |
| mega | `R6_mega` (`models/mega_adapter.py`) | ours_causal (fallback, W = 1,800 s) | R3 `policy_proposed`, unchanged | R4 `affinity`, unchanged |
| mega_noembed | `R6_mega` | ours_causal (fallback, W = 1,800 s) | R3 `policy_no_embedding` | R4 `affinity_no_embedding` |
| gfpxgb | `R2_b0/gfpxgb_scores` | n/a (trailing GFP features, no graph sampling) | R6 `policy_gfpxgb` (own cross-scores) | R6 `affinity_gfpxgb` (own pairs) |

Both GNNs took the same loader route, so sampling is not a confound between them. gfpxgb does no
neighbourhood sampling at all and its policy/affinity were retrained on its own cross-scored train
split with the embedding group dropped — its column is **policy-variant, not detector-only**.

MEGA's edge F1 of 0.6893 ± 0.0396 sits 1.9 points under the 70.83 ± 2.18 its authors report for
MEGA-GIN on HI-Small (arXiv:2412.00241), under causal sampling and their own hyper-parameters;
their Multi-GIN baseline is 64.79 ± 1.22. Policy CV AUC-PR values are **not** comparable across
detectors (`docs/EXPANSION.md`).
