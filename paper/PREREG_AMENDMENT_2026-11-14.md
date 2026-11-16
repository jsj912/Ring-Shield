# Pre-registration amendment, 2026-11-14

Amends: `paper/PREREG_2026-11-14.md` (sha256 568a296fd095abe8b07849f0dcfb71abce095de2a8143a9c7bae3831372110a6),
which stays frozen and unedited. Written on the author's instruction after the T-P2 result was seen.

## 1. Defect in the T-P2 bar

The three registered T-P2 readings (CI inside [−0.02, +0.02] → "no detectable effect"; CI excludes
0 → caveat; CI wider than ±0.05 → "under-powered") do not cover every possible interval: a CI that
includes 0, is narrower than ±0.05, and has one end outside ±0.02 matches none of them. This is a
defect in the pre-registration, found **after** the result was seen.

## 2. T-P2 ring-F1 verdict: INCONCLUSIVE

Ring-folded minus shipped expansion policy, primary window, 5 detector seeds, paired ring-unit
bootstrap (10,000 draws, seed 20261114): Δ ring-F1 = **+0.0028 [−0.0137, +0.0211], p = 0.77**.
The difference is not distinguishable from zero, and the ±0.02 equivalence reading is **not met**
(upper end +0.0211). No equivalence claim is made anywhere in the paper.

## 3. Post hoc analyses

Every analysis added after the T-P2 result (the precision comparisons of the ring-folded policy
against B1b, quiet-member recall, and the ring-folded comparison against B1b on ring-F1) is
**post hoc and exploratory**, and is labelled so wherever it appears.

## Addendum A (2026-11-14, after Checkpoint A, author-approved): ring-folded full pipeline

**Post hoc and exploratory**, like §3. The full pipeline (expansion + average-linkage partition) was
re-run per detector seed 1–5 with the ring-folded expansion policy
(`experiments/R3_ringfold/expansion/policy_proposed`, the ring-folded fixed cell from
`experiments/R3_ringfold/runs/proposed/seed*/config.yaml`). Everything else is shipped: the R1
detector, the R4 affinity model unchanged (note: it was trained on pairs built from day-folded
inputs), and the linkage cut chosen on validation as shipped. Before the run, shipped `full` seed 1
was reproduced with the shipped inputs: ring-F1 0.6045 = 0.6045.

Outputs, new files only: `experiments/R4_partition_ringfold/average/seed{1..5}`,
`results/tables/v45_posthoc_{ring_ci,quiet_members,significance}.csv`,
`results/tables/v45_ringfold_full_precision_paired.{csv,json}`.

Primary window, 5 seeds; ring bootstrap (1,000 resamples, seed 0) for single-arm intervals; paired
unit bootstrap (10,000 draws, seed 20261111) for paired differences:

| Quantity | Shipped full (day folds) | Ring-folded full | Ring-folded − shipped |
|---|---|---|---|
| ring-F1 | 0.5894 [0.5023, 0.6747] | 0.5893 [0.5034, 0.6722] | −0.0002 [−0.0170, +0.0185], p 0.96 |
| ring precision | 0.8184 | 0.7597 | (single-arm only) |
| ring recall | 0.4609 | 0.4828 | |
| added-member precision | 0.9257 | 0.8174 | −0.1084 [−0.1672, −0.0601], p 0.0002 |
| added-member precision vs B1b (0.5179) | +0.4078 [+0.3410, +0.4801] | +0.2995 [+0.2326, +0.3642] | |
| quiet-member recall | 0.2026 [0.1358, 0.2838] | 0.2425 [0.1710, 0.3355] | |
| ring-F1 vs B1b | +0.0342 [+0.0031, +0.0652] | +0.0340 [+0.0080, +0.0615] | |
