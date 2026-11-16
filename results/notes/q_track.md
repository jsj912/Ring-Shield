# Q track — notes (started 2026-11-15)

## What the repo already measured

- **Q0 (loss decomposition).** It is partly answered. `evaluation/unmatched_rings.py` → `r4_unmatched` (FINDINGS B7, B8, B11, B12) sorts *unmatched* rings into four classes: lt3_members, untouched by any *included* edge (seed or expanded), over-merged and under-covered. FINDINGS B12/B13 report under-covered as 6.8 rings per seed and over-merged as 5.2 rings per seed, and that 81.5 % of the missing edges in under-covered rings are disconnected inside the window. FINDINGS G #4 / `v36_component_scope` gives 77 of 174 rings with no in-window piece of ≥ 3 accounts. **Not yet measured:** a single bucket per ring with that structural class taking precedence, "touched" defined by *seed* edges only, and a split of the merged rings from the rings split across several predictions. Q0 adds these.
- **Q1 (score saturation).** FINDINGS G #6 (R12b): 2.9 % of day-8 raw scores sit on one tied value (0.079603), between p99 and p99.5. HI-Medium seed 3 is excluded because its scores saturate. No count yet of seeds decided by a tie at 0.1 % on HI-Small. Open.
- **Q2 (account-level seeding).** B14 / G #5: the per-account local budget (11c, `local_budget_seeds.py`) touches 116.2 rings against 129.6 for global, with full ring-F1 0.575 against 0.590. Q2 differs from it (top-ranked accounts take all their edges up to the budget, rather than one seed per account). That still has to be written up in the pre-registration.
- **Q3 (overlap).** Not measured.
- **Q4 (seed consensus).** `ensemble_seeds.py` (11b) ensembles *detectors* at the seed stage (+0.021 ± 0.038). No consensus across the five *detector-seed* rings outputs exists. Open.
- **Q5.** A plan only.

## Reference checks (2026-11-15) — PASS

`score_external.py`, default intervals, all four conventions:
- B0 (`../RS-e2e/experiments/R2_b0/gine_causal/seed1..5/rings.parquet`): test_visible τ 0.5 ring-F1 **0.52132** (target 0.5213).
- Full (`experiments/R4_partition/runs/average/seed1..5`): **0.58945** [0.5023, 0.6747] (target 0.5894).
Outputs: `results/tables/q0_ref_b0/`, `q0_ref_full/` (config.json holds each input's sha256). No tracked file in results/ or docs/ changed.

## Q0 — where the rings are lost (shipped full, primary window, 5 seeds)

The definitions are in the docstring of `evaluation/q0_loss_decomposition.py` and are tested in `tests/test_q0_buckets.py` (9 tests pass). Bucket order: a → d → b → c. The c sub-rules are c1 no overlapping prediction → c2 one-to-one conflict → c3 split (≥ 2 fragments with ≥ 2 members each, covering ≥ half of V) → c2 if outsiders > missing, otherwise c1.
Check: the matched total is 80.2 per seed, equal to the scorer's 0.4609 × 174.

| bucket | mean / seed (SD) | quiet-member share |
|---|---|---|
| a no ≥3 in-window piece | 77.0 (0) — of which 11.4 are still matched | 0.43 |
| b matchable, no seed touches it | 11.0 (2.3) | 1.00 (by definition) |
| c1 too few recovered | 14.4 (0.9) — 7.8 with no overlapping prediction, 6.6 partial fragment | 0.53 |
| c2 merged | 1.0 (1.7) — 0 lost to one-to-one; 2.8 ring-seeds' worth include another ring's member | 0.60 |
| c3 split | 1.8 (1.3) | 0.51 |
| d matched | 68.8 (4.0) | 0.21 |

Per pattern: `results/tables/q0_buckets_by_pattern.csv`. The STACK pattern accounts for 5.2 of the 14.4 c1 rings and has 0.8 matches. In bucket b, the largest contributors are GATHER-SCATTER (2.8) and FAN-IN (2.4).

**Reading.** Among the 97 matchable rings, 28.2 per seed are lost. The largest share is c1, too few members recovered: 14.4 rings. More than half of those (7.8) have *no* prediction of ≥ 3 accounts overlapping them even though a seed touches them, and the rest are clean fragments that are too small. Next comes b, untouched by seeds (11.0). Merging (1.0) and splitting (1.8) together come to under 3 rings. So Q4, whose consensus targets merges and splits, can move little. Seed placement (Q1, Q2) acts on b, and on the c1 rings whose seeds never formed a ring, so it has the most room, though B14 and B13 show that seed reallocation and reach are hard. Q4's leverage is ≤ about 3 rings per seed, with c1 partial fragments as a secondary possibility.

Outputs (sha256): q0_buckets.csv dfed40dc…, q0_buckets_by_pattern.csv 290d1ef3…, q0_buckets_per_ring.csv 6366f8fb…, q0_buckets.json 1779eb80…; script 512c2579….

### Q0 addendum (2026-11-15, after author decisions)

**Rebuild route.** `build_full_rings` (the route of `unmatched_rings.py`) reproduces the shipped test buckets exactly (0 of 870 differ). It first differed on seeds 2–5 because this checkout holds only the seed-1 embeddings. The seed 2–5 embeddings and the detector checkpoints are read-only from `../RS-e2e/experiments/R1_gine_causal/`. The checkpoints are model_best_seed1..5.pt (sha256 aca7a76f…, 6ecd6712…, 852dbf17…, c2e38d84…, 526c4497…). The test embeddings are seeds 1–5 f32be717…, fc539004…, 1ae25a5e…, 68bc57e5…, 7a8a227b…; the val embeddings are seeds 1–5 03a149c8…, 238a8ff7…, 2b8e9dc4…, 1fde031b…, 891b5d61…. The val and test scores are identical across the three checkouts where compared.

**Bucket a, test (77 rings; 11.4 matched and 65.6 unmatched per seed).** By visible accounts: 2 rings with 1 visible account (0.4 matched per seed), 58 with 2 (11.0 matched), and 17 with ≥ 3 visible accounts spread over pieces of < 3 (0 matched). How the matches came about: 7.8 per seed are an in-window prediction of < 3 accounts that meets min_size through out-of-window members (median unrestricted size 9, Jaccard 1.0; the B7 mechanism); 3.6 per seed are a 3-account in-window prediction holding both visible members plus one outsider (Jaccard 0.67). Tables: `q0_buckets_a_by_visible.csv`, `q0_buckets_a_how.csv`.

**Validation window (157 rings, 60 in bucket a; per seed, 5-seed mean).**

| bucket | test | val |
|---|---|---|
| a | 77.0 (11.4 matched) | 60.0 (4.4 matched) |
| b | 11.0 | 1.0 |
| c1 | 14.4 | 8.6 |
| c2 | 1.0 | 1.4 |
| c3 | 1.8 | 4.2 |
| d | 68.8 | 81.8 |

c1 is the largest lost bucket among matchable rings in both windows, so the author's rule lets the design proceed. Two differences: b is much smaller on validation (1.0 against 11.0), and c3 is second on validation (4.2). The validation window is where the expansion cell and the partition cut were chosen.

**Q4: dropped** (author decision, 2026-11-15). It targets merges and splits, which come to c2 + c3 = 2.8 rings per seed on test, too few to matter. Not run.

## Q3 — overlapping membership (descriptive; `evaluation/q3_overlap.py`, 4 tests pass)

| | primary (days 8–9) | whole test (8–17) |
|---|---|---|
| truth rings / visible accounts | 174 / 762 | 183 / 1,309 |
| accounts in > 1 ring (max rings per account) | 25 (8) | 42 (10) |
| rings sharing ≥ 1 account | 49 | 63 |
| overlapping pairs; shared part median / max accounts | 101; 2 / 2 | 169; 2 / 7 |
| median shared part / smaller ring | 1.0 (the smaller ring lies inside the larger) | 1.0 |
| max rings matchable at once by a hard partition, m* | 154 | 153 |
| ceiling ring recall / ring-F1 (precision 1) | 0.885 / **0.939** | 0.836 / **0.911** |

Calculation (in the docstring): predictions in a hard partition are disjoint, and a prediction matches T at Jaccard ≥ 0.5 at best as a subset of T with ≥ ⌈|T|/2⌉ members. A set of rings is matchable at once iff that b-matching is feasible (checked by max-flow), and m* is found exactly per overlap cluster. F1 = 2m*/(n + m*). It ignores min_size and observability. Overlap alone caps the primary window at 20 unmatchable rings (ring-F1 0.939), far above the shipped 0.589, so overlap is not what binds. Most overlap is small (often 2-account) rings sitting inside larger rings that share accounts (clusters of up to 8 rings where only 2 can be matched).
Outputs: `results/tables/q3_overlap.{csv,json}`.

## Q1 — score saturation: STOPPED by the pre-registered rule

`results/tables/q1_ties.csv` (computed inline with `threshold_for_pct`; scores from `experiments/R1_gine_causal/scores_{val,test}_seed*.parquet`). Edges with score exactly at the cut q: **0 on every seed in both splits**, so the share of the budget decided by a tie is 0 % (< 1 %). Q1 stops with no test run and leaves the Holm family. That family is now {Q2, Q6}.
Context: scores tied at the maximum do occur (test edges at 1.0 per seed: s1 178, s2 25, s3 146, s4 89, s5 1; val ≤ 62). All of them sit far above q (test q 0.33–0.96), so every one of them is a seed under the strict rule. Saturation reaches up to 21 % of the test budget (178 / 864, seed 1) but decides none of it. q is an interpolated percentile, not an observed score, so the strict rule never meets a tie at the boundary on HI-Small. The HI-Medium saturation problem (seed 3) does not appear here.

## Q5 — ring-balanced detector training (PLAN ONLY; nothing changed, nothing trained)

**What the detector does now.** R1 (`experiments/R1_gine_causal/config.yaml`, Multi-GINe v2) is trained by `models/tgn.py`, `--arch gine`. Loss: `nn.CrossEntropyLoss(weight=[w_ce1 = 1, w_ce2 = 9])` (tgn.py:695–696), mean over the batch's supervised edges (`train_epoch`, tgn.py:552–571; `loss = loss_fn(pred, gt)` at :571). Sampling: causal fallback loader (`models/causal_loader.make_loader`), batch 8,192, neighbours 100/100, shuffle on. There is no ring-aware sampling. Checkpoint: best validation minority-class F1 (tgn.py:700–734), patience 20, at most 100 epochs, LR plateau schedule. The threshold is tuned on validation (tgn.py:749).

**Train-split facts** (`amlworld_train.parquet`): 220 truth rings over 1,406 edges, ring size median 3, mean 6.39, max 38. 2,530 labelled positives, of which 1,312 are inside a ring. So today a 38-edge ring carries about 13× the loss of a 3-edge ring.

**Weighting formula.** For a supervised train edge e with label y_e and class weight c_y (1 or 9):
- w_e = n̄ / n_r if e is a positive edge of truth ring r, where n_r = number of supervised positive edges of r and n̄ = the mean of n_r over rings;
- w_e = 1 otherwise (negatives, and positives that belong to no ring).

Batch loss = Σ_e c_{y_e} w_e CE_e / Σ_e c_{y_e} w_e, the same normalisation PyTorch uses for a class-weighted mean. Every ring then contributes the same expected total weight n̄ per epoch, and the total ring-positive mass is unchanged (Σ_r n̄ = Σ_r n_r).

**Code that would change** (not changed here):
1. `models/tgn.py:695–696`: build the loss with `reduction="none"`.
2. `train_epoch` (tgn.py:552–571): gather w_e for the batch's supervised edges (`_get_mask_and_clean` already yields the positions of supervised seeds within `inds`, so index a precomputed weight tensor aligned with `inds`), then compute `(loss_vec * c * w).sum() / (c * w).sum()`.
3. `main()` (tgn.py:806 ff.): a new flag `--ring-balanced` that reads `ring_id` from the train parquet and builds the weight tensor. It is recorded in `config.yaml`.

**Validation selection stays the same.** Same checkpoint rule (validation minority F1), patience, epochs, LR schedule and validation threshold tuning; validation is scored unweighted. Downstream, the R3 policy, its cell, the R4 affinity and its cut are all the shipped ones, unchanged, with the seed budget fixed at 0.1 %. This is the detector-swap protocol of T-P7.

**GPU time** (from `experiments/R1_gine_causal/training_log_seed*.csv`): 246–266 s per epoch, 30–52 epochs until early stop, so 2.2–3.6 GPU-hours per seed and about 15.7 hours for five seeds. Add about 20 minutes of scoring per seed (`scores_test_seed1.log.json`: data load 1,069 s plus 114 s). It cannot run while R6_megagenagg holds the GPU.

**Proposed bars** (to be frozen in their own pre-registration before training):
- **Seed-1 gate:** validation AP ≥ 0.90 × R1 seed-1 validation AP. If it fails: "ring balancing degrades the detector", and seeds 2–5 are not trained.
- **Primary:** paired Δ full-pipeline ring-F1 against shipped full (`score_external.py --compare`, 10,000 draws), five seeds, primary window. The five exhaustive readings are those of PREREG_Q (IMPROVES / REACH AT A PRECISION COST / WORSE / NO DETECTABLE EFFECT / INCONCLUSIVE, added-member-precision veto at 0.85).
- **Secondary, descriptive:** Q0 buckets of the new detector. Prediction: c1 and b fall on rings with many edges, and per-pattern recall rises for patterns with long rings, except STACK (B13, disconnected in the window). Edge F1 on the primary window is reported beside it, because C6 says edge F1 and ring-F1 can move independently at a fixed budget.

## Q6 — undersized-group rescue: validation rejects it

Shipped values relaxed: p_min 0.7 (from {0.5, 0.3, 0.1}) and max_hops 2 (to 3, with the policy extrapolating). Groups: 386–420 per seed on validation have fewer than 3 accounts, almost all of them single seed edges. 1–2 seedless groups per seed (a hop-2 addition whose hop-1 link was not included) cannot be re-expanded and are left as shipped. This rule was not written in the pre-registration and is recorded here.
Validation ring-F1 (`experiments/Q6_rescue/val_grid.csv`) falls steadily as the rule is relaxed, on every seed. Means over seeds: shipped (p0.7) 0.593; p0.5 about 0.556; p0.3 about 0.516; p0.1 about 0.500. Hop 3 is equal to or worse than hop 2 at every p_min. Predictions per seed rise from 134 to as many as 234 while matches barely move. **Validation chose the shipped cell (no rescue) on all five seeds** (`experiments/Q6_rescue/choices.json`). So the test arm is the shipped pipeline. Rerun on test it gives Δ ring-F1 0.0000 [−0.0043, +0.0043], p 1.0 (`results/tables/q6_vs_full`).
Per pattern on validation (`q6_val_per_pattern_recall.csv`): the relaxed cells raise recall slightly (GATHER-SCATTER 0.817 → 0.852, FAN-OUT 0.56 → 0.61 at p0.1), at a large precision cost. **STACK is 0.080 in every cell**, as B13 predicts.
**Verdict:** reading 4 (NO DETECTABLE EFFECT) by the bar. Stated plainly, validation found no relaxed cell better than shipped, so no rescue was applied. Bucket c1 cannot be closed by loosening the policy for undersized groups: what it admits is mostly false rings.

## Q2 — account-level seeding: WORSE

Validation (full ring-F1, 5 seeds): Q2-top3 0.514 and Q2-max 0.465, so **top3 chosen** (shipped 0.593). Seed overlap with shipped (Jaccard): top3 0.35–0.50 and max 0.25–0.28 on validation; top3 0.42–0.48 on test.
Test, primary window, 5 seeds:

| arm | ring-F1 [95 %] | precision | recall | matched / predicted per seed |
|---|---|---|---|---|
| shipped seed-only (B0) | 0.5213 | 0.814 | 0.384 | — |
| Q2-top3 seed-only | 0.3482 [0.2758, 0.4219] | 0.509 | 0.267 | 46.4 / 92.2 |
| shipped full | 0.5894 [0.5023, 0.6747] | 0.818 | 0.461 | 80.2 / — |
| Q2-top3 full | 0.4516 [0.3770, 0.5323] | 0.576 | 0.376 | 65.4 / 114.6 |

Paired against shipped full: Δ ring-F1 **−0.138 [−0.184, −0.093]**, p 0.0002, Holm p 0.0004 (family {Q2, Q6}; Q1 stopped). Recall −0.085, precision −0.242. Seed-only against B0: −0.173 [−0.231, −0.115].
**Verdict: reading 3, WORSE.** Ranking accounts and taking up to three edges each moves about half the budget off the edges the detector ranks highest, and both precision and recall fall. This extends B14: reallocations of a fixed 0.1 % budget away from the global edge quantile have not helped, and this one hurts more than 11c did. Pending for the table: added-member precision, quiet-member recall, rings touched and accounts output (not computed yet; they cannot change a WORSE reading).

Holm family: `results/tables/q_family_holm.csv`. No part beats full, so the stop-and-report rule did not fire.

## Close-out (2026-11-15)

**Q6 row of the Holm table: corrected.** The Q6 test arm is identical to shipped full ring for ring on all five seeds (same member and edge sets). The [−0.0043, +0.0043] interval earlier reported from `--compare` is a scorer tie-break artefact, not a difference between arms. In seed 4, truth rings 243 and 259 (2 visible members each) tie at Jaccard 0.667 against shared predictions, and greedy one-to-one matching (`evaluation.ring_metrics.match_rings`) resolves the tie by the prediction's position in the file. The rebuilt file lists rings in a different order from the shipped file, so one ring gains a match and the other loses one. The row now reads Δ = 0 exactly, with no interval and no p-value, **excluded from the Holm family**. The family is Q2 alone, so p_Holm = p_raw = 0.0002. Side observation for the author (the scorer is not changed here): with tied Jaccards, greedy matching depends on ring order and can undercount. In the Q6 ordering, rings 243 and 259 had distinct predictions at 0.667 available.

**Q2 secondary columns** (`results/tables/q2_secondary.csv` and `_per_seed.csv`; `python -m evaluation.q2_account_seeds --secondary`; test, primary window, mean of 5 seeds):

| arm | rings touched | quiet-member recall | rings out (in window / all) | accounts out (in window / all) | matched |
|---|---|---|---|---|---|
| shipped full | 129.6 | 0.203 | 98.0 / 112.0 | 451.2 / 836.8 | 80.2 |
| Q2-top3 full | 108.6 | 0.174 | 114.6 / 130.8 | 528.0 / 818.6 | 65.4 |
| shipped B0 | 129.6 | 0.005 | 82.0 / 95.6 | 352.2 / 657.0 | 66.8 |
| Q2-top3 B0 | 108.6 | 0.002 | 92.2 / 108.2 | 444.2 / 651.6 | 46.4 |

Checks: matched 80.2 and touched 129.6 equal the scorer and FINDINGS B14; quiet recall 0.203 against the reported 0.2026 (pooled over accounts here). **Added-member precision is not available for Q2.** Its minimal rings files keep member_edges, which include induced transactions among members, but not the expansion's `expanded_edges`. The proxy (non-seed member edges) gives 0.22 for shipped against the reported 0.926, so it is a different quantity and is not reported. The exact figure would need Q2 rerun with expanded_edges saved, which is not done (author: do not rerun).

**Q6 validation grid** (`results/tables/q6_val_grid.csv`, `_per_seed.csv`, `_by_pattern.csv`; validation only; mean of 5 seeds):

| cell | ring recall | ring precision | ring-F1 | rescued groups | rescued that match a truth ring |
|---|---|---|---|---|---|
| p0.7 h2 (shipped) | 0.549 | 0.645 | 0.593 | 0 | 0 |
| p0.7 h3 | 0.549 | 0.645 | 0.593 | 0 | 0 |
| p0.5 h2 | 0.553 | 0.560 | 0.556 | 21.4 | 0.6 |
| p0.5 h3 | 0.553 | 0.558 | 0.555 | 22.0 | 0.6 |
| p0.3 h2 | 0.555 | 0.483 | 0.516 | 47.6 | 1.0 |
| p0.3 h3 | 0.555 | 0.473 | 0.510 | 51.4 | 1.0 |
| p0.1 h2 | 0.567 | 0.449 | 0.500 | 65.4 | 2.8 |
| p0.1 h3 | 0.567 | 0.437 | 0.493 | 70.8 | 2.8 |

Per pattern: ring recall and rescued matches per pattern are in `q6_val_grid_by_pattern.csv`. Per-pattern precision is undefined, because an unmatched prediction has no pattern. STACK (25 validation rings): recall 0.080 and 0 rescued matches in every cell. Rescued candidate groups per cell and seed, with `matched_truth`: `experiments/Q6_rescue/val_candidates/<cell>_seed<S>.parquet`, git-ignored by `experiments/Q6_rescue/.gitignore`. No relaxed Q6 cell was run or scored on test. The only Q6 test run is the validation-chosen shipped cell.

## For T-P5

**Partition ceiling under overlapping truth (Q3).** In the primary window (test days 8–9, scope test_visible), 25 of 762 visible accounts belong to more than one of the 174 truth rings (at most 8 rings per account), and 49 rings share at least one account with another ring. The shared part is at most 2 accounts (101 overlapping pairs). A hard partition makes predicted rings pairwise disjoint, and a prediction matches a truth ring at Jaccard ≥ 0.5 at best as a subset holding at least half its members. The largest set of rings matchable at once is therefore 154 (computed exactly as a capacity-1 b-matching per overlap cluster), which bounds ring recall at 0.885 and ring-F1 at 0.939 with precision 1. Over the whole test period (days 8–17, 183 rings) the bound is 0.911. The shipped pipeline reaches 0.589 [0.502, 0.675].

**Rings with no in-window piece of three or more accounts (Q0, bucket a).** 77 of the 174 primary-window rings have no in-window connected piece of ≥ 3 accounts: 2 have one visible account, 58 have two, and 17 have three or more spread over pieces of fewer than three. The shipped pipeline nonetheless matches 11.4 of them per seed (5 seeds), all with one or two visible accounts. 7.8 match through a prediction with fewer than three accounts inside the window that satisfies the minimum size of 3 through members outside the window (median 9 accounts unrestricted, Jaccard 1.0). 3.6 match through a three-account in-window prediction holding both visible members and one other account (Jaccard 0.67). The other 65.6 per seed are unmatched.

**Negative results (Q2, Q6).** Account-level seeding at the shipped seed count (Q2-top3, chosen on validation over Q2-max, 0.514 against 0.465 validation ring-F1) lowers primary-window full-pipeline ring-F1 from 0.589 [0.502, 0.675] to 0.452 [0.377, 0.532]. The paired difference is −0.138 [−0.184, −0.093], p 0.0002 (Holm over a family of one), reading WORSE. Rings touched fall from 129.6 to 108.6 per seed and quiet-member recall from 0.203 to 0.174. Relaxed expansion for groups the shipped pipeline leaves below three accounts (Q6; acceptance probability lowered from 0.7 to 0.5, 0.3 or 0.1, and/or a third hop) lowered validation ring-F1 at every setting (0.593 shipped; 0.493–0.556 relaxed), and validation chose no relaxation on any of the five seeds. The Q6 test arm is identical to the shipped pipeline and was not tested. Score ties did not decide any seed at the 0.1 % budget (Q1: no score equals the cut on any seed in either split), so no tie-breaker was tested.

**Unseeded truth rings, validation against test.** Among rings with an in-window piece of ≥ 3 accounts (97 per window), the number that no seed edge touches and no prediction matches is 1.0 per seed on the validation window (days 6–7, 157 rings) and 11.0 (SD 2.3) on the test primary window (days 8–9, 174 rings), 5 detector seeds. Validation is the window on which the expansion cell and partition cut were chosen.

## Q7 — tie audit of the greedy matcher (read-only on the scorer; CPU)

`evaluation/q7_tie_audit.py`, `tests/test_q7_tie_audit.py` (4 pass). Outputs: `results/tables/q7_tie_audit.csv` (rows) and `q7_tie_audit_pairs.csv` (differences and intervals). Setting: test_visible, τ 0.5, primary window, seeds 1–5. Predictions are restricted to the window exactly as the scorer does it. 200 shuffles of the prediction order (rng 20261115), with the arms of a pair shuffled independently.

**How the shipped scorer orders candidates.** `evaluation/ring_metrics.py:81` sorts candidate pairs by Jaccard descending, then by prediction index ascending (position in the rings file), then by truth id as a string, and consumes them greedily.

**Ties that greedy must break** (truth rings per seed, seeds 1–5): full 5 / 17 / 9 / 10 / 11 (mean 10.4); proposed 2.2; B1b 3.6; B0 2.0; Louvain r0.5 2.6; LPA on expansion 3.4; ring-folded proposed 2.4. Under component: B0 3.2 and Louvain 3.8. Under component_ge3: 0.0 and 0.2.

**Point estimates.** Every row's ring-F1 is identical under all 200 shuffles: min = max, SD 0. Every decision difference is identical too: full − B0 0.0681, full − B1b 0.0342, B0 − Louvain r0.5 0.0062 (component −0.0014, component_ge3 −0.0007), full − LPA on expansion 0.0344, ring-folded − shipped proposed 0.0028. A tie changes *which* truth ring is matched but not *how many*, and ring-F1 depends only on the count.

**Optimal matching** (maximum cardinality at Jaccard ≥ 0.5): equal to greedy for every row except full, 0.5924 against 0.5894 (+0.0030, about 0.5 rings per seed), and in every order, since the shuffle range is 0. It moves full − B0 to 0.0711, full − B1b to 0.0371 and full − LPA to 0.0374.

**Paired intervals under shuffles** (the `--compare` procedure, 10,000 draws, seed 20261114). Ties move intervals only where the arms' tied rings differ:

| difference | shipped-order 95 % interval, p | range over 200 shuffles |
|---|---|---|
| full − B0 | [0.0288, 0.1115], 0.0006 | lo 0.0288–0.0295; hi 0.1112–0.1115; p 0.0006 |
| full − B1b | [−0.0033, 0.0724], 0.074 | lo −0.0033 to −0.0026; hi 0.0714–0.0724; p 0.071–0.074 |
| B0 − Louvain r0.5 | [−0.0002, 0.0140], 0.072 | unchanged |
| B0 − Louvain r0.5, component / component_ge3 | [−0.0108, 0.0066] / [−0.0166, 0.0138] | unchanged |
| full − LPA on expansion | [0.0072, 0.0669], 0.0086 | lo 0.0072–0.0079; hi 0.0656–0.0669; p 0.0078–0.0086 |
| ring-folded − shipped proposed | [−0.0158, 0.0259], 0.84 | unchanged |

**Can the order range change past verdicts?** This is reported only; no verdict and no frozen table is changed.
- **T-P3 bar A** (the B0 / Louvain r0.5 swaps of 0.0015 under component and 0.0007 under component_ge3): **no.** Both differences are fixed under every order (−0.0014 and −0.0007 to 4 dp) and also under optimal matching, so both swaps stand.
- **T-P3 gate** (best baseline below full: full − LPA on expansion 0.0344): **no.** The point is fixed, the optimal gap is 0.0374, and the interval stays above 0 in every order. Bar B (B0 − Louvain p 0.072) is unchanged.
- **T-P2** (interval against the ±0.02 margin): **no.** The point is fixed, and under the `--compare` procedure the interval does not move with order. Separately, and not caused by ties, the registered T-P2 interval [−0.0137, +0.0211] comes from `evaluation/ringfold_report.py`, whose bootstrap resamples truth rings **plus off-ring prediction clusters**, while `--compare` resamples truth rings only and gets [−0.0158, +0.0259]. Under both, the upper end exceeds 0.02, so "equivalence not met" holds either way.
- The Q6 artefact (±0.0043 on identical arms) is this same mechanism.

### Proposed FINDINGS note (for the author to approve; NOT added to docs/FINDINGS.md)

> *Scorer tie audit (2026-11-15, `results/tables/q7_tie_audit*.csv`).* The greedy one-to-one matcher (`evaluation/ring_metrics.py:81`) breaks equal-Jaccard ties by the prediction's position in the rings file. On the primary window such ties involve 2.0–3.6 truth rings per seed for B0, B1b, proposed and the community baselines, and 10.4 for full. Over 200 random prediction orders, no row's ring-F1 and no difference behind a reported decision changes (SD 0). Ties change which ring is matched, not how many. Paired intervals move by at most 0.0013 at either end (full − LPA on expansion), and no verdict changes (T-P3 bar A and gate, T-P2). A maximum-cardinality matching differs from greedy only for full: 0.5924 against 0.5894. The scorer's docstring statement that ties are "rare and the difference is negligible" holds for point estimates. Two identical runs written in different ring orders can still give a non-degenerate paired interval (Q6: ±0.0043 at Δ = 0), so a paired comparison of identical arms should be reported as Δ = 0 without an interval. The registered T-P2 interval and the `--compare` interval for the same pair differ ([−0.0137, +0.0211] against [−0.0158, +0.0259]) because they resample different units (truth rings plus off-ring prediction clusters, against truth rings only). This is not a tie effect.
