# Historical bridging — diagnostic before build (Step 14, item 1a)

## The argument

Candidate generation runs on the split's scored edges, so test-period expansion only ever sees
test-period edges. The detector does not work that way: the causal loader already samples the full
past, and in deployment an analyst on test day 9 can see days 0–8. Those transactions are
**observable**; only their labels are off-limits. Restricting expansion to in-window edges is an
artificial limitation corresponding to nothing real.

`FINDINGS.md` **B13** measured that **80.7 %** of the missing members of under-covered rings have no
path to the recovered fragment *inside the window* — STACK **140/140**. The path may exist through
earlier edges. At the val-chosen Δt = 24 h and `max_hops` 2, a day-9 seed reaches back into day 8;
at Δt = 72 h it reaches day 5, which is in the **train** split.

## Pre-registration — written 2026-09-29, before the diagnostic ran

**No number below existed when this section was written.** The walk had not been implemented.

### What is measured

Per pattern, over the shipped `gine_causal` `full` runs, 5 seeds, primary window:

| col | quantity |
|---|---|
| (a) | missing member edges of under-covered rings |
| (b) | **control** — how many are disconnected *in-window* (must reproduce B13) |
| (c) | how many connect when **history** may be traversed |
| (d) | bridge hops needed, and how far back in time the bridge reaches |
| (e) | how many bridging edges are **members of the same ring** vs unrelated traffic |
| (f) | **null** — the same walk from random non-ring fragments (see below) |

Plus: does a historical bridge connect any of the **33.2 per seed class-(b) untouched rings** to a
seed edge? That is the larger prize — 19 % of primary rings against the under-covered class's 6.8.

### Rules the walk must obey, by assertion

* every hop respects the run's own **val-chosen Δt**; no hop exceeds it;
* **timestamps are non-increasing into history** — the walk goes backwards from the fragment and
  never traverses an edge later than the fragment's latest seed (causality at detection time);
* the **Step 6 candidate cap** (`MAX_EVENTS_PER_QUERY = 500`) applies to historical hops exactly as
  it does to in-window ones;
* `max_hops` is reported at the shipped value **and** swept, so "how many hops would be needed" is
  separable from "how many the shipped configuration allows".

### The null, and why it is not optional

Day 0 alone holds **34 % of all training edges at ten times day 1's per-minute density**
(`FINDINGS.md` C8). A backward walk with a 24–72 h window through that graph will find paths
through hub accounts almost regardless of whether any laundering structure connects them — which is
exactly what the Step 6 cap exists to suppress. So column (f) runs the identical walk from
**random 3-account fragments of non-ring edges** toward randomly chosen target edges. If random
fragments "reconnect" at a similar rate to real ones, (c) is measuring the generator's density and
not the ring's structure.

### The verdict, fixed in advance

**BUILD** — 14.1b is worth implementing — if *all* of:

1. (c) for **STACK** exceeds **25 %** of its missing edges (against 0 % in-window today);
2. that rate is at least **3×** the null rate (f) for comparable fragment sizes;
3. (e) shows at least **half** of bridging edges are members of the same ring — the bridge is the
   laundering chain, not a coincidental hub path.

**DO NOT BUILD** — the ceiling is structural — if any of:

1. (c) for STACK is below **10 %**; or
2. (c) is within **2×** of the null (f); or
3. (e) shows bridges are predominantly unrelated traffic, **even if (c) looks good**.

Anything between those bands is reported as **inconclusive**, with the numbers and the reason, and
14.1b is not built on an inconclusive diagnostic.

**A class-(b) reconnection changes the calculus independently.** If a historical bridge reaches
untouched rings at a rate clearly above the null, that is worth building even if STACK fails its
band, and it is reported as its own result.

### Control check — nothing else is trustworthy without it

Column (b) must reproduce B13 **exactly**: 80.7 % overall and STACK 140/140. If it does not, the
walk is not measuring what B13 measured and no other column in the table can be believed.

---

## Result — DO NOT BUILD (2026-09-29)

`evaluation/historical_bridge.py`, 5 seeds, shipped `gine_causal full` runs, val-chosen Δt per
seed, `MAX_EVENTS_PER_QUERY = 500` applied to historical hops, graph = **all 5,078,345 edges,
days 0–17**.

### (b) Control

| | B13 | this run |
|---|---|---|
| missing member edges | 218 | **216** |
| disconnected in-window | **176** | **176** |
| share | 80.7 % | 81.5 % |
| STACK | **140 / 140** | **140 / 140** |

The disconnected count and the STACK row reproduce **exactly**. The denominator differs by **2 edges
(0.9 %)** because this script defines the recovered fragment as the prediction's `member_edges`
where B13 used `seed_edges + expanded_edges`; the two differ on two edges across 5 seeds. Stated
rather than smoothed — the gate asked for exact reproduction and this is 176/176 on the quantity
that matters, with a 2-edge denominator difference that changes no conclusion.

**No search was truncated** (0 of 2,503 walks hit the 400,000-visit budget), so "not reached" means
not reachable under the rules, not "we stopped looking".

### (c) Historical reach, under-covered rings, `max_hops` 2

| pattern | reached | share | bridge edges in the same ring | median hops | median reach-back |
|---|---|---|---|---|---|
| **STACK** | **0 / 140** | **0.0 %** | — | — | — |
| BIPARTITE | 0 / 24 | 0.0 % | — | — | — |
| CYCLE | 7 / 19 | 36.8 % | **1.00** | 1 | 25.5 h |
| GATHER-SCATTER | 19 / 31 | 61.3 % | **1.00** | 1 | 20.0 h |
| RANDOM | 1 / 2 | 50.0 % | — | 1 | 8.3 h |

Hop sweep, all under-covered: **12.5 %** at 2 hops, **16.7 %** at 3. **STACK is 0 / 140 at both.**

### (f) Null — permutation control

Keeping the real fragments and real target sets and destroying only their pairing: **0 / 216 =
0.0 %** reached. So the CYCLE and GATHER-SCATTER reach above is genuine structure, not the
generator's density — and every bridging edge on those paths is a member of the same ring
(share 1.00), which is what column (e) was for.

*(The first null drew random fragments toward random targets and returned 0.0 % trivially — in a
5 M-edge graph two random edges are unreachable by construction, so it could not have discriminated
anything. It was replaced before the run.)*

### Verdict against the pre-registered criteria

**DO NOT BUILD.** The rule was: do not build if (c) for STACK is below 10 %. **It is 0.0 %**, at
both 2 and 3 hops, with no truncation. The BUILD band required >25 %.

**The ceiling is structural.** STACK's missing members are not merely outside the evaluation
window — they are not reachable from the recovered fragment through the *entire* 18-day graph under
the expansion's own reachability rules. Widening the window does not help (B13: 99.6 % still
disconnected on `whole`), and neither does letting the walk traverse history. The chain is severed
in a way no in-graph walk from the recovered fragment repairs.

### Class (b) — reported, and not a route either

Untouched rings, walking from the **whole seed set**: **58 of 166 ring-instances (34.9 %)** make
contact with at least one member edge through history, median **20 %** of the ring reached.

Two reasons this is not a build signal. First, matching requires Jaccard ≥ 0.5, and reaching a
fifth of a ring does not come close. Second — and this is a confound in the measurement, not in the
idea — those walks start from **864 seed edges**, not a 3-edge fragment, so their reach is not
comparable to the under-covered column or to the null. The honest reading is that history makes
*contact* with a third of untouched rings and recovers enough of none of them.

### What this closes

Item 1 was the only remaining route with a plausible path to a materially higher ring-F1. Its own
diagnostic cancelled it, which is what §0.2 asks a diagnostic to be able to do, and 14.1b is not
built. The ceiling decomposition is now complete in a stronger form than before: rings below
`min_size`, rings no detector touches, and rings whose members are unreachable **from the recovered
fragment in the full graph** — not merely in the window.

