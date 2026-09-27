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


---

# AMLworld HI-Small Split Manifest (v2 — 60/20/20)

Generated: 2026-09-10T00:49:06

## Split rule
Day-based chronological 60/20/20 split (matching Altman et al. NeurIPS 2023).
Optimal day boundaries found via min-max split error.

- Train: day [0, 6)  →  Timestamp < 518400
- Val:   day [6, 8)  →  Timestamp in [518400, 691200)
- Test:  day [8, 18)  →  Timestamp >= 691200

## Transaction counts

| Split | Total txns | Laundering | Illicit ratio | Unique rings |
|-------|-----------|------------|---------------|--------------|
| Train | 3248921 | 2530 | 0.08% | 220 |
| Val   | 965524 | 1036 | 0.11% | 157 |
| Test  | 863900 | 1611 | 0.19% | 183 |

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


---

# AMLworld HI-Small Split Manifest (v2 — 60/20/20)

Generated: 2026-09-16T16:49:49

## Split rule
Day-based chronological 60/20/20 split (matching Altman et al. NeurIPS 2023).
Optimal day boundaries found via min-max split error.

- Train: day [0, 6)  →  Timestamp < 518400
- Val:   day [6, 8)  →  Timestamp in [518400, 691200)
- Test:  day [8, 18)  →  Timestamp >= 691200

## Transaction counts

| Split | Total txns | Laundering | Illicit ratio | Unique rings |
|-------|-----------|------------|---------------|--------------|
| Train | 3248921 | 2530 | 0.08% | 220 |
| Val   | 965524 | 1036 | 0.11% | 157 |
| Test  | 863900 | 1611 | 0.19% | 183 |

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


---

# AMLworld HI-Small Split Manifest (v2 — 60/20/20)

Generated: 2026-09-27T16:37:27

## Split rule
Day-based chronological 60/20/20 split (matching Altman et al. NeurIPS 2023).
Optimal day boundaries found via min-max split error.

- Train: day [0, 6)  →  Timestamp < 518400
- Val:   day [6, 8)  →  Timestamp in [518400, 691200)
- Test:  day [8, 17)  →  Timestamp >= 691200

## Transaction counts

| Split | Total txns | Laundering | Illicit ratio | Unique rings |
|-------|-----------|------------|---------------|--------------|
| Train | 4432934 | 1993 | 0.04% | 75 |
| Val   | 1316442 | 770 | 0.06% | 54 |
| Test  | 1174673 | 802 | 0.07% | 56 |

## Feature set
Transaction-level: Amount Sent, Sent Currency, Amount Received, Received Currency, Payment Format, hour_of_day, day_of_week, day_index
Account-level (fit on train only): sender_out_degree, sender_out_amount_mean, sender_out_amount_std, sender_out_amount_max, sender_out_volume_total, receiver_in_degree, receiver_in_amount_mean, receiver_in_amount_std, receiver_in_amount_max, receiver_in_volume_total
Total feature dim: 18

## Pattern types in ground truth
pattern_type
SCATTER-GATHER    182
STACK             180
GATHER-SCATTER    150
FAN-OUT           149
BIPARTITE         129
CYCLE              83
RANDOM             77
FAN-IN             73

## Notes
- Account-level features (degree, amount stats) computed ONLY from train-period
  transactions to prevent future leakage.
- Ring ground truth saved separately in amlworld_ring_ground_truth.parquet for E7+.
- Pattern matching rate: 1113/1023 (108.8%)
