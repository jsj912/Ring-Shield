# Amendment to PREREG_Q_2026-11-15.md (2026-11-15)

Amends `paper/PREREG_Q_2026-11-15.md` (sha256 aa991ccee83d0f103a9f3af692d4f638705a33a824637893d6749ae97dbbff45),
which stays frozen. Written before any Q1, Q2, Q3 or Q6 data was computed or seen.

## 1. Q1 budget definition (correction)

The frozen file defines the budget as N = ⌈0.001 · n_edges⌉ "per the shipped `threshold_for_pct`".
That is wrong. `ringshield.aggregators.cc.threshold_for_pct` returns q = `np.percentile(scores, 99.9)`
over the non-NaN scores, and seeds are the edges with score > q. Corrected definitions:

- **Nominal budget** B = 0.001 × (number of non-NaN scores in the split).
- **Edges decided by a tie** T = number of edges with score exactly equal to q. These are excluded by
  the strict rule, and they sit on the boundary.
- **Share decided by a tie** = T / B. The stop rule (< 1 % on every seed in both splits → stop) applies
  to this share.
- Also reported: the shipped seed count n_seed = #(score > q), and the number of edges tied at the maximum.

The Q1 variant's N (the shipped seed count n_seed for that seed and split) and the Q2 rule's N
(the same n_seed) are unchanged.
