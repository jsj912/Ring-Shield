# Class (b) composition — what the untouched rings are made of (Step 14.5a)

Measurement only. No miner is built, nothing is tuned, nothing is chosen on test.

Class (b) is the largest block of unmatched rings after those with < 3 visible members (not a
`min_size` ceiling: FINDINGS B7/B9, corrected): truth rings with ≥ 3 visible
members that **no included edge of any prediction touches** — 33.2 per seed for the shipped
pipeline, 24.0 for MEGA (`FINDINGS.md` B8). B16 established that history does not reconnect them.
This describes them, so that any later decision about a structural seeder rests on what the targets
actually look like.

Source: `evaluation/class_b_composition.py`, shipped `full` runs, 5 seeds, primary window,
`test_visible`. Amount tolerance is the roles module's τ = 0.25, unchanged; Δt is each run's own
val-chosen value.

## 1. Composition by pattern

| pattern | gine class (b)/seed | share of class (b) | in-scope rings | share of in-scope | over-representation |
|---|---|---|---|---|---|
| **STACK** | **9.2** | 27.7 % | 22 | 12.6 % | **2.19×** |
| **BIPARTITE** | **8.2** | 24.7 % | 16 | 9.2 % | **2.69×** |
| RANDOM | 4.2 | 12.7 % | 17 | 9.8 % | 1.29× |
| CYCLE | 3.6 | 10.8 % | 22 | 12.6 % | 0.86× |
| GATHER-SCATTER | 3.4 | 10.2 % | 37 | 21.3 % | 0.48× |
| FAN-IN | 2.4 | 7.2 % | 18 | 10.3 % | 0.70× |
| FAN-OUT | 1.2 | 3.6 % | 20 | 11.5 % | 0.31× |
| SCATTER-GATHER | 1.0 | 3.0 % | 22 | 12.6 % | 0.24× |
| **total** | **33.2** | | 174 | | |

**STACK and BIPARTITE together are 17.4 of 33.2 — 52 % of class (b)** — and both are
over-represented by a factor of 2.2–2.7 against their share of the in-scope population. The
patterns the pipeline handles well (GATHER-SCATTER, FAN-OUT, SCATTER-GATHER) are correspondingly
under-represented at 0.24–0.48×.

### Where MEGA's 9.2-ring advantage comes from

| pattern | gine | mega | difference |
|---|---|---|---|
| CYCLE | 3.6 | 1.6 | **−2.0** |
| BIPARTITE | 8.2 | 6.6 | −1.6 |
| FAN-IN | 2.4 | 1.2 | −1.2 |
| GATHER-SCATTER | 3.4 | 2.2 | −1.2 |
| FAN-OUT | 1.2 | 0.2 | −1.0 |
| RANDOM | 4.2 | 3.2 | −1.0 |
| **STACK** | **9.2** | **8.6** | **−0.6** |
| SCATTER-GATHER | 1.0 | 0.4 | −0.6 |

The gap is **broad, not concentrated** — no pattern contributes more than 2.0 rings, and the
largest class (STACK) barely moves. A better detector reaches a few more of everything; it does not
unlock a pattern.

## 2. Shape in the primary window

Per class (b) ring, over its **visible** edges only (166 gine ring-instances):

| pattern | n | median members | median edges | max directed path | rings with a ≥3-hop conserving chain | rings with a ≥2×2 bipartite block |
|---|---|---|---|---|---|---|
| STACK | 46 | 7 | 4 | 2 | **0** | **0** |
| BIPARTITE | 41 | 6 | 3 | 1 | **0** | **0** |
| RANDOM | 21 | 4 | 3 | 3 | 6 | 0 |
| CYCLE | 18 | 3 | 2 | 6 | 3 | 0 |
| GATHER-SCATTER | 17 | 3 | 2 | 1 | 0 | 0 |
| FAN-IN | 12 | 5 | 4 | 1 | 0 | 0 |
| FAN-OUT | 6 | 6 | 5 | 1 | 0 | 0 |
| SCATTER-GATHER | 5 | 5 | 6 | 2 | 0 | 0 |

**The median longest directed path is 1 hop, and 110 of 166 ring-instances (66 %) have no directed
path longer than a single edge.** The median ring shows **0.67 edges per visible member** — its
visible transactions are mostly disjoint. Nine of 166 have a conserving ≥3-hop chain (all CYCLE or
RANDOM). **Not one has a 2 × 2 complete bipartite block — including the 41 BIPARTITE instances**,
whose median 6 members appear across a median 3 edges.

## Verdict

**Class (b) is concentrated in STACK and BIPARTITE (17.4 of 33.2, 52 %, over-represented 2.2–2.7×)
— and a structural seeder still has no target, because the structure those patterns are named for
is not present in the window.**

Both halves of the pre-specified verdict fire, and the second one governs. The concentration is
real and would, on its own, point a miner at chains and bipartite blocks. The shape measurement
says there is nothing there to find: STACK rings show a maximum directed path of **2 hops** and
**zero** conserving chains; BIPARTITE rings show a maximum path of **1 hop** and **zero** 2 × 2
blocks. A ring whose visible edges are a scatter of disjoint transactions has no topology to key
on, whatever its label says.

This is the same fact as B13 and B16 seen from the other side. Those rings are not missed because
the seeder is weak — they are **not present as objects** in the evaluation window. A structural
miner would have to detect a chain from one visible link, which is not a structural signal but a
per-edge one, and that is the detector's job, already measured.

**The line is closed.** The route worth naming as future work is not a better seeder but a
different evaluation unit — scoring a ring against evidence spanning the splits
(`full_membership`, C9) or reporting at the attempt level rather than the window level. Both change
the protocol, not the model.

## What this step did not do

No miner was built or tuned. No parameter was chosen. The amount tolerance (τ = 0.25) and Δt are
taken from the shipped configuration and were not swept — if a later step wants to claim that a
conserving chain exists at some *other* tolerance, that sweep has to be run and pre-registered, and
it would be choosing a structure detector's threshold on data this step only described.
