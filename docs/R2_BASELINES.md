# R2 — three detectors through the connected-components aggregator B0 (Step 4)

Status 2026-09-17: package (`ringshield/`) and runner (`ringshield/run_rings.py`) in place and
tested; the reportable rows wait for the trailing-feature R1 (training) and the 3b-w apply
step (evaluation window). Numbers in this file that come from legacy-feature scores are
marked as such and are pipeline checks, not results.

## Motivating figure: why B0 cannot be improved by turning its own knob

`ringshield/run_rings.py` grid on the **validation** split (157 `test_visible` val rings,
Jaccard 0.5), causal GNN scores, seed 1, legacy features (`experiments/R2_cc_gine_legacyfeat/seed1`,
pipeline check — to be regenerated on trailing-feature scores):

| seed quantile (top %) | seed edges (val) | ring-F1, min_size 2 | ring-F1, min_size 3 |
|---|---|---|---|
| 0.05 | 483 | 0.468 | 0.502 |
| **0.10** | 966 | 0.287 | **0.574** |
| 0.20 | 1,931 | 0.132 | 0.497 |
| 0.30 | 2,897 | 0.087 | 0.399 |
| 0.50 | 10,492 † | 0.042 | 0.070 |
| 0.75 | 10,492 † | 0.042 | 0.070 |
| 1.00 | 10,492 † | 0.042 | 0.070 |
| 1.50 | 14,483 | 0.037 | 0.058 |
| 2.00 | 19,310 | 0.035 | 0.054 |
| 3.00 | 28,966 | 0.033 | 0.050 |

† this grid was run with the inclusive cut (`score ≥ q`) that the legacy CLI used. The val
score distribution has a plateau of **5,835 edges at exactly 0.088088**, so the 0.5 / 0.75 /
1.0 % quantiles all landed on that value and swept in the same 10,492 edges (1.09 %). Since
3b-w apply the quantile cut is strict (`score > q`, `configs/threshold_rule.yaml`), so a
plateau on the boundary is excluded; the chosen 0.1 % cell is unaffected. What the plateau is
(checked on the exported head inputs and the seed-1 checkpoint): the classifier head's **dead
region** — for every one of those edges all 50 first-layer ReLU units of the head are inactive,
so the score is the bias path's constant (0.0881 recomputed). They are *not* structureless
edges: only 13 % have zero fan-in and fan-out, 3 % have a single-transaction sender, none has
all-zero GFP features; 94 % share one payment format (loader code 3, 4.7 % of that format's
val edges), and 1.34 % of them are illicit (12× the val base rate). The head-input embeddings
of these edges do vary (median max |h| 11.8) — the head simply has no opinion on them — so
the expansion policy should not read their scores as evidence, and their embedding similarity
is untested territory rather than known-meaningless.

At the chosen cell (0.1 %, min_size 3) the seed edges on the test split are **91.6 %
illicit but cover only 37 % of the test positives** (652 edges); the rings built from them
are precise (test ring-precision 0.68) and incomplete (ring-recall 0.37, 0.51 among rings
with ≥ 3 visible members). The moment the bar is lowered to buy recall — 0.5 % and beyond —
seed edges chain through hub accounts, components merge into a few giant blobs and ring-F1
collapses to 0.05–0.07 at either size floor. B0 therefore has one operating point and no
path from it: the missing members are the *quiet* ones (edges scored below the bar), and
lowering the bar recovers them only together with the hubs that glue unrelated rings
together. That is the case for the two contributions evaluated in Steps 6–8: **expansion**
(reach the quiet members from a high-precision seed set without lowering the bar) and
**partition** (cut the hubs so recall bought by expansion is not paid for in merged rings).
A time-gap split of the components is baseline B3 in Step 7, not a B0 knob.

## Rows — B0 (connected components), primary window = test days 8–9 (2026-09-18)

`results/tables/r2_ring_b0.csv` (`evaluation/aggregate_results.py --root experiments/R2_b0`),
mean ± sd over seeds, Jaccard 0.5, `test_visible`, 174 primary rings (114 with ≥ 3 visible
members); val cell chosen per seed on the 157 val rings (all seeds chose the same cell).
**CIs pending Step 9.**

| model | features | seeds | val cell (pct / min_size) | ring-P | ring-R | **ring-F1** | R≥3 | coverage | seed edges (n, precision, illicit recall) | tail F1 | whole F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gine_causal · cc | trailing | 5 | — | — | — | **pending R1** | — | — | — | — | — |
| gfpxgb · cc | trailing | 5 | 0.1 / 3 | 0.558 ± 0.032 | 0.248 ± 0.008 | **0.344 ± 0.012** | 0.332 ± 0.010 | 0.793 | 204, 0.837, 0.179 | 0.563 | 0.377 |
| density · cc | trailing | 1 (×5 copies) | 1.0 / 2 | 0.017 | 0.012 | **0.014** | 0.009 | 1.000 | 8,605, 0.002, 0.021 | 0.018 | 0.013 |

Per-pattern recall (primary): gfpxgb — SCATTER-GATHER 0.38, FAN-IN 0.38, GATHER-SCATTER 0.34,
CYCLE 0.32, FAN-OUT 0.27, RANDOM 0.13, STACK 0.05, BIPARTITE 0.00; density — FAN-OUT 0.05,
GATHER-SCATTER 0.03, all others 0. Jaccard sweep (gfpxgb): F1 0.42 at 0.3, 0.18 at 0.7.
Appendix (gfpxgb primary): strict F1 0.041, majority 0.118.

Edge level (`evaluation/edge_metrics.py`, labels `gfpxgb` / `density`, primary window, 5 seeds):
gfpxgb F1 0.353 ± 0.014, AP 0.306, AP/prevalence 276, P@R=0.5 0.17, AUC 0.974 (val: 0.421 /
0.370 / 345 / 0.23; whole: 0.496 / 0.492; tail: 0.742). density: AP/prevalence 1, AUC
**0.36** on primary (0.32 val) — the ranking is *anti*-correlated with the labels.

**gfpxgb** (`baselines/gfp_xgboost_aml.py --refit-from experiments/E5b_gfp_xgboost/config.yaml`,
scores in `experiments/R2_b0/gfpxgb_scores/`): E5b's best hyper-parameters including its
`num_round` = 724, fixed (E5b's final fit used the fixed count; with early stopping at
patience 30 the noisy first rounds of the val aucpr curve stopped seeds 1–3 after 1–5 trees,
val AP 0.12–0.15, while the curve is still rising at round 720 — recorded in the run
config); fit on train only, five XGBoost seeds 1–5; 17 features = 7 transaction fields +
10 trailing GFP columns (dropped: `day_index`, the train-period `sender_*` / `receiver_*`
aggregates, `from_bank` / `to_bank`); the re-keyed trailing GFP parquets are asserted (EdgeID
1:1 join, `gfp` schema metadata). GFP share of gain 43–55 %. Calibrated with
`models/calibrate.py` (isotonic, val-fit, val values cross-fitted 5-fold): test Brier
0.00226 → 0.00125, ECE 0.0025 → 0.0003; 815 k distinct raw test scores collapse to ~139
levels, which is why seed selection stays on `score_raw` (§ below).

**density** (`models/density_detector.py`, GARG-AML-style density proxy, no labels): six
trailing signals — sender out-count / out-sum and receiver in-count / in-sum over
[t − 24 h, t) from per-account timestamp-sorted arrays, plus `scatter_gather` and the
trailing `temporal_cycle` — z-scored on train-period statistics, clipped at 0, averaged, and
rank-normalised within the split (average ranks). Deterministic; five identical files.
15.9 % of val and 21.3 % of test edges sit on the score-zero plateau (all six signals below
the train mean); the top 1 % (8,639 test edges) forms one component of 3,456 members. It is
not merely weak, it is inverted: illicit edges have *lower* 24-hour in/out density than the
population (AUC 0.36), because on AMLworld the dense accounts are the licit hubs and ring
members are quiet. A density proxy therefore cannot serve as a seed detector here; it is kept
as the label-free reference row.

**Selection column.** Seeds are selected by the strict quantile cut on `score_raw`; the
calibrated score only feeds `confidence` / `max_edge_prob`. Cutting the calibrated column
would have landed inside an isotonic tie level and excluded 264 of the 960 intended gfpxgb
seeds at 0.1 % (first pass, discarded). Boundary plateaus at the chosen cell: gfpxgb 0 tied
edges, density 0 (the chosen 1 % cut falls between rank ties); the per-cell counts for every
grid cell are in each run's `config.yaml` (`val_n_on_boundary`, `test_n_on_boundary`).

**Legacy-feature check (not reported), causal vs non-causal GNN, seed 1, primary window,
same val cell 0.1 / 3:** causal — 88 rings, P 0.761 / R 0.385 / F1 0.512, R≥3 0.535, seed
edges 299 at 89.3 % precision covering 27.9 % of the 956 primary positives; non-causal — 86
rings, P 0.837 / R 0.414 / F1 0.554, R≥3 0.561, seed edges 355 at 86.5 % precision covering
32.1 %. (`experiments/R2_cc_gine_legacyfeat{,_noncausal}/seed1`.)

Item 6 (gine rows, three-detector comparison and write-up): **pending R1** (seeds 2–5 in
training).
