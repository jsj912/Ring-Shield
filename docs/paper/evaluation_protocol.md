# Chapter — Evaluation protocol

*Draft. Every number cited here has a source row in `docs/FINDINGS.md`; this chapter explains the
choices, it does not introduce results.*

## 1. The unit of evaluation is a ring, not an edge

Anti-money-laundering benchmarks on AMLworld are almost always reported as minority-class F1 over
transactions. We report **rings** — sets of accounts acting together — and treat edge F1 as a
diagnostic rather than an objective. The reason is measured, not stylistic.

Swapping our detector for MEGA-GNN raises test edge F1 by **9.4 points** (0.5957 → 0.6893) and
changes ring-F1 by nothing at all (0.5213 → 0.5208 at the B0 operating point). The two detectors
do not even agree on which edges to seed — their seed sets overlap at Jaccard **0.415** — yet they
reach the same number of truth rings (**128.8 vs 129.6** of 174) and score the same. The relation
is a ceiling rather than independence: a *worse* detector still costs rings (GFP-XGBoost, 9.6 edge
points below ours, loses 17.7 ring points). Above that point, edge ranking quality stops being the
binding constraint and the seed budget takes over.

A protocol that reports edge F1 alone would have scored MEGA-GNN as a 9-point improvement to this
system. It is not one. That single comparison is the argument for everything that follows.

## 2. Ground truth, scope, and what "a ring" means

Rings come from the AMLworld pattern files: each `BEGIN…END` block is one laundering attempt with
a type (FAN-IN, CYCLE, SCATTER-GATHER, …). A ring's **members** are the accounts appearing in its
transactions, and a prediction is scored against that account set.

The scope question — *which* rings a split can be held responsible for — matters more than it
sounds. A ring's transactions can straddle split boundaries, so we fix one rule and state it:
**`test_visible`** — a ring is in scope for the test period if it has at least one transaction
there, and its member set is the accounts of those transactions. Two stricter alternatives
(`strict`: every transaction in the window; `majority`: more than half) are reported in an
appendix block and never used for a headline number.

Even under the most generous scope, ring membership is only partly observable in one split:
**7.9 %** of members have no test-period transaction at all and **33.2 %** have none labelled
illicit. No method can recover what is not present; the protocol states this rather than
absorbing it into a model's error.

## 3. Matching rule

A predicted ring matches a truth ring when their account sets reach **Jaccard ≥ 0.5**, paired
greedily one-to-one by descending Jaccard. At a 0.5 threshold two truth rings cannot both match
the same prediction — their Jaccards would have to sum above 1 — so the greedy pairing is
effectively optimal and ties are rare.

The threshold is **fixed, never tuned**. Results at Jaccard 0.3 and 0.7 are reported as a
sensitivity sweep in every table's appendix, precisely so that the headline cannot be read as the
best of three.

`min_size = 3`: predictions smaller than three accounts are discarded. This is a real ceiling and
we quantify it rather than hide it — **28 %** of primary-window truth rings (48.6 of 174) have
fewer than three *visible* members, and 1,359 of those 1,387 ring-instances have exactly two. Ring
recall is therefore capped at about **0.72**, against 0.46 achieved.

### The matching threshold is a methodological choice, not a neutral one

Jaccard 0.5 is the field's convention, and our own results show that a method's apparent gain can
be **entirely a function of that choice**. Our partition stage gains **+0.024** ring recall at
τ = 0.3, **+0.015** at 0.5 and **+0.001** at 0.7, with ring-F1 turning negative (−0.009) at the
tight end — because re-cutting produces smaller predictions that clear a loose bar against small
truth rings, which is a fragmentation effect rather than better attempt separation.

We report this against our own method because that is the credible way to say it: **anyone
reporting a ring-level gain at Jaccard 0.5 without a threshold sweep may be reporting a
fragmentation artefact.** The sweep costs nothing — the matches are already computed — and it is
the difference between a method result and a scoring artefact. Our editorial rule is that the
τ = 0.7 row is quoted wherever the τ = 0.5 gain is.

## 4. Evaluation windows — and why a single test number is not comparable

The IBM 60/20/20 day split puts a pathology in the test period's tail. Days 10–17 hold 655 of the
test period's 1,611 positives inside **1,108 edges — a 59 % base rate**, against 0.11 % on days
8–9. Forty per cent of the test positives sit in 0.13 % of the edges, and a rule that reads the
clock ("after day 10 ⇒ illicit") scores **F1 0.48** there on its own.

### This is a property of the generator, not of HI-Small

We regenerated the whole preprocessing path on **LI-Small**, the low-illicit-ratio release of the
same simulator, and the collapse reproduces exactly. Both variants use the IBM 60/20/20 day split
and both land on train [0,6) / val [6,8) / test [8,17):

| test day | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 |
|---|---|---|---|---|---|---|---|---|---|---|
| **HI-Small** base rate | 0.079 % | 0.212 % | **58.6 %** | 60.5 % | 57.6 % | 57.9 % | 60.9 % | 56.5 % | 65.2 % | 72.7 % |
| **LI-Small** base rate | 0.041 % | 0.106 % | **61.0 %** | 56.3 % | 60.4 % | 58.1 % | 66.7 % | 71.4 % | 66.7 % | — |

| | HI-Small | LI-Small |
|---|---|---|
| tail edges (days ≥ 10) | **1,108** = 0.128 % of test | **223** = 0.019 % of test |
| test positives in the tail | **655 = 40.7 %** | **134 = 16.7 %** |
| tail base rate | 59.1 % | 60.1 % |
| lift over that split's test base rate | **318×** | **880×** |

**Every paper reporting HI-Small results on the IBM day split has some version of this in its test
set.** It is a property of the AMLworld generator, not of one release: two variants with different
illicit ratios, different ring counts and different sizes produce the same structure — the last
days of the test period contain a vanishing fraction of the traffic at a ~60 % base rate.

State the shared part precisely, because the two variants differ in degree. What reproduces is the
**concentration**: in both, ≤ 0.13 % of test edges sit at a ~60 % base rate, a 318× and 880× lift.
What does not reproduce is the *share of signal* — 40.7 % of HI-Small's test positives live there
against 16.7 % of LI-Small's. So the defensible claim is that a few hundred edges carry a
**disproportionate** fraction of the test signal in both variants, decisively so in HI-Small; it is
not that the fraction is the same.

So we report three windows and name them:

| window | days | what it is |
|---|---|---|
| **primary** | 8–9 | the reporting window; normal background traffic |
| tail | 10–17 | the collapsed-background region, reported separately |
| whole | 8–17 | for comparability with papers that report one number |

Every headline in this work is the **primary** window. A single-number test F1 on HI-Small is not
comparable across papers unless the split and window are stated, and we state ours. LI-Small's
primary window is defined the same way, for the same reason.

### A second generator artefact: the day-0 warm-up

The tail is not the only place the simulator shows through. **Day 0 holds a third of the training
period's traffic** — 34.3 % of HI-Small's train edges and 34.4 % of LI-Small's — at about ten times
day 1's per-minute density. Trailing graph-pattern features count structures inside a time window,
so that density distorts them in both directions at once: cycle-shaped features (`gather_scatter`,
`temporal_cycle`, `cycle_length`) fire on **12.6 %** of day-0 edges against **~2 %** on every later
day, while `fan_in` / `fan_out` are *depressed* (63 % against 89 %) because there is no history
behind day 0 to look back into.

Both effects reproduce in LI-Small **to within 0.3 percentage points on every feature and every
day**. Day 0 is not a sample from the same distribution as the rest of the period; it is the
simulation warming up. Anything trained across it is partly fitting that warm-up, which is why the
expansion policy's training set excludes day-0 rows.

Taken with the tail result, the same conclusion applies at both ends of the AMLworld timeline: the
**first day and the last days are generator artefacts**, and a protocol that reports one number over
the whole span is averaging over two of them.

### LI-Small: what a second dataset does and does not establish here

LI-Small is filed in this chapter rather than under generalisation on purpose. It is **evidence
about AMLworld**, not evidence about our method, and stretching it into a method claim would be
dishonest about what it can carry.

What it establishes. The preprocessing, splitting, scoping and windowing path runs unchanged on a
second release — one environment variable (`RINGSHIELD_PATHS`) selects a per-dataset paths file and
every script inherits it. 6,924,049 transactions, 705,907 accounts, the same day split, the same
tail collapse, the same scope rule.

What it cannot establish. **Its ring-level evaluation is under-powered and we say so rather than
report a noisy number.** LI-Small's primary window holds 55 in-scope rings of which only **38 have
three or more visible members** — the matchable population, against HI-Small's 114. A bootstrap
over 38 rings has a half-width wider than the entire B0 → `full` gain measured on HI-Small, so the
full method grid would produce a number rather than evidence. The threshold for stopping was fixed
in advance (`docs/GENERALISATION.md`), the count came in below it, and the reasoning is recorded in
`docs/ring_scope_li_small.json` alongside the decision.

Its scope table, ceiling (max ring recall 0.691 at `min_size` 3) and tail behaviour are reported on
their own terms, beside HI-Small's equivalents and never combined into a single cross-dataset
figure.

## 5. Nothing is chosen on the test period

Every parameter — the seed fraction k\*, `min_size`, the expansion Δt and p_min, the linkage cut,
the calibration map, the detector checkpoint — is selected on the **validation** split (days 6–7)
and then frozen. This is enforced structurally: the runners accept `--choose-on val` and no other
value.

Two consequences are worth spelling out because they cost us numbers:

* The operating point k\* = 0.1 % / `min_size` 3 is the validation argmax, and a robustness sweep
  shows it is **not** test-optimal — 0.15 % scores higher on test. We report the validation choice
  and the sweep beside it, and do not move the operating point.
* Validation is a *training signal*, not neutral data. When a pattern type is held out
  (Chapter: Generalisation), its labels are removed from **train and val together**, because val
  chooses every parameter.

**Calibration** is isotonic, fitted on exactly the validation rows and applied unchanged to test,
with a cross-fitted validation curve reported as a diagnostic. Selection uses the **raw** score,
not the calibrated one: isotonic collapses ~800k distinct scores onto ~100 levels, and a quantile
cut on a calibrated column lands inside a level and silently drops part of the intended seed set.

**Sampling is causal.** Neighbourhood sampling never shows the model an edge later than the batch's
latest seed. Where the installed library cannot express edge-level temporal sampling, the fallback
batches seeds into contiguous 1,800-second windows and filters afterwards, so within-batch leakage
is bounded by that window and recorded per run.

## 6. Statistics

**Confidence intervals** are bootstrap percentile intervals over **truth rings**, with the
detector seeds averaged *inside* each resample. The resampling unit is the ring because that is
the unit of the claim; folding seeds in means the interval carries seed variation as well as ring
sampling, which is what a reader needs.

**Significance** is a paired sign-flip permutation test on per-ring matched indicators (10,000
permutations), with **Holm** correction across a pre-registered family of comparisons. Families are
declared before the runs, not assembled afterwards.

**The one limitation that must travel with every p-value in this work:** the test operates on
matched-ring indicators and is therefore **blind to precision**. A method can produce far more
rings, match about as many, and test as indistinguishable. The clearest case in our results is
GFP-XGBoost's full pipeline sitting **13.9 ring-F1 points** below ours at **p_holm 0.807** — its
recall is comparable and the entire loss is on the precision side. Precision-side differences are
read from the confidence intervals on ring precision, ring-F1 and added-member precision. A
non-significant p_holm in this work means *"no evidence these methods find different rings"*, never
*"these methods are equivalent"*.

## 7. Pre-registration

Where a result could be read more than one way, the reading was fixed in writing before the
numbers existed, with the decision rule and both branches named. Three instances are recorded in
this work, with timestamps and the state of the running job at the time:

* the alternative explanation for a detector swap improving ring-F1 (seed spread vs genuine
  reach), with the two diagnostic signatures that would distinguish them;
* the prediction that a held-out-pattern detector run would be uninformative, with the label-mass
  measurement that motivated it and the compute reallocation it governed;
* the prediction that the partition stage helps more on a detector that over-merges more.

Pre-registration also records what would make a confirmed prediction *weak*. The held-out detector
null, for instance, was declared underpowered in advance: a 5.9 % change in positive labels against
a 7-point seed spread is an intervention the experiment had almost no power to detect, and the
confirmed null means exactly that and nothing more.

## 8. Reporting rules

* A metric a method cannot produce is **N/A**, never 0.00. A typing head cannot emit a class it was
  never shown, so a held-out type's typing cell measures the cost of omission, not failed transfer.
* Quiet-member recall is never quoted without added-member precision beside it. A method can raise
  the first arbitrarily by adding edges indiscriminately — GFP-XGBoost posts the table's highest
  quiet recall (0.2673) while adding 2,419 edges at 0.260 precision, against 453 at 0.932.
* Corrections are dated in place and the superseded reading is named, not silently overwritten.

---

## 9. The window choice is in tension with itself

Days 8–9 are the reporting window because days 10+ are a base-rate collapse — 0.13 % of test edges
at a 59 % base rate, a clock-reading rule scoring F1 0.48 on its own. That argument is sound and
the measurement supports it in both AMLworld releases.

But a two-day window **fragments long patterns**. Scoring a ring against the accounts of its
in-window transactions means a pattern spread over more than two days can present as two or more
disconnected components, and no expansion policy operating inside the window can bridge them.
Measured: **80.7 %** of the missing members of under-covered rings sit in a piece with no path to
the recovered fragment. That caps ring recall in a way a longer window would not.

Both facts are ours and both are measured, so the honest position is that **AMLworld's day split
offers no window that is both clean and long enough**: the tail is degenerate, and the clean part is
too short for long topologies.

The control sharpens this rather than resolving it. Widening to the whole ten-day split drops
disconnection **80.7 % → 51.7 %** and eliminates it for CYCLE (55 % → 0 %) and RANDOM — so for those
patterns the fragmentation *is* an artefact of our two-day choice. **But STACK stays disconnected at
99.6 % even across the whole test period.** For the pattern that dominates the class, the break is
not in our window at all: it is in the 60/20/20 **split**, which severs long chains at the train/val
and val/test boundaries. A longer reporting window would not recover them; only a different split,
or a scope rule that admits out-of-window member edges, would.

We therefore report the window choice as a **constrained decision with a measured cost**, not as a
free one.

### The scope rule is the other half of the trade, and the literature does not pose it

`test_visible` scores a ring against the accounts of **its in-window transactions**. That is what
makes a severed chain present as two objects: the member edges that would rejoin them are outside
the window, so they are outside the ring's definition as well.

The alternative is a scope rule that admits **out-of-window member edges** into the ring's account
set while still requiring the method to work from in-window evidence. Under such a rule STACK's
rings would be single connected objects again and the 99.6 % disconnection would largely vanish —
we know this because the disconnection is measured against the ring's own edge set, and the edges
that reconnect it exist; they simply sit in another split.

Neither rule is obviously right, and the trade is real:

* **`test_visible` (ours)** scores a method only against evidence it could have seen. It is fair to
  the method, and it makes long patterns **structurally unmatchable** whenever the split cuts them —
  a property of the protocol that is easy to mistake for a property of the method.
* **Out-of-window scope** keeps rings intact and makes the ground truth a better description of the
  laundering attempt. But it scores a method against members it had no way to observe, so a
  perfect in-window method would still be penalised, and the ceiling it implies is not achievable
  by any system operating causally on that split.

We chose the first and report its cost: **28 %** of primary rings below `min_size`, **19 %** untouched
by any detector edge, and of the touched-but-unmatched, the larger half unreachable by connectivity
rather than declined by policy — **99.6 % of STACK's missing members still disconnected across the
full ten-day test period**. Every one of those is a property of observing a multi-day process
through a windowed, split-bounded, set-overlap metric.

**We measured the size of the choice.** Re-scoring the same shipped runs under both policies, no
model re-run and no parameter re-chosen:

| detector / method | `test_visible` (reported) | `full_membership` | gap |
|---|---|---|---|
| gine B0 | 0.5213 | 0.1437 | **−0.378** |
| gine B1b | 0.5553 | 0.2073 | −0.348 |
| gine proposed | 0.5819 | 0.2297 | −0.352 |
| gine **full** | **0.5894** | 0.2428 | **−0.347** |
| mega B0 | 0.5208 | 0.1595 | −0.361 |
| mega **full** | **0.6074** | 0.2252 | **−0.382** |

The in-scope ring count is unchanged at 174 — only the member sets grow, median 4 → 11 accounts.
**The convention is worth 0.35–0.38 ring-F1; the entire expansion-plus-partition method is worth
0.068.** A reader comparing a ring-level number across two papers that took different sides of this
choice is comparing the choice, not the methods.

What survives is the **ordering**: b0 < b1b < proposed < full under both policies and both
detectors, with member coverage falling 0.944 → 0.728 consistently. Within-paper method comparisons
are robust to the convention; absolute cross-paper numbers are not.

We have not found this trade-off posed in the ring-level AML literature, and we think it should be:
a ring-level result is not interpretable without stating which side of it the authors took.

## 10. What pre-registration bought, with four examples

Four predictions in this work were written down with their decision rules before the relevant
numbers existed. **All four first predictions were wrong in some respect**, each differently, and in
each case the written criterion is what made the wrongness legible rather than absorbable:

1. **Detector swap.** The pre-registered alternative — that a ring-F1 gain would come from seeds
   being spread more evenly — never had to be adjudicated, because the gap fell inside the seed
   spread. The diagnostics agreed independently. *Value: prevented a post-hoc explanation of noise.*
2. **Held-out pattern (detector).** Predicted uninformative, and it was: Δ = +0.0014 points,
   p = 1.0000. But the pre-registration also recorded *why a confirmed null would be weak* — 5.9 % of
   labels against a 7-point seed spread — so the null is reported as "could not have detected an
   effect of this size", not as evidence of absence. *Value: stopped a null being over-read.*
3. **Partition on MEGA.** Prediction 1 was technically true and substantively false (+0.0172 vs
   +0.0149 is noise; the *interval* differs, not the effect), and prediction 2 failed outright —
   partitioning costs precision on both detectors. The mechanism prediction was confirmed. *Value:
   forced the distinction between a larger effect and a tighter estimate.*
4. **Chain-mode expansion (11d).** The pre-registered diagnostic ran **before** the implementation
   and invalidated the design: the missing members are disconnected in-window, so neither a relaxed
   floor nor a depth cap could reach them. *Value: saved the implementation, not merely explained
   its failure.*

The fourth is the one that matters most. A pre-registration that only makes failures legible is
worth having; one that prevents work on a mechanism that cannot apply is worth more. The rule this
project ended on: **before building a method for a loss, measure that the loss has the shape the
method assumes.**
