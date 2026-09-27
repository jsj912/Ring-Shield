# Stage B — expansion policy (Step 6, R3)

Status 2026-09-19: Step 6 complete — 6.1–6.3 (`ringshield/expand/`), 6.4 (policy, aggregator
`expand` in `run_rings.py` and the CLI, B1 / B1b, four ablations, `results/tables/r3_expansion.csv`).
Nothing here is chosen on the test period; every evaluation is on the primary window
(`configs/eval_window.yaml`). Headline: **ring-F1 0.521 → 0.582 (+0.061 ± 0.012 over B0 on every
seed)**, 93 % of the edges the policy adds are true member edges, and the policy does not need
the candidate's own detector score.

## What Stage B has to do

B0 (`docs/R2_BASELINES.md`) builds rings from the top 0.1 % of edges and nothing else. A member
edge below the cut — a *quiet member* — never enters a ring, so ring recall is bounded by what the
detector fires on. Stage B takes each seed component and asks, edge by edge around it, "is this
transaction part of the same ring?", using the ring's own structure (timing, conservation of
amounts at the shared account, reach to the other seeds, embedding similarity) rather than the
candidate's own suspiciousness.

## 6.1 candidates — `ringshield/expand/candidates.py`

`candidates(scored_edges, included_edge_ids, delta_t_h, max_hops=2)` → one row per candidate
edge: `candidate_edge_id, anchor_edge_id, shared_account, hop, gap_s, via_edge_id, gap_via_s,
n_anchors`. **Definition (since 6.4, all methods):** a candidate is an edge sharing an endpoint
with an included edge within Δt, taking at most the 500 events nearest in time at that account
(`MAX_EVENTS_PER_QUERY`); hop 2 touches a hop-1 candidate's far endpoint within Δt of that
candidate, under the same cap. Every candidate lies in
[min included time − Δt, max included time + Δt] (the 6.4 window rule, enforced at generation so
training rows and inference see the same set). Queries run on `ringshield/expand/index.py`: a
per-split table of two events per transaction sorted by (account, time), addressed through the
composite key `account·2³² + timestamp` — a window at an account is two `searchsorted` calls,
built once per split (the initializer-globals pattern of `graph/motif_features.py`, cached in the
module). Prefix sums over the sorted events give any window's inflow / outflow counts, sums and
low-amount counts in O(1). Amounts are `amount_received`; transactions duplicated on
(from, to, timestamp, amount) carry weight 0.

## 6.2 features — `ringshield/expand/features.py`

70 features in eight groups (`FEATURE_GROUPS`): timing (11), conservation at the shared account
(9), direction pair one-hot + far-endpoint-is-member (5), reach (3), account state of the far
endpoint and the shared account over the trailing 24 h and 72 h (28), embedding cosines (2),
detector (`score_quantile`, `dead_region`; 2), the candidate's 10 trailing GFP counts.

Two kinds of information go into a row for candidate c at time t_c:

* the **included set** (seeds + whatever expansion has added) is given context — the anchor, the
  gap to it, the included inflow / outflow balance at the shared account, the mean included
  embedding. Included edges may lie after t_c (a quiet member is often paid *before* the seed
  that fires); their latest time is carried as `max_included_ts`.
* the **transaction stream** is read only at or before t_c: account state over [t_c − W, t_c),
  reach through edges in [t_c − Δt, t_c], the trailing GFP counts, the detector score. The latest
  stream timestamp a row touched is `max_ts_used`; `tests/test_expand.py` asserts
  `max_ts_used ≤ candidate_ts` on the fixture, on real val rings and on the training set — the
  policy never sees a feature computed from a later transaction.

Amendments applied: (a) the detector feature is the within-split rank / N of `score_raw`
(cross-scored folds and the R1 test models are on different scales; the calibrated score is
recorded in the cross-score file but unused); (d) `dead_region` = the score equals one of the
head's two bias constants (`ringshield/expand/dead_region.py`: every first-layer unit inactive →
c₁, every second-layer unit inactive → c₂; both are real plateaus, seed 1: 0.010742 on 12–16 % of
every split and 0.079603 on 0.5–2.5 %). Such edges can never be seeds and their quantile is not
evidence.

## 6.3 cross-scoring and the training set

`ringshield/expand/cross_score.py`: the six train days are cut into five contiguous, day-aligned
folds chosen to balance edge counts — {0}, {1}, {2, 3}, {4}, {5} (1.11 M / 0.75 M / 0.41 M /
0.48 M / 0.48 M edges). For each fold a causal Multi-GINe with R1's configuration (same
adaptations, sizes, loss weights, learning rate, causal fallback window; 30 epochs; seed 1) is
trained on the other folds' edges — the held-out days are removed from the training *graph* as
well as the labels — with the checkpoint chosen on the real validation split, as R1 does. The
fold model then scores its held-out fold with the full train split as the causal neighbourhood
graph. `cross_scores_train.parquet` holds every train edge once with `fold`, `score_raw`,
`score_quantile` (within the fold), `dead_region` (the fold model's constants). **Check 1**: the
assembly asserts day(edge) ∉ train_days[fold(edge)] for every row; `make_training_set.py`
re-checks it from the fold records.

`ringshield/expand/make_training_set.py`: for each train-visible ring (membership = the
`test_visible` definition on the train window = the split parquet's `ring_id` column, asserted
equal to `load_ground_truth` — amendment c) seeds are its member edges above the 0.1 % cut
*within their fold*; `candidates()` with Δt = 72 h and 2 hops; label 1 iff the candidate is a
member edge of the same ring. Embeddings for a row come from the fold model of the candidate,
applied to the candidate and to the ring's included edges (one model per row; the candidate is
never seen by it). Rows whose candidate lies on day 0 are dropped (amendment b). Rings with zero
seeds contribute nothing and are counted in the ceiling.

### Results (2026-09-19)

**Cross-scoring** (`experiments/R3_cross_scores/`, 30 epochs per fold, 155–200 s per epoch,
≈ 8 h in total; check 1 passed: 0 of 3,248,921 rows scored by a model trained on their day):

| fold | held-out days | edges | illicit (base rate) | trained on | best epoch (val F1) | val thr | held-out F1 @ val thr (P / R) | held-out AP | oracle F1 | dead-region edges |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 1,114,921 | 322 (0.029 %) | 2,134,000 | 11 (0.510) | 0.60 | **0.044** (0.03 / 0.19) | 0.032 | 0.096 | 0 |
| 1 | 1 | 754,449 | 408 (0.054 %) | 2,494,472 | 24 (0.606) | 0.70 | **0.231** (0.25 / 0.22) | 0.153 | 0.245 | 1,622 |
| 2 | 2, 3 | 414,812 | 798 (0.192 %) | 2,834,109 | 4 (0.500) | 0.54 | **0.467** (0.89 / 0.32) | 0.415 | 0.515 | 0 |
| 3 | 4 | 482,650 | 471 (0.098 %) | 2,766,271 | 22 (0.524) | 0.55 | **0.538** (0.64 / 0.46) | 0.491 | 0.551 | 406 |
| 4 | 5 | 482,089 | 531 (0.110 %) | 2,766,832 | 19 (0.544) | 0.53 | **0.541** (0.79 / 0.41) | 0.474 | 0.553 | 129 |

Days 2–5 sit where they should (0.47–0.54, R1's primary-window F1 is 0.495). Days 0 and 1 do
not: day 0 is the opening-day burst (a third of the split, base rate 0.029 %, the 12.65 %
reciprocal-cycle rate of `docs/FEATURE_CAUSALITY.md` §7) and day 1 is the ramp (base rate
0.054 %); a model that never saw those days does not transfer to them, and the val-tuned
threshold is far too high for their score scale. Day-0 rows are dropped from the training set
anyway (amendment b); day-1 rows stay and are the noisiest fifth of it (41 of 244 positives).

**Training set** (`experiments/R3_expansion/training_set.parquet`, `training_set.json`):

| | |
|---|---|
| train-visible rings | 220 (1,406 member edges) |
| seeds (0.1 % within fold, strict) | 1,001 member edges = 71 % of member edges; 3,251 seeds in total |
| quiet member edges | 405 (29 %); 363 in the 195 rings with ≥ 1 seed |
| rings with zero seeds | **25** (FAN-OUT 6, BIPARTITE 5, RANDOM 5, FAN-IN 2, CYCLE 2, GATHER-SCATTER 2, STACK 2, SCATTER-GATHER 1) — contribute nothing, in the ceiling |
| quiet edges reachable as candidates (Δt 72 h, 2 hops) | **266** of 363 (73 %); 259 at hop 1, 7 at hop 2 |
| candidate rows before the day-0 drop | 4,017,145 (hop 1: 19,350; hop 2: 3,997,795) |
| day-0 rows dropped | 681,201 (22 positives) |
| **training set** | **3,335,944 rows, 244 positives, 1 : 13,671**; hop 1: 16,186 rows / 237 positives (1 : 68); hop 2: 3,319,758 / 7 |
| by fold (day) | fold 1 (day 1) 1,043,621 / 41 · fold 2 (days 2–3) 721,260 / 106 · fold 3 (day 4) 830,716 / 42 · fold 4 (day 5) 740,347 / 55 |
| by pattern (positives) | SCATTER-GATHER 66, GATHER-SCATTER 48, CYCLE 36, STACK 35, FAN-IN 29, RANDOM 16, FAN-OUT 14, **BIPARTITE 0** |
| rings with ≥ 1 positive | 89 |
| dead-region rows | 2,836 (1 positive) |

Two things the numbers say before any model is trained:

1. **Hop 2 is hub noise.** AMLworld has a few mega-accounts (account 135: 101,913 transactions,
   98992: 62,275, 231317: 12,406). Almost every ring has a hop-1 candidate that touches one of
   them, and hop 2 then pulls in every transaction of the hub within 72 h — ~80 k rows per ring,
   3.3 M rows in total, for 7 positives. The `reach_2hop` feature fires on 89 % of hop-2
   negatives for the same reason (any account is two hops from anything through a hub).
   **Applied in 6.4 to every method**: `max_events_per_query = 500` (a hub's window is cut to
   the 500 events nearest the query time) keeps all 266 reachable positives and turns the
   candidate rows into 292,919 (743 truncated queries, essentially all at accounts 135 and
   98992); after the day-0 drop the training set is **247,711 rows, 244 positives, 1 : 1,014**
   (hop 1: 16,186 / 237; hop 2: 231,525 / 7).
2. **The quiet members are not far from the cut.** Their median within-fold score quantile is
   0.992–0.996 on every pattern (positives: mean 0.974, 60 % above 0.99 vs 0.15 % of negatives).
   Ranking hop-1 rows by `score_quantile` alone gives AP 0.081; by `cos_mean_included` alone
   0.078 — the two strongest single features, and they are different information (the
   embedding cosine of positives averages 0.55 vs 0.01). BIPARTITE quiet edges (51 in rings with
   seeds) never share an endpoint with a seed of their ring (0 of 51) although they are within
   hours of one, so endpoint-adjacent expansion cannot reach them by construction.

## 6.4 the policy, the aggregator `expand`, baselines and ablations

**Policy** (`ringshield/expand/policy.py`): LightGBM, binary objective, max_depth 6, learning
rate 0.05, min_child_samples 20, feature_fraction 0.8, early stopping on the held-out fold's
AUC-PR, grouped 5-fold CV by `ring_id`. `scale_pos_weight` is chosen by the same CV from
{neg/pos, √(neg/pos), 1}: at 1 : 1,000 the full ratio wrecks the fit (CV AUC-PR 0.108 ± 0.052,
best iterations 4–598 — the hop-2 negatives are swamped), √ gives 0.50 ± 0.22, **weight 1
gives 0.833 ± 0.043** (folds 0.895 / 0.796 / 0.798 / 0.812 / 0.861; pooled out-of-fold 0.821).
For reference the single-feature APs quoted at 6.3 were 0.08 (quantile) and 0.08 (cosine); a
grouped-CV logistic regression on hop-1 rows reaches 0.57. The final model is refit on all rows
with the mean best iteration (306 rounds). Gain by group: timing 0.36, detector 0.28, account
state 0.14, GFP 0.12, conservation 0.07, embedding 0.03, direction and reach 0.00.

| policy | CV AUC-PR (mean ± std, 5 grouped folds) | fold range | weight | rounds | top features (gain share) |
|---|---|---|---|---|---|
| proposed (70 features) | **0.833 ± 0.043** | 0.796–0.895 | 1 | 306 | score_quantile 0.28, hop 0.17, shared_72h_out_cnt 0.07, gfp_gather_scatter 0.07, n_anchors 0.07 |
| drop detector | **0.835 ± 0.046** | 0.788–0.903 | 1 | 206 | cos_anchor 0.24, n_anchors 0.20, hop 0.15, gfp_gather_scatter 0.09 |
| drop account_state | 0.835 ± 0.043 | 0.790–0.896 | 1 | 392 | score_quantile 0.26, gfp_gather_scatter 0.20, hop 0.14 |
| drop embedding | 0.834 ± 0.056 | 0.782–0.907 | 1 | 225 | n_anchors 0.21, gfp_scatter_gather 0.20, score_quantile 0.18 |
| hop-1 rows only | 0.869 ± 0.038 | 0.830–0.911 | √ | 238 | gfp_scatter_gather 0.44, score_quantile 0.27 |

**These AUC-PRs compare policies, not detectors.** Step 10 (R6) trains a second policy on gfpxgb's own cross-scored train split (`experiments/R6_gfpxgb_expand/policy_gfpxgb`, embedding group dropped) and it reaches **0.924 ± 0.023** — higher than the 0.833 above. That is *not* evidence of a better policy. Each policy is scored on the candidate set its own detector generates: a different detector seeds different edges, so the rows, the positive rate and the difficulty of the ranking problem all change. Only rows within one column of the table above (same candidate set, features varied) are comparable to each other. The number that compares detectors is the ring-level one in `results/tables/r6_detector_swap.csv`.

**Inference** (`ringshield/aggregators/expand.py`): per seed component (connected component of
the thresholded edges, any size) — candidates within the *seed* window
[min seed time − Δt, max seed time + Δt], features, p = policy; add the argmax if p ≥ p_min;
repeat until no candidate reaches p_min, 200 additions, or closure: every included account with
both an inflow and an outflow closes ≥ 0.98 *and* no candidate with p ≥ p_min would raise closure
anywhere (without the second clause one balanced pass-through account stops a half-recovered
stack — the fixture test caught that). The rules add every candidate with p ≥ p_min in a single
pass. The greedy path is deterministic given the included set, so the run at the lowest p_min of
the grid is computed once and the higher p_min results are its prefixes. Every added edge is
asserted inside the seed window. Rings = components of seed + expanded edges
(`rings_from_masks`; an edge added by two components merges them), `min_size` from B0,
`expanded_edges` filled, `conservation_closure` = mean closure over included accounts with both
flows; `seed_edges` / `member_edges` / `confidence` as before.

**Grid on val** (`ringshield/expand/run_expand.py`, dispatched from `run_rings.py --aggregator
expand`): the B0 cell (0.1 % / min_size 3) is fixed per seed; Δt ∈ {24, 48, 72} h × p_min ∈
{0.3, 0.5, 0.7} for a model policy, Δt only for the rules; objective val ring-F1, ties → larger
p_min then smaller Δt; the grid and the chosen cell are written to `config.yaml` before the test
split is touched. **Every run chose Δt = 24 h, and every model run p_min = 0.7 — the
conservative corner of the grid on both axes.** The grid is the one specified; nothing beyond it
was tried, so the reported operating point sits at a boundary and a stricter one might do better.

### Results — `results/tables/r3_expansion.csv` (primary window, 5 detector seeds, mean ± std)

| method | Ring-P | Ring-R | **Ring-F1** | ΔF1 vs B0 (per-seed mean ± std, min) | R≥3 | coverage | expanded edges: true member / not | quiet accounts newly covered | chosen |
|---|---|---|---|---|---|---|---|---|---|
| B0 cc (R2) | 0.814 ± 0.049 | 0.384 ± 0.039 | 0.521 ± 0.045 | — | 0.516 | 0.866 | — | — | 0.1 / 3 |
| B1 shared endpoint within Δt | 0.171 ± 0.082 | 0.162 ± 0.035 | 0.162 ± 0.051 | −0.359 ± 0.082 | 0.193 | 0.970 | 132 / 3,583 | 230 | 24 h (4 seeds) |
| B1b … and quantile > 0.99 | 0.702 ± 0.105 | 0.463 ± 0.021 | 0.555 ± 0.034 | +0.034 ± 0.051 (−0.035) | 0.632 | 0.943 | 93 / 86 | 112 | 24 h |
| **proposed** (LightGBM policy) | **0.838 ± 0.044** | 0.446 ± 0.031 | **0.582 ± 0.034** | **+0.061 ± 0.012 (+0.045)** | 0.611 | 0.942 | **75 / 6** | 90 | 24 h / 0.7 |
| ablation: drop detector | 0.846 ± 0.031 | 0.434 ± 0.034 | 0.574 ± 0.034 | +0.052 ± 0.012 (+0.040) | 0.591 | 0.934 | 63 / 7 | 74 | 24 h / 0.7 |
| ablation: drop account_state | 0.825 ± 0.034 | 0.443 ± 0.030 | 0.576 ± 0.029 | +0.054 ± 0.019 (+0.026) | 0.605 | 0.941 | 74 / 7 | 89 | 24 h / 0.7 |
| ablation: drop embedding | 0.803 ± 0.053 | 0.433 ± 0.041 | 0.562 ± 0.042 | +0.041 ± 0.011 (+0.026) | 0.591 | 0.928 | 62 / 11 | 73 | 24 h / 0.7 |
| ablation: hop-1 rows only | 0.730 ± 0.088 | 0.460 ± 0.022 | 0.562 ± 0.027 | +0.041 ± 0.033 (−0.010) | 0.630 | 0.960 | 94 / 79 | 108 | 24 h / 0.7 |

`quiet_member_recall` is a placeholder column until Step 9. Tail / whole F1 are in the csv
(proposed tail 0.678 ± 0.065 vs B0 0.563 ± 0.084). Per-seed numbers: proposed 0.598 / 0.594 / 0.565 /
0.620 / 0.532 vs B0 0.539 / 0.539 / 0.490 / 0.576 / 0.463; proposed − B1b = +0.022 / +0.037 /
−0.031 / +0.079 / +0.025 (mean +0.027 ± 0.039, 4 of 5 seeds). Accounts lost vs B0: 0 on every
run (expansion only adds).

What the table says:

* **The proposed policy is the only method that beats B0 on every seed** (+0.045 to +0.075);
  its gain has a fifth of B1b's spread. Recall goes 0.384 → 0.446 and precision does not fall
  (0.814 → 0.838): merged components (an added edge joining two seed components) remove
  duplicate predictions, and the added edges are almost all real — **75 true member edges per
  seed against 6 that are not** (93 %), versus 93 / 86 for B1b (52 %) and 132 / 3,583 for B1.
  Expansion adds members, not noise, before any partition step cleans up.
* **B1b is most of the story on recall, not on precision.** The adjacency-conditioned second
  threshold recovers slightly *more* member edges than the policy (93 vs 75) and lifts R≥3 to
  0.632, but it also drags 86 non-member edges in and lands at 0.555 ± 0.034 with one seed below
  B0. The learned policy's contribution over B1b is precision (+0.14) at a small cost in recall;
  net +0.027 on ring-F1, inside one seed-std. A sceptical reading — "adjacency-conditioned second
  threshold gets you most of the way" — is fair for recall and wrong for precision.
* **The policy does not depend on the candidate's own suspiciousness.** Dropping the detector
  group (score quantile + dead region) costs 0.008 on ring-F1 (0.574 vs 0.582, per-seed gain
  still +0.040 minimum) and nothing in CV AUC-PR (0.835 vs 0.833); the model moves its weight
  onto the anchor cosine and `n_anchors` (how many seeds the candidate touches). That is the
  result Stage B was built for: membership is read off the ring's structure — timing, how many
  seeds an edge touches, its embedding similarity to them, the trailing GFP counts — not off a
  second look at the detector. Dropping the embedding group costs the most (0.562): the cosine
  to the anchor is what replaces the score when the score is gone.
* **Hop 2 neither helps nor hurts.** With 7 hop-2 positives the model cannot learn hop 2 and the
  proposed policy adds essentially none; the hop-1-only ablation's lower ring-F1 (0.562) is not
  about hop 2 — trained on 1 : 68 instead of 1 : 1,000 its probabilities are higher, so at
  p_min = 0.7 it adds more (94 / 79) and pays in precision. The comparison is between
  operating points, not row sets.
* **Val vs test.** On val the proposed policy is 0.556 vs B0 0.549 (+0.007) and B1b is *below*
  B0 (0.460); on test the gains are +0.061 and +0.034. Val recall barely moves with expansion
  (0.484 → 0.516 for seed 1 across the whole grid) — consistent with the val diagnosis below:
  val's B0 loss is chaining, which expansion cannot fix; the test primary window has more rings
  whose seed set is one edge short of a Jaccard-0.5 match. The selection was made on val
  regardless; the test delta is reported as found.

### Limitations

* **Endpoint adjacency is a structural ceiling.** BIPARTITE quiet edges never share an endpoint
  with a seed of their ring (0 of 51 in train), and the 25 zero-seed rings contribute nothing;
  neither is reachable by any candidate-generation trick short of counterpart-of-counterpart
  search — which is exactly the hub explosion the 500-event cap removes.
* **Where the rest of the loss lives.** On val with R1 seed 1, 87 % of member edges are
  already seeds and 146 of 157 rings have seed-account Jaccard ≥ 0.5, so B0's recall loss there
  is chaining and `min_size`, not missing members; expansion's contribution is modest by
  construction (+0.06 ring-F1 on test). Step 7's decomposition (`docs/PARTITION.md`) showed
  that chaining is a val phenomenon: on the test primary window only 4 predictions per seed
  hold more than one truth ring, and 76 of the 95 unmatched truth rings are touched by no
  prediction at all (median size 2, below `min_size` or without a seed). The earlier line here
  ("Step 7 is where the larger gain lives") was right for val and wrong for test.
* The operating point sits at the conservative corner of the specified grid (Δt 24 h, p_min 0.7)
  on every seed; the grid was not extended.
* Train embeddings come from the fold models with R1's normalisation statistics (caveat
  recorded in `cross_scores.json`); day-1 rows, scored by a model that transfers poorly to the
  ramp day (held-out F1 0.23), are a fifth of the training positives.

Artefacts: `experiments/R3_expansion/{policy_*,runs/<method>/seed<S>/}` (config.yaml with the
grid, metrics.json, rings.parquet, environment.txt), `results/tables/r3_expansion.csv`,
`models/artifacts/expand_gine_causal_seed1/` (exported from the proposed seed-1 run; the CLI
runs it with `--aggregator expand --gfp … --embeddings …`, `docs/CLI.md`). Tests:
`tests/test_expand.py` (17: index, candidates incl. hub truncation, features and the
`max_ts_used ≤ t_c` assertion on fixture / real val rings / the training set, fold assignment,
dead region, the 7-account stack fixture where two seeds recover four quiet hops and stop, the
seed-window assertion, the aggregator with expanded edges, policy train / save / load, CLI
export + run round trip).

### What the val split already says about the ceiling

Before the train numbers: on val with R1 seed 1 at k* (`scratchpad` probe, 157 val-visible
rings, 710 member edges), **615 member edges (87 %) are already seeds**; the 95 quiet member
edges sit at a median score quantile of 0.998 (just under the 0.1 % cut). 54 of the 87 quiet
edges in rings with ≥ 1 seed appear as candidates (48 at hop 1, 6 at hop 2), against 1.17 M
negatives (7.2 k at hop 1). 146 of the 157 rings have Jaccard ≥ 0.5 between their seed-covered
accounts and their truth accounts, so the B0 recall loss on val is mostly chaining and
`min_size`, not missing members. The train split (weaker fold models, 30 epochs on 80 % of the
days) will have more quiet members; see the results block.

---

## Pre-registration — 11d, chain-mode expansion

**Written 2026-09-27, before any chain-mode code existed.** It targets the loss measured in
`FINDINGS.md` **B12**, not a guessed one.

### What B12 says the problem is

Under-coverage is the largest touched-but-unmatched class on the primary window (6.8 rings/seed
against 5.2 over-merged), and the partition stage cannot act on it. Every instance is a **clean
subset** — purity 1.000 on 34 of 34 — with median coverage **0.176**: a median 3 accounts recovered
from a 14-member ring, 4 seed edges already on it. **Half the instances are STACK** (5 distinct
rings, median 17 members), the pattern whose B0 per-pattern recall is 0.05.

A STACK is a chain. Greedy expansion adds one adjacent edge at a time and stops at the `p_min`
floor or the closure condition, so clearing Jaccard 0.5 on a 17-link chain needs roughly nine
successive additions and the policy halts long before that. The method does not fabricate
membership; it stops early.

### The change

On an included edge whose shared account is a **clean pass-through** — inflow ≈ outflow within the
existing role tolerance, and one dominant counterparty on each side — the greedy step may continue
*along that account* even when the candidate's policy probability falls below `p_min`, subject to:

* a **depth cap** `d ∈ {3, 5, 8}` consecutive relaxed steps;
* a **relaxed floor** `p_chain < p_min`, swept on validation;
* the existing Δt window and closure stop, unchanged.

`d` and `p_chain` are chosen on **validation ring-F1** per seed, as every other L3 parameter is.
Nothing is chosen on test.

### The prediction

1. **STACK per-pattern recall improves** over `full`, and the **under-covered count falls** below
   6.8/seed — this is the loss the change targets and the only place it should act.
2. **Added-member precision falls** from 0.93, because relaxing a floor admits weaker edges. A fall
   to ~0.85 would be an acceptable trade for a real STACK gain; below ~0.75 the change is buying
   recall with noise and should be rejected on that basis alone.
3. **Overall ring-F1 moves inside seed noise** (±0.037, the shipped pipeline's seed SD). Chain mode
   helps a handful of large rings; 13 rings out of 174 cannot move the headline.

### Instrumentation required before the run

Chain mode has **two** mechanisms and they must not be confounded: the relaxed floor `p_chain`
(admitting weaker candidates at all) and the depth cap `d` (allowing a *run* of them). If STACK
recall improves, the first question is which one did it, so the run records **per ring**:

* `chain_steps_taken` — how many relaxed steps were actually used;
* `chain_depth_reached` — the longest consecutive relaxed run, and whether it hit the cap `d`;
* `n_added_below_p_min` — additions that only the relaxed floor allowed;
* `n_added_at_depth_ge_2` — additions that required a *continuation*, i.e. the depth mechanism.

**The distinction:** if gains come with `chain_depth_reached` ≈ 1, the relaxed floor alone did the
work and the depth cap is decoration — the honest description would be "a lower threshold on
pass-through accounts", not "chain following". If the cap is frequently reached and additions at
depth ≥ 2 carry the STACK gain, chain traversal is real. These are different claims and the
distinction is reported whichever way it falls.

### How it will be judged

Reported against `full` on: ring-F1, quiet-member recall, added-member precision, the
**under-covered count and its coverage/purity decomposition**, and per-pattern recall for STACK —
with bootstrap CIs over truth rings and the paired test on matched indicators. Because prediction 3
says the headline should not move, **ring-F1 is not the criterion**; the under-covered count and
STACK recall are, and the precision floor is the veto.

* **Succeeds** if STACK recall rises and under-coverage falls with added-member precision ≥ 0.85.
* **Fails** if either is flat, or precision drops below 0.75.
* Either outcome sharpens the ceiling statement: success gives a second method result aimed at a
  measured loss; failure establishes that greedy expansion cannot traverse long chains **even when
  the floor is relaxed**, which is a stronger claim than not having tried.

### Outcome: 11d is not run as designed (2026-09-27)

**The pre-registered diagnostic was run before the implementation, and it invalidated the design.**

11d assumed the STACK loss was the policy declining later links of a chain. `FINDINGS.md` **B13**
measured it instead of assuming it: **all 140 STACK missing member edges are disconnected from the
recovered fragment inside the evaluation window** — not distant, unreachable. 24 of 26 sit *inside*
the Δt window, so time is not the constraint either. A relaxed floor cannot admit a candidate that
was never generated, and a depth cap cannot walk a path that does not exist. **Both of 11d's
mechanisms are inapplicable to the pattern it was built for**, and its prediction 1 (STACK recall
improves) would have failed for a reason that has nothing to do with chain mode.

What the diagnostic *did* find is a smaller, real target: **GATHER-SCATTER's 31 missing edges all
sit exactly one hop from the recovered fragment**, 74 % were generated as candidates, and they were
declined by the policy. That is a genuine floor problem — about **19 % of the under-covered mass**,
roughly 1.6 rings per seed, on rings small enough (median 6.5 members) that adding a few members can
clear Jaccard 0.5.

So the honest disposition: **11d as pre-registered is withdrawn, not attempted and failed.** A
floor-relaxation experiment scoped to one-hop pass-through candidates on GATHER-SCATTER-like rings
remains defensible, but it addresses a fifth of the class rather than the half the original design
claimed, and that should be stated before anyone spends time on it.

This is the fourth pre-registration in Step 11 whose first prediction did not survive contact with
a measurement — and the first one where writing the diagnostic down in advance saved the
implementation rather than merely making its failure legible.
