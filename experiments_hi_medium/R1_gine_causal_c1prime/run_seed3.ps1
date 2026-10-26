# C1' seed 3 rerun (V3.3). Flags are copied verbatim from the seeds 2-3 invocation and match
# experiments_hi_medium/R1_gine_causal_c1prime/config.yaml. Seed 3's first attempt died at epoch 25
# when its parent shell went away (no OS fault: uptime unbroken, no WER/Kernel-Power/OOM events), so
# this writes to a log file and is meant to be launched detached from the terminal.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath 'E:\JSJ\Ring-Shield'
$env:PYTHONIOENCODING = 'utf-8'
$env:RINGSHIELD_PATHS = 'configs/paths_hi_medium.yaml'
$log = 'E:\JSJ\Ring-Shield\logs\c1prime_seed3.log'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
"SEED3 START $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $log -Encoding utf8
& .venv312\Scripts\python.exe -u models\tgn.py `
  --data-dir data/processed_hi_medium --raw-dir data/raw_hi_medium `
  --out-dir experiments_hi_medium/R1_gine_causal_c1prime `
  --feature-cache data/processed_hi_medium/feature_cache `
  --skip-final-test --train-label-days 1 3 `
  --arch gine --causal --window-s 1800 --split-days 4 6 `
  --epochs 100 --patience 20 --batch-size 8192 --lr 0.006 `
  --n-hidden 66 --n-gnn-layers 2 --w-ce1 1.0 --w-ce2 9.0 `
  --num-neighs 100 100 --emlps --ports --tds --reverse-mp --ego --gfp `
  --seeds 3 *>> $log
"SEED3 END $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') exit=$LASTEXITCODE" | Out-File -FilePath $log -Append -Encoding utf8
