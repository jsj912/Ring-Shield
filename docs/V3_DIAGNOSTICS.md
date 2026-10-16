# V3.0 — two diagnostics on the shipped HI-Small artefacts

Measurement only. No model is trained, no parameter is chosen, nothing is selected on test. Both
parts read artefacts that already exist in `experiments/R1_gine_causal` and
`experiments/R4_partition/runs/average`.

Source: `evaluation/v3_diagnostics.py`. Five seeds, primary window (test days 8–9),
`test_visible` scope, shipped `gine_causal` scores and the shipped `full` runs.

## Why these two

`FINDINGS.md` **B8** puts 33.2 rings per seed in **class (b)** — ≥ 3 visible members, and no
included edge of any prediction touches one of their accounts. **B13** puts 80.7 % of the
under-covered class's missing members in a piece of the ring with no in-window path to the
recovered fragment, and **B16** shows history does not bridge them. **B14** shows reallocating the
*edge* seed budget does not lift the ceiling.

Everything measured so far selects and connects **edges**. Two things have not been measured:

* **(a)** whether the same scores, aggregated to **accounts**, put class (b) rings within reach —
  a ring can be untouched at the edge level while several of its accounts each carry a
  middling-but-not-top edge, and an account-level ranking would surface them.
* **(b)** whether the detector's **edge embeddings** already place the disconnected pieces of one
  ring near each other. B13/B16 ruled out *topological* bridging; they say nothing about whether
  the representation groups the pieces without a path.

Neither is a build. Both are the measurement that a build would have to rest on.

## Pre-registration — written 2026-09-30, before either diagnostic ran

**No number below this heading existed when this section was written.** Both scripts were
unimplemented.

### (a) Account-level reach

Per seed, over in-window test edges, three per-account aggregates:

| aggregate | definition |
|---|---|
| `max_score` | maximum `score_raw` over the account's in-window edges |
| `top3_sum` | sum of the account's three highest in-window edge scores |
| `n_above_q99` | count of the account's in-window edges above the 1 % score quantile |

Accounts are ranked by each. Reported for the **class (b)** rings' visible member accounts: the
share landing in the top **0.1 %**, **0.5 %** and **1 %** of accounts, and the number of class (b)
rings placing **≥ 3** members in the top 1 %. A fourth, **budget-matched** tier is reported
alongside: the top *N* accounts where *N* is the number of distinct accounts the shipped 0.1 %
edge-seed set already touches — the only tier that answers "at a comparable budget" directly.

**Null:** licit accounts (no truth-ring edge) drawn to match the class (b) member accounts'
in-window transaction counts, in pseudo-rings of the same sizes, so the "≥ 3 members" statistic has
a null too. High-degree accounts win any max-over-edges ranking by having more draws; without the
degree-matched null the hit rate is not interpretable.

**Verdict, fixed in advance. REACH** — account-level seeding is worth a design step — if *both*:

1. at the **budget-matched** tier, **≥ 25 %** of class (b) rings place ≥ 3 visible members in the
   selected set (≈ 8 of 33.2 per seed, which would be a larger prize than B15's ~1 ring/seed); and
2. the member-account hit rate is **≥ 2×** the degree-matched licit null at that tier.

Otherwise **NO REACH**. Condition 2 alone failing means the ranking is finding *busy* accounts, not
ring accounts, and a seeder built on it inherits the null's precision.

### (b) Embedding grouping

The 198-dim `gine_causal` edge embeddings, as shipped. For each ring instance, its in-window member
edges are partitioned into **connected components** (two edges adjacent when they share an
account) — the same construction as B13's control. Four pair populations, cosine similarity:

| population | definition |
|---|---|
| **same-ring, cross-component** | the pairs of interest: one ring, two pieces with no path between them |
| same-ring, same-component | reference ceiling — edges that do touch |
| **different-ring** | one edge from each of two different rings in the same pool |
| score+time-matched random | for each positive pair, two non-ring edges drawn from the same score-rank and hour bins |

Over both pools: the **under-covered** rings (B13's disconnected pieces) and the **class (b)**
rings. AUC is reported for same-ring cross-component (positive) against different-ring (negative),
and against the matched random null.

**Verdict, fixed in advance. SEPARABLE** — embedding similarity is a usable grouping signal — if
*both*:

1. **AUC ≥ 0.75** for same-ring cross-component vs different-ring; and
2. **AUC ≥ 0.70** against the **score+time-matched** null.

Otherwise **NOT SEPARABLE**. Condition 2 is the one that matters: the score is a function of the
embedding, so two high-scoring edges at the same hour are similar for reasons that have nothing to
do with belonging to one ring. An AUC of 0.75 is already a weak bar in absolute terms — the
cross-component pairs of one ring are a vanishing fraction of all in-window edge pairs, so a rule
operating at this AUC would admit far more wrong pairs than right ones. Below it there is nothing
to discuss.

---

# Results

Run 2026-09-30, `python evaluation/v3_diagnostics.py`, RNG seed 20260930. 5 seeds, primary window,
354,447 accounts with an in-window transaction, 174 in-scope rings.
Tables: `results/tables/v3_account_reach.csv`, `v3_embedding_grouping.csv`,
`v3_ring_components.csv`, `v3_diagnostics.json`.

> **Correction, 2026-09-30 (before V3.0b).** Part (a) was first run with the seed quantile taken
> over the **in-window** edges (863 seeds). That is not the shipped rule: `run_partition` passes
> the **whole** test split to `seed_mask_for_pct`, so the shipped selection is **864 seeds over
> 863,900 edges**, of which only **463 per seed** fall inside the primary window — the rest land
> in the day 10–17 tail, which holds 0.13 % of the edges and 41 % of the positives
> (`docs/TEST_TAIL.md`). `under_covered.py` and `historical_bridge.py` both use the whole-split
> mask intersected with the window, and part (a) now does too. Every number in this section is the
> corrected one. The direction of the verdict did not change; its size did — the oracle prize fell
> from 16.8 to **7.8** rings per seed. The earlier figures (1357 accounts, 950 discarded, 59.7 %,
> 16.8) described a seed set the pipeline never used and should not be quoted.

## (a) Account-level reach

### One thing has to be said before the table

**Ranking accounts by `max_score` and thresholding edges by score are the same operation.** An
account's `max_score` exceeds the cut exactly when one of its edges does, so "the top *N* accounts
by max edge score", with *N* set to the number of accounts the seed set touches, returns **that
same account set, by construction** — whatever cut produced it. The measured overlap is 1.000, as
it must be. This is why `max_score` is the tier to read as "the shipped selection, re-expressed".
`top3_sum` (overlap 0.826) and `n_above_q99` (0.327) are genuinely different rankings.

So (a) is not asking whether a *different* ranking finds class (b). It is asking how much of class
(b) the **existing** ranking already has in hand — and what happens to it.

### What happens to it

| per seed, mean over 5 | | of which in an in-scope ring |
|---|---|---|
| seed edges, whole split (0.1 %) | **864** | |
| of those, inside the primary window | **463.0** (379–567) | |
| accounts those in-window seeds touch | **671.6** (499–887) | 474.0 — **70.6 %** |
| of those, accounts reaching *any* prediction | **450.0** (435–476) | 433.4 — **96.3 %** |
| accounts selected and then **discarded** | **294.8** — **44 %** of the selection | 107.6 — **36.5 %** |
| class (b) rings | 33.2 | |
| class (b) visible member accounts | 190.4 | |
| class (b) members that are an endpoint of an **in-window seed edge** | **70.8 — 37.2 %** | |

A component needs `min_size` 3 accounts to survive, so a seed edge that lands alone is dropped
along with both its accounts. Roughly **four in ten** selected accounts go that way, and they carry
**70.8 class (b) member accounts — 37.2 % of the class (b) membership**. Class (b) is not simply a
set of rings the scorer failed to see: for better than a third of its accounts, the scorer selected
them and the aggregator then discarded them for want of connectivity.

**The filter is not sloppy, which is the hard part.** It turns a selection that is 70.6 % ring
accounts into a kept set that is **96.3 %** ring accounts, and the 294.8 it discards are **63.5 %
non-ring**. Of the 107.6 real ring accounts it does throw away, **70.8 — 66 % — are class (b)
members**. So the discard is simultaneously where class (b) is lost and part of why ring precision
holds at 0.86. Retaining the class (b) accounts by relaxing the filter means retaining roughly 187
non-ring accounts with them, unless something discriminates between the two.

### Class (b) inside each tier

Member-account hit rate (%), 5-seed mean:

| tier | accounts selected | `max_score` | `top3_sum` | `n_above_q99` | degree-matched licit null (range over the three) |
|---|---|---|---|---|---|
| top 0.1 % | 354 | 19.6 | 21.8 | 12.8 | 0.00–0.06 |
| **budget-matched** | **672** | **38.0** | **37.7** | 20.4 | **0.06–0.18** |
| top 0.5 % | 1772 | 66.2 | 64.7 | 47.7 | 0.45–0.55 |
| top 1.0 % | 3544 | 72.7 | 73.5 | 73.5 | 1.05–1.16 |

Class (b) rings per seed (of 33.2) with **≥ 3** members in the tier, and — the number that bounds
the prize — with ≥ 3 members *and* at least half the ring, which is what it takes to clear the
Jaccard 0.5 bar if those accounts were handed over as a perfect prediction (purity 1, so Jaccard =
coverage):

| tier | ≥ 3 members (`max_score`) | **oracle ≥ 0.5 bar** (`max_score`) | oracle (`top3_sum`) | oracle (`n_above_q99`) | null (either statistic) |
|---|---|---|---|---|---|
| top 0.1 % | 5.2 | 3.0 | 1.6 | 1.0 | **0.0** |
| **budget-matched** | **10.2** | **7.8** | 6.6 | 1.6 | **0.0** |
| top 0.5 % | 21.0 | 20.2 | 18.6 | 11.8 | **0.0** |
| top 1.0 % | 23.0 | 22.6 | 23.4 | 23.4 | **0.0** |

The null never produces a single pseudo-ring with 3 members in any tier, across 20 draws × 5 seeds
× 4 tiers × 3 aggregates. Member-level lift over the null is **633×** at the budget-matched tier
(38.0 % against 0.06 %) and still **73×** at the top 1 %. Degree matching is doing its job — at the
top 1 % the null's hit rate tracks the tier size almost exactly (1.05 % of members for a tier
holding 1.0 % of accounts) — so the lift is score, not busyness.

### Why the oracle is only an upper bound

The 672-account budget-matched tier contains accounts of **138.4 of the 174 in-scope rings**, and
**70.6 %** of its accounts belong to some in-scope ring; **10.5 %** are class (b) members. (This
"touches an account of" count is broader than B14's 129.6, which counts a seed edge being a
*member edge* of the ring.) Converting the oracle into rings means pulling the right 3-or-more
accounts out of 672 and assigning them to the right ring — with no edge between them, since that
is what made the ring class (b) in the first place. The oracle assumes that assignment is free.

### Verdict (a): **REACH** — but the loss is at the aggregator, not the seeder

Both pre-registered conditions fire:

1. **≥ 25 % of class (b) rings with ≥ 3 members at the budget-matched tier**: **31.0 %** (10.2 of
   33.2) on `max_score`, **32.7 %** on `top3_sum`. ✓
2. **member hit rate ≥ 2× the degree-matched null**: 38.0 % against 0.06 %, **633×**. ✓

The bounded prize is **7.8 class (b) rings per seed** — 24.0 % of class (b), **4.5 points of ring
recall** against 174 in-scope rings, about **five times** B15's residual policy prize of 1.6 rings
(≈ 0.9 points). Condition 1 clears its bar by 6 points, not by a wide margin; on `n_above_q99` it
would fail outright (11.6 %), so the verdict rests on the two score-magnitude aggregates and not on
the count-above-quantile one.

**The pre-registered verdict is REACH and it stands, but the wording "account-level seeding" no
longer describes the thing that would collect it.** There is nothing to seed differently: at a
comparable budget the account ranking *is* the edge ranking, by construction. What the diagnostic
found is that the shipped pipeline already selects 37.2 % of class (b)'s member accounts and
discards 44 % of its own in-window selection at the `min_size` step, because those accounts are not
connected to each other in the window — which is B13's fact arriving at a different stage of the
pipeline.

Two things follow, and the second is the binding one.

* The prize is **reachable in principle** — the accounts are in hand at the shipped budget.
* It is **not collectable by relaxing the filter**, because the same filter is what makes the kept
  set 96.3 % ring-pure. The 70.8 class (b) accounts sit inside 294.8 discards that are 63.5 %
  noise, so a blunt relaxation buys the rings at a precision cost of the same shape B15 already
  measured for the expansion floor (0.653 → 0.509) and validation already rejected.

**So the open question is a grouping question: given 672 selected accounts, 70.6 % of them on some
ring and with no edges between the relevant ones, can anything assign them to rings?** That is
exactly what (b) tests — and V3.0b (c) tests it again with everything else observable.

## (b) Embedding grouping

### Component structure — B13 from the other side

Connected components of each ring instance's in-window edge graph:

| pool | ring-instances | median edges | median components | multi-component | median largest component |
|---|---|---|---|---|---|
| class (b) | 166 | 3 | 2 | **54.2 %** | 2 |
| under-covered | 34 | 8 | **7** | **76.5 %** | 3 |

Class (b) by pattern, share multi-component: **STACK 97.8 %** (46 instances), **BIPARTITE 100 %**
(41), RANDOM 14.3 %, CYCLE 5.6 %, and **0 %** for FAN-IN, FAN-OUT, GATHER-SCATTER and
SCATTER-GATHER. The two patterns that make up 52 % of class (b) are precisely the two that arrive
in pieces. The under-covered rings are worse: a median 8 visible edges in a median 7 components.

### Cosine similarity, 198-dim `gine_causal` edge embeddings

| pool | population | pairs | p25 | median | p75 |
|---|---|---|---|---|---|
| class (b) | **same ring, cross-component** | 734 | 0.551 | **0.746** | 0.882 |
| | same ring, same component | 401 | 0.594 | 0.758 | 0.886 |
| | different ring | 734 | 0.496 | 0.676 | 0.812 |
| | score+time-matched random | 733 | 0.422 | 0.608 | 0.823 |
| under-covered | **same ring, cross-component** | 904 | 0.547 | **0.737** | 0.897 |
| | same ring, same component | 199 | 0.549 | 0.725 | 0.899 |
| | different ring | 904 | 0.545 | 0.732 | 0.872 |
| | score+time-matched random | 903 | 0.469 | 0.659 | 0.842 |

The four distributions sit on top of each other, and the separation that exists is in the wrong
place. Between the two populations the AUC actually compares — cross-component and different-ring
— the median gap is **0.070** for class (b) and **0.005** for under-covered. The widest gap
anywhere, 0.150, is between same-component pairs and the score+time-matched random null, i.e.
between ring traffic and ordinary traffic, which is the detector's edge score restated. Every
interquartile range spans roughly 0.33 and they overlap almost completely.

### AUC

| pool | comparison | AUC (mean ± sd over 5 seeds) |
|---|---|---|
| class (b) | **cross-component vs different ring** | **0.577 ± 0.068** |
| class (b) | cross-component vs matched random | 0.616 ± 0.069 |
| class (b) | *same*-component vs different ring | 0.603 ± 0.071 |
| under-covered | **cross-component vs different ring** | **0.524 ± 0.019** |
| under-covered | cross-component vs matched random | 0.592 ± 0.121 |
| under-covered | *same*-component vs different ring | 0.534 ± 0.037 |

Per seed, class (b) runs 0.502 / 0.530 / 0.558 / 0.636 / 0.658 and under-covered
0.498 / 0.520 / 0.520 / 0.534 / 0.548 — one class (b) seed sits at chance and none clears 0.66.

The third row of each block is the one that closes the question. **Edges of one ring that actually
share an account are no more similar to each other than edges of two different rings** (AUC 0.603
and 0.534). The disconnection is not what defeats the embedding; the embedding does not carry ring
identity at all. What it does carry is a weak "ring-like" quality — ring edges beat score-and-time
matched ordinary traffic at AUC 0.59–0.62 — which is the detector's own signal, already fully
exploited by scoring each edge.

### Verdict (b): **NOT SEPARABLE**

Both pre-registered conditions fail:

1. **AUC ≥ 0.75 vs different-ring**: **0.577** (class b), **0.524** (under-covered). ✗
2. **AUC ≥ 0.70 vs the score+time-matched null**: **0.616**, **0.592**. ✗

And the bar was already generous. Grouping 672 selected accounts into rings means scoring on the
order of 2 × 10⁵ candidate pairs to find the few hundred real ones; at AUC 0.58 that produces a
candidate set dominated by wrong pairs at any threshold that keeps a useful share of the right
ones. There is no operating point to argue about.

## Joint reading

The two results are one result. (a) says the material for roughly **7.8 class (b) rings per seed**
is already inside the shipped 0.1 % selection and is discarded for want of connectivity. (b) says
the shipped embedding offers **nothing** with which to reconnect it — not for the disconnected
pieces, and not even for edges of one ring that do touch.

So the prize named in (a) is real and is bounded above at ~4.5 points of ring recall, and **the
route to it is not open with the artefacts in this repository**. Collecting it needs a grouping
signal that does not exist yet: not a different seed budget (B14), not topology in the window
(B13/CLASS_B_COMPOSITION), not history (B16), and not the current representation (this step).

## Limitations, stated plainly

* The oracle in (a) assumes each tier account is assigned to the correct ring at no cost, and that
  a ring's prediction is exactly its selected members (purity 1). It is an upper bound and is used
  as one. No achievable number is claimed.
* (a)'s budget-matched `max_score` tier is identical to the shipped seed-account set **by
  construction**; the 38.0 % and 7.8 figures describe the shipped selection, not a new one.
* (b) tests the **shipped** `gine_causal` edge embeddings exactly as saved. A representation
  trained with a ring-identity objective is a different model and is not ruled out by this — it is
  simply not what was measured. Nothing here licenses a claim about representations in general.
* 45.8 % of class (b) ring-instances are a single in-window component and contribute no
  cross-component pairs; (b)'s positives come from the other 54.2 %.
* Pair counts are modest (734 and 904 positives over 5 seeds) and capped at 200 per ring-instance,
  so the per-seed AUC sd of 0.07 is real spread and not a rounding artefact.
* Everything is measured on the primary window under `test_visible`. C9's scope caveat applies
  unchanged: under `full_membership` the member sets and therefore the oracle counts would differ.

## Nothing was chosen on test

No model was trained, no threshold swept, no parameter selected. The seed budget (0.1 %), the
window, the scope policy and the `full` runs are all taken from the shipped configuration. Both
verdicts were written to this file before `evaluation/v3_diagnostics.py` existed in runnable form.

## What is not done, and is waiting for a decision

Listed, not started:

1. **Locate the discard exactly.** (a) shows 294.8 accounts per seed selected and dropped, but not
   which rule drops them — `min_size` 3, the component split, or `max_gap_hours`. A one-pass count
   over the shipped runs would attribute the 294.8 to each. Cheap; pure measurement. *(Done in
   V3.0b part (c1) below.)*
2. **Price the relaxation.** This step measured the *composition* of the discard (63.5 % non-ring)
   but did not run the pipeline with the filter relaxed, so the ring-precision cost is inferred
   from B15's analogous sweep rather than measured. A forced-retention run at fixed budget would
   measure it directly.
3. **Non-embedding grouping signals.** (b) rules out cosine on the shipped embedding. It says
   nothing about shared counterparties one hop outside the ring, bank/currency/payment-format
   co-occurrence, or amount-and-time coincidence between selected accounts. Each is a measurement
   on existing artefacts, and each would be a *new* pre-registration.
4. **The validation window.** Both diagnostics ran on test. Reproducing them on the val window
   (days 6–7) would show whether the 37.2 % / 0.577 numbers are stable, and is the only honest way
   to develop anything against them. *(Oracle half done in V3.0b part (c2) below.)*
5. **`full_membership` sensitivity for the oracle**, per C9 — the oracle count in (a) is the one
   number here most exposed to the scope convention.
6. **MEGA.** Everything above is `gine_causal` only. MEGA's class (b) is 24.0 rings/seed and its
   embeddings exist in `experiments/R6_mega`; whether the (b) AUC is a property of this detector or
   of the task is untested.

Items 1, 3 and half of 4 are taken up by part (c) below. Items 2, 5 and 6 are not started.

---

# (c) Fragment linking — V3.0b

Measurement only. No linker is built and shipped, no parameter is chosen on test. Source:
`evaluation/v3b_fragment_linking.py`.

Parts (a) and (b) leave one question. The accounts of **7.8 class (b) rings per seed** are already
inside the shipped selection and are discarded because their pieces do not connect; the shipped
embedding cannot tell which pieces belong together. Part (c) asks whether **anything else
observable** can — time, amount, currency, payment format, bank, shared counterparties, graph
distance, GFP structure — and whether the combination is strong enough to justify building a
linker.

## Pre-registration — written 2026-09-30, before any of part (c) ran

**No number below this heading existed when this section was written.** The script was
unimplemented. The pipeline reproduction it rests on was verified first (seed 1 test: 864 seeds,
1,028 included edges, 203 components, 108 rings, member sets identical to the shipped
`rings.parquet`), but nothing in (c1)–(c4) had been computed.

### What is measured

**(c1) Where the discards go.** Per seed, the discarded seed-touched accounts attributed to the
rule that drops them: components of 1 graph edge / 2 accounts; components below `min_size` for any
other reason; and everything else (which can only be the partition stage — a cluster that falls
below `min_size` after `average` linkage and is not rescued by `reattach_small`). Ring vs non-ring
composition per category.

**(c2) Validation reproduction.** The same pipeline on the val window (days 6–7) at each seed's
own val-chosen cut: how many val truth rings have ≥ 3 members and ≥ half the ring inside the
seed-touched account set while no prediction touches them. Any linker would be tuned on
validation, so the oracle it would be tuned against has to exist there.

**(c3) Linking signals.** A **fragment** is a dropped component — a connected component of the
included (seed + expanded) edges that yields no ring. All fragment pairs within **72 h** of each
other are candidates. A pair is **positive** when both fragments belong to the same truth ring.
Negatives are split into **different-ring**, **ring–nonring** and **nonring–nonring**. Per signal,
AUC of positive against each negative type:

| signal | |
|---|---|
| time gap | seconds between the fragments' edge-time intervals |
| amount similarity | ratio of median amounts; shared round-number structure |
| currency / payment format | same receiving currency; same payment format |
| bank overlap | Jaccard of the fragments' account bank sets |
| shared counterparty | count of accounts adjacent to both, **anywhere in the 18-day graph**, no temporal constraint |
| hop distance | undirected distance in the full graph, capped at 4, no temporal constraint |
| GFP cosine | cosine between the fragments' mean GFP feature vectors |

B16's *temporal* historical walk is not re-tested here; the shared-counterparty and hop-distance
signals are deliberately atemporal, which makes them strictly more permissive than B16's.

Then a gradient-boosted classifier on all signals combined, **grouped CV by ring**, **trained on
training-window fragments** built the same way from the cross-scored seeds
(`experiments/R4_partition/included_train.parquet`: 3,251 within-fold 0.1 % seeds, 3,408 included
edges, 2,009 components). Pooled AUC and AUC-PR with fold spread.

### The bars, fixed in advance

**BUILD** — a fragment linker is worth implementing — only if **both**:

1. **Combined AUC-PR ≥ 5× the positive base rate** among candidate pairs. AUC-PR is scale-free
   only against its own base rate; a ratio below 5 on a base rate this low is a classifier that
   looks good by AUC and is useless at any threshold.
2. A **greedy linker at a 0.5 probability cut**, on the **training window**, recovers **≥ 5 of the
   oracle-bound rings per seed-equivalent** at **≥ 80 % link precision**. One seed-equivalent =
   one construction over one window at the shipped 0.1 % budget; the train construction is one
   such run, so the raw count is the number the bar is read on, and a seed-budget-normalised count
   is reported beside it.

If **either** fails, the fragments are **not linkable with observable signals**, and that goes in
the ceiling section as the explanation for why half of class (b) is lost — the missing half being
the part (a) oracle that no grouping rule can collect.

Both bars are read on the **training window**, never on test. Test fragments are described, and
the per-signal AUCs are reported for both windows, but nothing is selected on the test numbers.

---

## (c) Results

Run 2026-09-30, `python evaluation/v3b_fragment_linking.py`, RNG seed 20260930. Tables:
`results/tables/v3b_discard_attribution.csv`, `v3b_val_oracle.csv`, `v3b_signal_auc.csv`,
`v3b_linker.csv`, `v3b_fragment_linking.json`.

**The pipeline is reproduced, not approximated.** Seed 1, test split: 864 seeds, 1,028 included
edges, 203 components, 108 rings, and the member sets are **identical** to the shipped
`rings.parquet`. The script refuses to run if that check fails.

### (c1) Where the discards go

All 1,474 discarded seed-touched accounts over 5 seeds (294.8 per seed; 166 / 226 / 136 / 421 /
525):

| rule | per seed | share of discard | of which on an in-scope ring |
|---|---|---|---|
| **component of 1 graph edge / 2 accounts** | **290.8** | **98.6 %** | 36.1 % |
| component below `min_size` for another reason | 4.0 | 1.4 % | 65.0 % |
| cluster below `min_size` after partition | **0.0** | **0 %** | — |
| edge dropped by the partition | **0.0** | **0 %** | — |
| anything else | **0.0** | **0 %** | — |

**One rule accounts for the whole discard.** 98.6 % of it is a seed edge that landed alone: two
accounts, one transaction, nothing expansion could attach, and `min_size` 3 removes it. The
remaining 1.4 % is the same rule reached through a self-loop (8 accounts in single-account
components, 12 in 2-account components carrying a self-loop alongside a real edge). **The
partition stage discards nothing at all** — `average` linkage plus `reattach_small` never leaves a
cluster below `min_size`, on any of the 5 seeds.

That answers the open item from part (a) and has one useful consequence: on the training window,
where no partition labels were stored, defining a fragment by the `min_size` component rule is not
an approximation — it is the same rule, and it is the only one that fires.

### (c2) Validation reproduction

The same pipeline on the val window (days 6–7), each seed at its own val-chosen cut. Val has no
tail, so all **966** seeds fall inside the window (against 463 of 864 on test):

| seed | truth rings | matched | class (b) | ≥ 3 members in seed accounts | **oracle ≥ 0.5 bar** |
|---|---|---|---|---|---|
| 1 | 157 | 89 | 15 | 10 | **10** |
| 2 | 157 | 88 | 16 | 10 | **10** |
| 3 | 157 | 88 | 12 | 7 | **7** |
| 4 | 157 | 88 | 13 | 8 | **8** |
| 5 | 157 | 78 | 19 | 9 | **9** |
| **mean** | 157 | 86.2 | **15.0** | **8.8** | **8.8** |

**The oracle exists on validation, at 8.8 rings per seed** — comparable to test's 7.8, on a
smaller class (b) (15.0 against 33.2, because val spends all 966 seeds inside its window). So a
linker would have something to tune against without touching test.

One structural difference worth recording: on val, **every** class (b) ring with ≥ 3 members in
the seed-account set also clears the ≥ half bar (the two columns are equal on all 5 seeds),
whereas on test 10.2 rings reach 3 members and only 7.8 clear half. Val's class (b) rings are
smaller relative to what the seeds capture.

### (c3) Linking signals

**Fragments.** Train: 1,792 dropped fragments, **144 on a truth ring**, giving **1,038,786**
candidate pairs within 72 h and **295 positives** — a base rate of **2.84 × 10⁻⁴**. Test:
102 / 133 / 90 / 232 / 283 fragments per seed (65–85 on a ring), 3,987–39,628 candidate pairs,
51–75 positives, base rates 1.8 × 10⁻³ – 1.4 × 10⁻².

Neighbourhoods are small — median |N1| 7–9 accounts, median |N2| 34–44 — and no fragment came near
the 40,000 cap, so the graph signals are exact, not truncated. They were verified against direct
set intersection on 300 sampled pairs: **0 mismatches** on hop distance, shared-counterparty count,
bank Jaccard and currency.

**Per-signal AUC, positive against each negative type** (test, mean over 5 seeds; `max dev` is the
largest distance from chance in the row):

| signal | vs different-ring | vs nonring–nonring | vs ring–nonring | max dev |
|---|---|---|---|---|
| GFP cosine | 0.531 | 0.594 | **0.612** | 0.112 |
| amount ratio | **0.405** | 0.464 | 0.497 | 0.095 |
| time gap | 0.543 | 0.439 | 0.512 | 0.061 |
| same payment format | 0.500 | 0.559 | 0.533 | 0.059 |
| same currency | 0.525 | 0.498 | 0.518 | 0.025 |
| **hop distance** | 0.481 | 0.519 | 0.507 | **0.019** |
| min round level | 0.498 | 0.486 | 0.494 | 0.014 |
| bank Jaccard | 0.500 | 0.505 | 0.504 | 0.005 |
| **shared counterparty** | 0.500 | 0.504 | 0.504 | **0.004** |
| same round level | 0.500 | 0.499 | 0.500 | 0.001 |

On the training window the best single signal is the **time gap** at 0.705 against ring–nonring
(max dev 0.205), with amount ratio at 0.674 against nonring–nonring.

Three things in this table matter more than the headline numbers.

* **The two graph signals are dead.** Shared counterparty is 0.500–0.504 and hop distance
  0.481–0.519 — both within 0.02 of chance, against *every* negative type, and both were measured
  with **no temporal constraint at all**, which makes them strictly more permissive than B16's
  historical walk. Two pieces of the same ring are no closer in the 18-day graph than two pieces
  of different rings. 84 % of test candidate pairs are more than 4 hops apart.
* **Amount ratio points the wrong way** (0.405 against different-ring): fragments of the *same*
  ring have *less* similar amounts than fragments of different rings. Within a laundering pattern
  the amounts step down through the chain, while unrelated fragments drawn from the same heavy
  tail look alike.
* **The signals that move are the ones that identify "ring-ish traffic", not "this ring".** GFP
  cosine and payment format are strongest against **nonring** negatives (0.594, 0.559) and weakest
  against **different-ring** (0.531, 0.500) — the same shape part (b) found in the embedding.

**Combined model.** `HistGradientBoostingClassifier` on all ten signals, 5-fold GroupKFold grouped
by ring, trained on the training window:

| | |
|---|---|
| pooled out-of-fold AUC | **0.6923** |
| per-fold AUC | 0.682 / 0.731 / 0.772 / 0.778 / 0.808 |
| **AUC-PR** | **0.000526** |
| positive base rate | 0.000284 |
| **AUC-PR / base rate** | **1.85×** |
| per-fold AUC-PR | 0.00043 – 0.00213 |

### (c4) The bars

**Bar 1 — AUC-PR ≥ 5× the base rate: FAILS at 1.85×.**

**Bar 2 — greedy linker at p ≥ 0.5 recovering ≥ 5 oracle rings at ≥ 80 % link precision: FAILS,
0 links.** The maximum out-of-fold probability the model ever assigns is **0.0083**, so the 0.5 cut
is never reached. That alone would be an uninformative failure — at a base rate of 2.8 × 10⁻⁴ a
calibrated classifier has no reason to emit 0.5 — so the ranking was swept instead. This sweep is
a **diagnostic, not an operating point anyone chose**:

| operating point | links | link precision | rings matched (J ≥ 0.5) | oracle rings recovered |
|---|---|---|---|---|
| **p ≥ 0.5 (the bar)** | **0** | — | **0** | **0** |
| p ≥ 0.01 | 0 | — | 0 | 0 |
| p ≥ 0.005 | 2 | 0.000 | 0 | 0 |
| top 50 | 50 | **0.000** | 2 | 0 |
| top 100 | 100 | **0.000** | 4 | 0 |
| **top 295** (= the number of true pairs) | 295 | **0.000** | 4 | 0 |
| top 500 | 500 | 0.002 | 2 | 2 |
| top 2000 | 2000 | 0.0005 | 0 | 4 |

**Not one of the 295 highest-scoring pairs is a true same-ring pair.** The pooled AUC of 0.69 is
earned in the bulk of the distribution, where it is worthless; the head of the ranking, which is
the only part a linker would ever act on, is pure noise. The handful of "rings matched" at the
top-k points are not recoveries: with link precision 0.000 they are a single ring fragment merged
with unrelated junk into a group that happens to cover half of a small ring.

Of the **11 oracle-bound rings available on the training window**, the linker recovers **0** at
every operating point.

### Verdict (c): **NOT LINKABLE**

Both pre-registered bars fail, and the second fails by a margin that no threshold choice could
close. **The discarded fragments are not linkable with observable signals.**

This is the same finding as (b) reached with everything else the data offers. Part (b) ruled out
the detector's learned representation; part (c) rules out time, amount, round-number structure,
currency, payment format, bank, shared counterparties anywhere in the 18-day graph, atemporal
graph distance up to 4 hops, GFP structure, and every combination a gradient-boosted model can
find among them.

## For the ceiling section

**Why class (b) is lost, in one line:** the pipeline selects 37.2 % of class (b)'s member accounts
and then discards them — 98.6 % of the discard through a single rule, `min_size` on a lone seed
edge — and **nothing observable reconnects the pieces**. The part (a) oracle bounds what perfect
regrouping would be worth at **7.8 rings per seed on test (24 % of class (b), 4.5 points of ring
recall)** and **8.8 per seed on validation (59 % of class (b))**. That bound is not reachable:

| route | ruled out by |
|---|---|
| a different seed budget or allocation | B14 |
| topology inside the window | B13, `CLASS_B_COMPOSITION` |
| history, via temporal paths | B16 |
| the detector's edge embedding | V3.0 (b), AUC 0.577 |
| time, amount, currency, format, bank, counterparties, graph distance, GFP, and their combination | **V3.0b (c), AUC-PR 1.85× base, 0 of 11 oracle rings** |

The remaining honest routes are the two C9 already named — a different **evaluation unit**
(`full_membership`, or attempt-level rather than window-level reporting) — or a **representation
trained for ring identity**, which is a new model and not a gap in the current one.

## Limitations of part (c)

* **295 positives** on the training window and 51–75 per test seed. The per-fold positive counts
  run 26–161, which is why the fold AUC spread is 0.68–0.81. A stronger signal could hide under
  this much noise only if it were confined to a handful of rings.
* The training-window fragments come from `included_train.parquet`, whose expansion used the
  out-of-fold policy and whose seeds are within-fold 0.1 % — the same construction, but a
  different fold structure from the test run. (c1) shows the `min_size` rule is the only one that
  fires, so the fragment *definition* transfers exactly; the fold structure does not.
* The affinity model used in the test reproduction was trained on train-split pairs. That affects
  which components get *split*, and (c1) shows the partition splits nothing away, so it does not
  touch the fragment set — but the train and test constructions are not independent of each other.
* A pair's CV group is the first ring id it involves, so a different-ring negative spans two
  groups and is assigned to one of them. Non-ring pairs are spread round-robin. This leaks
  slightly in the optimistic direction, which does not threaten a negative result.
* `same_round_level` and `min_round_level` are computed on **cents**, because only 1.3 % of
  HI-Small amounts are whole units and 0.014 % are multiples of 100 — a divisibility test on the
  unit scale is identically zero on this data and carries no information.
* Everything is `gine_causal`. MEGA is untested here, as in (a) and (b).

## Still not done

1. **Price the relaxation** (unchanged from part (a)): the ring-precision cost of retaining the
   294.8 discarded accounts is still inferred from B15 rather than measured by a run.
2. **`full_membership` sensitivity** for the (a) and (c2) oracle counts, per C9.
3. **MEGA** for all three parts.
4. **A ring-identity representation.** Part (b) and part (c) together say the information is not
   in any *shipped* feature. Whether a metric-learning objective over edge pairs could put it
   there is a new model and a new pre-registration, not a measurement on these artefacts.
5. **The `min_size` rule itself.** (c1) shows one rule causes the whole discard. Whether
   `min_size` 2 with a stricter score cut trades better than `min_size` 3 at the shipped budget is
   a single grid point that has never been run — and it would have to be chosen on validation.

Nothing in this list is started. No commit.
