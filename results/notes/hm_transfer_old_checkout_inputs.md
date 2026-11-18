# Old-checkout inputs read by evaluation/hm_transfer_paired.py (2026-11-18, for T-P10)

The addendum 5 comparison (results/tables/hm_transfer_paired_addendum5.csv, sha256 b903268cbf5865b581c2aa84bead0800585bc8a93aede372969719922d13d473) reads exactly two files that
exist only in the old checkout E:\JSJ\Ring-Shield (read only, not modified). They are the old HI-Medium-trained
GINe test scores behind the 0.0898 bar (experiments_hi_medium/closeout_a15, seeds 1-2).

| path | bytes | sha256 |
|---|---|---|
| E:/JSJ/Ring-Shield/experiments_hi_medium/R1_gine_causal_c1prime/scores_test_seed1.parquet | 187976689 | fb6fc73fb9f01b70fca3141f62a5e8f8ee9b81ab5c6416175a02b9e6074fa3ef |
| E:/JSJ/Ring-Shield/experiments_hi_medium/R1_gine_causal_c1prime/scores_test_seed2.parquet | 228000476 | 896b8ac5e9f2295bb7c90e4852669ebfc5297126ff7f3884d1ed04ae03556f8a |

Everything else the script reads is in this repository: the old rings experiments_hi_medium/closeout_a15/primary/global/b0/seed{1,2}.parquet,
the transferred scores experiments/R18_hm_transfer/closeout_input/R1_gine_causal_c1prime/scores_test_seed{1..5}.parquet and
the rings experiments/R18_hm_transfer/closeout/primary/global/{b0,b1b}/seed{1..5}.parquet.
T-P10 must either copy the two files above into the package (and point the script's old-arm path at them) or reference them by these hashes.
