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

Only rings whose transactions **all** fall in the **test period** are scored (**strict** policy; N_test_rings = 86). Rings straddling the val/test boundary are out of scope for every reported number; the **majority** policy (> 50% of pattern transactions in test, 120 rings) is reported once in an appendix. See section 4 and Appendix A of the D1 document below, and `docs/ring_scope.json`.

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

A ring is **in scope for test evaluation** if its transactions fall inside the
test split (day boundaries i=6, j=8; 863,900 transactions).

Rings are the denominator of Ring-Recall, so this set must be computed once
and reused. Compute it before writing the aggregator:

```python
# rings whose transactions fall entirely within the test split
gt = pd.read_parquet("data/processed/amlworld_ring_ground_truth.parquet")
# ... intersect ring transaction ids with te_inds, group by ring_id
```

Record the count here once computed: **N_test_rings = 86** (strict), **N_val_rings = 13** (strict).

Computed by Step 2.2 (`preprocessing/ring_scope.py`, output `docs/ring_scope.json`):

```bash
python preprocessing/ring_scope.py --gt data/processed/amlworld_ring_ground_truth.parquet --splits data/processed --out docs/ring_scope.json
```

A pattern transaction belongs to the split whose day range contains its timestamp
(loader basis). A ring is **strict** in a split when all of its pattern transactions
fall in that split, **majority** when more than half do. Scope is defined on the
pattern lines (3,209), not on the 3,455 matched rows: duplicate payments in the
transaction table must not change which rings are in scope.

| | test | val |
|---|---|---|
| rings touching the split | 183 | 157 |
| **strict** (all transactions in split) | **86** | **13** |
| majority (> 50 %) | 120 | 49 |
| straddling a boundary | 97 | 144 |
| strict rings with < 3 members | 29 | 9 |
| pattern transactions in strict rings | 721 | 24 |

Strict test rings by pattern: BIPARTITE 15, CYCLE 9, FAN-IN 9, FAN-OUT 9, GATHER-SCATTER 16, RANDOM 12, SCATTER-GATHER 10, STACK 6.

**Why 86 and not the 85 in the legacy E7 metrics.** `models/ring_aggregator.py` took the
test window from `predictions_with_ids.csv`, whose timestamps are 10 s lower than the
loader basis used by the ground truth (`configs/paths.yaml: legacy_csv_time_offset_s`).
Ring 346's last transaction sits exactly at the test-window maximum (1,527,490) and was
pushed out by that 10 s mismatch. With one time basis the strict count is 86. The
majority count (120) is unchanged; counting matched rows instead of pattern lines would
give 123, because rings 213, 221 and 264 have exactly half their transactions in test and
duplicate rows tip them over — which is why scope is defined on pattern lines.

Over all 370 rings: 366 (98.9%) span more than one bank
(`n_banks > 1`, banks from `data/processed/account_bank.parquet`); 88 have fewer than
three members; 147 straddle at least one split boundary.

> If this number is small (under ~100), Ring-Recall moves in visible jumps and
> a single ring is worth more than a percentage point. Say so in the paper's
> limitations rather than reporting Ring-Recall to three decimals.

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

## 6. Decisions (recorded 2026-09-16, Step 2)

- [x] **Boundary rings.** Scope policy is **strict**: a ring is in scope for a split only
      if every one of its pattern transactions falls in that split. Rings straddling a
      boundary are out of scope for every reported number. The **majority** policy
      (> 50 %) is reported once, in Appendix A, and nowhere else.
      **Decision: strict; majority in appendix only.**

- [x] **N_test_rings** computed and recorded in section 4.
      **Value: N_test_rings = 86 (strict), N_val_rings = 13 (strict).**

- [x] **Jaccard threshold of 0.5** confirmed. A sensitivity sweep at 0.3 and 0.7 is
      reported alongside every headline ring number.
      **Decision: 0.5, sweep {0.3, 0.7}.**

- [x] **Singleton and pair components.** 88 of 370 rings have fewer than three
      members (29 of the 86 strict test rings). They **stay in the denominator**
      of Ring-Recall as guaranteed misses under FR04.6's minimum size of 3, so recall is
      bounded above by 0.663 on the strict test set.
      **Decision: keep in denominator.**

## 6a. Ceiling on test-period evidence (Step 2.3)

Produced by the same command as section 4 (`preprocessing/ring_scope.py`, key `ceiling`
in `docs/ring_scope.json`). Quote these in the report's limitations.

| | value |
|---|---|
| (a) laundering-labelled transactions in the test split | **1,611** |
| (b) of those, inside a strict-scope test ring | **721** (44.8%); 1,240 are in any ring, 371 in none |
| (c) strict-ring members unrecoverable from test evidence | **0 / 694 = 0.0%** |
| (c) majority-ring members unrecoverable | 80 / 1125 = 7.1% |
| (c) members of all 370 rings unrecoverable | 1855 / 3170 = 58.5% (459 with no test transaction, 1396 with only licit-labelled ones) |

A member is *unrecoverable* when it has no test-period transaction at all (everything in
train/val) or every test-period transaction it touches is labelled licit. For strict rings
this is 0 % by construction — every member has at least one laundering-labelled ring
transaction in test — so the strict denominator is fully recoverable in principle. The
59% figure over all rings is what a model scored on the test period cannot reach
if scope were widened.

Data note: 99 of the 1,339 ring-labelled rows in the test split carry
`Is Laundering = 0` (duplicate-payment matches, section 1). Edge-level labels come from
`Is Laundering`; ring membership from `ring_id`. They are not identical and are not
treated as such.

## Appendix A. Majority-policy counts (not used for reported numbers)

Under the majority policy (> 50 % of pattern transactions in the split): **120** test
rings (34 more than strict, all straddling the val/test boundary), **49** val
rings. Members of the 120 majority test rings: 7.1% unrecoverable from test evidence.

## 7. Metrics built on this definition

Given the matching rule in section 5:

- **Ring-Precision** = matched predicted rings / all predicted rings
- **Ring-Recall** = matched ground-truth rings / all in-scope ground-truth rings
- **Ring-F1** = harmonic mean of the two
- **Member-Coverage** = mean over matched pairs of `|P ∩ T| / |T|`
- **Time-to-Detection** = see caveat below

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