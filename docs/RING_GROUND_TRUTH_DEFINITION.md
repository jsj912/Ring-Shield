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

Only rings whose **majority of transactions** (≥50% by count) fall in the **test period** are scored. Rings entirely in train/val are training signal. Rings straddling val/test are scored only if ≥50% of their transactions are in test.

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

Record the count here once computed: **N_test_rings = ____**

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

## 6. Open decisions — need team sign-off

- [ ] **Boundary rings.** What happens to a ring whose transactions straddle
      the val/test boundary? Options: (a) exclude from both, (b) assign to the
      split holding the majority of its transactions, (c) assign by
      `start_time`. Recommend (a) — cleanest, and the count is small.
      **Decision: ____**

- [ ] **N_test_rings** computed and recorded in section 4. **Value: ____**

- [ ] **Jaccard threshold of 0.5** confirmed, or changed with a reason.
      **Decision: ____**

- [ ] **Singleton and pair components.** FR04.6 sets min ring size 3. Some
      ground-truth rings may have fewer than 3 members — check, and if any
      exist, decide whether they are excluded from the denominator (they are
      undetectable by construction) or counted as guaranteed misses.
      **Decision: ____**

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