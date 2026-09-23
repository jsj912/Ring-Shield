# Step 9 — metrics extensions and statistics

Status 2026-09-23. `evaluation/ring_metrics.py` is unchanged and its self-tests still pass;
everything here is built on top of it (`evaluation/ring_stats.py`, driver
`evaluation/step9_tables.py`). Nothing is chosen on test: every run's parameters were fixed on
validation in its own step, and this step only re-tabulates what those runs produced.

## The central claim, with an interval

**Quiet-member recall on the primary window** (Q = scored members of an in-scope truth ring with
no incident *seed* edge inside the window; 306 accounts per seed, 5 seeds):

| method | quiet-member recall | 95 % CI | ring-F1 | 95 % CI |
|---|---|---|---|---|
| B0 (cc at k\*) | **0.0054** | [0.000, 0.015] | 0.521 | [0.429, 0.607] |
| cc + partition (no expansion) | 0.0054 | [0.000, 0.015] | 0.536 | [0.452, 0.622] |
| B1b (adjacency + quantile rule) | **0.2229** | [0.163, 0.299] | 0.555 | [0.470, 0.632] |
| proposed (expansion policy, expand + cc) | **0.2098** | [0.142, 0.290] | 0.582 | [0.490, 0.668] |
| full (expansion + partition) | 0.2026 | [0.136, 0.284] | 0.589 | [0.502, 0.675] |
| ablation: hop-1 rows only | 0.2529 | [0.176, 0.346] | 0.562 | — |
| B1 (adjacency rule) | 0.1183 | [0.063, 0.187] | 0.162 | — |
| gfpxgb (cc at k\*) | 0.0112 | [0.000, 0.033] | 0.344 | [0.259, 0.426] |
| density | 0.0000 | [0.000, 0.000] | 0.014 | — |

**Read it this way.** The pipeline's central promise was to recover ring members the detector
never fires on. It does: from **0.5 % to 21 %** of quiet members, and the CIs do not overlap
([0.000, 0.015] vs [0.142, 0.290]); the paired permutation test gives
**Δ = +0.359 quiet accounts per ring, p_raw 0.0001, p_holm 0.0005**. That is the one comparison
in the table that survives correction. But the same table says the *learned* policy is not what
does it — the adjacency + quantile rule B1b reaches 0.223 [0.163, 0.299], statistically
indistinguishable from the policy's 0.210 (Δ −0.024 quiet accounts per ring, p_holm 1.00). What
the policy buys over B1b is precision, not quiet members (`docs/EXPANSION.md`).

Check 2 holds: **B0's quiet-member recall is 0.0054 ≤ 0.05**, as it must be by construction — its
rings are built from seed edges alone and can only touch a quiet account through the member-edge
rule. `tests/test_ring_stats.py::test_quiet_member_recall_of_b0_is_at_most_five_percent` asserts it.

Per pattern (primary, pooled): SCATTER-GATHER 0.65 (full) / 0.57 (B1b), FAN-IN 0.46 / 0.42,
GATHER-SCATTER 0.32 / 0.48, RANDOM 0.17 / 0.30, CYCLE 0.16 / 0.14, FAN-OUT 0.09 / 0.10,
STACK 0.01, **BIPARTITE 0.00** — the pattern whose quiet edges share no endpoint with a seed
(`docs/EXPANSION.md`), so no endpoint-adjacent expansion can reach them.

Other windows: quiet-member recall is 0.268 (tail) and 0.227 (whole) for `full`, against 0.025
and 0.000 for B0 — the effect is not an artefact of the two-day primary window.

## Significance — `results/tables/r9_significance.csv`

Paired sign-flip permutation on per-ring matched indicators (seeds averaged per ring), 10,000
permutations, Holm across the five pre-registered comparisons (amendment c):

| comparison | rings differing | Δ matched rate | 95 % CI | p_raw | p_holm | reject at 0.05 |
|---|---|---|---|---|---|---|
| **proposed vs B0** | 28 | **+0.062** | [+0.036, +0.092] | 0.0001 | **0.0005** | **yes** |
| cc+partition vs B0 | 7 | +0.018 | [+0.002, +0.039] | 0.058 | 0.233 | no |
| full vs B2 | 10 | +0.015 | [−0.002, +0.036] | 0.164 | 0.493 | no |
| proposed vs B1b | 32 | −0.017 | [−0.041, +0.005] | 0.175 | 0.493 | no |
| full vs B1b | 40 | −0.002 | [−0.032, +0.028] | 0.945 | 0.945 | no |

The same test on quiet accounts recovered per ring: proposed vs B0 **+0.359, p_holm 0.0005**;
every other comparison p_holm 1.00.

**What the table settles.** Expansion over the B0 baseline is real and survives correction on both
the ring-matched indicator and the quiet-member metric. Everything else in the pipeline —
the learned policy over the rule, the partition over plain components, the partition without
expansion — moves the number in the expected direction but **not by more than ring-sampling noise
on 174 rings**. The honest summary is one significant step (expansion) and three that are not
resolvable at this sample size.

## Method

* **Evidence.** For every (method, seed, window) the run's `rings.parquet` is re-matched with the
  unchanged `ring_metrics.match_rings`, and the per-truth-ring outcome (matched, Jaccard,
  coverage, quiet members and which were found, time-to-detection) is stored as a `RingEvidence`.
  Every later statistic is a re-tabulation of those records — no re-matching inside a loop.
* **Bootstrap** (`bootstrap_over_rings`): 1,000 resamples of the in-scope truth rings *with
  replacement*; inside each resample every seed's metrics are recomputed on that multiset and the
  seeds are averaged; the reported interval is the 2.5 / 97.5 percentiles. Ring precision is
  scaled by the resampled truth count, the standard treatment when the resampling unit is the
  truth ring. The interval therefore carries ring-sampling variation with seed variation folded
  in, which is what a reader needs.
* **Permutation** (`paired_permutation`): per ring, the seed-averaged outcome of each method; the
  null flips the sign of a random subset of the paired differences; p = (1 + #|perm| ≥ |obs|) /
  (1 + 10,000). Fixture behaviour is pinned in `tests/test_ring_stats.py`: identical methods → p
  = 1.0; 20 of 85 rings one way → p < 0.01; 20 rings differing but a wash → p > 0.5.
* **Holm** (`holm`): step-down over all comparisons in one table, monotone.
* **Time to detection** (amendment e): first seed-edge timestamp of the matched prediction minus
  the ring's first in-window truth edge. `ring_evidence` refuses a non-causal run.
* **τ sweep** (item 5): every ring row again at Jaccard 0.3 and 0.7 in `r9_tau_appendix.csv` and
  the per-table `r{2,3,4}_appendix.csv`.

## Time to detection — `results/tables/r9_ttd.csv`

Primary window, causal detector (R1 `causal_sampling: true`, loader route fallback W = 1,800 s):

| method | matched rings | median | IQR | first seed at or after ring start |
|---|---|---|---|---|
| B0 | 334 | **0 h** | 0 h | 96 % |
| B1b | 392 | 0 h | 0.8 h | 98 % |
| full (average) | 394 | **0 h** | 0 h | 93 % |

**The metric does not discriminate here, and that is itself the finding**: in the median the
*first* in-window transaction of a ring is already a seed, so detection is immediate and the
distribution is a spike at zero. The 2–7 % of rings with a negative value are cases where the
matched prediction's earliest seed edge precedes the ring's first truth edge — the prediction
contains a licit or another ring's edge earlier in time, not a causality violation. On this
dataset time-to-detection measures the generator's burstiness, not the detector's latency; it is
reported for completeness and should not carry weight in the paper.

## τ sensitivity (primary window, ring-F1)

| method | τ = 0.3 | **τ = 0.5** | τ = 0.7 |
|---|---|---|---|
| B0 | 0.551 | 0.521 | 0.393 |
| B1b | 0.585 | 0.555 | 0.484 |
| proposed | 0.598 | 0.582 | 0.514 |
| full | 0.617 | 0.589 | 0.506 |

The ordering is stable across τ; the gap between the methods narrows as τ rises (at 0.7 the
rule B1b's recall advantage matters less than the policy's precision).

## Typing, with the window sensitivity (amendment a)

`results/tables/r5_typing_ci.csv` — bootstrap over matched rings, 1,000 resamples:

| window | matched rings | head accuracy | 95 % CI | rule accuracy | 95 % CI |
|---|---|---|---|---|---|
| primary (days 8–9) | 401 | 0.219 | [0.182, 0.259] | 0.207 | [0.170, 0.249] |
| **whole (days 8–17)** | 433 | **0.594** | [0.547, 0.640] | 0.547 | [0.499, 0.591] |

This is the Step 8 prediction, now measured: typing on a two-day fragment is bounded by the
window, and the same pipeline typed on the full ten-day test period is **2.7× more accurate**.
The head beats the rule on both windows, and on `whole` the two intervals barely overlap.

## Files

`results/tables/`: `r9_ring_ci.csv` (every method × window, point + CI for six metrics),
`r9_quiet_members.csv` (per method / window / pattern), `r9_significance.csv` (+ `r3_pvalues.csv`,
`r4_pvalues.csv`), `r9_ttd.csv`, `r9_tau_appendix.csv` (+ `r{2,3,4}_appendix.csv`),
`r{2,3,4}_ci.csv`, `r5_typing_ci.csv`, and `r9_significance.log.json` (seeds, resample counts,
RNG seeds, the quiet-member rule, the bootstrap unit). Every previously "pending" marker is gone
from `results/`.
