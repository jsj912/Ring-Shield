# Generalisation — held-out pattern types (Step 11 / R7)

Two questions, deliberately separated, because they cost three orders of magnitude apart in
compute and only one of them is about the ring layer:

* **L3-only (primary).** The detector is frozen — the shipped `R1_gine_causal` models and their
  cross-scores, trained on everything — and the **ring layer** is retrained with one pattern type
  removed from every ring-label set. Reported as *"detector frozen; the ring layer was never
  trained on this pattern."* ~2 h per pattern.
* **Full (calibration).** Every training entry point holds the pattern out, detector included.
  ~25 h per pattern. Run once, for BIPARTITE, to find out whether the detector half of the
  experiment can say anything at all.

What "held out" means is defined once, in `ringshield/holdout.py`, and asserted by
`tests/test_holdout.py`: the pattern's rings leave every ring-label set a stage trains on, its
edges are relabelled licit in **train and val** (val is a training signal — it chooses every
parameter), and **the test labels, the graph, the candidate pool and the scored-edge tables are
untouched**. Held-out edges are still sampled, still scored, still eligible as expansion
candidates. Only their identity as ring members is withheld.

One consequence worth stating plainly: in the pairs table, pairs touching a held-out ring are
**dropped**, not relabelled. The affinity label is `same ring = (ra > 0) and (ra == rb)`, so
setting a held-out ring's id to −1 would label two edges of the *same* ring as *different* rings —
teaching the model to split the held-out pattern apart, which is worse than not training on it.

---

## Pre-registration — written 2026-09-27, while the BIPARTITE detector was at epoch 25 of seed 1

**No result from the full held-out run existed when this section was written.** It is recorded
here so that the decision it governs reads as a prediction, not as an explanation afterwards.

### The prediction

**The full (detector-inclusive) BIPARTITE holdout will return a detector row inside seed noise.**

The basis is a measurement taken before the run started, not a hunch. Holding out a pattern
removes very little label mass:

| held out | train illicit removed | train rings | val illicit removed |
|---|---|---|---|
| BIPARTITE | **148 of 2,530 (5.9 %)** | 27 of 220 | 49 of 1,036 |
| CYCLE | **122 of 2,530 (4.8 %)** | 36 of 220 | 80 of 1,036 |

A ~5 % change in the positive labels is small against the detector's own seed-to-seed spread:
`R1_gine_causal` test edge F1 per seed is 64.72 / 60.65 / 65.75 / 58.70 / 48.06, **mean 59.57,
SD 7.06**. BIPARTITE is additionally already at ring recall ≈ 0 and quiet-member recall 0.00 for
every method (`FINDINGS.md` B6), so its per-pattern row is near-floor with or without the holdout.

### The decision rule this governs

Let Δ = mean test edge F1 (held-out detector, 5 seeds) − mean test edge F1 (`R1_gine_causal`,
5 seeds), on the primary window.

* **If |Δ| ≤ 7.06 points (one R1 seed SD) and the paired per-seed difference is not significant**,
  the detector half of the holdout is declared uninformative: **the full CYCLE run is not
  performed**, the L3-only variant is the reported generalisation result, and the BIPARTITE full
  run is reported as the calibration that established this — with Δ and its interval stated, not
  suppressed.
* **If |Δ| > 7.06 points**, the detector half *is* informative, the full CYCLE run is performed,
  and this prediction is reported as having failed.

The ~25 h freed by the first branch goes to LI-Small's full pipeline, on the reasoning that a
second dataset is worth more to the report than a second full held-out run.

### What would make this pre-registration wrong rather than merely confirmed

A null here is weak evidence by construction — 5 % of labels is a small intervention, so failing
to detect an effect is close to guaranteed. The honest reading of the confirmed branch is
**"this experiment could not have detected a detector-level effect of the size a 5 % label change
would produce"**, not "the detector does not learn pattern-specific structure". The L3-only
variant is what carries the generalisation claim, and it is not subject to this limitation: it
removes **100 %** of the pattern from the ring layer's supervision.

---

## Result: the BIPARTITE arm is a no-op, and that is the finding

**Holding BIPARTITE out removes zero positive training rows from the expansion policy.** Measured
against the shipped all-patterns training set (`experiments/R3_expansion/training_set.parquet`):

| | all patterns | BIPARTITE held out |
|---|---|---|
| rows | 247,711 | 226,472 |
| **positive rows** | **244** | **244** |
| quiet members reached as candidates | 266 | 266 |
| train-visible rings | 220 | 193 |

Only negatives change (21,239 of them leave). This is the mechanical proof of `FINDINGS.md` B6:
**endpoint-adjacent expansion cannot see BIPARTITE at candidate-generation time.** Its quiet member
edges share no endpoint with any seed of their own ring, so they never enter the candidate pool,
so they never produced a positive row for the policy to learn from. The pattern is invisible to
the policy whether or not it is held out.

So this arm is reported as **a no-op with a mechanism, not as a null**. Its generalisation number
being unchanged is not evidence that the policy transfers to BIPARTITE; it is evidence that
BIPARTITE never reached the policy. Any claim of transfer must come from a pattern the policy can
actually see.

### Which patterns the policy can see

Positive rows of the shipped training set, by the pattern of the ring they belong to:

| pattern | positive rows | share |
|---|---|---|
| SCATTER-GATHER | 66 | 27.0 % |
| GATHER-SCATTER | 48 | 19.7 % |
| **CYCLE** | **36** | **14.8 %** |
| STACK | 35 | 14.3 % |
| FAN-IN | 29 | 11.9 % |
| RANDOM | 16 | 6.6 % |
| FAN-OUT | 14 | 5.7 % |
| **BIPARTITE** | **0** | **0.0 %** |

**The CYCLE arm is therefore informative and the pre-registered reading applies as written.**
Holding CYCLE out removes 36 of 244 positives (14.8 %) -- every positive row the policy had for
that topology -- so its quiet-member recall and added-member precision on CYCLE rings measure real
transfer rather than an absent intervention. This check was run *before* the CYCLE arm's results
existed, precisely so that a weak arm could be declared weak in advance, as BIPARTITE's was.

## Result: the CYCLE arm — the policy recovers a topology it was never taught

CYCLE is the arm that can carry a transfer claim: holding it out removes **36 of 244 positive
policy rows (14.8 %)** — every positive row the policy had for that topology — and the training
set goes 244 → 208 positives. The detector is frozen (`R1_gine_causal`), so everything below is
the ring layer's doing.

Paired bootstrap over the 22 CYCLE truth rings, seeds averaged inside each resample (a paired
difference, not two intervals compared by eye):

| CYCLE rings, `full` | all patterns | CYCLE held out | Δ [95 % CI] | p |
|---|---|---|---|---|
| quiet-member recall | 0.1614 | **0.1344** | +0.0270 [−0.0062, +0.0647] | 0.130 |
| ring recall | 0.3818 | **0.3455** | +0.0364 [−0.0125, +0.0728] | 0.286 |
| **added-member precision** | 0.952 (40/42) | **0.970 (32/33)** | — | — |
| overall ring-F1 (all 174 rings) | 0.5894 | 0.5853 | — | — |

The three policies are also indistinguishable in cross-validation: **0.833 ± 0.043** shipped,
0.826 ± 0.039 with BIPARTITE held out, **0.838 ± 0.031** with CYCLE held out.

**The claim, with its bound in the same breath.** The expansion policy recovers CYCLE members it
was never taught to recover, at undiminished precision (0.970 against 0.952), with no detectable
loss across 22 rings — and the data cannot exclude a loss of up to 6.5 points of quiet recall,
about **40 % in relative terms**. It is a real transfer result and it is not a tight one.

### Why this arm is more informative than its p-values suggest

The two wide intervals are on **recall**, and recall here is measured over 22 rings and ~41 quiet
member edges per seed — that sample size is what limits them, and no amount of care in the
experiment would have narrowed it.

**Added-member precision is not subject to that limit.** It is measured on the **33 edges the
policy actually added** to CYCLE rings, not on the 22 rings, and it is the quantity the mechanism
claim rests on: a policy that had memorised CYCLE's shape and then lost that memory would not keep
adding CYCLE edges at 97 % precision — it would add the wrong edges, and precision would fall
whether or not recall moved. It did not fall. That is direct evidence that what the policy uses to
decide "this edge belongs to that ring" is **conservation, timing and direction** — features that
describe flow and are pattern-agnostic by construction — rather than the ring's topology.

Read the arm as: *recall says "no detectable loss, at a sample size that could hide a moderate
one"; precision says "the mechanism is intact".* Dismissing the arm on the two recall intervals
alone would throw away the half of the evidence that is well powered.

---

## The three arms together

| arm | what was withheld | character | result |
|---|---|---|---|
| **BIPARTITE, L3-only** | 27 rings, **0 of 244 positive policy rows** | a mechanical no-op | Nothing to withhold: endpoint-adjacent expansion never generates a BIPARTITE candidate, so the pattern was already invisible to the policy. Ring recall 0.00 → 0.05, quiet recall 0.000 → 0.000. |
| **BIPARTITE, full (detector too)** | 148 of 2,530 train illicit labels (5.9 %) | an underpowered null | Δ test edge F1 = **+0.0014 points** (0.5967 vs 0.5967), exact paired sign-flip p = 1.0000. Pre-registered as uninformative in advance; the honest reading is that it could not have detected an effect of that size. |
| **CYCLE, L3-only** | 54 rings, **36 of 244 positive policy rows** | the only informative test | Quiet recall 0.161 → 0.134 (CI includes zero), **added-member precision 0.952 → 0.970**. Transfer holds on the well-powered half. |

Each arm's limitation is stated above its result, and each was established before the result
existed: BIPARTITE's zero-positive count from the shipped training set, the detector arm's power
from the label-mass measurement, CYCLE's informativeness from its 14.8 % share.

---

## Pre-registration — LI-Small

**Written 2026-09-27. Honest scope of this timestamp:** the loader finished while this section was
being drafted, so LI-Small's split sizes, base rates and ring counts (quoted below) *were* known.
**No LI-Small score, ring, or metric existed** — nothing downstream of the split parquets had been
run, and the criteria below are about method behaviour, not about the descriptive statistics.

### What the loader gave us

| | HI-Small | LI-Small |
|---|---|---|
| transactions | 5,078,345 | **6,924,049** |
| accounts | 515,088 | **705,907** |
| split days | train [0,6) val [6,8) test [8,17) | **identical** |
| train / val / test edges | 3,248,921 / 965,524 / 863,900 | 4,432,934 / 1,316,442 / 1,174,673 |
| illicit ratio, train / val / test | 0.07 % / 0.11 % / 0.19 % | **0.04 % / 0.06 % / 0.07 %** |
| rings, train / val / test | 220 / 157 / 183 | **75 / 54 / 56** |
| pattern match rate | 107.7 % | 108.8 % (duplicate payments, expected) |

Predictions 1 and 2 are already confirmed by these: the base rate is roughly **half to a third** of
HI-Small's in every split, and there are **about a third as many rings** (56 in-scope test rings
against 183). Prediction 3 — that ring-F1 lands below HI-Small's at frozen hyper-parameters —
remains untested, and follows mechanically if it holds: a rarer positive class at a fixed 0.1 %
seed quantile puts fewer true member edges inside the budget.

### What counts as the pipeline transferring

**Absolute ring-F1 parity is not the criterion and will not be used as one.** Different base rate,
ring count and day structure make absolute numbers incomparable.

The criterion is **within-dataset relative behaviour**:

* **Transfers** if, on LI-Small, `full` ≥ B0 on ring-F1 **and** the quiet-member recall ratio
  (method ÷ B0) stays within the same order of magnitude as HI-Small's ≈ 40× (B0 ≈ 0.005, expanded
  ≈ 0.20). The accepted band is **4× to 400×** — deliberately loose, because this is one run of one
  release and a tighter band would be false precision.
* **Fails** if expansion recovers essentially no quiet members (ratio ≈ 1), or if `full` falls
  *below* B0 on ring-F1. Either would mean the mechanism is specific to HI-Small's density rather
  than to laundering structure.
* **Inconclusive** if too few rings survive scope and `min_size` for a CI to separate anything — and
  with **56 test rings before either filter**, against HI-Small's 183, this branch is a live
  possibility rather than a formality. If it fires, the run is reported as a feasibility and scope
  result only, with the ring count named as the reason and no method claim drawn from it.

### Reporting rule, fixed now

**No single cross-dataset number will be reported.** LI-Small's scope table, ceiling decomposition
and tail behaviour are reported on their own terms. The method comparison is within-dataset (B0 vs
B1b vs proposed vs full), placed side by side with HI-Small's equivalent column, with each dataset's
ring count, base rate and day structure printed in the same table so no figure can be quoted out of
context.

Two carried-over checks, to be stated whatever they show: whether LI-Small's final days collapse to
pattern-dominated traffic as HI-Small's tail does (if so its primary window is defined the same way,
and said so), and whether its cycle features misbehave at the start of the period as HI-Small's
day 0 does.

## Reporting rules fixed in advance

**Typing rows for a held-out type are `N/A`, never `0.00`.** A classifier cannot emit a class it
was never shown, so that cell measures the cost of the omission, not transfer, and a zero invites
the reader to see a failed generalisation where there is only an absent label. The footnote
travels with the table.

**The informative pair for CYCLE is quiet-member recall and added-member precision, not ring-F1.**
CYCLE has non-zero baseline recall, and the expansion policy's conservation and direction feature
groups are pattern-agnostic by construction — they describe flow, not shape. So if CYCLE's
quiet-member recall survives the holdout at comparable added-member precision, that is a positive
transfer claim: *the expansion policy generalises to a topology it was never trained on because it
reasons about flow rather than shape.* If quiet recall collapses while ring-F1 holds up, the
policy was memorising the shape and the claim fails. Both outcomes are reported; the per-pattern
rows are the evidence, with Step 9's bootstrap CIs over truth rings.

**Everything is evaluated on the primary window** (days 8–9, `configs/eval_window.yaml`) with the
Step 9 machinery, and nothing is chosen on the test period.
