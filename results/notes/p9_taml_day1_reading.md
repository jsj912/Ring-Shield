# T-P9 day 1, reading only (2026-11-15). No TAML training run; the GPU is busy with GenAgg.

Code: github.com/rricocuevas1/taml at 15ebffde29c255e74a51e48248a81d4633c0f902 (2026-05-21), shallow-cloned to
external/taml (git-ignored by `.gitignore:94 external/`). About 3,300 lines: run_taml.py, TAML_algorithm.py, TAML_configs.py,
backbones/{mpnn_backbones, FraudGT}, dataset_scripts/build_ibm_graph_dataset.py, utils/. Nothing installed, nothing executed.

## What the code needs
- **Environment:** the README pins Python 3.9, torch 2.4.0 (cu121), torch_geometric 2.6.1, pyg_lib, torch_sparse and
  torch_scatter, pandas 2.3.3, scikit-learn 1.6.1 and pyarrow 21. `.venv312` has torch 2.5.1, PyG 2.8.0, torch_sparse and
  torch_scatter, but **no pyg_lib**, and it has **pandas 3.0.5** and scikit-learn 1.9. NeighborLoader needs pyg_lib or
  torch_sparse; pandas 3 copy-on-write and string dtypes are a real risk for the builder. → Use a **separate venv**
  (.venv_taml, recorded), as the runbook asks when pins conflict. The data builder needs the raw `HI-Small_Trans.csv`, which
  exists at E:/JSJ/Ring-Shield/data/raw (SHA pinned in the appendix manifest). It is copied, not edited.
- **Data model:** one account-to-account graph per **calendar day** (`Time_step = Timestamp.dt.day`), days 1–10 only.
  - Nodes are the accounts active that day. Each has 26 aggregate features, and its label is 1 if it took part in any
    laundering transaction that day.
  - Edges are that day's transactions, with 7 features.
  - Scalers are fitted on days ≤ 8.
  - `remove_leakage` drops account-day rows whose full feature vector repeats between days ≤ 8 and days 9–10, keeping each
    on one side at random (seed 1998 for the shuffle, unseeded `np.random` for the side). Exact feature repeats are rare,
    but this does make the test graph differ slightly from the full test day. Count it on day 1.
- **Their split:** train days 1–8 (validation 7–8 is used only for tuning, then folded back in), test days 9–10. Five seeds:
  28, 1999, 1130, 5898, 820. Best IBM configuration: FraudGT backbone, output 16, lr 1e-3, batch 16, λ 0.75,
  250 epochs, 2-hop exploration, η 2.
- **Outputs:** test_model writes **only per-day aggregates** (AUC-ROC, AUC-PR, mean set precision and recall per class).
  It does not write per-account signatures or anomaly scores.
- **Their metric** (utils/evaluation_utils.py): for each labelled target account v, the truth set is v plus the accounts
  labelled laundering within 2 hops of v through laundering-labelled accounts. Precision is |truth ∩ predicted| /
  |predicted| and recall is |truth ∩ predicted| / |truth|, averaged over class-1 targets (and separately over class 0, whose
  truth set is {v}). The truth comes from the day's account labels, not from pattern files.

## What must change to run it under our split and scope (no model-code edits)
1. **Days.** Our days are (timestamp − 10) // 86400 (docs/PROTOCOL.md), and the raw file starts 2022-09-01 00:20. So our train days 0–5,
   validation 6–7 and primary test window (691210–864009 s) are their calendar days 1–6, 7–8 and 9–10, up to an origin offset of
   at most 20 minutes that is not yet verified. **The splits line up almost exactly.** The only
   change is to train on 1–6 instead of 1–8: our rule keeps validation for thresholds and does not fold it back. On day 1, count the edges that fall
   on different days under the two rules.
2. **Training steps** are module-level dicts in TAML_configs.py. A wrapper outside their tree (experiments/R15_taml/run_ours.py)
   passes `training_steps=[1..6]` to `train_taml` directly. No edit to their files.
3. **Signatures and scores.** A wrapper re-implements only test_model's loop: it imports their model class, calls
   `model([v, data, emb_t, emb_s])` for every account on days 7–8 (validation) and 9–10 (test), and writes
   (day, account, anomaly score, signature). This touches no model code. It is the main piece of new code.
4. **Conversion to rings** is the fixed rule in the runbook: score > validation threshold, |signature| ≥ 3, sort by risk,
   greedy Jaccard < 0.5. Account sets map to edges and windows via our account ids (string account plus bank, as in
   `HI-Small_Trans.csv`). Signatures are per day, so a ring crossing midnight appears as two signatures. That limits TAML,
   and it is reported, not patched.
5. **Scoring:** `evaluation/score_external.py` (four conventions) for TAML's rings; `evaluation/taml_metric.py` applies their
   set P/R to B0, B1b, proposed and full. Their truth definition (2-hop labelled neighbourhood) is implemented as written.

Go/no-go reading: **probable GO.** Their split can be fed without editing model code: a config override plus an external
wrapper. Open risks are the environment (pyg_lib on Windows for torch 2.4 cu121; WSL2 fallback) and the test-loop cost
below. The gate itself needs the one-epoch run, which waits for the GPU.

## Estimated cost
- **Data build:** one pass over 5M rows in pandas with per-day groupbys, CPU only. About 10–30 min.
- **Training:** each epoch iterates over days, and each day yields balanced batches of 2 × (laundering accounts that day)
  / 16. HI-Small has roughly 0.1 % laundering edges, so a few hundred to ~1,000 positive accounts per day, which gives
  ~50–150 batches per day and ~300–900 per epoch on days 1–6. Each batch runs a 2-hop full-neighbour NeighborLoader plus
  a Python signature search per target. **Unmeasured guess: 1–4 min per epoch, so 250 epochs ≈ 4–16 h per seed.**
  For 3 seeds that is 12–48 h of GPU. The runbook allows 3 days in total, so the upper end would breach "training > 2× its
  estimate". The one-epoch measurement on day 1 sets this.
- **Inference:** LabeledSampler targets **every** labelled account on a day (all accounts are labelled 0/1 in the
  supervised setting), and each target runs a Python BFS. Our wrapper skips their `get_true_signature`, which uses
  torch.where over all edges per target. Days 7–10 have ~10^5 active accounts each, so at ~1–5 ms per target that is
  ~0.5–3 h per day and ~2–12 h per seed for 4 days. A cheaper option: score every account with the anomaly path first,
  and search signatures only above a low validation quantile. That changes no model code, but it changes which accounts get
  signatures. **If used, register it before test scoring.**
- **Our side:** wrapper, conversion and metric code plus tests, about 0.5 day of CPU-only work. It can be written before the
  GPU is free.

Day-1 actions waiting for the GPU: create .venv_taml; build the 10 daily graphs; one epoch on their own split (days 1–8) to
time it; attempt one headline number (FraudGT, seed 28) only if the measured cost fits; then GO/NO-GO.
