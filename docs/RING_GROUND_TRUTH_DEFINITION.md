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