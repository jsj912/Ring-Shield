# Chapter — Generalisation

*Draft. Sources: `docs/FINDINGS.md` (C6, C7, B6, B8, B11), `docs/GENERALISATION.md`,
`results/tables/r6_detector_swap.csv`, `results/tables/r7_heldout.csv`. The LI-Small section is a
placeholder until that run lands; nothing above it depends on the outcome.*

A ring-detection layer that only works with the detector, the pattern types and the dataset it was
fitted on is a curve-fit, not a method. This chapter asks three separate questions, each with its
own failure mode, and reports each one's limitation before its result.

1. Does the ring layer depend on **which detector** feeds it?
2. Does it recover a **pattern type it was never trained on**?
3. Does it survive a **different dataset**?

---

## 1. Detector-agnosticism

We replaced our Multi-GINe detector with **MEGA-GNN** (Bilgi et al., arXiv:2412.00241), published
code driven unmodified through an adapter, trained under our causal sampler on the same split, and
with a third detector — GFP-XGBoost on trailing graph-pattern features — as a weaker control. Every
downstream parameter was re-chosen on validation per detector per seed.

MEGA-GNN reaches **0.6893 ± 0.0396** test edge F1, against the **0.7083 ± 0.0218** its authors
report for the same configuration on this dataset; the 1.9-point gap is attributable to causal
neighbourhood sampling, which their published setup does not use. Our own detector reaches
0.5957 ± 0.0696, and GFP-XGBoost 0.4996 ± 0.0062.

**The ring layer does not notice.**

| detector | edge F1 | B0 ring-F1 | `full` ring-F1 |
|---|---|---|---|
| Multi-GINe (ours) | 0.5957 | 0.5213 [0.429, 0.607] | 0.5894 [0.502, 0.675] |
| MEGA-GNN | **0.6893** | 0.5208 [0.432, 0.609] | 0.6074 [0.522, 0.688] |
| GFP-XGBoost | 0.4996 | 0.3435 [0.259, 0.426] | 0.4508 [0.376, 0.526] |

A **9.4-point edge-F1 gain produces a 0.0005 ring-F1 change** at the B0 operating point, and no
pairwise difference between the two GNN detectors is significant after correction. Every seed of
both detectors independently selected the same operating point on validation.

The obvious objection — that the two detectors are simply making the same predictions — is wrong,
and the diagnostic that rules it out was specified before the table was built. Their **seed sets
overlap at Jaccard 0.415**: fewer than half the chosen edges coincide. What coincides is the
*number of truth rings a 0.1 % budget can reach* — **128.8 against 129.6** of 174 — and the
distribution of seeds across those rings (Gini 0.384 vs 0.395). Different edges, same reach, same
result: **the seed budget is the binding constraint, not the quality of the ranking that fills
it.**

This is a ceiling rather than independence. GFP-XGBoost, 9.6 edge points *below* ours, loses 17.7
ring points — ranking quality still matters on the way down. Above our operating point it stops
buying rings.

### What the ceiling is made of, and what it is not

The unreached rings are **not** mostly unreachable. Each detector touches about 74 % of
primary-window truth rings, but their touched sets overlap at only 71.5 %, so their misses are
partly complementary: **their union reaches 150.8 of 174 (86.7 %)**. Roughly half the gap one
detector leaves at a 0.1 % budget is closed by another detector at the same budget. The ceiling
belongs to *a single global quantile*, not to the rings — which points at ensembled seed sets or a
per-ring budget as the next step. We report this as a measured upper bound, not as a method: it was
computed post hoc and no such system was run end to end.

A second consequence is that a limitations chapter has to say **which detector** it is quoting.
"19 % of primary-window rings are untouched by any detector edge" is our detector's number
(33.2 of 174); MEGA-GNN leaves **24.0**. Of the 9.2 rings it newly reaches, **6.4 (70 %) become
matches** — reach does convert. The residual that does not convert is concentrated in
over-merging, which grows 5.2 → 8.2 while under-coverage stays flat (6.8 → 6.6): a stronger
detector fuses rings with their neighbours rather than covering more of them partially. That is a
partition problem, and it is the subject of a separate pre-registered test.

---

## 2. Held-out pattern types

The second question is whether the ring layer has learned *laundering structure* or merely the
seven shapes in its training labels. We removed one pattern type from every ring-label set the
layer trains on — its rings' edges relabelled licit in train **and** validation, since validation
chooses every parameter — while leaving the graph, the candidate pool and the test labels
untouched. Held-out edges are still sampled, still scored, still eligible for expansion; only
their identity as ring members is withheld.

Three arms, with three different characters. Each arm's limitation was established *before* its
result existed.

### BIPARTITE (ring layer only) — a mechanical no-op

Holding BIPARTITE out removes **zero of the 244 positive training rows** the expansion policy
learns from. Only negatives change. This is the mechanical face of a structural fact: BIPARTITE's
quiet member edges share no endpoint with any seed of their own ring, so they never enter the
candidate pool and never produced a positive row to begin with. The pattern is invisible to the
policy whether or not it is held out, and its unchanged generalisation number is **not** evidence
of transfer. We report the arm as a no-op with a mechanism.

### BIPARTITE (detector included) — an underpowered null, declared in advance

Retraining the detector itself with BIPARTITE held out changes **148 of 2,530 train illicit labels
(5.9 %)**. Before that run started we recorded the prediction that it would return a result inside
seed noise, the decision rule that would follow, and the reason a confirmed null would be weak.

The outcome: test edge F1 **0.5967 held out against 0.5967 all-patterns**, Δ = **+0.0014 points**,
exact paired sign-flip p = 1.0000. The pre-registered reading stands: this experiment **could not
have detected a detector-level effect of the size a 5 % label change produces**. It is not evidence
that the detector ignores pattern structure. The compute it freed was reallocated to the second
dataset, as the pre-registration specified.

### CYCLE (ring layer only) — the informative arm

CYCLE is the only held-out type that removes real supervision: **36 of 244 positive rows (14.8 %)**
— every positive the policy had for that topology. Paired bootstrap over the 22 CYCLE truth rings:

| CYCLE rings | all patterns | CYCLE held out | Δ [95 % CI] | p |
|---|---|---|---|---|
| quiet-member recall | 0.1614 | 0.1344 | +0.0270 [−0.0062, +0.0647] | 0.130 |
| ring recall | 0.3818 | 0.3455 | +0.0364 [−0.0125, +0.0728] | 0.286 |
| **added-member precision** | 0.952 (40/42) | **0.970 (32/33)** | — | — |

**The expansion policy recovers CYCLE members it was never taught to recover, at undiminished
precision (0.970 against 0.952), with no detectable loss across 22 rings — and the data cannot
exclude a loss of up to 6.5 points of quiet recall, about 40 % in relative terms.** It is a real
transfer result and it is not a tight one.

The two recall intervals are wide because recall here is measured over 22 rings and ~41 quiet
member edges per seed, and no care in the experiment would have narrowed that. **Added-member
precision is not subject to the same limit**: it is measured on the **33 edges the policy actually
added**, and it is what the mechanism claim rests on. A policy that had memorised CYCLE's shape and
then lost that memory would not keep adding CYCLE edges at 97 % precision — it would add the wrong
edges, and precision would fall whether or not recall moved. It did not fall. What the policy uses
to decide that an edge belongs to a ring is **conservation, timing and direction** — properties of
flow, pattern-agnostic by construction — rather than the ring's shape.

A reader who dismisses this arm on its two recall p-values discards the half of the evidence that
is well powered.

---

## 3. A second dataset — reported in the evaluation chapter, not here

LI-Small was regenerated end to end and **is not presented as a generalisation result**. Its
primary window yields 38 matchable rings against HI-Small's 114, which cannot separate any method
from any other at the effect sizes this pipeline produces, and that limit was fixed as a stopping
rule before the count was known.

What it does establish is about the *dataset family*, not about our method: the preprocessing and
evaluation path runs unchanged on a second release, and the day-split tail pathology reproduces in
both variants. Both belong to the evaluation-protocol chapter and are reported there. Filing them
here would stretch evidence about AMLworld into a claim about RingShield.

## What this chapter does and does not establish

**Established.** The ring layer's output is insensitive to a 9.4-point improvement in the detector
that feeds it, because the seed budget binds first. The expansion policy recovers a topology it was
never trained on, at undiminished precision. The untouched-ring ceiling is a property of a single
global seed budget, not of the rings, and is roughly halved by combining two detectors' seed sets.

**Not established.** That the detector learns nothing pattern-specific — the experiment that would
show this was underpowered by construction and we say so. That transfer to unseen topologies holds
at a tight bound — the interval admits a 40 % relative loss. That the method transfers to a second
dataset: LI-Small runs, but at 38 matchable rings it cannot answer the question, and we decline to
answer it rather than answering it badly. Nothing here establishes anything beyond the AMLworld
generator at all.
