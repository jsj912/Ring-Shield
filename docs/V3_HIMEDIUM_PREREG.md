# HI-Medium run — pre-registration

**Written 2026-09-30, before any model is trained on HI-Medium.** At the time of writing the
split is preprocessed (`data/processed_hi_medium/`), its GFP features were finished on
2026-10-01 under V3.2b, and
**no detector, expansion policy, affinity model or aggregator has been fitted on this release**.
Nothing below was chosen after seeing a result.

The split, and how it was chosen, are in `docs/V3_OBSERVABILITY.md` (V3.2 section): **train days
0–3, val days 4–5, test days 6–15** (primary), tail days 16–27, selected by a rule fixed before
the train/val counts were taken. Day 0 is the warm-up, kept in train and excluded from
evaluation, exactly as HI-Small does.

## The reference numbers this is measured against

HI-Small, shipped `full` / `average` runs, 5 seeds, primary window (days 8–9), `test_visible`:

| quantity | HI-Small | source |
|---|---|---|
| in-scope truth rings | 174 | `r4_partition.csv` |
| share with ≥ 3 visible members | 0.6552 (114/174) — a comparator, **not a bound** | `v3_bound_ge2.csv` |
| **(a) ring recall** | **0.4609** [0.3931, 0.5287] | `r4_partition.csv`, `average` |
| **(b) `Ring-Recall≥3`** | **0.6035** [0.5218, 0.6857] | `r4_partition.csv`, `average` |
| ~~recall efficiency = recall ÷ share≥3~~ | ~~0.7035~~ — **void, see Amendment 1** | — |
| class (b) untouched, share of truth rings | **19.08 %** (33.2/174) | `FINDINGS` B8 |
| under-covered, share of truth rings | **3.91 %** (6.8/174) | `FINDINGS` B12 |

HI-Medium, primary window (days 6–15), measured in V3.2 step 4 and **fixed before training**:

| quantity | HI-Medium |
|---|---|
| in-scope truth rings | **2,361** (13.6× HI-Small) |
| share with ≥ 3 visible members | **0.6993** |
| rings fully contained in the window | 1,042 — **44.1 %** (HI-Small: 11.5 %) |
| median visible members | 5 (HI-Small: 4) |

## Why the criterion is same-dataset quantities and class shares, never absolute ring-F1

`FINDINGS` **C9** measured that the scope convention alone moves ring-F1 by **0.347 to 0.383**,
about five times the largest method effect in the project (expansion's +0.068). Two releases with
different ring-size distributions, different containment and a different share of two-account
rings are at least that far apart for reasons that have nothing to do with method quality. An
HI-Medium ring-F1 placed next to HI-Small's would be a comparison of generators.

So every prediction below is stated either as a **recall against that dataset's own truth-ring
denominator** or as a **share of that dataset's own truth rings**. (Amendment 1 removed the one
prediction that was a ratio to a supposed ceiling; the ceiling was not one.) Absolute ring-F1
will be reported for the record and **will not be compared across datasets**, in either
direction, whatever it says.

## Amendment 1 — 2026-09-30, V3.2b: P1 replaced

**Recorded before any model is trained on HI-Medium.** No HI-Medium result exists; nothing below
was adjusted to fit an observed number.

**Reason.** P1 as originally written compared `efficiency = ring_recall ÷ share_ge3` across
datasets, on the understanding that `share_ge3` was the largest recall reachable under
`min_size` 3. **It is not a bound.** `min_size` constrains the *unrestricted* prediction, while
matching uses the *window-restricted* one, which can be smaller: 13 of 106 restricted predictions
per seed fall below 3 members, and 11.4 of HI-Small's 80.2 matched rings per seed have fewer than
3 visible members — one with a single member, matched at Jaccard 1.0. A ratio to a non-bound can
exceed 1 and does not mean what the original P1 said it meant. `FINDINGS` B9 is retracted and B7
corrected on the same date; see `docs/V3_OBSERVABILITY.md`.

**The original P1 is void and is not to be evaluated.** It is replaced by two plain quantities,
both already computed on every shipped run, neither of which is a ratio to anything:

## P1 — both primary-window recalls are higher on HI-Medium

**Prediction.** On the primary window, the shipped pipeline re-fitted on HI-Medium reaches

* **(a) full-denominator ring recall > 0.4609** — matched rings ÷ *all* in-scope truth rings; and
* **(b) `Ring-Recall≥3` > 0.6035** — matched rings with ≥ 3 visible members ÷ in-scope rings with
  ≥ 3 visible members.

HI-Small references, shipped `full`/`average`, 5 seeds, primary window, from
`results/tables/r4_partition.csv`:

| | HI-Small value | 95 % CI |
|---|---|---|
| (a) ring recall | **0.4609** | [0.3931, 0.5287] |
| (b) `Ring-Recall≥3` | **0.6035** | [0.5218, 0.6857] |

(The val-chosen `proposed` row is 0.4598 / 0.6053 and is reported beside it; if the two disagree
about whether a bar is cleared, that is reported and P1 is recorded as failed.)

**P1 passes only if both (a) and (b) clear their HI-Small value.** If they split, that is
reported as a split and P1 fails. The two are reported with the same bootstrap CIs as HI-Small's,
and the CIs are reported whether or not they overlap — clearing a point estimate is the
pre-registered bar, and CI overlap is context, not a second bar moved in afterwards.

**Mechanism.** 44.1 % of HI-Medium's in-scope rings are fully contained in the test window
against HI-Small's 11.5 %. B13 attributed 81.5 % of the under-covered residual to rings arriving
as disconnected pieces because the window cuts them; V3.0b (c1) showed 98.6 % of the class-(b)
discard is a lone seed edge whose component never reaches `min_size`. Both are truncation
effects, and truncation is what containment measures.

**What falsifies it.** Either quantity at or below its HI-Small value. That would say HI-Small's
recall was not truncation-limited after all, and that the V3.0/V3.0b diagnosis was measuring
something else.

**Not predicted:** precision, F1, or that HI-Medium is "better". In particular **(a) and (b) are
not comparable to each other** and no claim is made about the gap between them; HI-Medium's
share of rings with ≥ 3 visible members (0.699) differs from HI-Small's (0.655), which moves (b)'s
denominator but not (a)'s.

## P2 — the under-covered and class-(b) shares of truth rings fall

**Prediction.** On the primary window, as a share of that dataset's in-scope truth rings:

* class (b) untouched **< 19.08 %**, and
* under-covered **< 3.91 %**.

**P2 passes only if both fall.** Counts per seed will be reported alongside the shares; the
shares are the claim, because HI-Medium has 13.6× the rings and the counts are not comparable.

**Mechanism.** The same one as P1, seen through `evaluation/unmatched_rings.py`'s classes. Both
classes are populated by rings the window fragments.

**What falsifies it.** Either share at or above HI-Small's. A particularly informative failure
would be class (b) falling while under-covered rises, which would mean the extra rings are being
*reached* but not *completed* — a policy problem rather than an observability one.

**Not predicted:** the pattern composition of either class, or whether STACK and BIPARTITE stay
over-represented in class (b) (`CLASS_B_COMPOSITION`).

## P3 — two comparisons that are currently unresolvable become resolvable

At 174 rings, two of the project's headline comparisons cannot be called
(`r4_pvalues.csv`, `r3_pvalues.csv`, paired over truth rings, Holm-adjusted):

| comparison | mean Δ | 95 % CI | p (Holm) | rings differing |
|---|---|---|---|---|
| `full` (average) vs `b2` | +0.0149 | [−0.0023, +0.0356] | 0.493 | 10 |
| `proposed` (policy) vs `b1b` | −0.0172 | [−0.0414, +0.0046] | 0.493 | 32 |
| `full` (average) vs `b1b` | −0.0023 | [−0.0322, +0.0276] | 0.945 | 40 |

**Prediction.** With 2,361 rings instead of 174 — a **13.6×** increase, so a bootstrap CI on a
paired per-ring delta narrows by about **√13.6 ≈ 3.7×** — **at least one of `full` vs `b2` and
`policy` vs `b1b` is resolved** on HI-Medium's primary window.

**"Resolved" means**, fixed now: the Holm-adjusted paired test rejects at 0.05, **or** the
bootstrap CI on the mean per-ring delta excludes 0. Same test, same 1,000 resamples, same
`evaluation/ring_stats.py`.

**No direction is predicted, for either comparison.** If `b2` beats `full`, that is a resolution
and P3 passes. The whole point is that the question becomes answerable; which way it answers is
not something this step claims to know.

**What falsifies it.** Both comparisons still straddling zero with Holm p > 0.05. That would mean
the effects are smaller than the CI shrink, i.e. genuinely near-zero rather than merely
unmeasured — itself a publishable result about the partition and policy stages.

## Everything is re-chosen on HI-Medium validation

No HI-Small parameter is carried over. Re-chosen on **days 4–5** (773 in-scope val rings, 480 with
≥ 3 visible members), never on test:

| parameter | HI-Small value, not to be assumed |
|---|---|
| seed budget `seed_frac_pct` | 0.1 % |
| `min_size` | 3 |
| expansion Δt | 24 h |
| expansion floor `p_min` | 0.7 |
| partition method | `average` |
| partition cut | 0.5 |
| detector threshold / calibration | isotonic, val-fit |

The **expansion policy** (LightGBM) and the **affinity model** must both be **retrained on
HI-Medium train-split pairs**. Reusing the HI-Small-fitted ones would import that release's
structure into the comparison and is not permitted.

Two of these are worth flagging as likely to move, so that moving them is not read as a result:
the seed budget (0.1 % of 18.9 M test edges is 18,894 seeds against HI-Small's 864, a different
operating regime) and `min_size` (28 % of every ring population is a two-account object —
`V3_OBSERVABILITY` — so the 3-account bar is a live convention question, and if it is changed the
change applies to the HI-Small re-analysis too or the comparison is void).

## Amendment 2 — 2026-10-01, V3.3a: seed count fixed by runtime

**Recorded before the HI-Medium detector is trained.** No seed-1 run has started.

> **If seed 1's wall time exceeds 14 h, run 3 seeds; otherwise 5. Decided on runtime only.**

Nothing about the seed count is decided on any metric, on either split. The rule is written here
so that a slow first seed cannot later be used to justify a smaller — or a faster one a larger —
sample after the numbers are visible. Whichever branch fires is reported with the measured wall
time beside it, and every CI and paired test in 3e uses whatever count the rule selects.

## Amendment 3 — 2026-10-01 16:58, V3.3a: "wall time" means training wall time

**Recorded while seed 1 is still training** (epoch 5 of up to 100 at the time of writing; no
best epoch, no final val F1 and no total wall time exist yet, so the rule's outcome is not
knowable from anything on disk).

**"Wall time" in Amendment 2 means TRAINING wall time** — from the start of the first epoch to
the end of training — **excluding preprocessing.**

**Reason.** Preprocessing (loading, GFP join, ports/time-deltas, HeteroData conversion) took
82 minutes on seed 1 and is identical for every seed: it depends on the split and the data, not
on the seed. It is being cached (V3.3 item 3), so from seed 2 it costs approximately nothing.
The quantity the rule is budgeting is the **per-seed marginal cost**, and that is training time.
Counting an 82-minute one-off against every seed would overstate the marginal cost by the same
fixed amount three or five times over.

This changes where the threshold bites: at the measured 25.6 min/epoch, 14 h of *training* is
**32.8 epochs**, against 29.6 epochs under the original reading. The direction of the change was
not known when this amendment was written — seed 1 had completed 5 epochs with val F1 still
rising (0.0475 → 0.2766), so whether it would stop above or below either threshold was open.

Both figures are reported when seed 1 stops: training wall time (which decides) and total wall
time including preprocessing (for the record).

## Amendment 4 — 2026-10-02 10:26, V3.3: detector adequacy, P4, and a P2 note

### Disclosure first: this is NOT a clean pre-registration

**Seed 1 had already finished when this amendment was written.** It early-stopped at epoch 31
with best val F1 0.3782 at epoch 11, and that was visible in the run log before this text
existed. Specifically, the following were already seen:

| epoch | 1 | 5 | 10 | 15 | 20 | 25 | 30 |
|---|---|---|---|---|---|---|---|
| val AP | 0.0259 | 0.2401 | **0.3000** | 0.0073 | 0.1093 | 0.0172 | 0.0020 |

The trainer prints every fifth epoch, so **the best-checkpoint epoch is 11 and its val AP had
not been read** when this was written — the criterion below was fixed before that specific
number was looked at. But the surrounding values were known, and the highest printed val AP is
**0.3000**, already below the 0.45 bar. **A reader should assume the adequacy criterion was
expected to fail when it was written.** It is recorded anyway because the *interpretation rule*
is still worth fixing in advance of the ring-layer work, and because a rule written with the
outcome half-visible is better than one written after it, provided the fact is stated. It is
stated.

### 1. Detector adequacy gate

At seed 1's end, compare the **best-checkpoint val AP** on HI-Medium with HI-Small R1 seed 1's
**0.5726** (verified: `training_log_seed1.csv`, epoch 30, the best-val-F1 checkpoint).

* **HI-Medium val AP ≥ 0.45** → **P1 stands** as written.
* **HI-Medium val AP < 0.45** → **P1 is pre-declared confounded by detector strength.** It is
  still computed and reported, but **not interpreted as a test of containment**, in either
  direction. A P1 pass under a weak detector would not be evidence for containment, and a P1
  failure would not be evidence against it.

**Reason.** The split-selection rule in `docs/V3_OBSERVABILITY.md` had **no criterion for
detector-training adequacy** — it was chosen entirely on ring observability (train/val ring
counts, test containment) and never asked whether the resulting train split would train a
comparable detector. `FINDINGS` **C6** shows ring recall falls steeply with a weaker detector,
so a detector gap propagates directly into P1's quantities and is indistinguishable from the
containment effect P1 is meant to isolate.

**3b–3e proceed either way.** The gate changes interpretation, not execution.

### 2. P4 — matched-seed containment test (registered, not built)

A controlled diagnostic that removes the detector from the comparison entirely, by handing both
datasets a seed set of **identical quality** and measuring only what the ring layer does with it.

**Construction**, identical on both datasets, on the primary window:

1. sample illicit edges uniformly at **recall 0.28**;
2. add licit edges sampled uniformly from licit edges **incident to at least one account of an
   illicit edge**, until **precision 0.93**;
3. **10 draws** per dataset.

Run **B0** and **`full`** with **each dataset's own val-chosen L3 parameters**, swapping only the
seed set — nothing else differs.

**Reported:** ring recall, Ring-Recall≥3 and the **under-covered share**, each with a CI over the
10 draws.

**Prediction: HI-Medium higher than HI-Small on all three.**

**Labelling, mandatory and everywhere it appears:** this is a **controlled diagnostic with
label-derived seeds**. The seeds are built from the ground truth. It is **never** a detector
result, never a headline ring-F1, and never comparable to any number produced by a real
detector on either dataset.

**Not built and not run.** Registered here only.

#### Mandatory caveat on every P4 number — added 2026-10-06 13:05, before the `full` arm runs

**P4's synthetic seeds are 0.93 precise. HI-Medium's real training seeds are 0.29 precise.**
Measured, not assumed: the per-fold 0.1 % cut of the C1' cross-scores selects 4,682 seeds at
**precision 0.2903 and recall 0.3195** (`results/tables/v33_a8_training_sets.csv`). P4 hands the
ring layer a seed set more than **three times** as pure as the one the real pipeline produces, at
roughly the same recall (0.28 registered against 0.3195 realised).

**So P4 measures containment at matched, HI-Small-quality seeds. It does not forecast the real
pipeline on either dataset, and no P4 number may be quoted as an estimate of one.** The
quantity P4 isolates is *what the ring layer does with a fixed-quality seed set* — which is
exactly why it can compare two datasets whose detectors differ. That is also the limit of what it
can say.

**This sentence, or one with the same content, appears next to every P4 table and every P4 number
in any document, including the pooled and the Amendment 9 stratified views.**

*(The precision figure was corrected the same day: an earlier computation using a **global**
rather than per-fold seed cut gave 0.2519. The per-fold rule is the one the pipeline applies, so
0.29 is the number that belongs beside P4's 0.93 — see the Amendment 8 report's correction note.)*

### 3. P2 note — which metric carries the claim

In P2, the **under-covered share is the primary containment metric**. The **class (b) share is
reported but marked detector-dependent**: B8 already established that class (b) is a property of
the detector at a budget, not of the data — swapping the detector moves it 33.2 → 24.0 on
HI-Small alone. A change in class (b) between datasets therefore cannot be attributed to
containment without the detector being matched, which is exactly what P4 does and P2 does not.

P2's pass/fail is unchanged: **both** shares must fall. The note governs interpretation, not the
criterion.

## Amendment 5 — 2026-10-02 11:09, V3.3: how the C1 seed-1 gate value is obtained

**Recorded before the stuck seed-1 process is stopped**, i.e. before the gate value exists in any
form that can be read.

**State at the time of writing.** C1 seed 1 finished *training* (early stop at epoch 31, best val
F1 0.3782 at epoch 11) and then entered the post-training test evaluation over the 18,893,741-edge
test split. It has been in that call for **7.6 hours** (last log write 03:30:07, now 11:09), alive
and consuming ~4 cores, with no progress output. `training_log_seed1.csv` and
`metrics_seed1.json` are written **after** that call returns, so **the per-epoch val AP series is
held only in memory and is destroyed when the process is stopped.** The best-checkpoint val AP —
the exact quantity Amendment 4's gate is defined on — is therefore not recoverable from the
trainer.

**Definition.** The Amendment 4 gate value for C1 seed 1 is **val AP computed by
`models/score.py` on `model_best_seed1.pt`**, scoring the val split with the run's own
configuration (causal, `window_s` 1800, same adaptations, same `split_days`). That checkpoint is
on disk, written at 19:03:45 when epoch 11 improved val F1, so it *is* the best checkpoint; the
only thing lost is the trainer's own record of its AP.

This is a re-measurement of the same model on the same data, not a different quantity. It may
differ from the trainer's value in the last decimal places: scoring runs a fresh causal loader
whose neighbour sampling is nondeterministic run to run (measured in V3.3 item 3: one-epoch loss
sd ~0.013 over repeated identical runs). **The gate is 0.45 against a reference of 0.5726 and the
bracketing epochs are 0.3000 and 0.0073, so no plausible sampling difference decides it.** If the
value lands within 0.02 of 0.45, that is reported as indeterminate rather than resolved.

### Verdict — recorded 2026-10-02 12:58

**C1 seed 1 best-checkpoint val AP = 0.3073. The adequacy gate FAILS (0.3073 < 0.45).**

Computed as defined: `models/score.py` on `model_best_seed1.pt`, HI-Medium val split, causal
loader, `window_s` 1800, run config as reconstructed — 3,857,689 rows, 0 NaN, 3,904 illicit
(base rate 0.1012 %).

| | value |
|---|---|
| **C1 seed 1 val AP** | **0.3073** |
| HI-Small R1 seed 1 val AP (epoch 30) | 0.5726 |
| gate | 0.45 |
| indeterminate band (within 0.02) | no — 0.143 below the gate |
| AP / base-rate lift | 304× |

**Two independent corroborations that this is the right checkpoint, faithfully re-measured:**
the trainer printed val AP **0.3000** at epoch 10 (epoch 11 is the best checkpoint, unprinted),
and re-scoring gives val F1 **0.3800** at the trainer's tuned threshold 0.56 against the
trainer's own **0.3802**. The 0.0002 difference is the loader's sampling nondeterminism.

**Consequence, as pre-registered in Amendment 4: P1 is confounded by detector strength for the
C1 arm.** It is computed and reported for C1, but **not interpreted as a test of containment**
in either direction. P2, P3 and P4 are unaffected. 3b–3e proceed.

## Amendment 6 — 2026-10-02 11:27, V3.3: C1' registered, before training

**Recorded before any C1' training run starts.** No C1' model, score or ring result exists.

### The arm

**C1'** is C1 with one change: **day-0 edges are excluded from the detector's training labels
while remaining in the message-passing graph as causal history.**

| | C1 | **C1'** |
|---|---|---|
| split | train 0–3 / val 4–5 / test 6–27 | **identical** |
| primary window | days 6–15 | **identical** |
| supervised training edges | days 0–3, 9,146,808 | **days 1–3, 4,680,823** |
| train base rate | 0.0580 % | **0.0909 %** |
| day 0 in the sampled graph | yes | **yes** — history, features, neighbours, just not supervised |
| cross-scoring folds | held-out days 1, 2, 3 (day 0 never held out) | **held-out days 1, 2, 3** |

Implemented as `models/tgn.py --train-label-days 1 3`. The flag restricts the *training seed
edges* only; `tr_data` keeps every train edge, so day 0 still contributes message passing, ports,
time deltas and GFP context. `tests/test_train_label_days.py` asserts both halves separately —
day-0 edges **absent** from `tr_inds` and **present** in `tr_data.edge_index`, with labels
unaltered and val/test untouched.

### Reason

Day 0 is **48.8 % of C1's training edges at a 0.0236 % laundering base rate, ~0.27× the
0.0909 % of days 1–3** (`FINDINGS` C8; measured on both releases — HI-Small's day 0 is 34.3 % of
train at the same 0.27× ratio). C1's training set is therefore half warm-up, and its train base
rate (0.0580 %) falls **below HI-Small's** (0.0779 %) even though HI-Medium has 2.8× the edges.
**C1 seed 1's detector failed the Amendment 4 adequacy gate** (best val F1 0.3782 against
HI-Small's 0.6044). The split rule in `docs/V3_OBSERVABILITY.md` optimised ring observability and
contained no detector-training-adequacy criterion; C1' tests whether that omission, rather than
the data, produced the weak detector.

C1' trades training volume for label density: 4.68 M supervised edges at 0.0909 % against 9.15 M
at 0.0580 % — **4,253 illicit training edges against 5,309**. Whether that is a better trade is
the question, and **no direction is predicted**.

### Rules that carry over

* **Amendment 2/3 seed-count rule** re-applied to **C1' seed 1**: training wall time (first epoch
  to end of training, excluding preprocessing) > 14 h → 3 seeds, else 5.
* **Amendment 4 adequacy gate** re-applied to C1' seed 1: best-checkpoint val AP ≥ 0.45 → P1
  stands for C1'; < 0.45 → P1 reported but not interpreted as a containment test.
* **P1, P2, P3 and P4 carry over unchanged.** Same definitions, same HI-Small references, same
  criteria.
* **C1 seed 1 remains a reported arm.** It is not deleted, retracted or replaced. Both arms are
  reported side by side, and the comparison between them is itself informative about how much of
  the detector gap is the warm-up day.

### What is not claimed

C1' is **not** a tuned alternative. One flag changes, chosen on a documented property of the data
(C8) and a failed gate, not on any C1' or HI-Medium result. Nothing about its hyperparameters,
split, window or L3 grid differs from C1. If C1' also fails the gate, that is reported and the
detector gap is **not** attributable to the warm-up day.

## C1' seed 1 — result, seed count and gate verdict (recorded 2026-10-03 09:45)

Trained with `--train-label-days 1 3 --skip-final-test --feature-cache`, everything else
identical to C1.

| | C1 | **C1'** |
|---|---|---|
| supervised train edges | 9,146,808 @ 0.0580 % | **4,680,823 @ 0.0909 %** |
| illicit train edges | 5,309 | 4,253 |
| epochs run / early stop | 31 | **43** |
| best epoch | 11 | **23** |
| **best val F1** | 0.3782 | **0.4985** |
| mean epoch time | 1,520 s (25.3 min) | **1,665 s (27.7 min)** |
| **training wall time** | ~13.2 h | **19.88 h** (71,581 s) |
| **best-checkpoint val AP** (`score.py`) | **0.3073** | **0.4495** |
| AP / base-rate lift | 304× | **444×** |
| val F1 at tuned threshold (re-scored) | 0.3800 @ 0.56 | 0.4981 @ 0.50 |

HI-Small R1 seed 1 reference: best val F1 **0.6044**, val AP **0.5726**.

### Seed count — Amendment 2/3 rule

**C1' training wall time 19.88 h > 14 h → 3 seeds.** (C1's 13.2 h selected 5.) The two arms
therefore run at different seed counts, which is what the rule dictates; every CI and paired test
in 3e uses each arm's own count. Epoch time *rose* despite halving the supervised edges — the
graph the sampler walks is unchanged, so the saving is smaller than the label reduction suggests,
and C1' simply ran 12 more epochs before stopping.

### Adequacy gate — Amendment 4/5

**C1' best-checkpoint val AP = 0.4495. Gate = 0.45. |AP − 0.45| = 0.0005.**

**VERDICT: INDETERMINATE**, per Amendment 5's pre-registered band ("if the value lands within
0.02 of 0.45, that is reported as indeterminate rather than resolved"). The trainer's own
in-memory value at epoch 23 was **0.449956** — 0.000044 below the gate — so both measurements
agree and both sit essentially *on* the threshold. Nothing about this is a near-miss that further
measurement would resolve: the loader's sampling nondeterminism alone is larger than the margin.

**Consequence.** P1 is **not** interpreted as a containment test on the C1' arm either, because
the gate did not clear. It is computed and reported for both arms. **P4 is therefore the
load-bearing containment test**, as Amendment 4 anticipated, and P2's under-covered share remains
the primary observational metric.

### What the C1 → C1' comparison does establish

Excluding day 0 from supervision while keeping it as graph history moved the detector
substantially: **val AP 0.3073 → 0.4495 (+46 %), best val F1 0.3782 → 0.4985 (+32 %)**, on
*fewer* supervised edges (4.68 M vs 9.15 M). That is direct evidence that **C1's weak detector was
caused by the warm-up day diluting its training labels**, not by HI-Medium being intrinsically
harder — which is exactly what Amendment 6 registered the arm to test, and the direction was not
predicted.

It still does not reach HI-Small's 0.5726. The remaining gap is unexplained and is **not**
attributed here.

## Amendment 7 — 2026-10-03 18:23, V3.3: the ring layer is built on C1' only

**Recorded before any ring-layer component is trained.** No cross-scoring fold, policy, affinity
or typing model exists for either arm.

**Decision: 3b–3e run on C1' only, at 3 seeds** (the count its 19.88 h training wall selected
under Amendment 2/3). **No ring layer is built on C1.**

**C1 seed 1 remains a reported arm at the detector level**, with its gate failure stated: best
val F1 0.3782, best-checkpoint val AP **0.3073**, **gate FAIL** against 0.45. It is not deleted
and not retracted; it is the measurement that motivated C1' and it is reported as such.

**Reason.** C1's detector failed the adequacy gate by a wide margin (0.3073, 0.143 below). Under
Amendment 4 its P1 would be uninterpretable anyway, so a ring layer built on it would produce
ring numbers whose every difference from HI-Small is confounded by a detector that is known to be
weak — at roughly 60 GPU-hours (3–5 seeds of cross-scoring and ring training) for a result no
one could read. C1' is the arm registered in Amendment 6 precisely to remove that confound, and
it moved val AP to 0.4495.

**This narrows what the HI-Medium work can claim.** With no ring layer on C1 there is no
within-dataset contrast between a weak and a strong detector on the same split, so the C1 → C1'
detector improvement cannot be traced through to ring-level consequences. That contrast is not
available and is not claimed. C1' is still gate-indeterminate (0.4495 vs 0.45), so **P1 remains
uninterpreted as a containment test and P4 remains the load-bearing one**.

## Amendment 8 — 2026-10-03 18:28, V3.3c: the cross-scoring rule, before any fold runs

**Recorded before a single fold model is trained.** No fold checkpoint, score or ring-layer
training set exists.

Cross-scoring produces out-of-fold scores for the **training** split, which are what the
expansion policy, the affinity model and the typing head are fitted on. A fold model must
therefore never have been supervised on the day it scores.

### The rule

| | |
|---|---|
| folds | held-out days **1, 2 and 3** — day 0 is never a fold |
| epochs | **fixed 25**, no early stopping, no patience |
| training labels per fold | `--train-label-days` excluding **day 0 and the held-out day** |
| day 0 | **kept in the message-passing graph**, never supervised |
| final test eval | `--skip-final-test` |

**Why 25 epochs, fixed.** C1' seed 1's best epoch was **23**; 25 is that rounded up. It is fixed
rather than early-stopped because each fold has a different held-out day and therefore a
different val signal, and letting each fold choose its own stopping point would make the three
fold models differ in training length for reasons unrelated to the fold. A single fixed budget,
set from the full run that preceded it, keeps them comparable. **No fold metric is used to choose
it** — it is fixed here, before any fold trains.

**Why day 0 is excluded from every fold's labels.** C10 / Amendment 6: day 0 is 48.8 % of the
training edges at 0.27× the base rate, and supervising on it cost C1 a third of its val AP.
Including it in the fold models but not in C1' would make the cross-scores come from detectors
systematically weaker than the one whose scores the pipeline actually uses.

**Why day 0 is never itself a fold.** Scoring day 0 out-of-fold would require a model trained on
days 1–3 only, which is C1' itself; and day-0 edges are dropped from the ring-layer training
sets anyway (below), so their scores would be unused.

### Deliberate deviation from HI-Small's R3: held-out days stay in the graph

**Approved and recorded 2026-10-04.** HI-Small's shipped cross-scoring
(`ringshield/expand/cross_score.py` as it stood) **deleted** the held-out days from the fold's
training graph entirely — `subset_hetero` removed those edges, so the fold model never saw them
in any form. V3.3c instead **keeps them in the graph as unlabelled history** and removes only
their supervision, which is what `--train-label-days` does for the full C1' run.

**Reason: it matches scoring-time conditions.** When the fold model scores the held-out day, and
when the shipped detector scores val or test, the edges are *present in the graph* — their
neighbourhoods, ports, time deltas and GFP context are all visible — and only their labels are
withheld. A fold model trained on a graph with those edges deleted is scoring a graph denser than
the one it was trained on, which is a train/score mismatch that the deletion introduces rather
than removes. Keeping them unlabelled reproduces deployment: the transaction happened, nobody has
told you whether it was laundering.

**What this does not weaken.** Supervision is still strictly out-of-fold — asserted twice in
`run_fold`, once that no held-out-day edge is a supervised example and once that no
label-excluded day edge is — and again over the assembled table. An unlabelled edge in the
message-passing graph carries no target the model could memorise.

**It is a deviation and the two releases are not identical on this point.** Any HI-Small vs
HI-Medium comparison that runs through the cross-scored policy inherits it. The flag
(`--keep-held-out-in-graph`) defaults to **off**, so HI-Small's shipped behaviour is untouched
and reproducible.

### The assertion that must hold

**No edge is scored by a model whose training labels include that edge's day.** Checked
explicitly over the assembled cross-score table, not assumed from the fold construction. If it
fails, nothing downstream is built.

### How the folds are read — held-out AP lift (added 2026-10-05 06:29, before folds 1 and 2 finish)

A fold's cross-scores are the expansion policy's detector feature, so a fold whose held-out
scores carry no signal trains the policy on noise. **Folds are read by held-out AP lift =
average precision ÷ held-out base rate**, which is scale-free: the held-out days differ in base
rate by a factor of 4 within a release and by more across releases, so raw AP is not comparable
and lift is.

**Bar, fixed now: proceed to ring-layer training if folds 1 and 2 each reach ≥ 200×.**
Otherwise the ring layer is still built — 3d–3e proceed — but **the policy is reported as
trained on weak cross-scores**, and every policy-dependent result (`proposed`, `full`, and the
P4 `full` arm) carries that qualifier.

**The reference, measured** (`experiments/R3_cross_scores/fold*/fold.json`, HI-Small's shipped
5-fold cross-scoring):

| fold | held-out days | train edges | held-out edges | val F1 | AP | base rate | **lift** |
|---|---|---|---|---|---|---|---|
| 0 | **[0]** — the warm-up day | 2,134,000 | 1,114,921 | 0.5097 | 0.0322 | 0.00029 | **111×** |
| 1 | [1] | 2,494,472 | 754,449 | 0.6062 | 0.1533 | 0.00054 | **284×** |
| 2 | [2, 3] | 2,834,109 | 414,812 | 0.5003 | 0.4145 | 0.00192 | **215×** |
| 3 | [4] | 2,766,271 | 482,650 | 0.5237 | 0.4911 | 0.00098 | **503×** |
| 4 | [5] | 2,766,832 | 482,089 | 0.5443 | 0.4735 | 0.00110 | **430×** |

**HI-Small's weakest clean-day fold is 215×** (fold 2). The bar is set at **200×**, which rounds
that down, so it is **slightly lenient** rather than exactly matched — recorded here so the
threshold is not later mistaken for the measured value. The only HI-Small fold below 200× is
**fold 0 at 111×, the one holding out the warm-up day**, which is consistent with C8/C10 and is
excluded from the reference for that reason.

**Already measured on HI-Medium (fold 0, held-out day 1): AP 0.0571, base rate 0.000441,
lift 130×.** That is below the bar, but **fold 0 is not one of the two the bar is read on**: it
has the smallest supervised set of the three (1,659,565 edges against ~3.85 M for folds 1 and 2,
because day 1 is 3.02 M edges and days 2–3 are ~830 k each), so it is the fold most likely to be
weak for reasons of supervision volume rather than signal. It is reported either way.

**Both releases' per-fold lifts are reported side by side** in the Amendment 8 report, so the
comparison is visible rather than asserted.

### An observation that is recorded and NOT acted on

HI-Medium fold 0, trained on days **2–3 only** (1.66 M supervised edges), reached **val F1
0.5573** — *above* C1' seed 1's **0.4985**, which was trained on days **1–3** (4.68 M edges).
If that held up it would suggest **day 1's labels also hurt**, the same way day 0's did (C10),
and that the useful supervision is concentrated in days 2–3.

**This is one fold, one seed, a different training length (25 fixed epochs against 43 with early
stopping) and a different objective for checkpoint selection. It is not a controlled comparison
and nothing is concluded from it.** It is **not tested**, no C'' arm is registered, and no
parameter changes because of it. It is written down so that it is on the record before the
remaining folds land, and so that if it is pursued later it is pursued as a registered
experiment rather than a post-hoc rationalisation.

### Day folds are out-of-fold at the EDGE level, not the RING level (measured 2026-10-05)

**The assertion in Amendment 8 holds — and it is weaker than the policy needs.** "No edge is
scored by a model whose training labels include its day" is enforced and verified (0 violations
over 4,680,823 rows). But a fold holds out a **day**, and rings span days, so a fold model can be
supervised on some edges of ring R and then score R's held-out-day edges. The policy reasons
about **ring membership**, so out-of-fold should hold at the ring level, and under day folds it
does not.

**Incidence** (`results/tables/v33_ring_fold_leakage.csv`): share of each fold's held-out rings
that also appear in that fold's supervised days.

| | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | rings spanning >1 fold group |
|---|---|---|---|---|---|---|
| **HI-Medium** (days 1/2/3) | 79.5 % | 75.4 % | 57.7 % | — | — | 48.2 % of 626 |
| **HI-Small** (shipped R3) | 92.1 % | 92.4 % | 86.3 % | 84.6 % | 65.0 % | 62.3 % of 220 |

*(Shares corrected 2026-10-05: the first computation took a fold's supervised days to be every
other training day, which on HI-Medium wrongly included **day 0** — a day the C1' fold models
exclude from their labels. HI-Medium's shares were 82.8 / 77.1 / 59.5 % and 46.0 % of 657 under
that definition. The supervised pool is now read from each `fold.json`'s `train_days`, and the
626-ring denominator now agrees with the training-set report below. HI-Small excluded no day, so
its numbers are unchanged. The inflation measurement below was always computed against each
fold's recorded `train_days` and is unaffected.)*

**This is inherited, not introduced.** HI-Small's shipped R3 has the same design at a *higher*
leakage rate, so its published expansion policy was trained on cross-scores with this defect.
`--keep-held-out-in-graph` is unrelated: the leak runs through *labels on other days*, not graph
visibility, so deleting held-out days from the graph would not have prevented it.

**Measured inflation** (`results/tables/v33_leak_inflation.csv`). Within each fold the held-out
day's ring edges split into **leaked** (ring also in the supervised days) and **clean** (not),
scored against the same licit pool.

*A first attempt used AP÷base-rate lift and produced nonsense — 19,244× on a 21-edge clean group —
because both groups are scored against the same licit pool, so the base rate is set by the
group's own size. That is recorded as a discarded measurement. **ROC-AUC is used instead**, being
invariant to class balance, with AP on a size-matched subsample of the leaked group beside it.*

| dataset | fold | n leaked | n clean | AUC leaked | AUC clean | **gap** | AP leaked (size-matched) | AP clean |
|---|---|---|---|---|---|---|---|---|
| HI-Medium | 0 | 429 | 65 | 0.9875 | 0.9793 | **+0.008** | 0.032 | 0.016 |
| HI-Medium | 1 | 668 | 118 | 0.9948 | 0.9835 | **+0.011** | 0.491 | 0.350 |
| HI-Medium | 2 | 651 | 359 | 0.9941 | 0.9889 | **+0.005** | 0.572 | 0.465 |
| HI-Small | 0 | 92 | 6 | 0.9930 | 0.9624 | +0.031 | 0.029 | 0.000 |
| HI-Small | 1 | 168 | 6 | 0.9837 | 0.9916 | −0.008 | 0.161 | 0.002 |
| HI-Small | 2 | 445 | 40 | 0.9937 | 0.9575 | +0.036 | 0.463 | 0.202 |
| HI-Small | 3 | 275 | 21 | 0.9974 | 0.9915 | +0.006 | 0.477 | 0.838 |
| HI-Small | 4 | 280 | 73 | 0.9957 | 0.9959 | −0.000 | 0.682 | 0.506 |

**What this says.** The leak is **near-universal in incidence but small in ranking effect**: the
AUC gap is **+0.005 to +0.011 on HI-Medium** (bootstrap CIs overlap on all three folds) and
−0.008 to +0.036 on HI-Small, with two folds reversed. Size-matched AP shows a larger relative
gap (leaked ≈ 1.2–2.0× clean on HI-Medium) but HI-Small is inconsistent, including fold 3 where
clean exceeds leaked. **Clean-ring AUC stays high everywhere (0.958–0.996)** — the cross-score is
informative on rings the model has never seen labelled, which is the property the policy needs.

**HI-Small's clean groups are 6–73 edges**, so those estimates are noisy and the two reversals are
not evidence of a negative leak; they are evidence of small samples.

**The fold bar is reported exactly as registered — 200× on the pooled held-out AP lift — with
this caveat attached and the clean-ring statistics beside it.** The bar is not re-defined after
seeing the leak, and no fold's verdict is revised.

### Ring-layer training sets

Built from **train-visible rings with day 0 dropped**, matching the fold models' supervision.
Reported before any component is trained: fold edge-F1, training-set sizes, class ratios, and
**train rings with zero seeds** (rings the cross-scores never fire on, which no policy can learn
from).

**STOP and report at that point**, before the policy, affinity or typing head is fitted.

### Amendment 8 report — recorded 2026-10-05 21:07, at the STOP

**Cross-scoring is complete.** `experiments_hi_medium/R3_cross_scores_c1prime/`,
`cross_scores_train.parquet` = **4,680,823 rows, one row per training edge** (days 1–3; day 0 is
not scored because it is not supervised in C1′), rows per fold 3,021,258 / 828,958 / 830,607.

**The assertion of §"The assertion that must hold" passed: `violations: 0, passed: true`** — no
edge is scored by a model whose training labels include its day. Read with the §"Day folds are
out-of-fold at the EDGE level, not the RING level" caveat above.

#### Folds — per-fold edge-level metrics, both releases side by side

| | fold | held out | supervised days | train edges | train illicit | held-out edges | held-out illicit | best ep | val F1 | **held-out AP** | base rate | **lift** | F1 @ val thr | F1 @ oracle thr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **HI-Medium** | 0 | [1] | [2, 3] | 1,659,565 | 2,922 | 3,021,258 | 1,331 | 19 | 0.5573 | 0.0571 | 0.000441 | **130×** | 0.1006 | 0.1730 |
| **HI-Medium** | 1 | [2] | [1, 3] | 3,851,865 | 2,880 | 828,958 | 1,373 | 22 | 0.4297 | 0.4104 | 0.001656 | **248×** | 0.4333 | 0.4562 |
| **HI-Medium** | 2 | [3] | [1, 2] | 3,850,216 | 2,704 | 830,607 | 1,549 | 7 | 0.2788 | 0.4599 | 0.001865 | **247×** | 0.4219 | 0.5043 |
| HI-Small | 0 | [0] *(warm-up)* | [1…5] | 2,134,000 | — | 1,114,921 | — | — | 0.5097 | 0.0322 | 0.000290 | 111× | — | — |
| HI-Small | 1 | [1] | [0, 2…5] | 2,494,472 | — | 754,449 | — | — | 0.6062 | 0.1533 | 0.000540 | 284× | — | — |
| HI-Small | 2 | [2, 3] | [0, 1, 4, 5] | 2,834,109 | — | 414,812 | — | — | 0.5003 | 0.4145 | 0.001920 | 215× | — | — |
| HI-Small | 3 | [4] | [0…3, 5] | 2,766,271 | — | 482,650 | — | — | 0.5237 | 0.4911 | 0.000980 | 503× | — | — |
| HI-Small | 4 | [5] | [0…4] | 2,766,832 | — | 482,089 | — | — | 0.5443 | 0.4735 | 0.001100 | 430× | — | — |

All three HI-Medium folds ran 25 fixed epochs, train seed 1, held-out days kept in the graph
(`graph_edges` 9,146,808 in every fold, per the deviation registered above).

#### Verdict against the registered bar

**The bar was ≥ 200× lift on folds 1 and 2. Folds 1 and 2 reach 248× and 247×. → PROCEED to
ring-layer training**, with the policy reported *without* the "trained on weak cross-scores"
qualifier.

The bar is reported **exactly as registered**, and it is not re-defined now that the ring-level
leak is known. Beside it, the clean-ring statistics from the leak measurement: **clean-ring
ROC-AUC 0.979 / 0.984 / 0.989** on folds 0 / 1 / 2 — the cross-score separates ring edges from
licit edges on rings the fold model never saw labelled, which is the property the bar was meant to
test. Both readings point the same way, so no verdict changes.

**Fold 0 is 130×, below the bar, and is reported as such.** It was excluded from the bar in
advance (§"How the folds are read"), on the stated ground that it has the smallest supervised set
of the three — 1.66 M edges against ~3.85 M — and so is the fold most likely to be weak for
reasons of supervision volume. Its held-out day (day 1) is also 3.02 M of the 4.68 M scored edges,
**65 % of the policy's training rows carry a cross-score from the weakest fold.** That is a real
weakness of this design and is recorded here rather than averaged away.

#### Ring-layer training sets, class ratios, and rings with zero seeds

Built from train-visible rings on **days 1–3** (day 0 dropped, matching the fold models'
supervision). Seed rule and operating point are the validation-chosen cell from §B0 — **top 0.1 %,
`min_size` 3** — chosen before any of this was computed.

| quantity | value |
|---|---|
| training edges available | **4,680,823** |
| illicit edges | **4,253** — class ratio **1 : 1,101** |
| ring-member edges | **2,290** — class ratio **1 : 2,044** |
| seed threshold | top 0.1 % **within each fold**: `score_raw` > 0.697338 (fold 0) / 0.432370 (fold 1) / 0.500470 (fold 2) |
| seeds | **4,682** = 3,022 + 829 + 831 (0.100 % in every fold — the rule lands on budget) |
| seed precision | **0.2903** |
| seed recall | **0.3195** |
| train-visible rings with a cross-scored edge (days 1–3) | **626** |
| …with ≥ 3 accounts | **378** (60.4 %) |
| **rings with ZERO seeds** | **165 of 626 = 26.4 %** |
| rings with ≥ 1 seed | 461 |
| rings with ≥ 2 seeds | 282 |
| seeds per ring | median **1**, mean **2.23** |

Seeds-per-ring distribution: 0 → 165, 1 → 179, 2 → 91, 3 → 66, 4 → 32, 5 → 22, 6 → 18, 7 → 11.

**Corrected 2026-10-06 12:20 — the seed rule is per fold, not global.** The first version of
this table cut the top 0.1 % of `score_raw` over all 4,680,823 cross-scores at once. The
pipeline (`fold_seed_mask`) cuts the top 0.1 % **within each fold**, which is the rule B0 uses
per fold and the one the policy is actually trained under. The seed *count* is almost identical
(4,682 against 4,681) but the *set* is not — the two rules share only **4,133 seeds (88 %)**,
because fold 0's within-fold threshold is 0.697338 against the global 0.654853 while folds 1
and 2 are looser. Every ring-level figure moved with it, all in the same direction: **zero-seed
rings 213 → 165 (34.0 % → 26.4 %)**, rings with ≥ 2 seeds 253 → 282, seed precision
0.2519 → 0.2903, seed recall 0.2772 → 0.3195. The superseded figures are recorded here rather
than deleted. The numbers above are now the pipeline's own: `make_training_set.py` independently
reports *461 rings with seeds, 165 rings with zero seeds* on the same inputs.

**The number that matters for the next stage: a quarter of the training rings have no seed at
all**, so no seed-anchored policy can learn from them — they contribute no positive candidate rows.
The policy's effective training set is **461 rings**, and **282** of those have the ≥ 2 seeds that
make a within-ring linking decision possible at all. 626 rings is already a small training set for
a ring-level model; 282 is the number to keep in mind when reading any variance on the ring layer.

**Realised candidate set** (`experiments_hi_medium/R3_expansion/candidates.parquet`): **366,809
candidate rows over the 461 rings with seeds, 434 positives — a 1 : 845 class ratio**, with 737
queries truncated at the 500-event cap. HI-Small's shipped training set is 247,711 rows / 244
positives (1 : 1,014), so HI-Medium gives the policy **1.5× the rows and 1.8× the positives at a
slightly richer ratio**.

Source: `results/tables/v33_a8_training_sets.csv`, `v33_a8_fold_seed_cuts.csv`, `v33_ring_fold_leakage.csv`,
`v33_leak_inflation.csv`, `experiments_hi_medium/R3_cross_scores_c1prime/fold*/fold.json`,
`experiments/R3_cross_scores/fold*/fold.json` (HI-Small reference).

**Nothing beyond this point is fitted. STOP.**

## V3.3d — the HI-Medium ring layer's val-chosen parameters, recorded 2026-10-06 13:50

**Recorded before any test-split run and before the P4 `full` arm exists.** Nothing below was
informed by a test number, and the test split has not been read: the grid ran under a new
`run_expand.py --val-only`, which stops after writing `config.yaml` and never opens
`scores_test_seed1.parquet`.

| parameter | HI-Medium (chosen) | HI-Small (shipped) |
|---|---|---|
| `seed_frac_pct` (k\*) | **0.1 %** | 0.1 % |
| `min_size` | **3** | 3 |
| `delta_t_h` (Δt) | **48 h** | 24 h |
| `p_min` | **0.7** | 0.7 |
| `max_gap_hours` | None | None |
| val ring-F1 at the chosen cell | **0.4144** | 0.5765 |

k\* and `min_size` come from the 16-cell B0 validation grid recorded earlier (val ring-F1 0.457);
Δt and `p_min` from this 3×3 grid, on C1' seed 1's validation scores with embeddings.

**The full grid** (`experiments_hi_medium/R3_expansion/runs/proposed/seed1/val_grid.csv`):

| Δt | p_min 0.3 | 0.5 | 0.7 |
|---|---|---|---|
| 24 h | 0.379 | 0.397 | 0.413 |
| **48 h** | 0.379 | 0.398 | **0.4144** |
| 72 h | 0.379 | 0.398 | 0.4144 |

**Two things about this surface are recorded because they weaken the choice, and both are visible
in the table rather than argued around.**

1. **Δt is barely identified, and 48 h vs 72 h is an exact tie.** Every cell at 72 h reproduces
   48 h to four decimals *and* to the edge — 883 / 800 / 723 rings and 1,487 / 1,153 / 934 expanded
   edges, identical. No candidate exists between 48 h and 72 h, so the window saturates at 48 h and
   the tie was broken by the pre-existing sort rule (ring-F1, then larger `p_min`, then **smaller**
   Δt). 24 h is 0.413 against 0.4144 — a 0.0014 difference, far inside anything this grid can
   resolve. **So Δt = 48 h is a tie-break, not a measured preference, and HI-Medium's Δt should not
   be reported as "longer than HI-Small's" as though that were a finding.**
2. **`p_min` = 0.7 is again the grid corner.** The surface is monotone in `p_min`
   (0.379 → 0.398 → 0.414) on every Δt, exactly as on HI-Small, where every seed also chose the
   corner. The registered grid does not bracket the optimum from above, so 0.7 is a floor imposed
   by the grid, not an interior optimum. **The grid is not widened now** — that would be choosing a
   parameter after seeing which way the surface leans — and the limitation is carried instead.

**What `p_min` buys here, for the record:** moving 0.3 → 0.7 drops rings 883 → 723 and expanded
edges 1,487 → 934 while ring precision rises 0.356 → 0.429 at essentially unchanged recall
(0.406 → 0.401). The same precision-for-nothing trade HI-Small showed.

**Val ring-F1 0.4144 against HI-Small's 0.5765 is not a comparison of methods** — different
detector (C1', one seed, indeterminate gate), different release, different window. It is recorded
so the chosen cell is on the record, not as a result.

## Amendment 9 — 2026-10-04 16:45, V3.3: P4 is also reported stratified by visible-ring size

**Recorded before any P4 `full` result.** The P4 **B0** arm has been run (both datasets, 10 draws
each) and its pooled numbers are on disk; the `full` arm, which P4's verdict needs, has not.

### What is added

P4 is reported **stratified by the visible-member count of the truth ring**, strata **2, 3–5,
6–10, > 10**, for **both datasets** and **both B0 and `full`**, with the **per-stratum ring
count** shown beside every figure.

### Reason

Uniform edge sampling at a fixed recall covers a **smaller share of a larger ring**. At recall
0.28 a 2-member ring with two visible edges has a good chance of having both sampled; a 20-edge
ring almost surely gets a fraction, and whether it clears the Jaccard 0.5 bar then depends on how
that fraction falls. So the same seed quality does **not** mean the same per-ring difficulty
across size.

That would be harmless if the two releases had the same visible-size distribution. **They do
not** (`results/tables/v33_visible_member_distribution.csv`, primary window, `test_visible`):

| visible members | HI-Small (174 rings) | HI-Medium (2,361 rings) |
|---|---|---|
| 2 | 58 — 33.3 % | 709 — 30.0 % |
| 3–5 | 62 — 35.6 % | 577 — 24.4 % |
| 6–10 | 38 — 21.8 % | 525 — 22.2 % |
| **> 10** | **14 — 8.1 %** | **549 — 23.3 %** |
| median / mean / max | 4 / 4.78 / 18 | 5 / 7.41 / 45 |

HI-Medium has **nearly three times the share of rings above 10 visible members**. A pooled P4
comparison therefore mixes "what does the ring layer do with matched seeds" with "how big are the
rings it is asked to assemble", and the second of those is a property of the generator at scale,
not of containment.

### How it is read

* **The pooled verdict stays exactly as registered in Amendment 4** — HI-Medium higher than
  HI-Small on ring recall, Ring-Recall≥3 and the under-covered share, on B0 and `full`. The
  stratified table does not replace it and cannot rescue it.
* The stratified table is reported **beside** the pooled one.
* **If the two disagree, both are reported and the disagreement is stated as such** — not
  resolved in favour of whichever is more convenient, and not used to re-define the verdict after
  the fact.

Strata are fixed here, before any `full` result, and are not adjusted afterwards. A stratum with
too few rings to support a CI is reported with its count and no CI rather than merged into a
neighbour.

## Sequencing note — 2026-10-04 17:58: seeds 2–3 deferred, the count is unchanged

**The Amendment 2/3 rule still selects 3 seeds for C1'** (training wall 19.88 h > 14 h). Nothing
about the seed count is being revised.

What changes is the **order of work**: C1' seeds 2 and 3 are **not** trained yet. The cross-scoring
folds run first, then the ring layer and the P4 `full` arm (CPU), and seeds 2–3 are decided after
the **P4 `full` verdict** rather than before it. The reason is cost: seeds 2–3 are ~40 GPU-hours,
and P4 `full` is the load-bearing containment test (Amendment 4, since the gate is indeterminate),
so it is worth knowing its answer before spending them.

**Consequence for the record.** Every 3e statistic that needs variation across detector seeds —
the bootstrap CIs over seeds, and the paired permutation tests for proposed vs B0, proposed vs
B1b and full vs B2 — **cannot be computed from one seed**. If seeds 2–3 are not run, those
results are reported as **unavailable**, not as single-seed point estimates dressed up as
findings. P4's CIs are over its 10 draws and are unaffected.

### Superseded — 2026-10-06 11:58: seeds 2–3 run unconditionally

**The deferral above is withdrawn. C1' seeds 2 and 3 run regardless of the P4 `full` verdict.**

**Reason, and it is not a cost argument.** The deferral traded seeds against knowing P4's answer
first. That trade was wrong, because **P2 and P3 cannot be decided without the seeds** and no P4
result changes that:

* **P2** is read on the under-covered and class-(b) shares of truth rings. Both are per-seed means
  compared against HI-Small's 5-seed values, and a share from one seed has no spread to compare.
* **P3** exists precisely to make two currently-unresolvable *significance* comparisons resolvable.
  Its whole content is paired tests across detector seeds. With one seed there is nothing to pair,
  so P3 is not merely weakened, it is **unevaluable**.
* **P4 is a different instrument.** It draws synthetic seeds at fixed precision and recall, and its
  intervals are over its 10 draws. A P4 verdict in either direction leaves P2 and P3 exactly as
  unevaluable as before, so waiting for it buys nothing that the predictions need.

So the seeds are not an optional robustness extra here; two of the four registered predictions are
void without them. **Nothing about the seed count changes** — Amendment 2/3 selected 3, and it is
still 3.

**Status at the time of writing.** The run was launched 2026-10-05 20:42, immediately after the
folds finished, with the registered flags (`--train-label-days 1 3`, `--skip-final-test`,
`--feature-cache data/processed_hi_medium/feature_cache`). **Seed 2 is complete**: best val F1
**0.4652** at epoch 6, 26 epochs, mean 1,830 s/epoch. **Seed 3 is training** (~1,826 s/epoch).
Seed 2's 0.4652 against seed 1's 0.4985 is the first evidence of C1' seed spread, and it is
reported, not acted on: no parameter is re-chosen because of it, and the adequacy gate is **not**
re-read on a second seed — Amendment 4/5 fixed the gate on seed 1 and that verdict stands.

**The constraint that remains.** No test-window run of the **real-detector** pipeline until all
three seeds exist. Validation choices, the ring layer's training, and the P4 arms (which use
synthetic seeds, not the detector) are not blocked by this and proceed now.

## Amendment 10 — 2026-10-07 10:30, V3.3e: P4's detector confound, a structural arm, and a registered expectation

**Written before the HI-Medium test split is scored and before any P4 `full` number exists.** The
test split has not been read by any ring-layer code; only `models/score.py` is about to generate
features on it.

### 1. P4 matches seed quality, not detector quality

P4 hands both datasets a seed set of identical quality (precision 0.93, recall 0.28) — but
`full` is not seed-only. The expansion policy consumes **each dataset's own detector scores and
embeddings** as features: of its 70 features, `cos_mean_included`, `cos_anchor`, `score_quantile`
and `dead_region` are detector-derived, and `cos_mean_included` is the single largest contributor
on HI-Medium (0.38 gain). The affinity model likewise consumes `cos_emb`.

**So P4 `full` controls the seeds and leaves the detector uncontrolled.** HI-Medium's detector is
the weaker of the two — C1' val AP 0.4495 against HI-Small R1's 0.5726, with an *indeterminate*
adequacy gate — so **P4 `full` is biased against HI-Medium**, and a HI-Medium shortfall on it
cannot be attributed to the ring layer. The B0 arm has no such confound: B0 uses only the seed
mask and a constant score.

**This is a limitation of P4 `full` as registered in Amendment 4, found when building it, not a
change to it.** The test is run as registered and reported with this statement attached.

### 2. P4 `full-structural` — secondary arm, registered now

To separate the ring layer from the detector, a second arm re-trains **both** learned components
on each dataset **without the detector-score and embedding feature groups**, using the Step 6
ablation recipe already in the code (`--drop-feature-group detector embedding` on
`ringshield/expand/policy.py` and `ringshield/partition/affinity.py`).

* **Everything else is held fixed at each dataset's own val-chosen values** — Δt, `p_min`, the
  linkage cut, `min_size`, k\*. No parameter is re-chosen for this arm, because re-choosing on
  validation after seeing `full` would make the arms incomparable.
* **Reported beside P4 `full`**, pooled and stratified by visible-ring size per Amendment 9.
* **What it can show:** `full-structural` removes the detector from the ring layer's inputs
  entirely, so a HI-Medium-vs-HI-Small difference on it is a difference in what the ring layer does
  with structure, timing and account state alone. **What it cannot show:** it is a weaker model
  than `full` by construction on both datasets, so its absolute numbers are not the shipped
  pipeline's and are not comparable to any `full` number.

### 3. Registered expectation for 3e: `full` may not beat B0 on HI-Medium's test window

Recorded **before any test ring metric exists**. On HI-Medium validation the full stack is
**behind** plain connected components at every operating point, at `min_size` 3:

| k | B0 val ring-F1 | `full` best val ring-F1 | Δ |
|---|---|---|---|
| **0.10 %** (chosen) | **0.4563** | **0.4404** | **−0.016** |
| 0.15 % | 0.4392 | 0.3444 | −0.095 |
| 0.20 % | 0.4145 | 0.2751 | −0.139 |
| 0.30 % | 0.3552 | 0.1957 | −0.160 |
| 0.50 % | 0.2132 | 0.1123 | −0.101 |

**So the registered expectation is that `full` ≤ B0 on HI-Medium's primary test window, and that
A1/A5-style expansion gains do not replicate on this release.** If the test window contradicts
validation, that is reported as the surprise it would be, not quietly adopted.

**The mechanism, measured — and it is NOT the one first proposed.** The initial framing was that
HI-Medium's seed set is weaker and expansion amplifies the weakness (the Step 10 boundary
condition). **The numbers do not support that.** Same tool, same `--variant full` sweep, same
metric, `min_size` 3, k = 0.10 %:

| | B0 ring precision | expansion Δprecision | expansion Δrecall | ΔF1 |
|---|---|---|---|---|
| HI-Small (5 seeds, mean) | **0.6812** (range 0.654–0.707) | **−0.036** | +0.088 | **+0.043** (5/5 seeds positive) |
| HI-Medium (seed 1) | **0.6626** | **−0.224** | +0.094 | **−0.016** |

**B0's seed-set purity at the operating point is the same on both releases** — 0.663 against 0.681,
inside HI-Small's own seed spread — so the premise that HI-Medium starts from a weaker seed set is
**false at this operating point** and is withdrawn. **The recall gain is also the same** (+0.094
against +0.088). The entire difference is the **precision cost: −0.224 against −0.036, six times
worse.** HI-Medium's expansion admits far more non-member edges per true member recovered.

That is consistent with the two learned components being weaker here, both measured on
train-window data before any of this was known: the policy's grouped-CV AUC-PR is **0.799 ± 0.067**
against HI-Small's 0.833, and the affinity model's balance-invariant CV ROC-AUC is **0.955 ± 0.027**
against **0.980 ± 0.019** (its AUC-PR looks *better*, 0.985 against 0.973, only because its pair set
is 75.1 % positive against 39.7 % — see `results/tables/v33_affinity_comparison.csv`).

**Also recorded:** HI-Small's own expansion gain is specific to the tight operating point. Averaged
over its 5 seeds the gain is +0.043 at k = 0.10 %, +0.027 at 0.15 %, +0.014 at 0.20 % and
**−0.002 at 0.30 %**. The stage was never a general win there either.

### 4. The linkage-cut grid is complete

The sweep is the registered seed_frac × cut × min_size grid, **all five seed fractions present**
(`results/tables/v33_partition_val_grid.csv`, `v33_partition_val_chosen.json`).

**It had to be run in chunks.** A single process exceeded the available 2-hour background limit
twice, and `grid_val.csv` is written only at the end, so each killed run persisted nothing. The
cells are independent of one another, so a `--seed-frac` restriction was added and the union of the
chunk files is the same grid; the chosen cell was recomputed over the union with the tool's own
documented tie-break (ring-F1 desc, then seed_frac asc, then `min_size` desc, then cut desc).

**Chosen: k 0.10 %, `min_size` 3, cut 0.3, average linkage — val ring-F1 0.4404.** Decided on the
fourth decimal (cut 0.3 at 0.4404 against cut 0.5 at 0.4400), not by the tie-break.

**The cut is close to inert**, as B3/B4 found on HI-Small: at the chosen k and `min_size` the three
cuts give 0.4404 / 0.4400 / 0.4363, and only **50 of 487** training components are mixed-ring, so
there is little for it to act on.

### 5. C1' seed 3 did not finish — recorded 2026-10-07 10:20

Seed 3 reached **epoch 25** (val F1 0.4683) at 02:59 on 2026-10-07 and stopped there: no best-epoch
line, no `metrics_seed3.json`, `training_summary.json` still holding seed 1 only, and no process
alive. Seed 1 ran 43 epochs under early stopping, so seed 3 was **terminated mid-run, not
completed**. Its checkpoint exists but is untuned and unrecorded.

**Consequence: seeds 2–3 do not both exist, so everything gated on them stays gated** — no
real-seed B0 or `full` ring metric on test, and no test edge metric. Scoring the test split for
seed 1 is feature generation for P4, which was registered on the primary window from the start, and
is explicitly not covered by that gate.

## C1' all three seeds — results, and the adequacy gate re-read on three seeds (2026-10-09 19:30)

Seed 3 finished on 2026-10-09 (59 epochs, best val F1 0.4409 at epoch 39), after its first attempt
was killed at epoch 25 by its parent shell going away — see the note in Amendment 10 item 5; the
diagnosis found no OS fault (uptime unbroken since 2026-09-22, no Kernel-Power, WER or
resource-exhaustion events). **All three registered seeds now exist.**

Val AP is the best checkpoint's, scored by `models/score.py` on the HI-Medium validation split
(3,857,689 rows, 0 NaN, base rate 0.001012), then `average_precision_score` against the split's
labels. Seeds 2 and 3 were scored on the GPU at batch 16,384 in 558 s each; seed 1's figure is from
a CPU rescore that reproduces its original 0.4495 as 0.4497.

| seed | best val F1 | best epoch | epochs run | threshold | **val AP** | AP ÷ base rate |
|---|---|---|---|---|---|---|
| 1 | 0.4985 | 23 | 43 | 0.50 | **0.4497** | 444× |
| 2 | 0.4652 | **6** | 26 | 0.64 | **0.3955** | 391× |
| 3 | 0.4409 | 39 | 59 | 0.56 | **0.3695** | 365× |
| **mean ± sd** | **0.4682 ± 0.0289** | — | — | — | **0.4049 ± 0.0409** | **400×** |

Source: `results/tables/v33_c1prime_seeds.csv`,
`experiments_hi_medium/R1_gine_causal_c1prime/metrics_seed{1,2,3}.json`.

### The adequacy gate fails on three seeds

**Amendment 4 fixed the gate at val AP 0.45, with a ±0.02 indeterminate band, before any training.**
Amendment 5 read it on seed 1 at **0.4495 — INDETERMINATE**, and on that basis 3b–3e proceeded.

**On three seeds the verdict is no longer indeterminate. It is a FAIL.** The mean is **0.4049**,
which is 0.045 below the bar and **outside** the 0.43–0.47 indeterminate band. Seeds 2 and 3 are
individually 0.3955 and 0.3695, both clear fails; only seed 1 reaches the band at all. HI-Small's
R1 seed 1 reference is **0.5726**, so HI-Medium's detector sits at **71 %** of it.

**What this does and does not change.** The gate was registered to decide whether a ring layer is
worth building on this detector, and that decision was already taken on seed 1's indeterminate
reading (Amendment 7). The seeds were not re-read to revisit it, and **no parameter, arm or
prediction is altered now** — doing so after the fact is exactly what pre-registration prevents.
**What changes is the framing of every 3d/3e number: they are ring-layer results on a detector that
fails its own pre-registered adequacy bar on three seeds.** That sentence belongs beside the P1/P2
verdicts, not in a footnote, and it is the honest reading of Amendment 10 item 1's confound at full
strength.

### Validation instability — measured on both releases, and NOT specific to HI-Medium

The three HI-Medium seeds disagree about when training peaks: best epochs **6 / 23 / 39** out of
26 / 43 / 59 run, with seed 2 peaking at epoch 6 and then early-stopping. That is real and it is
reported. **But it is not a HI-Medium phenomenon.** HI-Small's five shipped R1 seeds behave the
same way, and on two of three measures slightly worse:

| | val F1 (mean ± sd) | val F1 range | best epochs | tuned-threshold range |
|---|---|---|---|---|
| **HI-Small** (5 seeds) | 0.5828 ± **0.0398** | 0.5288–0.6196 | 30, **10**, 27, 32, 23 | 0.32–0.65 (**0.33 wide**) |
| **HI-Medium** (3 seeds) | 0.4682 ± **0.0289** | 0.4409–0.4985 | **6**, 23, 39 | 0.50–0.64 (0.14 wide) |

HI-Medium's spread is **smaller in absolute terms** (±0.029 against ±0.040), smaller in relative
terms (**6.2 %** against 6.8 % coefficient of variation), and its tuned thresholds vary **less than
half** as much. Both releases contain one seed that peaks in the first third of its run — HI-Small's
seed 2 at epoch 10 of 30, HI-Medium's seed 2 at epoch 6 of 26.

**So the claim that this instability is new on HI-Medium is withdrawn.** What is distinctive on
HI-Medium is the *level* of val AP, not its variance. The widest best-epoch spread is HI-Medium's
(33 epochs against 22), which is the one measure on which it is less stable, and it is reported
as such.

**Nothing is tuned in response.** The seed count stays at 3 (Amendment 2/3), the checkpoints stay
as selected by each seed's own validation F1, and the thresholds stay as each seed tuned them. The
spread is carried into 3e as seed variance, which is what the bootstrap and the paired tests are
for.

## Amendment 11 — 2026-10-09 19:10, V3.3e: the policy variant becomes a val-chosen parameter

**Registered before any real-seed test ring metric exists.** The HI-Medium test split has detector
scores and embeddings (feature generation, Amendment 10), but no ring-layer code has been run on it
and no `full`/B0/B1b/proposed test ring number exists for any seed.

### What is added

The **expansion-policy variant** joins Δt, `p_min`, k\*, `min_size` and the linkage cut as a
parameter **chosen on validation ring-F1, per dataset, at that dataset's val-chosen cell**. The
candidates are the four already-trained policies:

| variant | feature groups dropped |
|---|---|
| `proposed` | none |
| `no_detector` | detector (`score_quantile`, `dead_region`) |
| `no_embedding` | embedding (`cos_anchor`, `cos_mean_included`) |
| `structural` | detector **and** embedding |

### Why this dimension exists, stated plainly

**It was created by a measurement, not by a hope.** B17's leak work forced a re-measurement of the
Step 6 ablations on HI-Medium, and the result was an **asymmetry**: dropping the detector group
*costs* 0.008 ring-F1 on HI-Small but **gains 0.026 on HI-Medium** (val, chosen cell: 0.4144 →
0.4403), because the ablated policy expands less (934 → 733 edges) and more precisely
(0.429 → 0.496) at unchanged recall. On HI-Small the same two ablations move CV AUC-PR by +0.003
and +0.001 — nothing.

So the shipped `proposed` policy is **not** the validation-preferred policy on HI-Medium, and
pretending otherwise would mean reporting a configuration that validation rejects. The honest
options were (a) report `proposed` and note that validation prefers another variant, or (b) make
the variant a val-chosen parameter on both datasets under one rule. **(b) is chosen**, because it
applies the same selection discipline already used for every other parameter in this project.

**This is a genuine addition to the design and it is disclosed as one.** It was not in the original
V3.3 registration. It is added **before any test ring metric**, it is chosen on **validation only**,
and the selection rule is fixed here before the grid is read.

### Rules

* **Selection: highest validation ring-F1** at the dataset's val-chosen cell (k\*, `min_size`, Δt).
  Ties break toward the **simpler** variant (more groups dropped), then toward `proposed`.
* **One variant per dataset.** No per-seed or per-window selection.
* **HI-Small's shipped results are not re-run or revised.** If HI-Small's validation prefers a
  variant other than `proposed`, that is reported as an **additional val-selected row** beside the
  shipped numbers, which stand exactly as published. The shipped pipeline remains the shipped
  pipeline; the extra row is a statement about what validation would have chosen.
* **Nothing is chosen on test, and no test number is consulted before this choice is recorded.**

## Amendment 12 — 2026-10-09 19:10, V3.3e: `p_min` extended past the grid corner

**Registered at the same time as Amendment 11, before any real-seed test ring metric.**

### The problem

`p_min` = 0.7 is a **corner solution on both datasets**: the validation surface is monotone
increasing in `p_min` everywhere it has been measured, so the grid never bracketed the optimum from
above. HI-Medium, Δt 48 h, `min_size` 3 (`run_expand` val grid): **0.379 → 0.398 → 0.4144** for
`p_min` 0.3 → 0.5 → 0.7. HI-Small's five shipped seeds each also chose 0.7, the corner of
{0.3, 0.5, 0.7}. A parameter pinned at the edge of its grid is a property of the grid.

### What is added

The grid is extended to **`p_min` ∈ {0.7, 0.8, 0.9}** at each dataset's val-chosen Δt, **crossed
with the four Amendment 11 variants** — one 4 × 3 grid per dataset, read on validation ring-F1.

* **Choose the (variant, `p_min`) pair on HI-Medium validation ring-F1**, recorded before any test
  run, under Amendment 11's tie-break (then toward the **lower** `p_min`, as the less aggressive
  filter, when ring-F1 ties).
* **The same extension is run on HI-Small validation.** If it beats the shipped configuration
  there, it is reported as an **additional val-selected row**; the shipped results are left
  unchanged, exactly as under Amendment 11.
* **Validation only.** These are `run_expand --val-only` runs; the test split is not read.
* **What a win here would and would not mean.** Raising `p_min` makes the policy add fewer, higher-
  confidence edges. If the optimum is interior (0.8), that is a real operating point. If it is
  again at the corner (0.9), **the parameter is still unbracketed and that is reported as an
  unresolved limitation, not as a choice** — the grid is not extended a second time after seeing
  which way it leans.

### Honest accounting of what these two amendments are

Amendments 11 and 12 add **12 validation configurations per dataset** where the original design had
one. That is a real increase in validation-side search, and it raises the chance that the chosen
cell is partly fitted to the validation window — which on HI-Medium is **two days (4–5)** and
holds far fewer rings than the test window. **No correction for multiple validation comparisons is
applied, and none is claimed.** The mitigation that does apply is the one that always applied: the
test window is read **once**, after these choices are frozen in writing, and both the
validation-chosen and the **originally registered** configuration (`proposed`, `p_min` 0.7) are
reported side by side in 3d so a reader can see what the added search bought.

## Amendment 11/12 result — HI-Medium's val-chosen (variant, `p_min`), recorded 2026-10-09 20:05

**Recorded before any real-seed test ring metric exists.** Validation ring-F1, C1' seed 1, at the
val-chosen cell (k 0.1 %, `min_size` 3, Δt 48 h, cut 0.3). Source
`results/tables/v33_a12_val_grid.csv`, `v33_a12_val_chosen.json`.

| variant | `p_min` 0.7 | 0.8 | 0.9 | optimum |
|---|---|---|---|---|
| `proposed` | 0.4144 | 0.4281 | **0.4496** | corner |
| `no_embedding` | 0.4260 | 0.4370 | **0.4585** | corner |
| **`no_detector`** | 0.4403 | 0.4596 | **0.4769** | corner |
| `structural` | 0.4649 | **0.4756** | 0.4692 | **interior** |

**Chosen by the registered rule: `no_detector`, `p_min` 0.9 — val ring-F1 0.4769.**

### Three things about this choice that weaken it, recorded with it

**1. The margin over the runner-up is 0.0013.** `structural` at `p_min` 0.8 reaches 0.4756. A
difference of thirteen ten-thousandths on a single seed, on a two-day validation window, is not a
preference — it is a coin flip that the rule happened to resolve. **Any claim that
`no_detector` is the better policy on HI-Medium is unsupported by this grid.** The rule is applied
as registered because re-deciding after seeing the numbers is what pre-registration forbids, not
because the evidence distinguishes the two.

**2. The chosen cell sits at the grid corner; the runner-up does not.** `no_detector` is still
monotone increasing at `p_min` 0.9, so its optimum is **unbracketed** — exactly the condition
Amendment 12 was written to expose, now one notch further out. `structural` is the only variant
whose surface **turns over inside the grid** (0.4649 → 0.4756 → 0.4692), so it is the only one
whose `p_min` is genuinely determined. **Per Amendment 12's pre-committed rule the grid is NOT
extended a third time**, and the chosen `p_min` is reported as pinned at its grid edge — an
unresolved limitation, not a measurement.

**3. Three of four variants are unbracketed**, so the direction of the whole surface is the finding:
on HI-Medium the expansion policy wants to add **far less** than it was configured to. Across
`proposed` 0.7 → 0.9 the expanded-edge count falls 934 → 529 and ring precision rises 0.429 → 0.527
while recall barely moves (0.401 → 0.392). The same holds for every variant. HI-Medium's expansion
is over-admitting at the shipped floor, and both the `p_min` extension and the detector-group
ablation are two routes to the same correction.

### This reverses the basis of Amendment 10 item 3's registered expectation

Amendment 10 registered the expectation that **`full` may not beat B0 on HI-Medium's test window**,
formed on `proposed` at `p_min` 0.7, which loses to B0 by **−0.016** on validation (0.4144 against
0.4563). **The val-chosen configuration now beats B0 by +0.021** (0.4769 against 0.4563), and so
does the runner-up (+0.019), and so does `structural` at every `p_min` tested.

**The registered expectation stands as registered — it is not edited.** It was written down before
this grid existed and its value as a pre-registration is that it cannot be revised once the answer
appears. What is recorded here is that **the expectation was formed on a configuration validation
rejects**, and that on the configuration validation selects, validation now points the other way.
Both readings go into 3e beside the test result, and the test window decides between them exactly
once.

### What 3d must therefore report

Per the user's instruction and Amendment 12's accounting clause, 3d reports **both**:

* the **val-chosen** configuration — `no_detector`, `p_min` 0.9, Δt 48 h, k 0.1 %, `min_size` 3,
  cut 0.3; and
* the **originally registered** configuration — `proposed`, `p_min` 0.7, same cell —

so a reader can see what the Amendment 11/12 search bought. **A third row for `structural` at
`p_min` 0.8 is reported as a sensitivity**, because it is within 0.0013 of the winner and is the
only properly bracketed configuration in the grid; it is labelled a sensitivity, not a selection.

## 3d first test run — the validation window is 2 days and the test window is 10 (2026-10-10 18:40)

**Recorded at the first real-seed test ring metric, before the remaining 3d runs.** One run exists:
`proposed` under the val-chosen configuration (`no_detector`, `p_min` 0.9, Δt 48 h, k 0.1 %,
`min_size` 3), C1' seed 1, 4,551 s. Source
`experiments_hi_medium/R3_expansion/runs/A_valchosen/seed1/metrics.json`.

### The numbers, and a 5× collapse from validation to test

| | truth rings | predicted | matched | precision | recall | **ring-F1** | member coverage |
|---|---|---|---|---|---|---|---|
| **validation** (days 4–5) | 773 | 485 | 300 | 0.6186 | 0.3881 | **0.4769** | 0.943 |
| **test primary** (days 6–15) | 2,361 | 1,529 | 185 | 0.1210 | 0.0784 | **0.0951** | 0.721 |

### The cause is a window-length mismatch baked into the V3.2 split choice

| | validation window | primary test window | ratio |
|---|---|---|---|
| **HI-Small** | days 6–7 — **2 days** | days 8–9 — **2 days** | **1×** |
| **HI-Medium** | days 4–5 — **2 days** | days 6–15 — **10 days** | **5×** |

**On HI-Small validation and test are the same length, so val ring-F1 was a fair proxy. On
HI-Medium every parameter was chosen on a 2-day window and applied to a 10-day one.** The
mechanism is the one C9 already documented for scope and B13/B16 for window length: a longer window
admits more of each ring, so `test_visible` member sets grow — HI-Medium's primary window has a
median of 5 visible members, mean 7.41, and **23.3 % of rings above 10** — and a Jaccard 0.5 match
gets strictly harder as the set grows. Member coverage falling 0.943 → 0.721 across the two windows
is the same effect measured directly.

A second, additive cause: spread over 10 days the 0.1 % budget fragments. 18,894 seed edges give
**16,894 seed components, of which 15,258 fall below `min_size` 3**, leaving 1,574 candidate rings
against 2,361 truth rings. On the 2-day validation window the same rule yields 485 predictions
against 773 truth.

**This is a defect in the window selection, not in the ring layer, and it was introduced in V3.2**
when the split was chosen to maximise ring observability without constraining the validation window
to the primary window's length. It is recorded here, at the first test run that could reveal it,
before the remaining 3d runs.

### What is still valid, and what is not

**Valid: within-dataset, same-window comparisons.** B0 and the expansion were both evaluated on the
identical 10-day primary window with the same seeds:

| test primary, C1' seed 1 | rings | precision | recall | **ring-F1** | matched of 2,361 |
|---|---|---|---|---|---|
| **B0** | 1,187 | 0.0388 | 0.0195 | **0.0259** | 46 |
| **`proposed`** (val-chosen variant) | 1,529 | 0.1210 | 0.0784 | **0.0951** | **185** |

**Expansion multiplies ring-F1 by 3.7× and matched rings by 4.0× on the test window** (+0.0692
absolute). Expanded-member precision is 0.523 (767 true member edges against 699 not), and 1,098
quiet accounts are newly covered with **0 lost** against B0. In relative terms this is a far larger
expansion effect than HI-Small's (+0.068 on a base of 0.521, i.e. 1.13×).

**Not valid as registered: the cross-dataset absolute comparison.** P1 asks whether HI-Medium's
primary-window recalls exceed HI-Small's. HI-Medium's are far lower (ring recall 0.078 against
HI-Small's ~0.49 at the same stage), **but the two numbers are computed on windows of different
length, which is exactly the comparison C9 showed moves ring-F1 by five times more than any method
effect in this project.** Reporting 0.0951 against HI-Small's 0.589 as if they were comparable
would repeat the error this project already retracted once (the 0.72 cap, B9, 2026-09-30).

**No window is re-chosen now.** Picking a 2-day slice of the test window after seeing these numbers
would be selecting a result. The primary window stays days 6–15 as registered; P1's verdict is
reported **together with the statement that its two sides are not length-matched**, and the
like-for-like question is left as a named, unresolved limitation rather than answered with a
post-hoc window.

## Amendment 13 — 2026-10-16, V3.3e: P1 and 3d are also evaluated on length-matched windows

**Registered before anything is computed on these blocks.** No per-block pipeline run exists, and
no per-block number has been seen.

### The reason

HI-Medium's **validation window is 2 days** (4–5) and its **primary test window is 10** (6–15).
HI-Small's are both 2 days (6–7 validation, 8–9 primary). So HI-Small's val ring-F1 was a
length-matched proxy for its test result and HI-Medium's is not, and a HI-Medium-vs-HI-Small
comparison of primary-window numbers compares a 10-day window against a 2-day one. C9 measured that
the scope convention alone moves ring-F1 by **five times** the largest method effect in this
project; window length acts through the same mechanism, by growing each ring's visible member set
until a Jaccard 0.5 match is strictly harder. The first test run showed exactly that signature —
member coverage 0.943 on validation against 0.721 on the 10-day primary window.

### What is added

**P1 and the main 3d comparison are also evaluated on the five consecutive 2-day blocks of the
primary window: 6–7, 8–9, 10–11, 12–13, 14–15.**

* **The pipeline is run per block, exactly as it is run on validation** — the seed quantile k\* is
  taken **within the block**, so each block gets its own budget at the same rate, matching how
  validation selects seeds within its own 2-day window.
* **Reported as the mean over the five blocks with a CI over blocks**, beside the 10-day
  primary-window result, which is **not** replaced.
* **The blocks are fixed by window geometry alone** — consecutive, equal, non-overlapping, covering
  days 6–15 exactly. No block is chosen, dropped, re-cut or re-ordered for any reason, and in
  particular not for anything observed in the data.
* **This changes no parameter.** Δt, `p_min`, the variant, the cut, k\* and `min_size` stay at the
  values already recorded. Only the evaluation geometry is added.

### A known property of block 14–15, recorded now so it cannot look like a surprise later

The seed diagnostic run before this amendment (`results/tables/v33_seed_by_day.csv`) shows that
**day 15 takes 16,531 of the 18,894 primary-window seeds — 87.5 % of the whole budget — at a seed
precision of 0.0071**, against 0.21–0.87 on days 6–14. Day 15 also carries 3.02 M edges against an
interior median near 1.93 M.

**Block 14–15 therefore contains a day that behaves unlike the other nine, and its block result
should be expected to differ.** That is recorded here, **before** the blocks are run, precisely so
that a poor 14–15 block cannot later be excluded as an outlier. **All five blocks are reported
whatever they show.** Per-block seed counts and seed precision are reported beside each block's
ring metrics, so a reader can see the budget each block actually received.

### What this does and does not resolve

**Does:** it makes the HI-Medium number comparable in window length to HI-Small's published
primary-window number, and it makes validation a length-matched proxy for the blocks.

**Does not:** the blocks are still drawn from a test split whose detector is three to twelve days
further from its training days than validation is, so temporal degradation is not controlled by
this amendment and is not claimed to be. Nor does it fix the seed-budget concentration on day 15;
it localises it to one block.

## Amendment 14 — 2026-10-16, V3.3e: a per-day seed budget, reported beside the registered global cut

**AMENDED AFTER FIRST TEST CONTACT. This is disclosed before anything else is said about it.**
The seed diagnostic that motivates this amendment (`results/tables/v33_seed_by_day.csv`) used
**test labels** — it reports seed precision per test day. So this amendment is **not** a clean
pre-registration: it was written after a label-bearing look at the test split, and it must be read
as a post-hoc addition, not as a prediction made in advance. Everything registered before this
point stays exactly as registered, and **the global-quantile rows are reported beside the per-day
rows in every table, always.**

### What is added

For HI-Medium test runs — both the 10-day primary window and each Amendment 13 block — seeds are
**also** selected with a **per-day budget**: within each day, the top **0.1 %** of that day's edges
by `score_raw`, strict cut, the same k\* as the registered rule. No other parameter changes: Δt,
`p_min`, the variant, the cut, `min_size` all stay as recorded.

### The justification, which is label-free

The registered rule takes a single global quantile of `score_raw` across the whole split. Two facts
about HI-Medium, **neither of which requires a label**:

1. **Day 15 carries 3,021,866 edges against an interior median near 1.93 M — about 1.56× a normal
   day.** This is a property of the data's daily volume profile, observable from timestamps alone,
   and it is the same shape C8 already recorded at the other boundary (day 0, 2.31× the interior
   median, the identical ratio on all three releases).
2. **Day 15 receives 16,531 of the 18,894 global-quantile seeds — 87.5 % of the budget.** This is
   computed from `score_raw` and timestamps only. **No label is involved in observing it.** A
   single day taking seven-eighths of the budget is visible to anyone holding the scores, before
   any ground truth is consulted.

**That the seeds on day 15 then turn out to be 0.7 % precise is the part that needed labels, and it
is the part that is NOT used as justification here.**

**Correction to this justification, 2026-10-16, from the cross-release boundary check (C11).** The
two facts above are both true, but the implied link between them — that the 1.56× volume is *why*
day 15 takes 87.5 % of the budget — **is not supported.** HI-Small's own pre-shutdown spike day is
1.36× the weekday norm and takes **23.4 %** of its global-quantile seeds ~~while holding 23 % of the
edges, i.e. exactly its share~~ *(corrected 2026-10-25: it holds 75.8 % of the test split's edges, so
it takes far less than its share; 23.4 % is seed 1, 22.0–36.3 % over seeds 1–5;
`evaluation/c11_seed_share.py`)*. Volume alone does not capture a global quantile. HI-Medium's day 15
captures it because **that detector's scores are systematically elevated on that day**, which is a
property of the model, not of the generator's volume profile.

**What survives as justification for this amendment is therefore narrower, and it is still
label-free:** under a global quantile, *whatever* the cause, one day currently receives 87.5 % of
the seed budget — an allocation visible from `score_raw` and timestamps alone — and a per-day
budget makes the allocation across days an explicit design choice rather than an artefact of the
score distribution. The operational argument (daily alert review) is unchanged. **The volume
argument is withdrawn.** The label-free statement is sufficient on its
own: a global quantile over a multi-day split does not distribute the budget across days, and the
fraction it gives to the largest-volume day is a property of the score distribution, not of the
rings.

**Operational justification, also label-free.** A per-day budget is what a deployed alert queue
actually does: an institution reviews a roughly fixed number of alerts per day, not a fixed number
per fortnight with seven-eighths of them falling on one Friday. The registered global rule is the
one HI-Small used and is retained for comparability; the per-day rule is the one that matches daily
review, and it is reported beside it.

### How it is read

* **Every table carries both rows.** No result is reported under the per-day rule alone.
* **The registered global-quantile result remains the headline for any comparison with HI-Small**,
  which was produced under the global rule on a 2-day split where the distinction barely binds.
* **If the per-day rule does better, that is a finding about seed allocation, not a method win**,
  and it is stated that way: nothing about the detector, the policy or the partition changed.
* **If it does worse, it is reported too.** It is not dropped.

### What it does not fix

A per-day budget redistributes the budget; it does not improve the ranking within a day. If the
detector's scores on day 15 are poorly separated, a per-day cut will take that day's top 0.1 %
regardless and simply stop them from crowding out the other nine days. The temporal-degradation
confound (validation sits adjacent to training; the test window runs 3–12 days further out) is
untouched by this amendment and is not claimed to be addressed by it.

## Recorded non-predictions

* Nothing is predicted about the **tail** (days 16–27). It is reported beside the primary numbers
  and never merged in, as on HI-Small.
* Nothing is predicted about **edge-level** metrics (F1, AP). C6/C7 showed a 9.4-point edge-F1
  gain producing 0.000 ring-F1 change; edge metrics are reported and not used as evidence for or
  against any of P1–P3.
* Nothing is predicted about **runtime**. The V3.1 projection (8.9 h/seed, 44.3 h for 5 seeds) is
  a linear extrapolation and was called a floor.
* Nothing here revisits V3.0/V3.0b's verdicts. Those were measured on HI-Small and stand as
  HI-Small results; whether they reproduce on HI-Medium is a later question and is **not**
  pre-registered here.

## Status at the time of writing

Done: pattern verification (all 22,743 HI-Medium pattern transactions exist in `_Trans.csv`),
split selection by rule, formatting (31,898,238 rows, 2,077,023 accounts), account-bank map,
loader (train 9,146,808 / val 3,857,689 / test 18,893,741; rings 657 / 773 / 2,396), ring scope
and ceiling tables, `configs/paths_hi_medium.yaml`, `configs/eval_window_hi_medium.yaml`.

**GFP features: complete (V3.2b).** The adjacency is now CSR arrays that workers memory-map
read-only, so the pool shares one copy instead of pickling ~8.5 GB into each worker. Validated by
regenerating HI-Small's GFP **value-identical to the shipped parquets** on all three splits at
both 12 and 36 workers, with `tests/test_gfp_causality.py` still passing. HI-Medium: train
9,146,808 / val 3,857,689 / test 18,893,741 rows, zero nulls, `EdgeID` aligned, 3 h 04 total,
hashed into the manifest. Measurements are in `docs/V3_OBSERVABILITY.md`.

**The HI-Medium split is now complete and trainable.** Nothing in the data pipeline is
outstanding.

Not started: anything that trains. **This pre-registration is not conditional on the GFP
blocker** — it fixes the predictions and their criteria now, so that they cannot be adjusted
once features exist and a first result is visible.

### Status update — 2026-10-05 21:07

The paragraph above is kept as written (this is a pre-registration; it is appended to, not edited).
What has happened since:

| stage | state |
|---|---|
| detector C1 (days 0–3 supervised), seed 1 | **done, gate FAIL** — val AP 0.3073 against the 0.45 bar. Reported at the detector level only; no ring layer built on it (Amendment 7) |
| detector C1′ (day 0 unsupervised, still in graph), seed 1 | **done** — val AP 0.4495, best val F1 0.4985, gate **INDETERMINATE** (inside the ±0.02 band) → 3 seeds |
| C1′ seeds 2–3 | **deferred**, not cancelled — decided after the P4 `full` verdict (sequencing note below) |
| B0 validation grid | **done** — 16 cells, chosen 0.1 % / `min_size` 3, val ring-F1 0.457 |
| P4 B0 arm | **done** — against the prediction on all three quantities; uninterpretable until the `full` arm exists |
| P4 `full` arm, incl. Amendment 9 stratification | **registered, not built** — next after this stop |
| cross-scoring folds (3 folds) | **done** — bar met on folds 1 and 2; see the Amendment 8 report |
| expansion policy / affinity / typing head | **not started — this is the stop** |

Nothing in the ring layer has been fitted. `ring 657` in the paragraph above is the loader's train
count over days **0–3**; the ring-layer training set uses days **1–3** and has **626** rings, which
is why the two numbers differ.

---

## Dated notes (2026-11-12)

**An undocumented third detector arm, now recorded.** `experiments_hi_medium/R1_gine_causal_c2prime`
(in the `Ring-Shield` checkout, files dated 2026-10-16) is a C1′-style run with training labels
restricted to **days 2–3**, three seeds. It is not referenced anywhere else in `docs/`.

| seed | epochs run | best val F1 | val AP at that epoch |
|---|---|---|---|
| 1 | 32 | 0.5207 | 0.4751 |
| 2 | 51 | 0.5386 | 0.5075 |
| 3 | 53 | 0.5179 | 0.4692 |

Only `scores_val_seed1.parquet` was written, with no test scores, so no ring result exists for it
and nothing downstream uses it. It is recorded here as an exploratory arm. It is not a registered
detector and plays no part in the C1′ choice or in Amendments 13–14.

**P1–P4 and Amendments 13–14 have no outcome yet.** No verdict and no output table existed as of
this date. The close-out runs are in progress:
- `evaluation/hm_closeout.py`: seeds 1–3, the primary window and the five 2-day blocks, both budget
  rules, writing to `experiments_hi_medium/closeout/`;
- `evaluation/hm_closeout_report.py`: computes P1–P3 (to be written);
- registration of the execution: `docs/deep-analysis.md` §7.

Every verdict will carry the C1′ gate-failure caveat (mean val AP 0.4049 < 0.45) and the P4 caveat.
