# Calibration and the seed-fraction rule (Step 3c, 2026-09-18)

## What was fit on what

`models/calibrate.py`, per run and per seed: `sklearn.isotonic.IsotonicRegression(out_of_bounds="clip")`
fit on **(score_raw of the validation split, `contract/out/labels_val.parquet`)** — asserted to be
exactly `len(val)` = 965,524 rows — and applied to the val and test scores. `score_calibrated` is
written into `scores_<split>_seed<S>.parquet` next to the unchanged `score_raw`; the calibrator
is saved as `calibrator_seed<S>.pkl`; `calibration.json` records Brier and ECE (15 equal-mass
bins) before / after on val and on test. Test is reported and never used. Because an isotonic
fit's in-sample val ECE is ~0 by construction, the same file also reports a 5-fold cross-fitted
val ECE (diagnostic only; the parquet values are the full-fit ones, per the rule). Training was
not touched. Calibrated so far: `experiments/R1_gine_causal` (Multi-GINe, trailing features,
5 seeds) and `experiments/R2_b0/gfpxgb_scores` (GFP + XGBoost, 5 seeds).

## ECE table — `R1_gine_causal` (trailing features, causal W = 1,800 s)

| seed | val ECE raw → cal (cross-fit) | val Brier raw → cal | test ECE raw → cal | test Brier raw → cal | isotonic knots |
|---|---|---|---|---|---|
| 1 | 0.0023 → 0.00003 (0.00002) | 0.00073 → 0.00060 | 0.0048 → 0.0003 | 0.00127 → 0.00096 | 82 |
| 2 | 0.0017 → 0.00002 (0.00003) | 0.00081 → 0.00066 | 0.0040 → 0.0003 | 0.00129 → 0.00104 | 90 |
| 3 | 0.0021 → 0.00002 (0.00003) | 0.00075 → 0.00058 | 0.0046 → 0.0004 | 0.00131 → 0.00091 | 92 |
| 4 | 0.0020 → 0.00002 (0.00003) | 0.00073 → 0.00058 | 0.0029 → 0.0003 | 0.00129 → 0.00111 | 80 |
| 5 | 0.0026 → 0.00001 (0.00002) | 0.00082 → 0.00066 | 0.0100 → 0.0012 | 0.00236 → 0.00134 | 90 |

Check 1 holds: val ECE after < before for all five seeds (also cross-fitted). The raw scores
were already close to calibrated in ECE terms because the base rate is 0.1 % — most of the
mass sits in bins where both the mean score and the mean label are ≈ 0; the gain shows up in
Brier (−15 to −20 % on val, −13 to −43 % on test) and at the top of the ranking. Isotonic
collapses the ~600–850 k distinct raw test scores to 91–1,781 levels, which is why seed
*selection* stays on `score_raw` (below). `gfpxgb`: test ECE 0.0025 → 0.0003, Brier 0.00226 →
0.00125, val cross-fitted ECE 0.0018 → 0.00003 (`experiments/R2_b0/gfpxgb_scores/calibration.json`).

**Did calibration do its job?** The per-seed val-F1-optimal thresholds on the raw score span
0.33–0.64 (legacy features: 0.46–0.71); on the calibrated score they span **0.23–0.31**. The
seed fractions those thresholds select were already a narrow band (0.065–0.077 % of val, raw)
because the F1 optimum is a quantile whatever the score scale; after calibration they are
0.065–0.075 %. So the calibrated scale is comparable across seeds (thresholds agree within
0.08 instead of 0.31) — no reliability diagrams needed.

## The seed-fraction rule (`configs/threshold_rule.yaml`, `provisional: false`)

seeds(split) = { e : score_raw(e) > q }, q = quantile(score_raw over the split's non-NaN
scores, 1 − k/100), computed on the **same split being scored** (val quantile for val, test
quantile for test, within the `--edge-subset` when one is given) — a quantile, never an
absolute cut-off. Grid k ∈ {0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.00} % with
min_size ∈ {2, 3} jointly; **k\* = argmax validation Ring-F1 under B0** (`test_visible`, Jaccard
0.5), ties → smaller k then larger min_size, chosen per scorer seed and written to the run's

> **`min_size` 2 was available at every step and never chosen by a working detector.** Across the **158** runs on disk that record a val-chosen cell, 153 chose `min_size` 3 and **5 chose 2 — all five are the density baseline**, at `seed_frac` 1.0 with val ring-F1 **0.0276** (its B0 test ring-F1 is 0.014; it scores below chance because illicit edges are *less* dense than licit hubs). So the precise statement is: `min_size` 2 was in the validation grid at every step and was never chosen by any detector that produces usable rings; the only selections come from a baseline that fails at every cell. Changing `min_size` now on the strength of a test-window number would be choosing on test.

`config.yaml` before the test run. Step 4 exists, so k\* is the Ring-F1 argmax, not the edge-F1
stand-in — the config is not provisional. Two refinements to the 3c wording, recorded in the
yaml with their reasons: the cut is **strict** (`>` not `≥`; ties are edges the model cannot
distinguish, e.g. the 5,835-edge plateau at 0.088088 in the legacy val scores) and selection
uses **`score_raw`** (isotonic ties would otherwise drop a slice of the intended seeds — 264 of
960 for gfpxgb at 0.1 %); the calibrated score feeds `confidence` / `max_edge_prob`, XAI
weights and the expansion policy's score feature.

**k\* found**: 0.10 % / min_size 3 for every gine_causal seed and every gfpxgb seed
(val Ring-F1 0.52–0.57 and 0.35–0.39 respectively); 1.0 % / min_size 2 for the density
detector (val Ring-F1 0.028 — it has no operating point).

## Contract regeneration

`contract/make_scored_edges.py --scores experiments/R1_gine_causal/scores_test_seed1.parquet
--split test --model-id gine_causal --seed 1 --k-from experiments/R2_b0/gine_causal/seed1/config.yaml`
→ `contract/out/scored_edges_gine_causal_1.parquet`: **863,900 rows**, exactly
`SCORED_EDGES_COLUMNS`, `score_calibrated` with **0 NaN** (the Step 3a seed-mask fix removed the
841 unscored rows), no `true_label`, `is_seed` = 864 edges (k\* = 0.1 %, q = 0.929521, 0 tied
on the boundary), `model_id = 'gine_causal'`, `seed = 1`. A val counterpart
(`scored_edges_gine_causal_1_val.parquet`, 965,524 rows, 966 seeds) is written for the
platform's validation harness.

Rings stub: `python -m ringshield run --scores contract/out/scored_edges_gine_causal_1.parquet
--model-dir models/artifacts/cc_gine_causal_seed1 --aggregator cc --out contract/out/rings_stub_cc.parquet`
(the Step 5 CLI replaces the Step 1 `make_rings_stub.py` route; k\* and min_size 3 come from
the exported model dir) → **98 rings**, `topology_type = 'UNKNOWN'` on every row, `expanded_edges`
empty on every row, `ring_id` like `cc-gine_causal-1-0`, `tenant_id` = sender bank of the
earliest seed edge. Evaluated on the primary window with `python -m ringshield eval`:
82 rings vs 174 truth rings, P 0.842 / R 0.397 / F1 0.539, R≥3 0.526
(`contract/out/rings_stub_cc.metrics.json`). The Step 1 stub is kept as
`contract/out/rings_stub_cc_step1_legacy.parquet` for the Step 1 checks. Both teammates are
to be told the file changed: `ring_id` / `tenant_id` rules and `is_seed` semantics are new
(`contract/README.md`, regenerated from `schema.py`).

Contract tests: 38 passed (`contract/tests`); package + CLI tests: 16 passed.
