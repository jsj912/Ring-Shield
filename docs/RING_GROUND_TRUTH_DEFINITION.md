# Ring Ground Truth Definition

**Status:** Draft — must be signed off by all team members before E7 results are reported.  
**Last updated:** September 2026

---

## 1. What is a ground-truth ring?

A ground-truth ring is one `BEGIN LAUNDERING ATTEMPT ... END LAUNDERING ATTEMPT` block in `HI-Small_Patterns.txt`. Each block corresponds to a single coordinated laundering attempt by one or more accounts.

- **Total rings:** 370
- **Total pattern transactions:** 3,209 (matched 3,455 rows in formatted_transactions.csv due to ~246 duplicate-payment matches — see §5)

## 2. Pattern types

| Pattern | Count | Description |
|---------|-------|-------------|
| GATHER-SCATTER | 716 txns | Multiple sources → intermediary → multiple destinations |
| SCATTER-GATHER | 626 txns | Single source → multiple intermediaries → single destination |
| STACK | 466 txns | Layered chain of transactions through multiple accounts |
| FAN-OUT | 342 txns | Single source → many destinations |
| FAN-IN | 318 txns | Many sources → single destination |
| CYCLE | 287 txns | Money returns to origin through a chain of accounts |
| BIPARTITE | 263 txns | Two groups of accounts trading back and forth |
| RANDOM | 191 txns | No fixed structural pattern |

## 3. Ring membership

For a given ring `r` with `ring_id = r`:

- **Member transactions:** all rows in `amlworld_ring_ground_truth.parquet` where `ring_id == r`
- **Member accounts:** the union of `from_id` and `to_id` across those transactions
- **Time window:** `[min(timestamp), max(timestamp)]` across the ring's transactions

## 4. Evaluation protocol

### 4.1 Which rings are scored?

Scope policy is **`test_visible`** (decided 2026-09-16): a ring is in scope for the test
split if it has at least one pattern-line transaction in the test period, and its scored
member set is the union of `from_id`/`to_id` over its transactions **in that split only**.
N_test_rings = 183, N_val_rings = 157. The `strict` (all transactions in the split,
86 test rings) and `majority` (> 50 %, 120 test rings) policies are reported only in
Appendix A of the D1 document below. Numbers: `docs/ring_scope.json`.

### 4.2 Ring-level detection

A ring is considered **detected** if the model's per-edge fraud scores, when aggregated, exceed a ring-level threshold. Two aggregation strategies are evaluated:

- **Mean-score:** mean of `pred_prob` across all test-period transactions in the ring
- **Max-score:** max of `pred_prob` across all test-period transactions in the ring

### 4.3 Ring-level matching (predicted → ground truth)

When the ring aggregator proposes a predicted ring (a connected component of high-score edges), it is matched to a ground-truth ring using **Jaccard similarity** on account sets:

```
Jaccard(predicted, ground_truth) = |accounts_pred ∩ accounts_gt| / |accounts_pred ∪ accounts_gt|
```

A predicted ring matches a ground-truth ring if Jaccard ≥ 0.5.

**Why Jaccard over one-directional overlap:** one-directional (e.g., "≥50% of GT accounts appear in prediction") lets a giant predicted blob "match" everything it swallows. Jaccard penalizes both false positives (extra accounts) and false negatives (missed accounts).

### 4.4 Ring-level metrics

| Metric | Definition |
|--------|-----------|
| Ring Precision | # matched predicted rings / # predicted rings |
| Ring Recall | # matched GT rings / # GT rings in test |
| Ring F1 | Harmonic mean of ring precision and ring recall |
| Time-to-Detection (TTD) | For each detected ring: timestamp of first high-score edge minus ring start time |

### 4.5 Per-pattern-type breakdown

All ring metrics are also reported broken down by pattern type (FAN-IN, FAN-OUT, CYCLE, etc.) to show which patterns the model handles well vs poorly.

## 5. Known data quality notes

### 5.1 Pattern match rate: 107.7%

3,209 pattern transactions in `HI-Small_Patterns.txt` matched 3,455 rows in `formatted_transactions.csv`. The overshoot is caused by ~246 duplicate payments in the synthetic AMLworld data: multiple rows in the transaction CSV have the same `(from_id, to_id, Timestamp)` key. All matching rows receive the ring label.

**Decision:** accepted. The duplicates represent the same real-world payment appearing multiple times in the synthetic data generator's output. They do not inflate ring membership counts because they involve the same accounts.

### 5.2 Account ID normalization

Bank/account IDs in `HI-Small_Patterns.txt` have leading zeros (e.g., `021174`). Pandas reads these as integers from `HI-Small_Trans.csv`, stripping the zeros (e.g., `21174`). The pattern parser applies `str(int(val))` normalization to match.

### 5.3 Temporal leakage in GNN neighbor sampling

The `LinkNeighborLoader` in E6 does NOT enforce temporal ordering — neighbors sampled for a seed transaction at time `t` may include edges from after `t`. This matches IBM's protocol (their code has the same behavior), so detection F1 numbers are comparable to theirs. However, **Time-to-Detection computed on these scores is not a causally valid metric** — it should be computed in a separate causal pass with `temporal_strategy='last'` if PyG supports it, or by manually masking future edges.

## 6. Consistency requirement

The ring definition, matching rule (Jaccard ≥ 0.5), and evaluation metrics defined here must be used identically in:

- **E5b** (if ring-level evaluation is added retroactively)
- **E7** (ring aggregation — primary user of this document)
- **E9** (full cascade — ring-level results section)
- **E13** (no-ring-aggregation ablation — comparison baseline)

Any change to this definition requires updating all four experiments.





# D1 — Ring Ground Truth Definition

**Status:** DRAFT — needs sign-off from all three team members before E7 code is written
**Blocks:** E7 (ring aggregation), E13 (pattern-type breakdown)
**Must be consistent with:** E5b (GFP features), `preprocessing/amlworld_loader.py`

This document fixes what counts as a "fraud ring" in RingShield, so that the
aggregator, the evaluation metrics, and the paper all mean the same thing by
the word. Most of this is documenting a decision the parser already makes —
the open items in section 6 are the ones that genuinely need a decision.

---

## 1. What a ground-truth ring is

A ground-truth ring is **one `BEGIN LAUNDERING ATTEMPT` / `END LAUNDERING
ATTEMPT` block** in `HI-Small_Patterns.txt`.

`preprocessing/amlworld_loader.py` assigns each block a sequential integer
`ring_id` as it parses the file. That id is the ring's identity throughout the
project. It has no meaning beyond "the Nth block in the file" and must not be
compared across re-parses of a different patterns file.

Totals in HI-Small:

| Quantity | Value |
|---|---|
| Ground-truth rings | 370 |
| Pattern transactions listed | 3,209 |
| Rows matched in the transaction table | 3,455 (107.7%) |
| Pattern types | 8 |

Transactions per pattern type: GATHER-SCATTER 716, SCATTER-GATHER 626,
STACK 466, FAN-OUT 342, FAN-IN 318, CYCLE 287, BIPARTITE 263, RANDOM 191.
(These are transaction counts, not ring counts.)

The 107.7% match rate is expected. The synthetic generator emits duplicate
payments — same sender, receiver, amount and timestamp — so one pattern line
can match several rows in the transaction table. All matching rows are
retained. This is not a data-quality defect and needs no correction.

## 2. Ring membership

The **members** of a ring are the union of `from_id` and `to_id` over every
transaction in that ring's block.

Membership is a set of account ids. It is unordered, and an account may belong
to more than one ring.

## 3. Ring time window

`start_time` = minimum `Timestamp` over the ring's transactions
`end_time` = maximum `Timestamp` over the ring's transactions

Timestamps are seconds since the dataset's minimum timestamp, matching the
convention in `formatted_transactions.csv`.

## 4. Which rings are scored

**Decision (2026-09-16): the primary scope policy is `test_visible`.**

A ring is **in scope for a split** if it has **≥ 1 pattern-line transaction in that
split**. Its **scored member set** is the union of `from_id` / `to_id` over its
transactions **in that split only** (the accounts a model scoring that split can see).
Scope is defined on the 3,209 pattern lines, never on the 3,455 matched rows, so
duplicate payments in the transaction table cannot change which rings are in scope.
A pattern line belongs to the split whose day range contains its timestamp (loader
basis).

Rationale for replacing the earlier `strict` default:

1. strict scope leaves **13 validation rings** — too few to choose any threshold or
   hyper-parameter on;
2. it discards the **97 rings straddling the val/test boundary**, which hold most
   of the illicit test transactions (1,240 of 1,611 laundering-labelled
   test transactions lie in a `test_visible` ring, only 721 in a strict one);
3. the model only sees test-period edges, so comparing its predictions to a ring's
   full member list penalises it for accounts that never transacted in the window.

`strict` (all lines in the split, full membership) and `majority` (> 50 % of lines in
the split, full membership) remain as **appendix** policies (Appendix A).

Computed by Step 2.2 (`preprocessing/ring_scope.py`, output `docs/ring_scope.json`):

```bash
python preprocessing/ring_scope.py --gt data/processed/amlworld_ring_ground_truth.parquet --splits data/processed --out docs/ring_scope.json
```

**N_test_rings = 183** and **N_val_rings = 157** (`test_visible`).

| policy | test rings | test rings < 3 scored members | val rings | val rings < 3 scored members |
|---|---|---|---|---|
| **test_visible** (primary) | **183** | **51** | **157** | **43** |
| strict | 86 | 29 | 13 | 9 |
| majority | 120 | 29 | 49 | 9 |

Rings straddling a boundary: 97 touching test, 144 touching val, 147 overall.
"Scored members" is the visible set for `test_visible` and full membership otherwise.

Pattern type of the rings with < 3 scored members:

| | test_visible test | test_visible val | strict test | strict val |
|---|---|---|---|---|
| count | 51 | 43 | 29 | 9 |
| by pattern | BIPARTITE 10, CYCLE 7, FAN-IN 4, FAN-OUT 5, GATHER-SCATTER 6, RANDOM 4, SCATTER-GATHER 5, STACK 10 | BIPARTITE 1, CYCLE 7, FAN-IN 7, FAN-OUT 9, GATHER-SCATTER 4, RANDOM 5, SCATTER-GATHER 5, STACK 5 | BIPARTITE 10, CYCLE 1, FAN-IN 2, FAN-OUT 2, GATHER-SCATTER 2, RANDOM 4, SCATTER-GATHER 4, STACK 4 | BIPARTITE 1, FAN-OUT 2, RANDOM 4, SCATTER-GATHER 1, STACK 1 |

Over all 370 rings, **88 have fewer than three members** in full: BIPARTITE 18, CYCLE 14, FAN-IN 4, FAN-OUT 8, GATHER-SCATTER 8, RANDOM 13, SCATTER-GATHER 11, STACK 12.
Two-member CYCLE / BIPARTITE / STACK blocks are how the AMLworld generator emits its
smallest patterns; they are undetectable under FR04.6's minimum ring size of 3 and stay in
the denominator (section 6).

`test_visible` test rings by pattern: BIPARTITE 20, CYCLE 22, FAN-IN 19, FAN-OUT 21, GATHER-SCATTER 37, RANDOM 17, SCATTER-GATHER 22, STACK 25.

**Why the strict count is 86 and not the 85 in the legacy E7 metrics.**
`models/ring_aggregator.py` took the test window from `predictions_with_ids.csv`, whose
timestamps are 10 s lower than the loader basis used by the ground truth
(`configs/paths.yaml: legacy_csv_time_offset_s`). Ring 346's last transaction sits exactly
at the test-window maximum (1,527,490) and was pushed out by that 10 s mismatch. The
majority count (120) is unchanged; counting matched rows instead of pattern lines would
give 123 (rings 213, 221, 264 have exactly half their lines in test and duplicate rows tip
them over), which is why scope is defined on pattern lines.

**Labels versus membership.** Ring membership comes from the pattern lines
(`ring_id` on matched rows); edge labels come from `Is Laundering`. The 99 ring-labelled
rows in the test split with `Is Laundering = 0` are duplicate-payment matches (section 1),
and no code treats the two as identical. Flow sums over a ring are deduplicated on
(from, to, timestamp, amount).

**Banks.** 366 of 370 rings (98.9%) span more than one bank (`n_banks > 1`,
banks from `data/processed/account_bank.parquet`), most likely because the AMLworld
generator draws pattern accounts across banks uniformly. The tenancy experiment (R10)
must therefore treat a ring as belonging to every bank with a member, and this
near-universal cross-bank rate is a synthetic-data caveat, not a property of real
laundering rings.

## 4a. Evaluation windows inside the test split (Step 3b-w apply, 2026-09-17)

`docs/TEST_TAIL.md`: the last eight test days (days 10–17, 1,108 edges) hold 655 of the
1,611 test positives at a 59 % base rate and no licit background. Headline numbers are
therefore computed on the **primary window, test days 8–9** (`configs/eval_window.yaml`);
the **tail, days 10–17**, is always reported beside them and never merged in; the whole
split is kept as a labelled third column.

The `test_visible` rule is applied **per window**: a ring is in scope of a window if ≥ 1 of
its pattern-line transactions falls in the window, and its scored members are the
endpoints of its transactions inside that window only. **A straddling ring's tail edges
belong to the tail block**, on the truth side and on the prediction side (a predicted ring
is likewise restricted to the endpoints of its member edges inside the window;
`ringshield/evaluate.py`). Counts (`tests/test_eval_window.py` asserts them):

| window | days | in-scope rings (`test_visible`) | rings with ≥ 3 scored members |
|---|---|---|---|
| primary | 8–9 | **174** (= 183 − 9 rings whose every visible edge is in the tail) | 114 |
| tail | 10–17 | **109** (rings with ≥ 1 tail edge; 100 of them also have primary edges) | 84 |
| whole | 8–17 | 183 | 132 |

Ring-Recall on the primary window has 174 in the denominator; the 9 all-tail rings and
the tail-only edges of the 100 partial rings are scored in the tail block. Val (days 6–7)
has no tail; thresholds and grids are chosen there as before.

## 5. Matching a predicted ring to a ground-truth ring

A predicted ring `P` (set of accounts) **matches** a ground-truth ring `T`
(set of accounts) when:

```
Jaccard(P, T) = |P ∩ T| / |P ∪ T|  ≥  0.5
```

**Jaccard, not one-directional overlap.** One-directional overlap
(`|P ∩ T| / |T|`) is not used, because a single huge predicted component that
swallows many true rings would "match" every one of them and score near-perfect
recall on a useless result. Jaccard penalises the over-merge.

Each predicted ring matches at most one ground-truth ring and vice versa. Where
several pairings clear the threshold, take the highest-Jaccard pairing first
and remove both from the pool (greedy one-to-one).

## 6. Decisions (recorded 2026-09-16, Step 2; scope policy revised the same day)

- [x] **Scope policy: `test_visible`.** A ring is in scope for a split if ≥ 1 of its
      pattern-line transactions falls in that split; its scored members are the accounts
      on those in-split transactions. Boundary (straddling) rings are therefore in scope
      for both splits they touch, each with its own visible member set. `strict` and
      `majority` are appendix-only. **Decision: test_visible; strict and majority in
      Appendix A only.**

- [x] **N_test_rings** and **N_val_rings** computed and recorded in section 4.
      **Value: N_test_rings = 183, N_val_rings = 157 (`test_visible`).**

- [x] **Jaccard threshold of 0.5** confirmed (computed between the predicted member set and
      the ring's *visible* member set). A sensitivity sweep at 0.3 and 0.7 is reported
      alongside every headline ring number. **Decision: 0.5, sweep {0.3, 0.7}.**

- [x] **Singleton and pair components.** 51 of the 183 `test_visible` test rings
      (43 of the 157 val rings) have fewer than three visible members. They **stay in the
      denominator** of Ring-Recall. The aggregator's minimum ring size is a
      **validation-grid parameter, `min_size ∈ {2, 3}`**, chosen on the val rings together
      with the score threshold and recorded in the run config before any test run. ~~Under
      `min_size = 3` these rings are guaranteed misses and recall is bounded above by 0.721 on
      the test set.~~ **CORRECTED 2026-09-30 (V3.2b): they are not guaranteed misses and there is
      no such bound** — `min_size` constrains the unrestricted prediction, matching uses the
      window-restricted one, and 11.4 of these rings are matched per seed. See §6a.
      **Decision: keep in denominator.**

## 6a. Ceiling on test-period evidence (Step 2.3, `test_visible`)

Produced by the same command as section 4 (`preprocessing/ring_scope.py`, key
`ceiling.by_policy.test_visible` in `docs/ring_scope.json`). Quote these in the report's
limitations.

| | value |
|---|---|
| (a) laundering-labelled transactions in the test split | **1,611** |
| (b) of those, inside an in-scope (`test_visible`) ring | **1,240** (77.0%); the other 371 laundering-labelled test transactions belong to no ring |
| (c) in-scope-ring members (full membership) with **no test-period transaction** | **155 / 1,962 = 7.9%** — unrecoverable from test evidence |
| (c′) additionally, members whose every test transaction is licit-labelled | 497 / 1,962; together with (c): 652 = 33.2% |

(c) is the share of full ring membership that no model scoring the test period can
recover, whatever it does; it is exactly the gap between full and visible membership and
is why `test_visible` scores visible members. (c′) members do have test transactions but
none labelled illicit; they are not in the visible set either.

**Ring-level ceiling on the primary window (Step 7 close, 2026-09-22.)** The same question at
ring level: of the 174 `test_visible` rings in the primary window (test days 8–9), how many can
a pipeline match at Jaccard 0.5 at all? Mean per detector seed over 5 seeds, from
`evaluation/unmatched_rings.py` (`results/tables/r4_unmatched.csv`), for the best pipeline to
date (`full` = detector at 0.1 % + expansion + partition):

| | primary (174 rings) | val (157 rings) |
|---|---|---|
| matched at Jaccard 0.5 | **80.2** | 86.2 |
| **(a) fewer than 3 visible members** — undetectable under `min_size` 3 | **48.6 (28 %)** | 39.6 (25 %) |
| **(b) ≥ 3 members, untouched by any seed or expanded edge** | **33.2 (19 %)** | 15.0 (10 %) |
| (c) touched, Jaccard < 0.5: over-merged / under-covered | 5.2 / 6.8 | 7.2 / 9.0 |

*(c) corrected 2026-09-27 — see the note in `docs/PARTITION.md`; matched, (a) and (b) are unaffected.*

(a) counts the small rings this pipeline leaves **unmatched**: 1,359 of the 1,387 (a)-rings
counted across seeds have exactly 2 visible members and 28 have 1.

> **Correction, 2026-09-30 (V3.2b).** This paragraph previously said that with `min_size` 3 fixed,
> *"ring recall on the primary window is capped at about 0.72 ((174 − 48.6)/174)"*. **Retracted.**
> That arithmetic subtracts an observed outcome (48.6 unmatched small rings) and calls the result
> a bound. `min_size` constrains the **unrestricted** prediction; matching is done on the
> **window-restricted** prediction, which can be smaller — 13 of 106 per seed fall below 3
> members. **11.4 of the 60 sub-`min_size` rings are matched per seed**, 11.0 of them at exactly
> 2 members and most at Jaccard 1.0. (a) is therefore an outcome of this pipeline, not a property
> of the ground truth.

The reachable part beyond today's 0.46 is mostly class (b) — rings the detector does not fire on
at all. Quote (a) and (b) in the limitations next to (c) above; the per-pattern split (BIPARTITE is
almost entirely (a) + (b)) is in `docs/PARTITION.md`.

## Appendix A. Strict and majority policies (not used for reported numbers)

| | strict | majority |
|---|---|---|
| test rings | 86 | 120 |
| test rings < 3 members | 29 | 29 |
| val rings | 13 | 49 |
| val rings < 3 members | 9 | 9 |
| (b) test laundering txns in scope | 721 (44.8%) | 1,038 (64.4%) |
| (c) members with no test txn | 0 / 694 = 0.0% | 18 / 1,125 = 1.6% |
| (c) unrecoverable incl. licit-only | 0 / 694 = 0.0% | 80 / 1,125 = 7.1% |

Under strict scope (c) is 0 % by construction: every member has a laundering-labelled
ring transaction in the test split. Strict scope was the default until 2026-09-16; the
legacy E7 numbers (`experiments/legacy_E7_test_tuned`) were computed under it with the
10 s window error described in section 4 and are not reported.

## 7. Metrics built on this definition

Given the matching rule in section 5:

- **Ring-Precision** = matched predicted rings / all predicted rings
- **Ring-Recall** = matched ground-truth rings / all in-scope ground-truth rings
  (`test_visible`: 183 test rings, 157 val rings — rings with < 3 visible members included)
- **Ring-Recall≥3** (secondary) = matched ground-truth rings with ≥ 3 visible members /
  in-scope ground-truth rings with ≥ 3 visible members (132 test, 114 val). Reported
  next to Ring-Recall so the size floor's cost is visible rather than hidden in the
  denominator.
- **Ring-F1** = harmonic mean of Ring-Precision and Ring-Recall (the primary recall)
- **Member-Coverage** = mean over matched pairs of `|P ∩ T| / |T|`
- **Time-to-Detection** = see caveat below

**Validation grid.** Every aggregator parameter is chosen on the validation split
(`test_visible` val rings) and written to the run's `config.yaml` before the test run:
the seed quantile (`seed_frac_pct`, `configs/threshold_rule.yaml`) and `min_size ∈ {2, 3}`.
That is the whole B0 grid ("threshold, components, size"); a time-gap split or a density
filter is not a B0 knob but a baseline variant (B3, Step 7), evaluated on the same expanded
subgraph as the proposed method (corrected 2026-09-17, Step 4). Nothing is tuned on the
test period. Jaccard stays fixed at 0.5 (sweep 0.3 / 0.7 reported, not tuned).

> **Time-to-Detection caveat.** Neighbour sampling in `LinkNeighborLoader` has
> no temporal filter, so a transaction's score can depend on transactions that
> occur after it. This follows IBM's benchmark protocol and is fine for the
> detection metrics, but it means Time-to-Detection computed on these scores is
> not a causally valid number. Either add a time mask and re-score for this
> metric alone, or drop it. Do not report it from the current scores without
> saying so.

## 8. Sign-off

| Member | Date | Agreed |
|---|---|---|
| | | |
| | | |
| | | |