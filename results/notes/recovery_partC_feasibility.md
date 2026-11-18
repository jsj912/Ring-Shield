# Part C feasibility: HI-Small-trained GenAgg on HI-Medium (2026-11-16). STOP, inputs not ready

Labelled throughout: trained on HI-Small, zero-shot on HI-Medium. Pre-registration: paper/PREREG_RECOVERY_2026-11-16.md, Part C step 1.
No GPU work was run, and no HI-Medium score exists.

## What is available
- HI-Medium raw and formatted transactions: E:/JSJ/Ring-Shield/data/raw_hi_medium/ (HI-Medium_Trans.csv 3.03 GB; formatted_transactions.csv 1.75 GB).
- Processed splits and ring ground truth: ../RS-e2e/data/processed_hi_medium/ (read-only, as in T-P4).
- GenAgg seed 1 checkpoint: experiments/R6_megagenagg/model_best_seed1.pt.
- Host RAM 127.6 GB, about 102 GB free. The formatted CSV is 1.75 GB, so loading it stays far below 80 %.

## Why it stops (pre-registered rule: stop if any input is missing)
1. **Categorical codes do not match.** The formatter numbers currencies and payment formats in order of first appearance in each dataset's raw file. MEGA reads `Received Currency` and `Payment Format` as numeric edge features. HI-Small and HI-Medium give different orders:
   - currency (HI-Small vs HI-Medium): code 1 = Bitcoin vs Euro, 2 = Euro vs UK Pound, 3 = Australian Dollar vs Bitcoin, and so on; only US Dollar (0) and Ruble (9) keep their codes;
   - payment format: Cash and Wire swap (codes 4 and 5).

   Scored as is, the model would see wrong currencies and formats. A remap of HI-Medium codes onto HI-Small's vocabulary is a missing input. It is a small, deterministic step: a new file such as `formatted_transactions_hsvocab.csv`, with the original left untouched.
2. **"HI-Small's fitted normalisation" does not exist in the published code.** MEGA's `get_data` applies `z_norm` to each split with that split's own mean and SD: train, validation and test are each normalised by their own statistics (third_party/mega_gnn/data_loading.py lines 132–136). HI-Small's validation and test scores were produced that way. There are two possible readings, and the pre-registration fixed neither in a workable way:
   - **(i) as published:** self-normalise HI-Medium validation and test. This matches how every HI-Small score was made, but it "refits" statistics on HI-Medium.
   - **(ii) HI-Small train statistics:** apply HI-Small's train-split mean and SD to HI-Medium. This needs a code path the published loader does not have, and it differs from how HI-Small validation and test were scored. The timestamp feature, raw seconds from the dataset start, also has a different range in HI-Medium.

## Proposed next step (author decision)
- Write the vocabulary remap: a new file, with a test that the remapped HI-Medium codes decode to the same strings as HI-Small's.
- Choose (i) or (ii). (i) is recommended, because it is the procedure the reported HI-Small numbers used.
- Then run step 1 as pre-registered: a 1 % validation slice at batch 2048 with the watchdog, then projections, then the gate.

Part C step 1 is not complete. Steps 2–5 were not started.

## Update (2026-11-16 13:10Z, after the amendment): STOP at the split check
The vocabulary remap is done and verified (experiments/R18_hm_transfer/raw/HI-Medium/mapping.json). The 1 %
slice run then loaded HI-Medium (peak host RAM 51 %, GPU 1.1 GB including TAML) and stopped at
`mega_adapter.check_splits`: `MEGA's train split differs from ours: 19,487,126 vs 9,146,808`.
- MEGA's `get_data` makes its own split by cumulative-transaction share (60 / 20 / 20) over days. On HI-Small that split equals ours, which is asserted. On HI-Medium it does not.
- Our HI-Medium split (the close-out and the 0.4495 reference AP) is train days 0–3 (9.15 M), validation days 4–5 (3.86 M), and test days 6–27 (18.89 M).
- Scoring with MEGA's split would evaluate other days than the reference value. Scoring with ours needs the loader's split replaced by our EdgeID lists. Normalisation then follows our split: validation edges normalised over train + validation, test over all edges.

No score was produced and no timing projection exists yet. Proposed: a wrapper that overrides MEGA's split indices
with our HI-Medium EdgeIDs (no change to their code; the check then passes by construction). Then rerun the 1 % slice.
This needs the author's approval because it changes the input definition again.

## Addendum 2 wrapper: normalisation (2026-11-16)
`z_norm` (third_party/mega_gnn/data_util.py) runs once per data object inside `get_data`, unchanged:

| data object | edges in it, HI-Small as shipped (MEGA's own split = ours) | edges in it, HI-Medium under the wrapper (our split) | statistics computed over |
|---|---|---|---|
| train | train days 0–5 | train days 0–3 | those edges |
| validation | train + validation days 0–7 | train + validation days 0–5 | those edges |
| test | all edges, days 0–17 | all edges, days 0–27 | those edges |

The rule is identical in both cases. Only the day cut points differ, and under the wrapper they are supplied from our
processed split. `check_splits` asserts edge-for-edge equality with that split.
