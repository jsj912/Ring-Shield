#!/bin/bash
# Build TAML's 10 daily IBM graphs with their unmodified builder. Raw file copied (not edited), SHA logged.
# Layout their builder expects: cwd=work/build -> ../data/IBM/HI-Small_Trans.csv, writes ../data/IBM/Graphs/Account_to_Account/.
set -eu
cd /e/JSJ/RS-react/experiments/R15_taml
mkdir -p work/build work/data/IBM/Graphs/Account_to_Account
[ -f work/data/IBM/HI-Small_Trans.csv ] || cp /e/JSJ/Ring-Shield/data/raw/HI-Small_Trans.csv work/data/IBM/
sha256sum work/data/IBM/HI-Small_Trans.csv /e/JSJ/Ring-Shield/data/raw/HI-Small_Trans.csv > work/raw_sha256.txt
cd work/build; t0=$(date +%s)
PYTHONIOENCODING=utf-8 ../../../../.venv_taml/Scripts/python.exe -u ../../../../external/taml/dataset_scripts/build_ibm_graph_dataset.py
echo "build done in $(( $(date +%s) - t0 )) s"
