# T-P9 addendum (2026-11-17): TAML representability count before any retraining or scoring

Author decision, 2026-11-17. Written and sha256-logged in paper/RUNBOOK_PROGRESS.md before anything below is run.
Supersedes nothing in PREREG_2026-11-14 T-P9; it inserts a gate ahead of it.

## Context
- TAML seed 28 was trained twice: on their split (`runs/`) and on our split (`runs_ours/ours_e250_FraudGT_seed28`, early stop at epoch 36).
- Neither can be mapped to our accounts. TAML's graphs store no account names: a node id is the account's position in that step's sorted name list. `remove_leakage` assigns each recurring account to one side at random with an unseeded `np.random.rand`, so the released graphs cannot be rebuilt.
- Both trained models and their logs are kept unchanged and labelled "not scored" in the progress log.

## Step 1: seeded rebuild (CPU only, no training)
- Run TAML's unmodified builder (`external/taml/dataset_scripts/build_ibm_graph_dataset.py` @ 15ebffde) through a wrapper (`experiments/R15_taml/rebuild_seeded.py`). The wrapper:
  - executes the builder's function definitions unchanged;
  - runs the builder's top-level sequence verbatim, with `np.random.seed(20261117)` set immediately before it;
  - saves, per step, the sorted account-name list (node id → name) and the graphs, into a new directory `experiments/R15_taml/work_seeded/build_<A|B>/`.
- The original `work/` graphs are not touched. CUDA is hidden (`CUDA_VISIBLE_DEVICES=""`).
- Split: TAML's default steps (train 1–6, validation 7–8, test 9–10). This equals our split, since our day k = calendar day k+1 = their step k+1. Verified: our `timestamp_int` = seconds since 2022-09-01 00:00 + 10, so primary days 8–9 = steps 9–10.
- **Repeatability check:** build twice (A and B). Per step, the following must be identical: x, y, edge_index, edge_attr, n_id and the name list. If they are not, stop and report.

## Step 2: representability count (primary window, steps 9–10 = our days 8–9)
- **Truth set:** the 174 rings in scope `test_visible`, primary window (`ringshield.truth.load_ground_truth`). Members are the visible accounts.
- **Matchable subset:** the 97 rings with an in-window connected piece of ≥ 3 accounts (`evaluation.component_scope.component_truth`, min_members 3), as in Q0.
- **Account identity:** our account_id → `account_number` string (`data/processed/account_bank.parquet`), since TAML keys accounts by the account string alone. 8 account strings occur at more than one bank; TAML merges them, and so does this count.
- **Counts:**
  - a. members present as a node in their step-9 graph, step-10 graph, or either (count and share per ring);
  - b. rings with ≥ 3 members present (per step and either);
  - c. rings with ≥ 3 members present that are connected to each other inside TAML's test graph: some connected component of the subgraph induced on the present members has ≥ 3 members, with edges taken undirected. Reported for step 9, for step 10, and across both, where the union graph joins the two steps' edges by account name;
  - d. a–c restricted to the 97 matchable rings.
- **Transaction survival:** for each ring's in-window transactions, the share whose (sender, receiver) account pair is an edge of TAML's graph for that transaction's step.

## Step 3: decision rule (declared before counting)
- **Gate statistic:** count (c), across both days, on the 97 matchable rings.
- **If fewer than 60 % (< 58.2, i.e. ≤ 58 rings) satisfy it, T-P9 ends as NO-GO.**
  - Write results/notes/p9_taml.md (appended, dated) with:
    - the four protocol differences (truth definition; feature aggregation over the test days with normalisation fitted on steps 1–8; the one-sided assignment of recurring accounts and how thin it makes the test graphs; the unseeded random step that makes the released graphs unrepeatable);
    - the representability counts as the measured ceiling;
    - one paragraph proposed for the paper's related work and limitations, marked as a proposal. The paper is not edited.
- **If 60 % or more (≥ 59 rings) satisfy it:** stop. Report the counts with a proposed conversion rule from TAML's per-account sub-networks to ring predictions, for the author's approval, before any retraining or scoring.

## Priority
HI-Medium (addendum 5 close-out and seeds 2–5) has priority on GPU and CPU. The rebuild runs only when it does not slow the HI-Medium work.
