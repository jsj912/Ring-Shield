# Addendum: MEGA-GenAgg paired family (2026-11-16). EXPLORATORY

Written and hashed before any test in this family is run. The sha256 of this file is recorded in
paper/RUNBOOK_PROGRESS.md.

## Status: exploratory
Four of the five GenAgg seeds (1–4) were already seen descriptively, in
results/tables/r6_genagg_provisional_4seed.csv and r6_genagg_provisional_4seed_valpicked.csv, before
this family was declared. The family is therefore exploratory, not confirmatory. Its intervals and
p-values are reported as such and are not part of the pre-registered primary results.

## Arms
Every arm uses the fixed 0.1 % budget (configs/threshold_rule_k010.yaml), scoring batch 2048, seeds 1–5,
the primary window, the test_visible scope, and Jaccard 0.5. The matcher's tie-break is the one in force
when the shipped tables were scored (file order); see item 4 of the 2026-11-16 instructions.
- GenAgg B0: experiments/R6_b0_sb2048_k010/megagenagg
- GenAgg full: experiments/R6_full_sb2048_k010/megagenagg
- GenAgg full without embeddings: experiments/R6_full_sb2048_k010/megagenagg_noembed
- MEGA-GIN full: experiments/R6_full_sb2048_k010/mega
- GINe (shipped) B0 and full: ../RS-e2e/experiments/R2_b0/gine_causal and R4_partition/runs/average

## Family (four comparisons, Holm over the four)
- (i) GenAgg full vs GINe full
- (ii) GenAgg full vs MEGA-GIN full
- (iii) GenAgg B0 vs GINe B0
- (iv) GenAgg full vs GenAgg full without embeddings

## Test
- Statistic: ring-F1, the per-seed value averaged over the five seeds.
- Method: paired unit bootstrap with 10,000 draws and rng seed 20261111. It uses evaluation/precision_paired.py unchanged, through evaluation/genagg_paired.py.
- Resampling unit: each truth ring, plus each off-ring account cluster. Both arms are recomputed on the same draw.
- Reported: the difference, its 95 % percentile interval, the two-sided p-value and Holm's adjusted p-value.
- Added-member precision comes out of the same draws and is reported descriptively. It is outside the Holm family.

## Decision rule for (iv)
- **The interval excludes zero in favour of no embeddings** (GenAgg full minus no-embeddings is below 0 and the upper bound is below 0): stop and ask the author before anything else. The follow-up would be to export GenAgg train-split embeddings on the GPU, then retrain the expansion policy and affinity on them, as was done for GFP+XGB.
- **The interval includes zero:** do not retrain. The paper reports both rows with a policy-transfer caveat: the policy cut-offs were learned in GINe's 198-dimensional embedding space and are applied unchanged in GenAgg's 192-dimensional space.
- **The interval excludes zero in favour of embeddings:** there is no retraining, and both rows are reported with the same caveat.
