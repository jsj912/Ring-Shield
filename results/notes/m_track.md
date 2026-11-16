# Method track (M1 / M2 / M3) — results

Pre-registration `paper/PREREG_METHOD_2026-11-15.md` (sha256 5b14316f…4d49); amendments
`PREREG_METHOD_AMENDMENT_2026-11-15.md` (7feb2334…95bd: primary verifier without policy/affinity
probabilities) and `PREREG_METHOD_AMENDMENT2_2026-11-15.md` (60dbe5c1…2b2b: train-split embeddings).
Progress and hashes: `paper/METHOD_PROGRESS.md`. Holm family m = 3; M2 and M3 not tested (p = 1).

## M1 — over-generate at 0.2 % and verify

**Reading: R6 INCONCLUSIVE.** M1-V − REF ring-F1 = **+0.0040 [−0.0409, +0.0457]**, p 0.85,
p_Holm 1.00 (test_visible, τ 0.5, primary window, 5 seeds, 10,000 paired draws). Added-member
precision 0.830 (bar 0.80, met; irrelevant to R6). The interval contains 0 and extends beyond
±0.02. No improvement is claimed.

### Reproduction checks
- Shipped B0 0.5213, full 0.5894, ring-folded full (REF) 0.5893 — all equal.
- v42 `gine_causal | global | 0.20 | seed 1` reproduced exactly (B0 0.557, full 0.582, AMP 0.5278).
- This generator reproduces REF: val seed 1 0.5852 = 0.5852; test seed 1 0.6109 = 0.6109; the 0.1 %
  test candidates equal REF's rings (same member sets) for all 5 seeds.
- Train embeddings: CPU re-export on copied fold checkpoints (sha256-verified); median cosine to the
  stored ones 0.99966–0.99999 per fold (bar 0.999 met). Tail: cosine < 0.99 for 7.9 / 1.2 / 1.4 /
  12.6 / 12.9 % of edges (folds 0–4), minimum 0.086 — consistent with batch composition changing the
  causal neighbourhood. Closure in 3 iterations (555,264 + 10,568 + 43 edges).

### Training set
1,097 train candidates (0.2 % per fold), 75 matched to one of 220 train rings. One expansion/partition
cell is shared by all 5 detector seeds, so one training set; seeds differ by `random_state` and their
own val/test candidates. 318 of 4,832 train expansion runs cross a fold boundary.

### Validation (thresholds chosen per seed, as pre-registered; frozen grid t 0.1–0.9)
`experiments/M1_verifier/chosen_cells.json` (sha256 dea2ac41…bbfbec), written before any test scoring.

| seed | REF val | 0.2 % unverified val | M1-V val (t) | M1-V-IS val | M1-S val |
|---|---|---|---|---|---|
| 1 | 0.5852 | 0.4182 | 0.6204 (0.1) | 0.6148 | 0.5753 |
| 2 | 0.5074 | 0.4135 | 0.5316 (0.1) | 0.5277 | 0.5296 |
| 3 | 0.5742 | 0.4329 | 0.5679 (0.1) | 0.5679 | 0.5704 |
| 4 | 0.5528 | 0.4386 | 0.5714 (0.2) | 0.5630 | 0.5944 |
| 5 | 0.5570 | 0.4009 | 0.5517 (0.1) | 0.5556 | 0.5522 |

The seed-1 gate passed; seeds 3 and 5 are below REF on validation. On validation the 0.2 % budget
raises recall only from 0.580 to 0.586 (seed 1); M1-V's validation gain is a precision gain bought
with lower recall (seed 1: P 0.864, R 0.484 vs REF P 0.591, R 0.580).

### Test (run once)
| Arm | ring-F1 [95 % CI] | P | R | rings / seed (in window) | accounts / seed (in window) | rings touched | AMP | quiet-member recall (own seeds / 0.1 % seeds) |
|---|---|---|---|---|---|---|---|---|
| REF (0.1 %) | 0.5893 [0.503, 0.672] | 0.760 | 0.483 | 126.6 (111.0) | 919.6 (501.6) | 104.2 | 0.817 | 0.243 / 0.243 |
| **M1-V** | **0.5933 [0.504, 0.683]** | 0.858 | 0.454 | 100.6 (92.0) | 889.0 (462.2) | 99.6 | **0.830** | 0.255 / 0.309 |
| M1-V-IS (in-sample features) | 0.5998 [0.514, 0.685] | 0.847 | 0.466 | 105.8 (95.8) | 908.6 (477.6) | 101.8 | 0.841 | 0.260 / 0.316 |
| M1-S (score filter) | 0.5347 [0.461, 0.611] | 0.641 | 0.463 | 133.8 (126.0) | 896.2 (539.6) | 102.6 | 0.586 | 0.138 / 0.237 |
| 0.2 % unverified | 0.5205 [0.452, 0.586] | 0.505 | 0.540 | 200.4 (187.2) | 1219.2 (778.0) | 118.8 | 0.385 | 0.286 / 0.362 |

**Secondary result (descriptive; not Holm-adjusted; not an improvement).** Paired M1-V − REF
(τ 0.5): ring precision **+0.098 [+0.034, +0.156]**, ring recall **−0.029 [−0.063, +0.005]**;
rings output per seed **126.6 → 100.6**. M1-V trades recall for precision and outputs fewer rings
and accounts; the primary ring-F1 reading is R6. "Rings touched" = truth rings with ≥ 1 in-window member edge
in the output. Quiet-member recall depends on the seed set (r9 definition); both columns are given.
M1-V beats the score-only filter by +0.059 ring-F1 (point estimates; not tested).

Per seed (`results/tables/m1_per_seed.csv`):

| seed | REF test | M1-V test | Δ test | Δ val | REF val→test | M1-V val→test |
|---|---|---|---|---|---|---|
| 1 | 0.6109 | 0.6067 | −0.0042 | +0.0352 | +0.0257 | −0.0137 |
| 2 | 0.5944 | 0.5909 | −0.0035 | +0.0242 | +0.0870 | +0.0593 |
| 3 | 0.5745 | 0.6081 | +0.0335 | −0.0063 | +0.0003 | +0.0402 |
| 4 | 0.6159 | 0.6394 | +0.0235 | +0.0186 | +0.0631 | +0.0680 |
| 5 | 0.5505 | 0.5214 | −0.0291 | −0.0053 | −0.0065 | −0.0303 |

Per-seed test deltas split 2 positive / 3 negative; the seed-1 gate's +0.035 on validation became
−0.004 on test.

### Post hoc (requested after the primary result was written; outside the Holm family)
`results/tables/m1_posthoc.csv`, `m1_posthoc_{a,b,c}_val.csv`.

| Row | test ring-F1 | P | R | rings / seed | Δ vs REF [95 % CI], p |
|---|---|---|---|---|---|
| a: M1-V verifier on the 0.1 % REF candidates (t on val) | 0.5646 | 0.899 | 0.411 | 79.6 | −0.025 [−0.067, +0.011], 0.19 |
| b: M1-V at t = 0.02 (val mean 0.589) | 0.6012 | 0.777 | 0.491 | 109.8 | +0.012 [−0.025, +0.046], 0.50 |
| b: M1-V at t = 0.05 (val mean 0.583) | 0.6018 | 0.824 | 0.475 | 100.2 | +0.013 [−0.029, +0.051], 0.53 |
| c: M1-V refit without mixed-fold train candidates | 0.5758 | 0.779 | 0.458 | 102.2 | −0.013 [−0.059, +0.029], 0.55 |

- (a) Verification alone, on REF's own candidates, lowers ring-F1 (recall 0.483 → 0.411). Whatever
  M1-V does at 0.2 % is not a gain from verification of REF's rings.
- (b) Below the grid edge, validation ring-F1 is higher (mean 0.589 at t 0.02 vs 0.569 at the chosen
  cells) and test moves the same way, but every interval still contains 0. Not a basis for a claim.
- (c) **Uninformative.** Dropping the 290 train candidates that mix owner folds (rule: seed +
  expanded edges in > 1 fold) removed 26 of the 75 positives, so the refit confounds "no mixed-fold
  cosines" with "a third less positive training data". Its −0.013 vs REF says nothing either way
  about whether the mixed-fold cosine values drive the result.

### What failed / caveats
- The primary reading is R6: the interval is too wide to call either direction. Seed spread is
  larger than the effect (per-seed Δ from −0.029 to +0.034).
- The validation gate was seed-1 only; across 5 seeds the validation advantage was +0.013 on average
  and negative for 2 seeds, a warning the gate did not catch.
- Train candidates are generated with per-fold seed quantiles and owner-fold embeddings; val/test use
  the global quantile and the R1 detector. The verifier's features use score ranks within split to
  limit that shift; it is not removed.
- Embedding re-export reproduces medians closely but has a heavy tail (up to 13 % of edges below
  cosine 0.99 in two folds).
- R1 files were read from `../RS-e2e/experiments/R1_gine_causal` (scores byte-identical to the local
  copy; the local copy lacks checkpoints and seed 2–5 embeddings), matching how REF was built.

## M2 — temporal motif search from 0.1 % seeds

**Reading: R0 NOT TESTED — the seed-1 validation gate failed.** Best cell (grid order tie-break):
M2-G, T 24 h, f 5, L 4, g 1 % → validation ring-F1 **0.5693** (P 0.691, R 0.484, 110 rings,
563 accounts) against REF seed 1 **0.5852**. Best M2-S cell 0.2128 (T 24 h, f 5). No test run.
**The best validation cell is identical to the seed-only (B0) rings** (same ring-F1 0.5693, same 110
rings), so M2 did not improve on seed-only either, in addition to failing the gate against REF.

- Grid: all 24 pre-registered cells, `results/tables/m2_val_grid_seed1.csv`; 966 seeds; the whole
  grid ran in 11 s. Neither cap bound in any cell (instances per seed ≤ 50: 0 seeds; cycle-search
  step limit: 0 seeds). L 4 vs 6 changed nothing in any cell.
- Structure-only search over-generates: 360–440 rings, ring-F1 0.17–0.21. The score gate removes
  almost all of it: the best M2-G cell equals the seed-only rings (B0) on validation exactly
  (0.5693, 110 rings), i.e. the motif instances that pass the gate add no matched ring.
- Instance mix (M2-S, T 24 h, f 3): FAN-OUT 639, FAN-IN 564, GATHER-SCATTER 423, BIPARTITE 13,
  SCATTER-GATHER 11, CYCLE 3.
- Implementation details fixed in code before the run (the pre-registration left them open):
  scatter-gather needs ≥ 2 middles; gather-scatter ≥ 2 distinct sources and ≥ 2 targets with every
  in-edge before the last out-edge; bipartite and stack layers are complete 2 × 2 blocks; a cycle is
  any time-ordered rotation through the seed; a cycle search stops after 20,000 steps per seed
  (never reached). Edge visibility: the scored split's edges within ± T of the seed. 9 unit tests
  (`tests/test_m2_motif.py`).

## M3 — flow-following expansion

**Reading: R0 NOT TESTED — the seed-1 validation gate failed.** Best cell (first in grid order
among ties): ε 0.01, D 6 h, 1 hop → validation ring-F1 **0.5693** (P 0.691, R 0.484, 110 rings,
550 accounts) against **0.5852**. No test run.
**The best validation cell is identical to the seed-only (B0) rings** (same ring-F1 0.5693, same 110
rings), so M3 did not improve on seed-only either, in addition to failing the gate against REF.

- Grid: all 18 cells, `results/tables/m3_val_grid_seed1.csv`; 7 s. Flow-following added 8–140 edges
  to the 110 B0 rings depending on the cell, but changed no match in 14 cells and lost one matched
  ring in the 4 cells with D = 72 h and ε ≥ 0.05 (0.5618). Its best value is exactly B0's.
- Details fixed in code before the run: anchors are the ring's own edges, then each hop's added
  edges; amounts compared as received (incoming) vs sent (outgoing); different currencies compared in
  the repository's hub currency (currency 0, `contract/fx_rates.json`) rather than USD, and currency
  1 (no rate) never matches. 5 unit tests (`tests/test_m3_flow.py`).

## Track summary (2026-11-15)

| Part | Reading | Primary Δ ring-F1 vs REF [95 % CI] | p | p_Holm (m = 3) |
|---|---|---|---|---|
| M1 over-generate + verify | **R6 INCONCLUSIVE** | +0.0040 [−0.0409, +0.0457] | 0.852 | 1.00 |
| M2 motif search | **R0 NOT TESTED** (val gate: 0.5693 < 0.5852) | — | 1 (by rule) | 1.00 |
| M3 flow-following | **R0 NOT TESTED** (val gate: 0.5693 < 0.5852) | — | 1 (by rule) | 1.00 |

Holm: sorted p = 0.852, 1, 1; adjusted p = min(1, 3 × 0.852) = 1.00, then 1.00, 1.00. No part
rejects. No SUCCESS reading; HI-Medium replication is not triggered.

**What the track shows, with seed fusion and the Q track.** On this protocol (HI-Small, primary
window, test_visible, Jaccard 0.5, Multi-GINe causal at a fixed 0.1 % budget), none of the
post-detector reassembly strategies tried raised ring-F1 over the ring-folded full pipeline.
Verifying an over-generated 0.2 % candidate set (M1) moved precision up and recall down, and its
ring-F1 difference is indistinguishable from zero. Motif search and flow-following from seeds (M2,
M3) collapsed on validation to the seed-only rings: whatever they add either does not match truth
rings or, once score-gated, is not added. Seed fusion across detectors (FINDINGS B14, 11b) gave
+0.021 ± 0.038 under `full`, inside seed spread, and the per-account local budget lowered ring-F1.
The Q track's account-level seeding (Q2) was significantly worse (−0.138 [−0.184, −0.093]) and its
validation-chosen partition cell (Q6) was ring-for-ring the shipped one. Together these results are
consistent with B13/B16 and the Q0 decomposition: most unrecovered rings have no in-window piece a
min-size-3 method can match, or are never touched by a seed, and rearranging what the detector's
0.1 % seeds already reach did not raise ring-F1 here.

## For the paper (PROPOSAL for the main session; not applied to the paper, FINDINGS or any tracked file)

> We tried five ways of reassembling rings after the detector, each pre-registered against the
> leak-free full pipeline at a fixed seed budget. Fusing seeds across detectors and spreading the
> budget per account did not help (FINDINGS B14; `results/tables/v37_realloc_full.csv`), and
> account-level seeding was significantly worse (`results/tables/q_family_holm.csv`).
> Over-generating at twice the budget and filtering with a ring-level verifier traded recall for
> precision with no detectable change in ring-F1 (`results/tables/m1_primary.json`).
> Temporal motif search and flow-following from the seeds did not pass their validation gates, and
> their best cells reproduced the seed-only rings exactly (`results/tables/m2_gate.json`,
> `m3_gate.json`). The loss breakdown explains why: most unrecovered rings have no in-window piece of
> three or more accounts, or are never touched by a seed (FINDINGS B13, B16;
> `results/tables/q0_buckets.csv`). Reassembly can only rearrange what the seeds already reach, and on
> this protocol that was not enough to raise ring-F1.
