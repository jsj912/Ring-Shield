# Stage C — partition into attempts (Step 7, R4)

Status 2026-09-22 (updated at the Step 7 close: ceiling table, pre-registered sweep,
`_split_by_time` fix, CSGM provenance): 7.1–7.4 implemented (`ringshield/partition/`, `ringshield/aggregators/full.py`,
aggregator `full` in `run_rings.py` and the CLI), 26 runs (B2–B4, pivot, average × 5 detector
seeds; B5 once), `results/tables/r4_partition.csv`. Nothing chosen on the test period; every
evaluation is on the primary window. **Headline: the partition changes ring-F1 by +0.008 ± 0.005
over plain components (0.582 → 0.589), buying recall (+0.015) with precision (−0.020); check 3 is
not met on test (precision and mean Jaccard do not rise). The reason is in the data: at the
0.1 % operating point the primary window has ~4 hub-merged components per seed, and the
recall that is missing sits in 76 truth rings no prediction touches (median size 2).**

## Where the losses are (why this step has little to work with)

Before building anything, the B0 / R3 predictions were decomposed (seed 1, `scratchpad/diag_partition.py`):

| | val (B0) | test primary (R3 proposed) |
|---|---|---|
| predicted rings / matched | 110 / 76 | 90 / 79 |
| truth rings / matched | 157 / 76 | 174 / 79 |
| unmatched truth rings **untouched by any prediction** (any size; see the ceiling table for the split by class) | 48 | **76** |
| unmatched truth rings touched by a prediction | 33 | 19 |
| predictions holding > 1 truth ring | 8 (6 matched), 35 rings inside | **4 (all matched), 19 rings inside** |
| unmatched predictions with 1 truth ring, Jaccard < 0.5 | 24 (size 3, best J 0.13) | 10 (size ~3, best J 0.2) |

Chaining through hubs is a val phenomenon (8 components holding 35 rings) and rare on test
(4 holding 19, and all four already count as one match each). The test recall loss is dominated
by rings with 2 visible members — invisible to every aggregator under `min_size` 3 — and by rings
no seed lands on at all; the ceiling table below quantifies both. The Step 6 write-up's
expectation ("Step 7 is where the larger gain lives") was right for val and wrong for test;
corrected there.

## 7.1 pairs — `ringshield/partition/pairs.py`

`pair_features(idx, gfp, inc_pos, is_seed, comp, emb_of=…, ring_id=…)`: within an expanded
component (components of the account graph of seeds + expanded edges, `components_of`), every two
included edges sharing an account; earlier edge = `a`. 20 features (`PAIR_FEATURES`): time gap;
amount ratio min/max; direction pair at the shared account (in→out, out→out, in→in, out→in);
embedding cosine; GFP cosine (log1p vectors); kind (seed/seed, seed/expanded, expanded/expanded);
shared-account role over the component's included edges at that account — mule if both flows,
closure ≥ 1 − τ (τ_role = 0.25) and an inflow followed by an outflow within 72 h; source if
inflow/outflow < τ; sink if outflow/inflow < τ; other (hub-like) — with the closure, the number of
included edges and distinct counterparties at the account and log1p of the account's stream
events inside the component's time span; on-chain flag (inflow then outflow within 72 h,
amount ratio ≥ 0.75). Label = both edges carry the same `ring_id` > 0; grouped by component.

**Training pairs** (`make_pairs_training_set.py`): train-split components built the way the
pipeline builds them — seeds = the within-fold 0.1 % cut of the cross-scores, expanded = the 6.3
candidate rows whose *out-of-fold* policy probability is ≥ 0.7 (the R3 val-chosen p_min):
3,408 included edges (3,251 seeds + 157 expanded, 145 of them members) in 2,009 components, 11
with more than one ring, 535 with any pair. **10,439 pairs, 4,141 same-ring (39.7 %)**; by kind
seed/seed 9,223 (3,107 +), seed/expanded 1,042 (874 +), expanded/expanded 174 (160 +); by role of
the shared account source 1,722 (78 % +), sink 6,010 (29 % +), mule 1,482 (26 % +), other 1,225
(57 % +). Embeddings for a pair come from the fold model of the earlier edge applied to both
edges (every included edge exported under every fold model, `cross_score.py --embed-edges`,
0 NaN cosines).

## 7.2 affinity and clustering — `ringshield/partition/affinity.py`

LightGBM as in Step 6, grouped 5-fold CV by component, `scale_pos_weight` swept by CV
(neg/pos 0.971, √ **0.973 ± 0.016**, 1 0.973; base rate 0.40). **CV AUC-PR 0.973 ± 0.016**
(folds 0.947–0.987, pooled out-of-fold 0.956), 133 rounds. Gain by group: **role 0.83**
(`acc_log_degree_window` 0.42, `acc_n_counterparties` 0.26, `acc_n_included` 0.10, closure 0.05),
amount 0.05, GFP 0.04, direction 0.03, timing 0.03, embedding 0.02, kind 0.00 — the affinity is
almost entirely a hub detector, which is what "same attempt through this account" mostly is. On
test (seed 1) same-ring pairs score 0.90 ± 0.16 and different-ring pairs 0.46 ± 0.36.

Clustering over the included edges of a component with w = logit(p) on the shared-account pairs:

* `cluster_pivot` — greedy pivot (Ailon-Charikar-Newman) with the neighbourhood taken
  *transitively* over positive pairs among unclustered nodes: on a sparse pair graph a 5-edge
  stack has no pair (e1, e3), so the direct ACN neighbourhood would cut every chain; with the
  transitive neighbourhood the seeded pivot order only fixes cluster numbering.
* `cluster_average` — average-linkage agglomerative with distance 1 − p averaged over the pairs
  joining two clusters (no joining pair → never merged), merge while the smallest distance is
  below a val-chosen cut ∈ {0.3, 0.5, 0.7, 0.9}.
* `reattach_small` (both) — a cluster spanning fewer than `min_size` accounts cannot become a
  ring, so it is merged into its best-linked neighbour, smallest first. Added after the first
  pass: without it the splits produced 2-account fragments that vanished under `min_size` —
  23 matches lost against 8 gained over five seeds; with it 5 lost against 18 gained.

Both are deterministic (`tests/test_partition.py`). Each cluster → one `Ring` (`full.py`):
members = endpoints of its included edges, `seed_edges` / `expanded_edges`, `member_edges` =
every edge among the members inside [start, end]; rings of a partition may share a hub account.
Since Step 8 the ring also carries the roles, the contract `conservation_closure` (NaN for the
5–6 rings per seed with no source or sink — `docs/TYPING.md`), `confidence` = mean
`score_calibrated` over the seed edges × that closure, `expanded_edge_probs` and the topology.

## 7.3 baselines — same expanded subgraph for all (`ringshield/aggregators/full.py`)

* **B2** plain components (= the `expand` aggregator's rings; reproduces the R3 proposed row exactly).
* **B3** time-windowed components: two included edges joined if they share an account and lie at
  most `gap_h` apart, gap chosen on val ∈ {6, 12, 24, 48, 72}. **The spec named
  `cc._split_by_time` for this; that legacy helper adds every account-graph edge to its
  re-clustering graph before the time test, so it never splits anything — `max_gap_hours` has
  been a no-op since E7.** It was left untouched (existing behaviour; see "anything else");
  `full.time_windowed_labels` implements the intended semantics.
* **B4** Louvain (python-louvain 0.16, `random_state` 0) on the account graph of the component
  with edge weight = mean pair affinity of the transactions between the two accounts, resolution
  chosen on val ∈ {0.5, 1, 2}; edges crossing communities dropped.
* **B5** CSGM (`evaluation/csgm_baseline.py`; upstream **https://github.com/zhihuat/Collaborative-AML**,
  commit **2db6537252490c83617f5627d5adb7ed3b3c3eae** (2025-06-24), cloned to `external/` which is
  **git-ignored** — only the adapter is committed): accounts
  split into two institutions at random (seed 0, no label information — the reference places
  every scatter-gather source and sink in opposite banks from the pattern file); forward /
  backward cross-institution edge sets by the reference's `AMLBFS` (K = 2); exact Jaccard in
  place of the MinHash-LSH-Bloom estimate; matched (source, sink) pairs with a non-empty shared
  intermediate set become rings; `len_threshold` ∈ {2, 3, 4, 8} and the similarity threshold
  chosen on val. It ran in 33 s on the test edges. It proposes scatter-gather-shaped rings only.

  **Deviations from the reference, all recorded in the run's `config.yaml`:** (i) institutions are
  a deterministic random 2-way split of the accounts (`--bank-seed 0`) — the reference's AMLworld
  preprocessing (`data_process/ml_extraction.py`) places every scatter-gather source and
  destination in *opposite* banks using the pattern file, which is label information the
  comparison must not have; (ii) exact Jaccard of the two edge sets instead of the MinHash-LSH +
  Bloom-filter estimate of it (`--rows` / `--bands` / `--bf_size` drop out) — the private estimate
  is a communication-cost device, not a detection device, and with the data in one place the exact
  value is the quantity it approximates; (iii) the reference reports account-level precision /
  recall against `alert_accounts.csv`, so rings are formed here as {source, sink} + the
  intermediates the two node sets share, evaluated like every other method (test_visible, Jaccard
  0.5, primary window); (iv) `len_threshold` is chosen on val from {2, 3, 4, 8} rather than fixed
  at the reference's HI-Small value 8, because our in-window rings are small (val picked 4);
  (v) the transactions are our test-split edges in the loader basis, not the reference's
  re-extracted `transactions.csv`. `utils.AMLBFS`, the K = 2 depth and the similarity-threshold
  grid are the reference's.

## 7.4 results — `results/tables/r4_partition.csv` (primary window, mean ± std over 5 detector seeds)

| method | Ring-P | Ring-R | **Ring-F1** | ΔF1 vs B2 per seed | R≥3 | mean Jaccard | coverage | rings > 100 members | components split | chosen |
|---|---|---|---|---|---|---|---|---|---|---|
| B0 cc (R2) | 0.814 ± 0.049 | 0.384 ± 0.039 | 0.521 ± 0.045 | | 0.516 | 0.852 | 0.866 | 0 | — | 0.1/3 |
| B2 plain components (= R3 proposed) | 0.838 ± 0.044 | 0.446 ± 0.031 | 0.582 ± 0.034 | — | 0.611 | 0.921 | 0.942 | 0 | 0 | — |
| B3 time-windowed | 0.825 ± 0.053 | 0.431 ± 0.025 | 0.566 ± 0.033 | −0.016 ± 0.012 | 0.609 | 0.908 | 0.927 | 0 | 18 | 48 h (4 seeds), 24 h |
| B4 Louvain | 0.838 ± 0.044 | 0.446 ± 0.031 | 0.582 ± 0.034 | 0.000 | 0.611 | 0.921 | 0.942 | 0 | 0 | resolution 2.0 (splits nothing) |
| B5 CSGM (1 run, no detector) | 0.545 | 0.069 | 0.122 | | 0.070 | 0.674 | 0.856 | 0 | — | len 4 / sim 0.2 |
| affinity + pivot | 0.822 ± 0.043 | 0.451 ± 0.032 | 0.582 ± 0.034 | −0.000 ± 0.005 | 0.611 | 0.921 | 0.940 | 0 | 3.8 | threshold 0.5 |
| **affinity + average (proposed)** | 0.818 ± 0.045 | 0.461 ± 0.034 | **0.589 ± 0.037** | **+0.008 ± 0.005** (+0.004 … +0.015) | 0.604 | 0.917 | 0.944 | 0 | 6.2 | cut 0.5 (all seeds) |

`proposed` in the csv = the val-better of pivot / average per seed (average on 4 seeds, pivot on
seed 1 where val F1 tied within 0.0004): 0.589 ± 0.037. Per-seed test P / R / F1 — B2 0.878/0.454/0.598,
0.859/0.454/0.594, 0.841/0.425/0.565, 0.850/0.488/0.620, 0.763/0.408/0.532; average 0.862/0.466/0.604,
0.835/0.466/0.598, 0.810/0.442/0.572, 0.840/0.511/0.636, 0.745/0.420/0.537. On **val** the same cut
gives +0.036 ± 0.003 ring-F1 over B2 on every seed with precision +0.018 *and* recall +0.048
(mean Jaccard −0.013); on **test** the gain shrinks to +0.008 with precision −0.020, recall
+0.015, mean Jaccard −0.005. Splits on test: 21 multi-ring and 8 single-ring components over
five seeds, 18 truth matches gained, 5 lost. Tail / whole F1 are in the csv.

**Checks.** (1) Fixture (two 5-account rings through one hub → two rings at Jaccard 1.0 for pivot,
average and B3; one ring for B2) and determinism: pass (`tests/test_partition.py`, 7 of 8).
(2) Predicted rings with > 100 members: **0** for every method (largest ring 12 accounts inside
the window, 27 overall) — the 500-event candidate cap of Step 6 already keeps hubs out of the
expanded subgraph, so the role feature has nothing to cut at that scale. (3) **Not met on test**:
precision 0.838 → 0.818 and mean Jaccard 0.921 → 0.917 both fall; recall rises 0.015 (well within
the seed std 0.031). The check encodes the hypothesis that hub-merged components are common
and cutting them yields precise rings; on this test window they are 4 per seed and cutting them
turns one matched prediction into several smaller ones of which some match — recall up,
precision down. `test_r4_checks_on_the_runs` asserts check 3 and fails on the precision clause
(verbatim in PROGRESS).

## The ceiling table — why each unmatched ring is unmatched

`evaluation/unmatched_rings.py` → `results/tables/r4_unmatched.csv` / `.json`. Every truth ring in
scope of a window that no prediction matches at Jaccard 0.5 is put in exactly one class:
**(a)** fewer than 3 visible members in the window (undetectable under `min_size` 3); **(b)** ≥ 3
members but no included edge (seed or expanded) of any prediction touches one of its accounts;
**(c)** touched but Jaccard < 0.5, split into *over-merged* (the covering prediction also holds
accounts of another truth ring) and *under-covered* (it does not). Mean per detector seed, 5 seeds:

| window | method | truth rings | matched | (a) < 3 members | (b) untouched | (c) over-merged | (c) under-covered |
|---|---|---|---|---|---|---|---|
| **primary** | B0 (cc) | 174 | 66.8 | 52.0 | 40.2 | 10.8 | 4.2 |
| | B2 (expand, components) | 174 | 77.6 | 52.0 | 33.2 | 9.2 | 2.0 |
| | **full** (expand + partition) | 174 | **80.2** | 48.6 | 33.2 | 9.6 | 2.4 |
| **val** | B0 (cc) | 157 | 72.4 | 42.6 | 23.2 | 11.8 | 7.0 |
| | B2 | 157 | 78.6 | 42.6 | 15.0 | 11.8 | 9.0 |
| | **full** | 157 | **86.2** | 39.6 | 15.0 | 7.2 | 9.0 |

Reading it: **(a) is 30 % of the primary window's ground truth and is a hard ceiling** — 1,359 of
the 1,387 (a)-rings have exactly 2 visible members, 28 have 1; no aggregator with `min_size` 3
can match them (`full` matches 3.4 per seed more than B2 only because expansion sometimes lifts a
ring from 2 to ≥ 3 visible members). **(b) is the next 19 %** and is a detector matter: these
rings have ≥ 3 members (mean 5.8, median 4, max 14 on primary) and *no* seed or expanded edge
lands on any of their accounts. Expansion converts 7 rings per seed from (b) to matched; the
partition converts none — by construction it only re-cuts what is already included. **(c) is
12 per seed on primary**, of which the partition can only act on the over-merged 9.6, and it does:
val over-merged falls 11.8 → 7.2 (−39 %). On primary the same step moves 9.2 → 9.6 (it splits
some merges and creates others), which is the precision loss of check 3 in a second view.

Correction to the earlier decomposition in this file: the line "76 truth rings no prediction
touches (median size 2)" mixed classes (a) and (b) — classes (a) and (b) together are 85 per seed
on primary; the untouched rings with ≥ 3 members are 33 and their median size is 4.

Per pattern (primary window, summed over 5 seeds, `full`): BIPARTITE 5 matched / 25 (a) / 41 (b)
/ 5 + 4 (c) — the pattern is essentially unreachable, consistent with Step 6's finding that its
quiet edges share no endpoint with a seed; STACK 4 / 40 / 46 / 17 + 3 — long chains lose their
ends; SCATTER-GATHER 78 / 25 / 5 / 1 + 1 and GATHER-SCATTER 116 / 44 / 17 / 8 + 0 are the
patterns the pipeline handles. The full table is in the csv.

## Pre-registered extension: does the partition allow a looser operating point?

*Written 2026-09-22 before the sweep was run; the grid, the selection rule and the stopping rule
below were fixed in advance and the result is reported as found.*

**Hypothesis: partitioning prevents the chaining collapse B0 shows above 0.3 % seeds, allowing a
looser operating point.** B0's val grid (`docs/R2_BASELINES.md`, the motivating figure) collapses
from ring-F1 0.57 at 0.1 % to 0.05 at 0.5 % because a few false-positive edges on a hub chain
many rings into one component. If the affinity clustering cuts those chains, a larger seed
fraction should recover more members without the collapse, and val should pick a looser k.

Grid, on **val** only, for `full` (expansion + partition) and for `cc+partition` (partition of the
plain seed components, no expansion): seed_frac ∈ {0.10, 0.15, 0.20, 0.30, 0.50} % × cut ∈
{0.3, 0.5, 0.7} × min_size ∈ {2, 3}; objective val ring-F1, ties → smaller seed_frac, then larger
min_size, then larger cut. The winner per detector seed is then evaluated on the test primary
window exactly once. The fixed-k\* rows above are not replaced. If val picks 0.10 % again, that
is recorded and the extension stops there.

### Result — **hypothesis not supported; val picked 0.10 % again, so the extension stops here**

`ringshield/partition/sweep_operating_point.py`, 10 runs (`experiments/R4_sweep/`),
`results/tables/r4_sweep_val_curve.csv` (val grid) and `r4_sweep_test.csv` (test at the chosen cell).

**Val ring-F1 vs seed fraction** (best cut / min_size at each k, mean ± std over 5 detector seeds;
figure `results/figures/r4_val_ringf1_vs_seedfrac.png`):

| k | B0 (cc) | cc + partition | full (expansion + partition) |
|---|---|---|---|
| 0.10 % | 0.549 ± 0.021 | **0.587 ± 0.024** | **0.593 ± 0.022** |
| 0.15 % | 0.515 ± 0.036 | 0.551 ± 0.039 | 0.543 ± 0.031 |
| 0.20 % | 0.489 ± 0.030 | 0.523 ± 0.032 | 0.503 ± 0.026 |
| 0.30 % | 0.376 ± 0.044 | 0.402 ± 0.044 | 0.374 ± 0.033 |
| 0.50 % | 0.188 ± 0.037 | 0.202 ± 0.040 | 0.194 ± 0.036 |

The three curves fall together. Partitioning shifts the whole curve up by a constant 0.01–0.04 and
changes its shape not at all: from 0.10 % to 0.50 % B0 loses 66 % of its ring-F1, cc + partition
66 %, full 67 %. **The chaining collapse is not a partition problem.** What collapses above
0.2 % is precision at the *edge* level — at 0.5 % of 965 k val edges the seed set is 4,828 edges
of which the great majority are licit, so the components are not "two attempts merged through a
hub" (which the affinity can cut) but licit subgraphs with no ring structure to recover. The
affinity's own training distribution never contained such components.

**Chosen on val: 0.10 % / cut 0.5 / min_size 3 — on every seed, for both variants.** Per the
pre-registration, that is recorded and the extension stops. Test at the chosen cell (primary
window, reported next to the fixed-k\* rows above, which are unchanged):

| variant | Ring-P | Ring-R | Ring-F1 | R≥3 | mean Jaccard | coverage | chosen |
|---|---|---|---|---|---|---|---|
| B0 (fixed k\*) | 0.814 ± 0.049 | 0.384 ± 0.039 | 0.521 ± 0.045 | 0.516 | 0.852 | 0.866 | 0.1 / 3 |
| cc + partition (swept) | 0.806 ± 0.060 | 0.402 ± 0.042 | 0.536 ± 0.049 | 0.516 | 0.849 | 0.870 | 0.1 / 0.5 / 3 |
| full (swept) | 0.818 ± 0.045 | 0.461 ± 0.034 | 0.589 ± 0.037 | 0.604 | 0.917 | 0.944 | 0.1 / 0.5 / 3 |

The `full` row is the same cell the fixed-k\* average row already used, so it reproduces it
exactly (0.589 ± 0.037) — the sweep found nothing better. `cc + partition` is the one new number:
partitioning the plain seed components without expansion is worth **+0.015 ring-F1 over B0**
(0.521 → 0.536, recall +0.018 at equal precision), i.e. about a fifth of what expansion adds.

## Limitations and what would move the number

* The partition can only act on components that merge attempts; on the primary window at 0.1 %
  seeds there are four per seed. The rings in classes (a) and (b) of the ceiling table are beyond
  every aggregator: (a) has fewer than 3 visible members, (b) has no seed or expanded edge on any
  of its accounts. **Class (b) — 33 rings per seed, mean size 5.8 — is a detector question, not an
  aggregation one, and no new model work is started for it here. It is carried into Step 10 as one
  extra column: the class-(b) count per detector, which answers whether a different detector fires
  on those rings** (decision recorded 2026-09-22). The under-covered predictions are an expansion
  matter (Step 6's Δt = 24 h corner).
* The affinity is a hub detector (role group 83 % of gain); embeddings and timing add little.
  Training pairs come from 11 multi-ring train components (39 mixed components carry the
  discriminative pairs), so the model has seen few genuine "same account, different attempt" cases.
* B3's `_split_by_time` finding: `cc.aggregate_cc(max_gap_hours=…)` and the CLI's
  `--max-gap-hours` have never split a component. Fixing it changes a documented behaviour of
  an existing function — listed, not done.
* B5 is a single run (it uses no detector seed) and is not comparable in scope: it can only
  propose scatter-gather rings and needs ≥ `len_threshold` cross-institution edges.

Artefacts: `experiments/R4_partition/{pairs_train.parquet,pairs_train.json,affinity/,runs/<method>/seed<S>/}`,
`results/tables/r4_partition.csv`, `models/artifacts/full_gine_causal_seed1/` (export of the
average seed-1 run; CLI `run --aggregator full --gfp … --embeddings …`). Tests: `tests/test_partition.py`.
