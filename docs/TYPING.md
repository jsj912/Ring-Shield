# Stage D — roles and topology typing (Step 8, R5)

Status 2026-09-22: 8.1–8.4 implemented (`ringshield/roles.py`, `ringshield/typing/`), the rings
contract extended to **v1** and `contract/out/rings_full_gine_causal_<S>.parquet` produced for
seeds 1–5 with every field filled. Nothing chosen on the test period: the typing head variant was
selected on the validation split's ground-truth rings. **Headline: filling the fields changed no
membership (primary ring-F1 0.5895 ± 0.0371, the R4 `average` row reproduced to 1e-9), the rule
scorer clears its sanity bound on true train rings (0.783 ≥ 0.60), and typing accuracy on matched
primary-window rings is 0.21 (head) / 0.20 (rule) — the two-day window, not the classifier, is
what makes it hard (see "Why typing is hard here").**

## 8.1 roles and `rerun_ring` — `ringshield/roles.py`, `configs/roles.yaml`

`account_roles(ring, scored_edges) -> {account: {role, inflow, outflow, hold_time_s, closure,
n_in, n_out}}` over the ring's edges inside `[start_time, end_time]`, amounts **deduplicated** on
(from, to, timestamp, amount). Five roles with `tau_role` 0.25 and a 72 h hold (`configs/roles.yaml`,
the same constants the Step 7 pair features use, so the role a pair feature sees and the role the
contract reports are one thing):

| role | rule |
|---|---|
| source | no inflow, or inflow / outflow < τ |
| sink | no outflow, or outflow / inflow < τ |
| mule | both flows, closure ≥ 1 − τ, median hold ≤ 72 h |
| holder | both flows, closure ≥ 1 − τ, held longer |
| peripheral | both flows, unbalanced with neither side dominant |

`rerun_ring(subgraph_edges, aggregator_id) -> {confidence, n_rings, largest_ring_edges}` re-runs
**only the grouping stage** on the edges handed to it — `cc`: components + size filter; `full`:
shared-account pairs, the affinity, average linkage at the val-chosen cut, fragments re-attached.
It never expands and never reads the split: the XAI layer calls it once per edge for
leave-one-out. Deterministic, and `tests/test_roles_typing.py` asserts the 50 ms budget:

| ring size | `full` | `cc` |
|---|---|---|
| 10 edges | 29 ms | 6 ms |
| 30 edges | **37 ms** | 6 ms |
| 60 edges | 40 ms | 7 ms |

Getting there needed two changes: summarising the groups directly instead of building full `Ring`
records (160 → 64 ms), and vectorising `roles.flows_of` and the Step 7 `pairs.account_roles` /
`pair_features` (64 → 37 ms; per-account python loops and column-by-column DataFrame inserts were
the cost). The partition results are unchanged by that refactor — `contract/make_rings_full.py`
re-asserts every seed against the R4 run.

## 8.2 features and the rule scorer

`ringshield/typing/features.py` — 30 features per ring: role counts and fractions; size, duration,
density, transactions per member; longest directed path, cycle presence and cover, bipartite score
and smaller side, degree summary, branch points, leaf fraction; **fragmentation** (components,
largest-component fraction, 2-account pieces, pass-through accounts, in/out/both hubs); and
`seed_ratio`.

`ringshield/typing/rules.py` — the 8-way hand-written scorer. **The first version was wrong.**
Written from the idealised shapes (one sink and ≥ 3 sources for FAN-IN, a single mule for
GATHER-SCATTER, …) it scored **0.336** on true train rings, well under the 0.60 sanity bound.
The reason is that a ring visible in one split is a *fragment* of its pattern: a 45-account STACK
arrives as seven short chains, a BIPARTITE as six disjoint pairs, a GATHER-SCATTER often as its
gather half alone. Rewritten on the fragment's account graph — degrees, pass-throughs, pieces —
it scores **0.783** (check 1 passed; `tests/test_roles_typing.py` asserts ≥ 0.60):

| | BIPARTITE | CYCLE | FAN-IN | FAN-OUT | GATHER-SCATTER | RANDOM | SCATTER-GATHER | STACK |
|---|---|---|---|---|---|---|---|---|
| rule recall on true train rings | 1.00 | 0.58 | 1.00 | 1.00 | 0.63 | 0.38 | 0.76 | 0.75 |

## 8.3 the typing head

`ringshield/typing/head.py` — LightGBM 8-way, grouped (stratified) 5-fold CV by ring id, trained
on train-visible ground-truth rings with ≥ 3 visible members plus the **recovered** train rings
(`ringshield/typing/recovered_rings.py`: the train included edges partitioned exactly as `full`
does, each ring matched to the truth ring it overlaps most, 187 rings, mean Jaccard 0.54 —
the shape as the aggregator sees it).

Two variants, selected on **val** (the validation split is two days, the same fragment size the
primary window has; `experiments/R5_typing/chosen_head.json`):

| head | trained on | train rows | own OOF accuracy | **val truth rings (114)** |
|---|---|---|---|---|
| `head` | the whole 6-day train split + recovered | 330 | 0.600 (rule on the same rows 0.506) | 0.500 |
| **`head_w2` (chosen)** | train sliced into 2-day windows + recovered | 398 | 0.558 (rule 0.420) | **0.509** |
| rule scorer | — | — | — | 0.439 |

## Why typing is hard here (and where the loss is)

Two separate losses, measured rather than assumed:

1. **Window length.** The same rule scorer gets 0.783 on 6-day train fragments, **0.531 on 2-day
   train windows** and 0.439 on the val split. Two days of a pattern is often one half of it:
   GATHER-SCATTER shows its gather half and looks like FAN-IN, SCATTER-GATHER shows its scatter
   half and looks like FAN-OUT, a CYCLE that has not closed yet is a chain. On the primary
   window's **ground-truth** rings (114 with ≥ 3 visible members) the rule scores 0.404 and the
   head 0.421 — that is the ceiling for any classifier reading a 2-day fragment.
2. **The predicted edge set.** On *matched* predicted rings accuracy falls further, to 0.207
   (head) / 0.207 (rule) with the chosen head. A Jaccard-0.5 account match does not mean the same edges: the
   prediction carries the member edges the aggregator included (seeds + expansions + licit
   traffic between members) and misses the quiet ones, so its shape differs from the pattern's.

Neither is a classifier problem, and that is the reportable finding: **ring typing on AMLworld is
bounded by the evaluation window, not by the model.**

**Measured in Step 9** (`results/tables/r5_typing_ci.csv`, bootstrap over matched rings):

| window | matched rings | head accuracy | 95 % CI | rule accuracy | 95 % CI |
|---|---|---|---|---|---|
| primary (days 8–9) | 401 | 0.219 | [0.182, 0.259] | 0.207 | [0.170, 0.249] |
| **whole (days 8–17)** | 433 | **0.594** | [0.547, 0.640] | 0.547 | [0.499, 0.591] |

The prediction holds: the same rings typed over the full ten-day test period are **2.7× more
accurate**, because the window no longer truncates a gather-scatter into a fan. Typing is
reported as a bounded-by-window result with the confusion matrix and this sensitivity; nothing
about it is chosen on test.

## 8.4 results — `results/tables/r5_typing.csv`

Typing on matched primary-window rings, pooled over 5 detector seeds (per-seed rows in the csv,
confusion matrices and per-class counts in `r5_typing.json`). **Check 2**: accuracy is reported on
matched rings only, with the full 8x8 confusion matrix.

| | matched rings | head accuracy | rule accuracy |
|---|---|---|---|
| seed 1 | 81 | 0.185 | 0.123 |
| seed 2 | 81 | 0.173 | 0.173 |
| seed 3 | 77 | 0.156 | 0.169 |
| seed 4 | 89 | 0.270 | 0.281 |
| seed 5 | 73 | 0.315 | 0.288 |
| **pooled (401)** | | **0.219** (macro-F1 0.155) | 0.207 (0.143) |

Per class (pooled; the counts matter more than the rates here, amendment d):

| true type | n | head recall | rule recall |
|---|---|---|---|
| FAN-OUT | 64 | **0.56** | 0.58 |
| FAN-IN | 56 | 0.30 | 0.41 |
| GATHER-SCATTER | 117 | 0.13 | 0.09 |
| SCATTER-GATHER | 78 | 0.17 | 0.08 |
| CYCLE | 42 | 0.12 | 0.05 |
| RANDOM | 35 | 0.03 | 0.14 |
| BIPARTITE | 5 | 0.00 | 0.00 |
| STACK | 4 | 0.25 | 0.00 |

Head confusion, rows = true, columns = predicted (pooled over seeds):

| | FAN-OUT | FAN-IN | G-S | S-G | CYCLE | RANDOM | BIPARTITE | STACK |
|---|---|---|---|---|---|---|---|---|
| FAN-OUT | **36** | 3 | 12 | 6 | 1 | 0 | 0 | 6 |
| FAN-IN | 11 | **17** | 15 | 9 | 2 | 1 | 0 | 1 |
| GATHER-SCATTER | 40 | 12 | **15** | 17 | 13 | 5 | 0 | 15 |
| SCATTER-GATHER | 11 | 17 | 12 | **13** | 9 | 3 | 0 | 13 |
| CYCLE | 13 | 6 | 6 | 4 | **5** | 2 | 0 | 6 |
| RANDOM | 3 | 10 | 6 | 4 | 7 | **1** | 0 | 4 |
| BIPARTITE | 2 | 1 | 1 | 0 | 1 | 0 | **0** | 0 |
| STACK | 1 | 0 | 1 | 0 | 1 | 0 | 0 | **1** |

Reading it: the errors are not spread at random. **GATHER-SCATTER loses 40 of 117 rings to
FAN-OUT and 12 to FAN-IN** -- the two-day window shows one half of the pattern and that half *is*
a fan. SCATTER-GATHER loses 17 to FAN-IN and 13 to STACK for the same reason. Only FAN-OUT, whose
fragment still looks like a fan, is typed better than chance-with-priors. BIPARTITE (5) and
STACK (4) have too few matched rings for a rate to mean anything -- the counts are given instead,
per amendment d. RANDOM is not the hardest class here (the box expected it to absorb the errors);
the fan classes absorb them, because a truncated pattern *is* a fan.

Rule vs head: the head is 0.012 better pooled (0.219 vs 0.207) and better on 3 of 5 seeds -- a
difference of five rings. On the training distribution the gap is real (0.558 vs 0.420 OOF on
2-day train windows, 0.509 vs 0.439 on val); on matched test rings both are bounded by the same
fragment problem, and neither should be reported as a working topology classifier.

## Rings without a closure (and what the XAI narrative must say)

`conservation_closure` is NaN for **5–6 rings per detector seed** (seed 1: 6 of 108; seed 2: 6 of
112; seed 3: 5 of 113; seed 4: 6 of 120; seed 5: 5 of 107) — rings with no source or no sink, i.e.
every account both sends and receives, which is what a closed CYCLE looks like. That is a
legitimate ring, not a defect, so `confidence` **drops the closure factor** for it and is the mean
`score_calibrated` over its seed edges alone; the count is in every run log as
`fields.conservation_closure.n_nan`. Mean closure over the rings that have one is 0.91–0.94.

Consequence for the XAI layer: the evidence narrative must have a branch for a missing closure
clause. "The ring moves X in and X out through its mules (closure 0.97)" cannot be generated for
these rings; the honest sentence is that the ring has no distinguishable source or sink — the
money circulates inside it — and the confidence is then carried by the detector scores alone.
Treating NaN as 0 would be wrong twice over: it would read as "nothing is conserved" and it would
drive confidence to zero for exactly the rings whose shape is most ring-like.

## The contract: rings.parquet v1

Changes from the Step-1/3c stub, for both teammates:

| field | before | **v1** |
|---|---|---|
| `expanded_edge_probs` | *did not exist* | **new column**: the expansion policy's probability per expanded edge, same order and length as `expanded_edges` (the XAI layer needs it — an expanded edge's own detector score is low by definition) |
| `expanded_edges` | always `[]` | the policy's additions around the seeds |
| `confidence` | "aggregator confidence" (mean edge score) | **mean `score_calibrated` over `seed_edges` × `conservation_closure`**; when the closure is NaN the factor is dropped and the ring is counted in the run log (`n_rings_closure_nan`) |
| `conservation_closure` | NaN | 1 − \|Σ inflow at sinks − Σ outflow at sources\| / max(both), clipped to [0, 1], over the ring's seed + expanded edges with deduplicated amounts; **NaN only when the ring has no source or no sink — 5 to 6 rings per seed** (of 107–120), typically a closed loop where every account both sends and receives |
| `topology_type` / `topology_probs` | `UNKNOWN` / uniform | the head's argmax and its 8 probabilities (TOPOLOGY_TYPES order, summing to 1) |
| `source_accounts` / `sink_accounts` / `mule_accounts` | `[]` | filled from `configs/roles.yaml` (`mule_accounts` = roles *mule* and *holder*; `account_roles()` returns the two separately) |
| `ring_id` / `tenant_id` | unchanged | `full-gine_causal-<seed>-<idx>`, tenant = sender bank of the earliest seed edge |

Everything else (members, member/seed edges, times, density, `max_edge_prob`) is unchanged, and
`contract/README.md` is regenerated from `contract/schema.py`. Files:
`contract/out/rings_full_gine_causal_{1..5}.parquet` with a `.log.json` each. The Step-1 stub
(`rings_stub_cc_step1_legacy.parquet`) and the 3c stub (`rings_stub_cc.parquet`) were regenerated
under the new schema; their ring contents are unchanged (178 and 98 rings).
