# Amendment to PREREG_RECOVERY_2026-11-16.md (2026-11-16): Parts A, B2, C

Written and hashed before B2 or the unblocked Part C is run. The sha256 is logged in paper/RUNBOOK_PROGRESS.md.
The original pre-registration (sha256 a265194c…) is not edited.

## Part A — closed at the gate
- **Validation only.** The selected ensemble (E-All15) reached 0.5753, below GINe full's five-seed mean of 0.5927 (results/notes/recovery_ensemble.md).
- **Not tested on test.** No test number of any ensemble is read or reported.
- **Closed.** No further ensemble variants will be run.

## Part B2 — history-reserved seeds (CPU only)
**Step 0, descriptive, before design.** For the edges touching a history account under (b) days 0–7
and (d) days 0–5, report how many are illicit, and their illicit share restricted to the shipped GINe
detector's top 1 % and top 0.5 % of test scores. This is per seed and mean, on the primary window.
These counts are added to results/notes/recovery_history.md.

**Rule.** The detector is shipped Multi-GINe, seeds 1–5. The total seed budget is fixed at 0.1 % of
the split's scored edges (K edges, as the shipped global rule).
- A share r of the budget, round(r·K) edges, is reserved for the highest-scored edges that meet the endpoint rule against the history set H.
- The remaining K − round(r·K) seeds are the highest-scored edges among the rest, as usual. No edge is counted twice.

**Grid (fixed, six cells).** r ∈ {0.10, 0.25, 0.50} × endpoint rule ∈ {one endpoint in H, both endpoints in H}.

**History is strictly earlier than the scored window.**
- Validation (days 6–7): H = endpoints of labelled-illicit edges in days 0–5 (train split).
- Test (days 8–9): H = days 0–7 (train and validation splits).
- A unit test asserts that no edge with timestamp at or after the scored split's first second can enter H.
- Label-delay sensitivity for test: H from days 0–5.

**Implementation.** The shipped runners select seeds as the top 0.1 % of `score_raw` and re-derive the seed mask from the score file. The rule is therefore applied by writing a new score directory per cell and seed (experiments/R17_history_seeds/<cell>/):
- the reserved edges' `score_raw` is lifted above the split maximum, keeping their order;
- every other edge keeps its `score_raw`;
- `score_calibrated` stays unchanged;
- embeddings and the checkpoint are hard links to the shipped GINe files.

This makes the top-K selection reproduce the rule exactly.

Side effect, disclosed: the policy's `score_quantile` and dead-region features read `score_raw`. For the reserved seeds (round(r·K) of about 864 per split) they therefore see the top quantile. Every other edge is unchanged.

**Arms.**
- B0: `run_rings` cc, configs/threshold_rule_k010.yaml.
- Full: `run_expand` with experiments/R3_expansion/policy_proposed and `run_partition` average with experiments/R4_partition/affinity, the shipped settings.

**Gate, validation only.** The best cell's five-seed mean validation ring-F1 (full arm, `chosen.val_ring_f1`) must exceed shipped GINe full's 0.5927. Ties go to the first cell in the order r ascending, then one endpoint before both. If the gate fails: stop, report the validation grid, and read no test number.

**If the gate passes (test once).**
- Primary: the selected cell's full arm vs shipped full (../RS-e2e/experiments/R4_partition/runs/average). Paired unit bootstrap (precision_paired machinery), 10,000 draws, rng seed 20261117, ring-F1.
- Descriptive: ring precision, ring recall, rings touched, matchable-untouched and too-thin counts (Q0 definitions), and added-member precision.
- Label-delay sensitivity: the same cell with the test history from days 0–5, descriptive.

## Part C — corrections, then as written
1. **Normalisation (correction).** The instruction to apply HI-Small's fitted normalisation was wrong; none exists. The loader's own per-split z-normalisation (`z_norm` per split in MEGA's `get_data`) is used on HI-Medium exactly as on HI-Small. Every split, test included, is normalised with its own statistics. This is recorded in results/notes/open_items.md as a limitation for the paper.
2. **Vocabulary remap.**
   - HI-Medium's currency and payment-format codes are remapped to HI-Small's numbering by name, in a new processed copy under experiments/R18_hm_transfer/data/. The RS-e2e and Ring-Shield sources stay read-only.
   - The mapping table is written to disk.
   - If any HI-Medium category has no HI-Small counterpart: stop and report which.
3. **Other inputs.** Before scoring, check every categorical or id-derived input the model reads for the same first-appearance problem (bank ids, account ids, anything else), and report the findings.
4. **Then Part C from step 1 as written:**
   - GenAgg seed 1 only;
   - 1 % validation slice at batch 2048 with the watchdog; projections; stop if over 6 h or 80 % of RAM;
   - full validation scoring; gate on validation AP ≥ 0.4495 (day-0 labels excluded, as for the reference value);
   - test and ring rows only if the gate passes.

   Every number is labelled "trained on HI-Small, zero-shot on HI-Medium".

## Order
Finish the clean full-suite run first. Then B2's illicit-share counts, then B2, then C. A report
follows each. A gate stop in one does not stop the other.

---
## Addendum 2 (2026-11-16, after the split-check stop): Part C split wrapper (author-approved)
Hashed before the wrapper is run. The sha256 of this file after this addendum is logged in RUNBOOK_PROGRESS.md.

**The problem.** MEGA's `get_data` chooses its own day split, the one closest to 60/20/20 by
transaction count. On HI-Medium that split differs from ours: train days 0–3, validation 4–5, test 6–27.

**The wrapper.** The wrapper supplies our split. MEGA's code stays unmodified.
- `get_data` picks the split by calling `min(split_scores, key=...)` over the (i, j) day cut points.
- The wrapper places one function named `min` in that module's namespace. When it is called with `split_scores`, it returns the (i, j) cut points that reproduce our processed split. Every other call goes to the built-in `min`.
- Nothing else changes: `get_data`, `z_norm` and the loaders run as published.
- The split-equality assertion (`check_splits`) stays and is checked against our processed split. It verifies that our edge lists, not just our day numbers, were applied.

**Normalisation (unchanged rule).** `z_norm` runs per data object, as published:
- train edges with train statistics;
- the validation object, train + validation edges, with train + validation statistics;
- the test object, all edges, with all-edge statistics.

The rule is the same on HI-Small (shipped) and on HI-Medium under the wrapper. Only the day cut points come from our split.

**Gate 0: HI-Small reproduction, before any HI-Medium scoring.**
- Run the wrapper on HI-Small with our split and GenAgg seed 1, scoring batch 2048, validation in full.
- Compare with the stored experiments/R6_megagenagg/scores_val_seed1.parquet.
- Report the maximum and median absolute difference, and the Spearman correlation.
- **Pass:** median absolute difference below 1e-4 and Spearman above 0.9999. Otherwise stop, and score no HI-Medium edge.

**Then, as pre-registered:**
- 1 % slice timing, with the 6 h and 80 % RAM stops;
- the runbook 0.7 test command (`$PY -m pytest tests contract/tests preprocessing/tests -q -rs`), run once B2 has finished and nothing else is writing, **before** full HI-Medium validation scoring;
- full validation scoring, then the AP ≥ 0.4495 gate;
- test and ring rows only if the gate passes.

GenAgg seed 1 only.

---
## Addendum 3 (2026-11-16, 13:4xZ): gate-0 bar replaced; B2 time limit (author-approved)
**Disclosure.** This addendum was written after the result of the same-order diagnostic had already been read, not
before. The diagnostic, scoring train then validation through the wrapper, finished and was read at about 13:40Z.
The author's instruction to write this addendum before reading it arrived afterwards. Its result: max |Δ| 0.746,
median 1.4e-17, Spearman 0.99787, 13,207 edges with |Δ| > 1e-4. It is reported as criterion (a) below.

**Gate 0, replacing the original bar:**
- **(a) Same-order reproduction.** HI-Small through the wrapper in the stored run's order (train, then validation), same seed and settings. Pass if the validation scores equal the stored file exactly, or with max |Δ| < 1e-6.
- **(b) Noise floor,** if (a) fails.
  - Score HI-Small validation twice through the ORIGINAL path (models/mega_adapter.py --score-only, no wrapper, validation only), and once through the wrapper in the same order.
  - Pass if the wrapper-vs-original agreement is no worse than the original-vs-original agreement on all three measures: share of edges differing by more than 1e-4, Spearman, and max |Δ|.
  - For each measure, the wrapper-vs-original figure is taken as the worse of its two comparisons against the original runs.
- **(c)** If neither passes: stop and report. No HI-Medium scoring.

**Sampling-noise quantification (whatever the outcome; a reproducibility item, not a gate).** HI-Small validation
and test, GenAgg seed 1, two scoring runs that differ only in random state. Report:
- the share of edges whose score differs, and the distribution of the differences;
- the overlap of the top 0.1 % seed edges between the runs (count and Jaccard);
- edge F1 at the validation threshold for each run;
- B0 ring-F1 for each run.

State whether scoring sets a random seed, and whether the shipped GINe and MEGA-GIN score files share this
property. On HI-Medium, the scoring order and random state are recorded so the run can be repeated.

**B2 time limit, cell r = 0.50, both endpoints.** Declared before any of its results exist. The cell started at about
12:44Z. If its first seed has not finished by 16:44Z (4 h), the cell is killed and recorded as "did not complete
(expansion cost)", and the gate is decided on the five cells that did complete. Its candidate counts at the kill
point are reported.

---
## Addendum 4 (2026-11-16, ~16:50Z): B2 gate decided on five cells (author decision)
**Disclosure.** This rule change is made AFTER r50_both's seed-1 validation result was seen (full-arm
val ring-F1 0.4821). Seed 1 finished at 16:35Z, before the addendum-3 deadline, so the 4 h kill rule did not fire.
At that point the five other cells were complete, and r25_both led with a five-seed mean of 0.5960.

**Why.** To overtake r25_both, r50_both's seeds 2–5 would need to average above 0.6745
((5 × 0.5960 − 0.4821) / 4), above every single-seed value of any cell. The remaining seeds would cost
about 15 h of expansion.

**Rule.** r50_both is stopped and recorded as "did not complete; seed 1 = 0.4821; stopped by author decision after
one seed". The gate is decided on the five completed cells: r25_both, 0.5960 > 0.5927, passes. The test read then
proceeds exactly as pre-registered (primary paired comparison, secondary metrics, days 0–5 label-delay sensitivity).
No test number had been read when this addendum was written.

---
## Addendum 5 (2026-11-16): Part C continuation bar and primary comparison (author-approved)
Written and hashed after the HI-Medium validation gate passed (seed 1 AP 0.5445) and BEFORE any HI-Medium test
score or ring number was read. All HI-Medium numbers from these models are labelled
"trained on HI-Small, zero-shot on HI-Medium".

**Seed-1 ring rows.** Produced with evaluation/hm_closeout.py unchanged (Amendment-15 close-out: tie-safe top-k
seed cut, primary window test days 6–14, global and per-day budget rules, test-day blocks 6–7 … 14–15; methods b0
and full with the close-out policy `policy_no_detector` and affinity), reading the transferred GenAgg scores in place
of the old detector's.

**Continuation bar.** If GenAgg seed 1's B0 ring-F1 (primary window, global rule) exceeds the existing HI-Medium
detector's B0 ring-F1, mean of its two usable seeds = 0.0898 (closeout_a15: 0.1035, 0.0761), then GenAgg seeds 2–5
are scored on HI-Medium validation then test with the same settings (validation only, then test; rng offset 0;
batch 2048), one after another, before TAML. Otherwise Part C stops, the seed-1 rows are reported, and TAML starts.

**Primary comparison (once five seeds exist).** Transferred GenAgg (seeds 1–5) vs the existing HI-Medium detector
(seeds 1–2), B0 arm, global seed rule, primary window, ring-F1; paired unit bootstrap over the 2,187 in-scope rings,
10,000 draws, seeds averaged inside each draw.

**Secondary, descriptive.** The full arm with the close-out no-embedding policy; the per-day seed rule; ring
precision, ring recall, rings touched, untouched share, added-member precision; ring-F1 by test-day block (6–7
through 14–15), to show whether decay with distance from training persists.

**Per seed, recorded.** Validation AP, ROC-AUC, saturated share, and the per-day share of the global seed budget
(the old detector put 87.5 % of it on day 15).

**Caveat.** The HI-Medium expansion policy was trained on the old detector's cross-scores, so the full arm measures
policy transfer as well as the detector.

**Addendum 5, clarification (same day, still before any HI-Medium test score or ring number was read).** The
transferred model has no HI-Medium embeddings, so "the close-out no-embedding policy" is applied as:
expansion `experiments_hi_medium/R3_expansion/policy_no_detector` (no embedding or detector feature) and partition
`experiments_hi_medium/R4_partition/affinity_no_embedding` (the close-out affinity minus `cos_emb`). The rings are
built by a wrapper (evaluation/hm_transfer_closeout.py) that runs evaluation/hm_closeout.py unchanged except that the
feature context is built without an embeddings file. The dead-region constants come from the GenAgg checkpoint, as on
HI-Small. The old detector's close-out full arm used `affinity` with `cos_emb`; that difference is part of the
descriptive full-arm comparison and is stated with it. The primary (B0) comparison uses neither.

---
## Addendum 6 (2026-11-16, ~21:20Z): day-chunked test scoring (author-approved)
Written and hashed after the single-pass HI-Medium test scoring of GenAgg seed 1 was stopped by the watchdog
(total VRAM 24,012 MiB > 24,000, 20:57:46Z, no file written) and BEFORE any HI-Medium test number exists.

**Settings unchanged.** GenAgg seed 1 (seeds 2–5 the same way if the addendum-5 bar passes), our split through the
addendum-2 wrapper, scoring batch 2048, neighbours 100/100, rng offset 0, the same per-data-object z_norm (the test
data object, i.e. the graph and its normalisation, is all edges exactly as in a single pass).

**Blocks.** The test split is scored in contiguous blocks of whole days (day = processed Timestamp // 86400), each in
its own process, each writing its own file experiments/R18_hm_transfer/genagg_seed<S>/blocks/d<lo>-<hi>/scores_test_seed<S>.parquet
when it finishes. The block restricts only which test edges are scored (the seed edges); `check_splits` still asserts
the full split first. HI-Medium order (primary window, days 6–14, first): 6–7, 8–9, 10–12, 13–14, then 15–27.
HI-Small check: 8, then 9–17.

**GPU memory.** `torch.cuda.empty_cache()` is called every N = 50 batches inside a copy of `mega_adapter.score_split`
that is otherwise line-for-line the same; per block, peak allocated and peak reserved memory are logged. Releasing
the allocator's cache does not touch the model, the inputs or any random number generator, so it does not change
any score.

**What chunking does change.** Each block starts in a fresh process with the RNG seeded as in a single pass, so the
neighbour-sampling random stream differs from a single pass. That is the sampling noise already measured (open item
20: changing only the random state moved 1 of 864 test seeds and left B0 ring-F1 unchanged); the HI-Small check
below bounds it for this procedure.

**Fallback, declared now.** A block stopped by the watchdog is split in half by days and retried, down to a single
day. If a single day still fails, that day alone is scored at batch 1024, the day is recorded, and it is reported as
a deviation. Completed blocks are kept; a finished block is never rescored.

**Check on HI-Small first.** HI-Small test, GenAgg seed 1, the same code, blocks 8 and 9–17, against the stored
single-pass batch-2048 file (experiments/R6_megagenagg/scores_test_seed1.parquet). Reported: share of edges with
|Δ| > 1e-4, Spearman, top-0.1 % seed overlap (count, Jaccard), and B0 ring-F1 (run_rings cc, fixed 0.1 %, the stored
validation file and seed-1 calibrator, as for the stored row). **Pass:** seed Jaccard ≥ 0.99 and B0 ring-F1 within
0.005 of 0.5504. Otherwise stop; no HI-Medium test edge is scored.

**After all HI-Medium blocks.** Concatenate; assert row count = 18,893,741, edge ids unique, none missing against
the processed test split; then per-day budget shares and seed 1's ring rows against the 0.0898 bar (addendum 5).

**TAML.** The seed-1 retrain on our split runs alongside on the GPU (about 104 MiB). If the first two scoring blocks
run more than 20 % slower than the validation rate (3,857,689 edges in 1,545 s of scoring, about 2,497 edges/s), TAML
is paused and resumed after scoring.

**Addendum 6, correction (before any block was run).** The validation rate above is wrong: 1,545 s is the whole
run including the 838 s data load. Scoring alone took about 707 s, i.e. about 5,460 edges/s. The TAML pause rule
uses that rate: if either of the first two blocks scores below 4,370 edges/s (20 % slower; timed from the block's
first batch to its last), TAML is paused.
