# Causality audit of the edge features (Step 3b-y, 2026-09-17; resolved in Step 3b-z, same day)

Read-only audit of every engineered edge feature the Multi-GINe model sees
(`models/tgn.py::load_data`, 18 columns: 4 raw transaction fields, 10 GFP motif features,
2 port ids, 2 time deltas). Question: for an edge *e* = (u → v) at time *t_e*, which other
edges enter the computation of each feature — only edges at or before *t_e* (causal), or
also later ones (non-causal)? Two independent answers: a reading of the code with line
numbers (§1, §2) and a recomputation of the GFP features on a time-restricted graph
(§3, `tests/audit_feature_causality.py`, `docs/feature_causality_check.json`).
§1–§5 are the Step 3b-y audit as written (the code it describes is the pre-3b-z
`graph/motif_features.py`; line numbers refer to that version). §7 records the Step 3b-z
fix: the two cycle columns were regenerated with a trailing definition, the parquets
replaced, and R1 retrained.

**Headline.** 8 of the 10 GFP features, both port ids and both time deltas are causal as
implemented. `temporal_cycle` and `cycle_length` are not: they search **forward** from
*t_e* through edges of *any* split with no time bound (observed look-ahead up to 16.4 days;
21 % of train-edge cycle flags and 29 % of val-edge flags are closed by an edge in a later
split), and the flag lifts the illicit rate 12–16×. They must be recomputed with a trailing
definition (or dropped) before any result that uses GFP features is reported; §5 lists
the cost.

## 1. GFP features — `graph/motif_features.py`

Setup: the adjacency is built once from **all** edges, train + val + test
(`main`, lines 314–327), and the same adjacency is used for every split's feature run
(lines 337–351). Per-node lists are sorted by timestamp (`build_adjacency`, 205–218);
`_WINDOW` = 86,400 s and `_MAX_HOPS` = 5 (README command). The per-edge dispatcher is
`_process_chunk`, lines 174–187. Note the module docstring (lines 5–15) is stale: it
says fan-in/out use `[t-Δ, t+Δ]`; the code is trailing (see below).

| # | feature | computation (lines) | window definition for edge (u→v, t_e) | uses future? | max look-ahead |
|---|---|---|---|---|---|
| 0 | `fan_out` | `_fan_out_count(u, t)` 68–74: `lo = bisect_left(ts, t−Δ)`, `hi = bisect_left(ts, t)` | # out-edges of u with **t_e − 86,400 ≤ ts < t_e** (trailing, strict; excludes e itself and same-second edges) | no | – |
| 1 | `fan_in` | `_fan_in_count(v, t)` 77–83 | # in-edges of v with t_e − 86,400 ≤ ts < t_e (trailing, strict) | no | – |
| 2 | `deg_out_src` | `_cum_out_degree(u, t)` 86–90: `bisect_right(ts, t)` | # out-edges of u with **ts ≤ t_e** (trailing, inclusive: counts e itself and other edges in the same second) | no | – |
| 3 | `deg_in_src` | `_cum_in_degree(u, t)` 93–97 | # in-edges of u with ts ≤ t_e | no | – |
| 4 | `deg_out_dst` | `_cum_out_degree(v, t)` 86–90 (call 178) | # out-edges of v with ts ≤ t_e | no | – |
| 5 | `deg_in_dst` | `_cum_in_degree(v, t)` 93–97 (call 179) | # in-edges of v with ts ≤ t_e (counts e) | no | – |
| 6 | `scatter_gather` | `_scatter_gather` 118–122 via `_out_neighbors_before(u, t)` 100–106 and `_in_neighbors_before(v, t)` 109–115, both `bisect_left(ts, t)` | \|{w : u→w before t_e} ∩ {w : w→v before t_e}\| — all edges **ts < t_e** (trailing, strict) | no | – |
| 7 | `gather_scatter` | `_scatter_gather` 124–127 | \|{w : w→u before t_e} ∩ {w : v→w before t_e}\|, ts < t_e | no | – |
| 8 | `temporal_cycle` | `_temporal_cycle(u, v, t)` 132–159: gate `u, v ∈ _SCC_NODES` (134; SCCs of the **static all-split graph**, `build_scc_set` 223–236, call 333); BFS from v with `min_ts = t` (138), `lo = bisect_right(ts, min_ts)` (149) → only edges with **ts > min_ts**, `min_ts` advanced to the edge's time at each hop (157), ≤ 5 hops (142, 155); returns 1 when an edge reaches u (153–154) | **forward** temporal path v → … → u using edges **strictly after t_e**, no upper time bound, across split boundaries | **yes** | unbounded: any edge up to the last timestamp of the dataset (t = 1,527,490 s); observed max 16.4 d (train), 10.0 d (val), 8.0 d (test) — §3 |
| 9 | `cycle_length` | same call, hop count of the first cycle found (154) | as `temporal_cycle` | **yes** | as above |

The SCC gate (line 134) is itself computed on the full static graph, but it is lossless
for the BFS result (any temporal cycle through u and v puts both in a non-trivial SCC), so
the future use is entirely in the BFS.

## 2. Ports and time deltas — `models/tgn.py` (IBM `data_util.py` helpers)

Both are computed per split on the expanding-window graph (`load_data`, lines 347–358:
train graph = train edges, val graph = train + val, test graph = all edges) by
`add_ports_and_tds` (112–126), after the GFP columns are attached and before
z-normalisation (fit on train, 360–366).

| feature | computation (lines) | what enters the value of edge (u→v, t_e) | uses future? |
|---|---|---|---|
| in-port (`compute_ports(edge_index, adj_in)`, 118) | 78–93: for each node v, its incident (neighbour, t) pairs sorted by t (85), distinct neighbours in order of **first** appearance (86–87), `ports_dict[(u, v)] = rank` (88–89), looked up per edge (90–92) | rank of u among v's distinct senders ordered by first-contact time = # senders whose first transaction into v precedes u's first transaction into v (≤ t_e). Later edges of v — including later first contacts — only take **higher** ranks and cannot change this value. The id is the same for every u→v edge, whatever its time. | no |
| out-port (`compute_ports(edge_index.flipud(), adj_out)`, 119) | same, on u's receivers | rank of v among u's distinct receivers by first contact (≤ t_e) | no |
| in-time-delta (`compute_time_deltas(…, adj_in)`, 122) | 96–109: per node, incident edges sorted by t (105); `a_tds = [0] + [t_{k+1} − t_k]` assigned to edge k+1 (106–108) | t_e − time of v's **previous** in-edge (0 for the first). References the previous edge, never the next. | no |
| out-time-delta (`compute_time_deltas(…, adj_out)`, 123) | same on out-edges | t_e − time of u's previous out-edge | no |

Two remarks, neither a leak: (i) `np.argsort` (lines 85, 105) is not stable, so among
edges with the *same* timestamp the port rank / which of them gets the non-zero delta is
arbitrary — reproducible for a fixed input but not a deterministic function of the data;
(ii) because ports are constant per (u, v) pair and computed on a graph that ends at the
split boundary, their values are identical whether computed on the train, val or test
graph (§2 reasoning; the ranks depend only on earlier first contacts).

## 3. Empirical check (10,000 random test edges, seed 1)

`tests/audit_feature_causality.py --all-illicit --lookahead`. The production functions
of `graph/motif_features.py` are called unchanged on (a) the full adjacency the script
builds and (b) the same adjacency truncated per edge to timestamps ≤ t_e (also < t_e as a
strict variant). The full-graph recomputation reproduces
`data/processed/amlworld_gfp_features_test.parquet` exactly for all 10 features (100.0 %),
so the wrapper reads the graph the way production does. The random sample holds 18
illicit edges; the illicit column is therefore repeated for **all 1,611 illicit test
edges** (last two columns). Differences are on the raw counts (before log1p).

| feature | differs (≤ t_e) all | mean \|Δ\| all | differs illicit (n=18) | differs licit (n=9,982) | differs, all 1,611 illicit | mean \|Δ\|, all illicit | differs / mean \|Δ\| with strict < t_e (all) |
|---|---|---|---|---|---|---|---|
| `fan_out` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 0.00% / 0.000 |
| `fan_in` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 0.00% / 0.000 |
| `deg_out_src` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 100.00% / 1.697 |
| `deg_in_src` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 4.93% / 0.052 |
| `deg_out_dst` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 2.42% / 0.063 |
| `deg_in_dst` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 100.00% / 1.063 |
| `scatter_gather` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 0.00% / 0.000 |
| `gather_scatter` | 0.00% | 0.000 | 0.0% (0/18) | 0.00% | 0.00% | 0.000 | 0.00% / 0.000 |
| `temporal_cycle` | 0.29% | 0.003 | 11.1% (2/18) | 0.27% | 4.16% | 0.042 | 0.29% / 0.003 |
| `cycle_length` | 0.29% | 0.003 | 11.1% (2/18) | 0.27% | 4.16% | 0.047 | 0.29% / 0.003 |

Reading: with the graph cut at ≤ t_e, eight features never change; the two cycle features
change exactly where they are non-zero (on the restricted graph the forward BFS has no
edges to walk, so they become 0 for every edge). The strict-cut column shows that the
cumulative degrees count e itself plus other edges of the same second (mean 0.7 extra
out-edges of the sender in the same second; 1.1 for the receiver's in-edges) — inclusive
of the present, not the future.

**How far ahead the cycle features look** (every edge whose stored `temporal_cycle` is 1;
look-ahead = timestamp of the cycle-closing edge − t_e; same BFS order as production):

| split | edges with cycle = 1 | median | p90 | max | share > 24 h | closed by an edge **after the split's last timestamp** |
|---|---|---|---|---|---|---|
| train | 24,636 (0.76 %) | 14.0 h | 153.3 h | 16.4 d | 35.6 % | 5,099 (20.7 %) — in val / test |
| val | 4,119 (0.43 %) | 8.4 h | 37.8 h | 10.0 d | 28.1 % | 1,207 (29.3 %) — in test |
| test | 2,240 (0.26 %) | 0.2 h | 26.8 h | 8.0 d | 12.5 % | 0 (nothing after test) |

The falling non-zero rate (0.76 % → 0.26 %) is the same artefact seen from the other
side: later edges have less future left to search. The flag is informative:
P(illicit | `temporal_cycle` = 1) = 0.96 % / 1.58 % / 2.99 % on train / val / test against
base rates 0.08 % / 0.11 % / 0.19 % (12–16×), and among illicit edges the flag is set for
9.3 % / 6.3 % / 4.2 %. Mean `cycle_length` given a cycle is 1.01–1.13, i.e. almost always
the direct return payment v → u — the model is being told, at training time, that the
receiver pays the sender back later.

## 4. Conclusion per feature group

| group | features | verdict |
|---|---|---|
| A — GFP counts | `fan_out`, `fan_in`, `deg_out_src`, `deg_in_src`, `deg_out_dst`, `deg_in_dst`, `scatter_gather`, `gather_scatter` | **causal as-is** (trailing windows; the cumulative degrees are inclusive of t_e, which is present, not future) |
| B — GFP cycles | `temporal_cycle`, `cycle_length` | **non-causal, split-wide and beyond**: forward search over all later edges of the whole dataset, 5 hops, no time bound; observed look-ahead up to 16.4 d, 21–29 % of the flags on train / val edges are closed inside a later split |
| C — ports | in-port, out-port | **causal as-is** (rank by first contact; later edges cannot change it) |
| D — time deltas | in-delta, out-delta | **causal as-is** (time since the node's previous edge) |

## 5. Recommendation and cost

* **Group A, C, D**: no recomputation.
* **Group B**: recompute with a trailing definition **before Step 4 consumes any R1
  output**, or drop the two columns. The trailing analogue keeps most of the signal for the
  edge that *closes* a cycle: `closes_cycle(e)` = does a temporal path v → … → u with
  strictly increasing timestamps **ending before t_e** exist (the mirror image of the current
  BFS: walk in-edges backwards from u with decreasing time bound, or forward from v with the
  upper bound t_e), plus its length. This flags the same rings at the moment they close
  instead of at their opening edge. Dropping the columns is the cheaper fallback (no feature
  code, same retraining cost).
  * Runtime: the original run took 506 + 475 + 462 s ≈ 24 min for all three splits on 36
    workers; a backward BFS has the same cost, so ≈ 25 min for a full regeneration (all 10
    columns; the eight causal ones are reproduced bit-for-bit, as §3 verified).
  * Parquets that change: `data/processed/amlworld_gfp_features_{train,val,test}.parquet`
    (columns `temporal_cycle`, `cycle_length` only). `docs/data_manifest.json` does not list
    them (raw files + formatted CSV only), so it stays as is. `amlworld_motif_features.parquet` (legacy v1, unused by the
    GNN) is unaffected.
  * Experiments that consume GFP: `R1_gine_causal` (5 seeds × ~3 h) with its `models/score.py`
    outputs (scores, embeddings) and `evaluation/edge_metrics.py`; `R1_gine_noncausal`
    (re-score from whichever non-causal checkpoints replace E6); `E6_tgn` / `E6_gine_L4`
    (retire — R1 is the reference); the contract stub `contract/out/scored_edges_gine_1.parquet`
    (built from `E6_tgn/predictions_with_ids.csv`). `E5b_gfp_xgboost` is **not re-run as such**:
    Step 4 refits GFP + XGBoost with five seeds on the recomputed features and supersedes it, so
    the reported E5b figure (F1 0.534) is retired (decision 2026-09-17). Step 4 (ring
    aggregation) has not started and consumes the new outputs. The Step 3b-x window analysis
    (`docs/CAUSAL_LEAK.md`) is about neighbour sampling, not features, and does not need to be
    repeated. Runs that do not use `--gfp` (E5a baselines, E4) are unaffected.
* The reported E6/R1 numbers therefore carry a feature-level look-ahead that the causal loader
  work in Step 3a/3b did not remove; they should be labelled as such until the Group B
  recompute lands. The E5b figure is retired rather than relabelled.

## 6. Outside this audit's scope, noted for completeness

* `preprocessing/amlworld_loader.py`'s `sender_*` / `receiver_*` account aggregates (lines
  213–240; whole-train-period, joined onto every edge) look ahead within train; nothing that
  survives uses them (E5a only), so they are noted here and not pursued.
* `models/tgn.py::load_data` also feeds the raw `Timestamp` column as an edge feature
  (z-normalised) — causal, but it lets the model read absolute time.

Artefacts: `tests/audit_feature_causality.py`, `docs/feature_causality_check.json`
(seed 1, 10,000 edges + 1,611 illicit + look-ahead over 30,995 cycle-flagged edges;
55 s on one core). The JSON was regenerated after Step 3b-z: its main table now shows the
trailing parquets (0 differences everywhere) and its `temporal_cycle_lookahead` block still
measures the legacy definition from the `*_legacy_forwardcycle.parquet` files; the §3 table
above is the 3b-y record of the legacy files.

## 7. Step 3b-z — trailing recomputation of `temporal_cycle` / `cycle_length`

**New definition** (`graph/motif_features.py::_closes_cycle`): for e = (u → v, t_e),
`temporal_cycle` (column name kept) = 1 if there is a temporal path v → … → u using only
edges with timestamp **< t_e**, strictly increasing along the path, at most 5 hops, and no
edge older than **t_e − 14 days** (`--lookback-days`, recorded with the window and hop
limit in the parquet schema metadata under key `gfp`); `cycle_length` = hop count of the
shortest such path, else 0. Implemented as a backward BFS from u over incoming edges with
decreasing timestamps on the existing per-account sorted arrays; a node is re-expanded only
when reached with a larger time bound, which keeps the search exact. The static SCC gate is
gone (it would have to be computed on the graph restricted to edges < t_e per edge, which is
infeasible; without it the search costs 0.02–0.08 ms per edge, so no gate is needed). The
other eight features and the fan-in/out docstring were left as they were except that the
stale `[t−Δ, t+Δ]` docstring now reads `[t−Δ, t)`.

**Verification** (`tests/test_gfp_causality.py`, 3 passed): on 10,000 random edges per
split the production function on the full train+val+test adjacency equals the same function
on the adjacency cut at < t_e (0 differences on both columns); on 2,000 edges per split it
equals an independent forward brute-force search (0 mismatches); the eight counts are
unchanged on the cut graph (regression for §3). `tests/audit_feature_causality.py` on the
regenerated parquets: 0 differences for all 10 features, full-graph recomputation ==
stored parquet 100 %. Regeneration: 570 + 559 + 559 s on 36 workers. The legacy files are
kept as `amlworld_gfp_features_<split>_legacy_forwardcycle.parquet`; both sets are hashed in
`docs/data_manifest.json` (`derived`).

**Flips on `temporal_cycle`, legacy forward → trailing** (`preprocessing/gfp_cycle_flips.py`,
`docs/gfp_cycle_flips.json`; the eight count columns are asserted bit-identical):

| split | edges | illicit | legacy = 1 | trailing = 1 | both | 1 → 0 | 0 → 1 | P(illicit \| legacy) | P(illicit \| trailing) | base rate | recall of illicit: legacy → trailing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| train | 3,248,921 | 2,530 | 24,636 | 186,079 | 10,982 | 13,654 | 175,097 | 0.96 % | 0.08 % | 0.078 % | 9.3 % → 6.0 % |
| val | 965,524 | 1,036 | 4,119 | 21,881 | 3,615 | 504 | 18,266 | 1.58 % | 0.40 % | 0.107 % | 6.3 % → 8.5 % |
| test | 863,900 | 1,611 | 2,240 | 19,456 | 2,079 | 161 | 17,377 | 2.99 % | 0.75 % | 0.186 % | 4.2 % → 9.1 % |

Reading. The trailing flag fires 5–8× more often (a return payment *before* the edge is
common) and is far less informative: the lift over the base rate drops from 12–16× to
**1.0× on train, 3.7× on val, 4.0× on test** (mean cycle length given a flag 1.00–1.01, i.e.
almost always direct reciprocation v → u). Most of the legacy flags survive (both = 1 for
45 % / 88 % / 93 % of them on train / val / test) because a ring that pays back later is
also usually one that paid before; what is lost is the part of the legacy signal that was
literally "the receiver will pay the sender back" — which is the leak. The train-split lift
of 1.0 means the model can no longer read ring membership off this column during training;
whatever R1 now gets from it is the licit-reciprocation base behaviour, which is what a
deployable feature can offer.

**Per day** (`docs/gfp_cycle_flips.json` → `per_day`; day = (Timestamp − 10) // 86400, i.e.
calendar days of the data; train = days 0–5, val = 6–7, test = 8–17):

| day | split | edges | base rate | trailing rate | lift | illicit recall | legacy rate | legacy lift |
|---|---|---|---|---|---|---|---|---|
| 0 | train | 1,114,921 | 0.029 % | **12.65 %** | **0.15** | 1.9 % | 1.28 % | 7.3 |
| 1 | train | 754,449 | 0.054 % | 1.93 % | 2.5 | 4.9 % | 0.42 % | 22.8 |
| 2 | train | 207,382 | 0.189 % | 2.13 % | 2.4 | 5.1 % | 0.67 % | 13.0 |
| 3 | train | 207,430 | 0.196 % | 2.22 % | 3.4 | 7.6 % | 0.65 % | 18.3 |
| 4 | train | 482,650 | 0.098 % | 2.22 % | 3.5 | 7.9 % | 0.46 % | 21.1 |
| 5 | train | 482,089 | 0.110 % | 2.24 % | 3.1 | 7.0 % | 0.46 % | 16.1 |
| 6 | val | 482,751 | 0.103 % | 2.25 % | 3.3 | 7.4 % | 0.43 % | 17.2 |
| 7 | val | 482,773 | 0.112 % | 2.28 % | 4.2 | 9.5 % | 0.42 % | 12.4 |
| 8 | test | 654,467 | 0.079 % | 2.13 % | 3.8 | 8.0 % | 0.26 % | 24.7 |
| 9 | test | 208,325 | 0.212 % | 2.47 % | 4.7 | 11.5 % | 0.21 % | 22.1 |
| 10–17 | test | 396 → 11 per day | 57–73 % | 27–52 % | 0.0–0.6 | – | 3.5–28 % | ≤ 0.85 |

The train-split lift of 1.0 is entirely **day 0**: a third of all training edges (1.11 M)
fall on the first day, where 12.65 % of edges close a cycle and almost none of them are
illicit (base rate 0.029 %) — the generator's opening-day burst of reciprocal licit
activity. From day 1 the trailing flag is stable: fire rate 1.9–2.5 % and lift 2.4–4.7 on
every day of train, val and test alike, rising slightly over days 1–3 and flat thereafter
(cycles are mostly same-day reciprocation, so the 14-day look-back truncation plays no
visible role). Days 10–17 hold only 1,504 edges in total, 58–73 % of them illicit pattern
transactions, so the lift there is not interpretable (the legacy flag is 0 on those days
because there is nothing after them to look at). Conclusion: the feature is fine; the train
split under-represents it only through day 0. Anything trained on train-period rings that
uses this column (Step 4 typing head, expansion policy) should either drop day 0 from its
training rows or carry an elapsed-day covariate, and must not expect the legacy lift.

**Consequences applied**: `experiments/R1_gine_causal` (legacy features) →
`experiments/R1_gine_causal_legacyfeat` untouched; R1 retrained on the trailing features as
`experiments/R1_gine_causal` (seeds 1–5, same command as 3b) and scored val / test / train
with embeddings; `results/tables/r1_edge_metrics.csv` now has one row per run with
`sampler` and `feature_set` columns (`noncausal_legacyfeat`, `causal_legacyfeat`,
`causal`) and `evaluation/edge_metrics.py --feature-set` tags every `metrics.json`. E5b is
not re-run (Step 4 refits GFP + XGBoost, five seeds, on these features). The reported R1
numbers on legacy features stay in the table, labelled, for the before/after comparison.
