#!/usr/bin/env bash
# deep-analysis #8 (B17 re-registration 2026-11-12): ring-folded cross-scores -> training set ->
# policy -> run_expand on detector seeds 1-5 with the shipped cell fixed (24 h / p_min 0.7).
set -euo pipefail
cd /e/JSJ/RS-react
PY=.venv312/Scripts/python.exe
R1=../RS-e2e/experiments/R1_gine_causal
OUT=experiments/R3_ringfold
export PYTHONIOENCODING=utf-8
$PY -u ringshield/expand/cross_score.py --run-dir $R1 --out-dir $OUT/cross_scores --epochs 30 --ring-folds
$PY -u ringshield/expand/make_training_set.py --cross-scores $OUT/cross_scores --out $OUT/expansion --run-dir $R1 --device cuda
$PY -u ringshield/expand/policy.py --training-set $OUT/expansion/training_set.parquet --out $OUT/expansion/policy_proposed --seed 1
for S in 1 2 3 4 5; do
  $PY -u ringshield/expand/run_expand.py --seed $S --r1-dir $R1 --policy-dir $OUT/expansion/policy_proposed \
      --labels-dir ../RS-testing1/contract/out --p-min-grid 0.7 --delta-grid-h 24 --out $OUT/runs/proposed/seed$S
done
echo CHAIN_DONE
