#!/bin/bash
# T-P9 addendum step 1: two seeded CPU rebuilds (A, B) for the repeatability check.
set -eu
cd /e/JSJ/RS-react/experiments/R15_taml
for T in A B; do
  B=work_seeded/build_$T; mkdir -p $B/build $B/data/IBM/Graphs/Account_to_Account
  [ -f $B/data/IBM/HI-Small_Trans.csv ] || ln work/data/IBM/HI-Small_Trans.csv $B/data/IBM/HI-Small_Trans.csv
  ( cd $B/build; t0=$(date +%s); CUDA_VISIBLE_DEVICES= PYTHONIOENCODING=utf-8 ../../../../../.venv_taml/Scripts/python.exe -u ../../../rebuild_seeded.py --seed 20261117 > ../build.log 2>&1; echo "build $T done in $(( $(date +%s) - t0 )) s" >> ../build.log )
done
