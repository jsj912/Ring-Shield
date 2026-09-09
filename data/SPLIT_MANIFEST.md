# Elliptic Split Manifest

Generated: 2026-09-08T16:54:30

## Split rule
Time-based split on `time_step` (NOT random — avoids future-leakage into training).

- Train: time_step 1 - 34
- Test:  time_step 35 - 49

## Feature set
**AF** (165 features (93 local + 72 one-hop aggregated))

## Node counts

| Split | Total nodes | Illicit (1) | Licit (0) | Unknown (-1) |
|-------|-------------|-------------|-----------|--------------|
| Train | 136265 | 3462 | 26432 | 106371 |
| Test  | 67504 | 1083 | 15587 | 50834 |

## Edge counts (cross-split edges dropped)

| Split | Edges kept |
|-------|-----------|
| Train | 156843 |
| Test  | 77512 |

## Notes
- Illicit-class F1 (label == 1) is the headline metric, per Weber et al.
- "Unknown" labeled nodes are typically excluded from supervised train/eval loss
  but may still be used as graph structure (their features/edges still count).
- This split must be reused unchanged for every baseline (E1-E4) for a fair comparison.


---

# AMLworld HI-Small Split Manifest

Generated: 2026-09-09T14:10:44

## Split rule
Chronological split at 70% of transactions sorted by timestamp.

- Train: Timestamp < 572110
- Test:  Timestamp >= 572110

## Transaction counts

| Split | Total txns | Laundering | Illicit ratio | Unique rings |
|-------|-----------|------------|---------------|--------------|
| Train | 3554649 | 2856 | 0.08% | 244 |
| Test  | 1523696 | 2321 | 0.15% | 226 |

## Feature set
Transaction-level: Amount Sent, Sent Currency, Amount Received, Received Currency, Payment Format, hour_of_day, day_of_week, day_index
Account-level (fit on train only): sender_out_degree, sender_out_amount_mean, sender_out_amount_std, sender_out_amount_max, sender_out_volume_total, receiver_in_degree, receiver_in_amount_mean, receiver_in_amount_std, receiver_in_amount_max, receiver_in_volume_total
Total feature dim: 18

## Pattern types in ground truth
pattern_type
GATHER-SCATTER    716
SCATTER-GATHER    626
STACK             466
FAN-OUT           342
FAN-IN            318
CYCLE             287
BIPARTITE         263
RANDOM            191

## Notes
- Account-level features (degree, amount stats) computed ONLY from train-period
  transactions to prevent future leakage.
- Ring ground truth saved separately in amlworld_ring_ground_truth.parquet for E7+.
- Pattern matching rate: 3455/3209 (107.7%)
