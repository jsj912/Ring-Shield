# Pre-registration: recovery probes A, B, C (2026-11-16)

Written and hashed before anything in Parts A–C is run. The sha256 is logged in paper/RUNBOOK_PROGRESS.md.
All three parts are **post hoc and exploratory**: they were declared after the main results were known.
TAML seed 1 keeps running on the GPU and is not disturbed. Nothing is committed. The frozen tables
are untouched, and every output goes to a new file.

Common protocol, unless a part says otherwise:
- primary window, test_visible scope, Jaccard 0.5, min size 3;
- fixed 0.1 % seed budget;
- every downstream parameter chosen on validation only;
- the matcher's tie-break is file order, as the reference tables were scored.

## Order
Part B first, then Part A, then Part C's feasibility step. A report follows each part. A gate stop in
one part does not stop the others.

## Part A — rank-averaged ensemble as the seed source (CPU, existing score files)
**Not** the best-rank fusion of FINDINGS B14. This averages ranks; it does not take a union.

1. **Ensemble scores.** Within each split (validation, test) separately:
   - each model's `score_raw` becomes its percentile rank over that split's edges (average ranks for ties, scaled to (0, 1]);
   - the ensemble score is the mean rank across the models.

   Three ensembles, in this order:
   1. **E-GenAgg5**: GenAgg seeds 1–5 (experiments/R6_megagenagg, batch 2048).
   2. **E-2048**: E-GenAgg5 plus MEGA-GIN seeds 1–5 (experiments/R6_mega_sb2048), all at batch 2048.
   3. **E-All15**: E-2048 plus shipped Multi-GINe seeds 1–5 (../RS-e2e/experiments/R1_gine_causal). GINe was scored at batch 8192, so its look-ahead differs (median 600 s against 180 s). The write-up says so.

   Each ensemble is written as one "seed" (seed 1) in experiments/R16_ensemble/<name>/, as `scores_{val,test}_seed1.parquet` with columns edge_id, timestamp, score_raw. `score_calibrated` comes from the existing isotonic calibration (models/calibrate.py, fit on validation only). The ensemble has no embeddings and no checkpoint, as for GFP+XGB.
2. **Arms per ensemble:**
   - **B0**: `ringshield.run_rings`, cc, rule configs/threshold_rule_k010.yaml.
   - **Full**: run_expand with experiments/R3_expansion/policy_no_embedding, then run_partition (average) with experiments/R4_partition/affinity_no_embedding.

   An ensemble has no single embedding space, so only the no-embedding arms are used. Policy features that use the score quantile take the ensemble's own scores and quantiles, which is automatic, since the pipeline reads the ensemble's score file.
3. **Selection and gate, validation only.**
   - Pick the ensemble whose full arm has the best validation ring-F1: the `chosen.val_ring_f1` in that run's partition config.yaml. Ties go to the first in the order above.
   - **Gate:** its validation ring-F1 must exceed the best of these single-detector five-seed means of `chosen.val_ring_f1` (full arm):
     - GINe full: ../RS-e2e/experiments/R4_partition/runs/average
     - MEGA-GIN full: experiments/R6_full_sb2048_k010/mega
     - GenAgg full without embeddings: experiments/R6_full_sb2048_k010/megagenagg_noembed
   - If the gate fails: stop Part A, report the validation table, and do not score test.

   The ring runners score test as part of their run. Test outputs of all ensembles therefore exist on disk. Under this protocol only the selected ensemble's test numbers are read, and only after the gate passes. If the gate fails, no test number from any ensemble is read or reported.
4. **If the gate passes, read test once.**
   - Primary comparison: selected ensemble full against GINe full, ring-F1. The ensemble is one run; GINe is the five-seed mean inside each draw.
   - Test: paired unit bootstrap (evaluation/precision_paired.py machinery), 10,000 draws, rng seed 20261116.
   - Secondary, descriptive: ring precision, ring recall, rings touched and added-member precision, and the same comparison against GenAgg full without embeddings.
   - The ensemble is one run, not five seeds, and every report says so.
5. **Descriptive edge metrics.** Each ensemble's test edge F1 (threshold from validation, reference grid: 400 quantiles in [0.90, 0.99999]) and its test AP, beside the single-detector five-seed means. These are read only after step 3's gate decision is recorded.

## Part B — do test rings have labelled history? (CPU, a count; no method is run)
**Assumption:** labels of transactions before the evaluation window are available at test time.
**Caveat:** in practice laundering labels arrive with a delay. Sensitivity (d) shortens the history accordingly.

1. For each of the 174 primary-window truth rings (test_visible member sets):
   - (a) the ring itself has transactions before day 8;
   - (b) some in-window member account is an endpoint of a labelled-illicit edge in days 0–7, from any ring;
   - (c) as (b), counting only edges of a *different* ring;
   - (d) as (b), with history limited to days 0–5 (label-delay sensitivity).

   Days are `timestamp // 86400`; days 0–7 are the train and validation splits.
2. Cross-tabulate (a)–(d) against the Q0 loss buckets (results/tables/q0_buckets.csv definitions), per seed and mean, using the shipped GINe full runs that Q0 used. Buckets:
   - matched;
   - unobservable-unmatched (Q0 `a_unmatched`);
   - matchable-untouched (Q0 `b`);
   - recovered-too-thinly (Q0 `c1`);
   - merged / split (Q0 `c2` + `c3`).

   The per-ring bucket assignment is recomputed with the Q0 code. If the per-ring counts differ from q0_buckets.csv, the note says so.
3. **Cost side.** Among all accounts active on days 8–9 (in-window edges):
   - how many have labelled-illicit history under (b) and under (d);
   - what share of their in-window edges are illicit;
   - how many in-window edges a seed rule "every in-window edge touching such an account" would add, against the 463 in-window seeds of the current budget.
4. Outputs: results/notes/recovery_history.md and results/tables/recovery_history_counts.csv.
5. **Bar.** Count the rings per seed that are matchable-untouched or too-thin (about 25 per seed) and have history under (b); take the five-seed mean.
   - If it is below 8: record "not worth building" and stop.
   - Otherwise: stop and report for the author's decision.

   Nothing is built in either case.

## Part C — HI-Small-trained GenAgg, zero-shot on HI-Medium (GPU scoring only, no training)
Every number is labelled "trained on HI-Small, zero-shot on HI-Medium". One seed (GenAgg seed 1), no paired test.

1. **Feasibility.**
   - HI-Medium processed data come from ../RS-e2e, read-only, with hashes verified as in T-P4.
   - Confirm that the feature columns, categorical vocabularies and normalisation the model expects exist for HI-Medium. Apply HI-Small's fitted normalisation; never refit.
   - Score a 1 % slice of HI-Medium validation at batch 2048, with the watchdog on (TAML shares the card). Project time and memory for full validation and test.
   - **Stop** if: the projection is over 6 h in total; host memory would exceed 80 % of RAM; or any input is missing.
2. **Score HI-Medium validation in full.** Report AP, ROC-AUC and F1 beside the existing HI-Medium detector's validation values: AP 0.4495 with day-0 labels excluded, 0.3073 without. Report the share of scores saturated at exactly 1.0.
3. **Gate:** if validation AP is below 0.4495 (same day-0 handling), stop and report; do not score test. A negative result is a result.
4. **If the gate passes:**
   - Score HI-Medium test.
   - Run B0, and the full arm with the HI-Medium close-out's no-embedding policy if it exists. Both use the fixed 0.1 % budget under the close-out's two seed-allocation rules: global and per day.
   - Score with score_external.py under the v41 protocol.
   - Report ring-F1, precision, recall, rings touched and the untouched share, beside the existing HI-Medium rows (full recall 0.187, untouched 28.7 %).
5. Stop and report. Seeds 2–5 and other detectors on HI-Medium need the author's decision.
