# Attempt-level evaluation protocol and scorer

`evaluation/score_external.py` scores any file of predicted rings (ours or another method's)
against the AMLworld laundering-attempt ground truth under every convention the paper
discusses. It imports the repository's own scope, matching and bootstrap code, so it cannot
drift from the reported tables: on the shipped HI-Small runs it reproduces
`results/tables/r14_scope_sensitivity.csv` and `v36_component_scope.csv` exactly (90 cells,
maximum absolute deviation 0.0; `results/notes/p1_scorer.md`).

## Definitions

- **Ground-truth ring.** One laundering attempt: one block of the generator's pattern file
  (`data/processed/amlworld_ring_ground_truth.parquet`: `ring_id, from_id, to_id,
  timestamp_int, pattern_type`).
- **Window.** A contiguous range of days of one split (`configs/eval_window.yaml`; HI-Medium:
  `configs/eval_window_hi_medium.yaml`). Days are `(timestamp − 10) // 86400`.
- **Scope conventions** (the target set a method is scored against):
  - `test_visible` (reported): a ring is in scope if at least one of its transactions is in the
    window; its members are the accounts of those in-window transactions.
  - `full_membership` (sensitivity): the same rings; members are all of the ring's accounts.
  - `component`: each in-window connected piece of a `test_visible` ring (its in-window
    transactions joined when they share an account) is its own target.
  - `component_ge3`: the same, keeping pieces with at least three accounts.
- **Predictions.** `min_size` (default 3) is applied to the unrestricted prediction. Matching
  uses the prediction restricted to the window: the endpoints of its member transactions that
  fall in the window; a prediction with no in-window transaction is dropped from that window.
  For an input that lists accounts only, a ring's transactions are taken to be every split
  transaction between two of its members.
- **Matching.** Greedy one-to-one by descending Jaccard on account sets; a pair counts when
  Jaccard ≥ τ. τ = 0.5 is reported; 0.3 and 0.7 are always swept alongside it.
- **Metrics.** Ring recall = matched targets / targets; ring precision = matched predictions /
  predictions in the window; ring-F1; recall on targets with ≥ 3 members; member coverage of
  matched pairs; recall per pattern type.
- **Intervals.** 2.5/97.5 percentile bootstrap over truth targets, 1,000 resamples, seed 0,
  runs (seeds) averaged inside each resample. Each resample draws |T| targets with replacement
  and a target drawn k times counts k times (draw counts passed as weights), the procedure of
  `evaluation.ring_stats.bootstrap_over_rings` behind the r9 tables. For the full pipeline this
  gives ring-F1 0.5894 [0.5023, 0.6747], equal to r9.
  `--legacy-subsample-intervals` reproduces the older r14/v36 tables
  (`evaluation.scope_sensitivity.boot`): there the repeats collapse, so each resample is a
  ~63 % subsample of targets and the intervals are about a quarter too narrow
  ([0.5234, 0.6529] for the same row). Use it only to reproduce those tables. Point estimates
  are identical under both.
- **Paired comparison.** `--compare A B`: paired bootstrap over truth targets of A − B
  (`evaluation.ring_stats.paired_unit_bootstrap`, 10,000 draws, seed 20261114), for ring-F1,
  recall and precision, per convention and threshold. Apply Holm within a pre-registered family.
- **Observability.** In-scope rings; rings with fewer than three visible members; rings with no
  in-window piece of three or more accounts (no method emitting rings of ≥ 3 accounts can match
  them under `component_ge3`); rings split into two or more pieces; share of ≥ 3-account pieces
  recovered at τ = 0.5.

## Command

```bash
cd /e/JSJ/RS-react
PY=.venv312/Scripts/python.exe
export PYTHONIOENCODING=utf-8
$PY evaluation/score_external.py --rings runs/seed1/rings.parquet runs/seed2/rings.parquet \
    --split test --window primary --out results/scored/my_method
$PY evaluation/score_external.py --compare results/scored/my_method results/scored/b0 \
    --out results/scored/my_method_vs_b0
# HI-Medium:
RINGSHIELD_PATHS=configs/paths_hi_medium.yaml $PY evaluation/score_external.py --rings ... --out ...
```

Flags: `--rings PATH …` (one file per seed/run), `--split {val,test}`,
`--window {primary,tail,whole,val}`, `--eval-window FILE` (default: the dataset's own window
file), `--truth FILE`, `--min-size 3`, `--thresholds 0.3 0.5 0.7`,
`--conventions …` (default all four), `--n-boot 1000`, `--boot-seed 0`,
`--legacy-subsample-intervals` (reproduce r14/v36 only),
`--compare DIR_A DIR_B`, `--compare-n-boot 10000`, `--compare-seed 20261114`, `--out DIR`.

Input schemas: the repository's `rings.parquet` (any schema version), or a minimal parquet /
JSONL with `ring_id` and `members` (list of account ids), optionally `member_edges`.

## Output

- `summary.csv` — one row per convention × threshold: `n_runs, n_targets, ring_precision
  (+_lo/_hi), ring_recall (+_lo/_hi), ring_f1 (+_lo/_hi), ring_recall_ge3, member_coverage,
  matched_per_run, predicted_per_run`.
- `metrics.json` — the same rows plus `per_pattern_recall`, the `observability` block, the
  window, thresholds and interval description.
- `evidence.json` — per convention × threshold, the target ids and each run's matched
  indicators and prediction count (what `--compare` needs).
- `config.json` — git commit, arguments, paths file, window file, sha256 of the ground truth
  and of every input file, and each input's schema and ring counts.
- `compare.csv` / `compare.json` (with `--compare`) — Δ, 95 % interval and two-sided p per
  convention × threshold × metric.

## Reporting checklist

A group-level result on AMLworld should state:

1. **Scope rule**: which convention, and the result under at least one other.
2. **Split**: the day ranges of train, validation and test.
3. **Window**: which test days are scored; whether the high-base-rate last days are excluded.
4. **Budget allocation across days**: whether a seed or alert budget is set globally, per day or
   inside the window, and how much of it falls outside the window.
5. **Tie handling of quantile cuts**: whether "top k %" is `score > q` or `score ≥ q`, and what
   happens when many scores are tied (saturation).
6. **Threshold sweep**: the matching rule and results at more than one Jaccard threshold.
7. **Observability**: how many targets cannot be matched by any method under the stated scope
   and minimum size.
8. **Precision beside recall**: never ring recall or member recall alone.
9. **Intervals**: over truth targets, with the seeds folded in; Holm within a registered family.
