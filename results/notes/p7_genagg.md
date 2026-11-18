# T-P7 notes — MEGA-GenAgg (2026-11-15)

## Seed-1 gate
Test edge F1 0.7558 (threshold tuned on validation, batch-2048 val scores), PASS. Details: `paper/RUNBOOK_PROGRESS.md`, `experiments/R6_megagenagg/gate_seed1.json`.
Caveat recorded at launch: GenAgg as published — the MLPAutoencoder's inverse-objective forward hook never fires (GenAgg calls f.forward() directly), so f^-1 is trained only by the task loss; one node-stage GenAgg is shared by every GINE layer.

## Is a validation-to-test gap of ~0.09 usual here? (author decision 2b)
Same rule for every row: threshold = argmax of val F1 over 400 val-score quantiles (0.90–0.99999), applied to test (`r6_detector_swap.edge_f1`). Existing score files only; GenAgg seed 1 uses its batch-2048 val scores. Per-seed table: `results/notes/p7_val_test_gap.csv`.

| Detector | seeds | val F1 (tuned) mean [min, max] | test F1 mean [min, max] | test − val mean [min, max] |
|---|---|---|---|---|
| GINe (causal) | 5 | 0.594 [0.551, 0.628] | 0.596 [0.481, 0.658] | +0.002 [−0.070, +0.046] |
| MEGA-GIN | 5 | 0.613 [0.590, 0.661] | 0.689 [0.644, 0.746] | +0.076 [+0.053, +0.093] |
| MEGA-GenAgg | 1 | 0.665 | 0.756 | +0.091 |

The means reproduce r6 (0.5957, 0.6893). **A gap of ~0.09 is usual for the MEGA family on this split:** every MEGA-GIN seed has test above val by 0.053–0.093, and GenAgg's +0.091 is inside that range. GINe shows no systematic gap. Why MEGA generalises upward to test is not established here.

## Scoring-batch sensitivity (author decision 2a) — STOP condition met
MEGA-GIN seed 1, the shipped model, rescored with `--score-only` at batch 2048 (shipped scoring batch 8192):

| | val F1@0.5 | test edge F1 (val-tuned) |
|---|---|---|
| shipped, batch 8192 | 0.5722 | 0.6435 |
| rescored, batch 2048 | 0.5329 | 0.6309 |
| Δ | −0.0393 | **−0.0126** (limit 0.005) |

14.8 % of test scores change (max |Δ| 0.999). For GenAgg, 4096 → 2048 moved val F1 by only −0.0026.
Likely mechanism (not tested): the fallback causal loader (`causal_loader`, route `fallback`, window 1,800 s) groups seeds into time windows of at most `batch_size` edges and drops neighbour edges later than the batch's latest seed, so the scoring batch size changes how much same-window context each edge sees. Scores are therefore a function of the scoring batch, not only of the model.
Outputs (scratch, git-ignored): scratchpad `megagin_rescore/`. Peak VRAM 6,760 MiB.

## Scoring-batch sensitivity: cause (decision C-4, 2026-11-15; nothing retrained or rescored)

**What an edge can see.** `models/causal_loader.py`, route `fallback` (the route recorded as
`loader_route` in every MEGA-family and GINe causal run; window 1,800 s):

- `WindowBatchSampler` (l.146-174) sorts the split's seed edges by timestamp and cuts contiguous
  batches, a new batch starting when the batch is full (`batch_size`) or the next seed is more than
  1,800 s after the batch's first seed.
- `SeedFixTransform` (l.109-112) keeps every sampled neighbour edge with
  `timestamp <= max(seed timestamps of the batch)`, and appends all seeds of the batch to the graph
  (l.116-121).
- So an edge at time t sees neighbour edges, and the other seeds of its batch, up to
  `t_max(batch) >= t`, i.e. up to `t_max - t` seconds **after itself** (at most 1,800 s). The
  docstring states this ("Within-batch leak <= window_s"). Causality holds per batch, not per edge.
  The batch size sets where batches are cut, so it sets each edge's look-ahead.

**Measured on the test split** (863,900 edges; contract timestamps in seconds; sampler replayed
exactly; `results/notes/p7_batch_span.json`):

| scoring batch | batches | median batch size | batch span median / max (s) | look-ahead per edge median / p95 / max (s) | edges with look-ahead > 0 |
|---|---|---|---|---|---|
| 2048 | 600 | 2,048 | 300 / 1,800 | 180 / 720 / 1,800 | 90.1 % |
| 4096 | 390 | 4,092 | 600 / 1,800 | 300 / 1,380 / 1,800 | 95.0 % |
| 8192 | 307 | 11 | 1,140 / 1,800 | 600 / 1,440 / 1,800 | 97.1 % |

(At 8192 the 1,800 s window cuts most batches, so the median batch is small but the spans are the longest.)

**GINe.** The shipped GINe causal scores (`R1_gine_causal`, via `models/score.py`) go through the
same `make_loader`, route `fallback`, window 1,800 s, scoring batch **8192** (run config
`batch_size`; no `--batch-size` override). They have the same look-ahead as the 8192 row.

**FINDING for the author (not acted on).** Under the fallback route, an edge can see neighbour
edges up to 1,800 s later than itself. At the shipped scoring batch 8192 the median look-ahead is
600 s (p95 1,440 s) and 97 % of test edges see some future. At 2048 it is 180 s (p95 720 s). This
affects GINe and MEGA alike. It is the likely reason scores depend on the scoring batch (smaller
batch, less future: MEGA-GIN seed-1 test F1 −0.0126 from 8192 to 2048). GINe was not rescored and
the loader was not changed.

## MEGA-GIN rescored at batch 2048 (decision C-1)

Test edge F1, val-tuned threshold (`r6_detector_swap.edge_f1`), shipped models, `experiments/R6_mega_sb2048`:

| seed | 8192 (shipped) | 2048 | difference |
|---|---|---|---|
| 1 | 0.6435 | 0.6309 | −0.0126 |
| 2 | 0.6813 | 0.6784 | −0.0029 |
| 3 | 0.6671 | 0.6658 | −0.0013 |
| 4 | 0.7463 | 0.7512 | +0.0049 |
| 5 | 0.7083 | 0.7014 | −0.0069 |
| mean ± SD | 0.6893 ± 0.0396 | 0.6856 ± 0.0447 | −0.0037 |

## Detector-swap rows rebuilt at batch 2048 — STOP (budget re-selected on val)

`results/tables/r6_detector_swap_sb2048.{csv,json}` and `r6_pvalues_sb2048.csv` (builder
`evaluation/r6_detector_swap_sb2048.py`; GINe and GFP+XGB rows reproduce the shipped table exactly).

| row | shipped (8192) | 2048 |
|---|---|---|
| MEGA edge F1 | 0.6893 | 0.6856 |
| MEGA B0 ring-F1 | 0.5208 | 0.4137 [0.334, 0.490] |
| MEGA full ring-F1 | 0.6074 | 0.5098 [0.427, 0.585] |
| MEGA no-embedding full | 0.5881 | 0.4925 |
| MEGA full added-member precision | 0.9316 | 0.9252 |

**Cause.** The rebuild re-runs the val-only B0 grid (seed_frac_pct x min_size) on the 2048 val
scores. Seeds 4 and 5 now choose **k = 0.05 %** (val ring-F1 0.5485 / 0.5523), where the shipped
runs chose 0.1 % for all five. Test B0 ring-F1 per seed, new vs shipped:
0.506/0.523, 0.508/0.504, 0.482/0.494, **0.289/0.516**, **0.284/0.567**. Seeds 1-3 differ by at
most 0.017. The top-0.1 % seed sets overlap 94-99 % with the shipped ones (Spearman 0.994-0.999).
So the ring rows move because of the budget, not the ranking.

The paired tests now reject mega vs gine for both B0 and full (Holm p 0.0004 / 0.0006, MEGA lower).
At k = 0.1 % for every seed, the 2048 rows would be expected near the shipped ones.

Not used anywhere yet: no paper or FINDINGS change. The T-P8 MEGA sweep (k fixed by the grid
for B0) is running, but the delta_t / p_min cells of seeds 4-5 were chosen under k = 0.05 %.

## Proposed FINDINGS note (for author approval; FINDINGS.md not edited)

> **Note (2026-11-15), within-batch look-ahead.** The causal loader runs in its fallback route
> (window 1,800 s) for every neural detector (Multi-GINe, MEGA-GIN, MEGA-GenAgg). Causality holds per
> batch, not per edge: an edge sees neighbour edges and the other edges of its batch up to the
> batch's latest seed, at most 1,800 s after itself. Measured on the test split: median / p95
> look-ahead 180 / 720 s at scoring batch 2048 and 600 / 1,440 s at 8192 (the shipped Multi-GINe and
> MEGA-GIN scoring batch). 90 % and 97 % of test edges see some later edge. Scores therefore depend
> on the scoring batch. MEGA-GIN test edge F1 is 0.6893 at 8192 and 0.6856 at 2048 (per seed
> −0.0126 to +0.0049). All MEGA-family comparisons now use batch 2048. Multi-GINe was not rescored
> and the loader is unchanged. Sources: `results/notes/p7_genagg.md`, `results/notes/p7_batch_span.json`.

## Scoring reproducibility and sampling noise (2026-11-16; PREREG_RECOVERY addendum 3)
- **Bit-reproducible for a fixed seed.** GenAgg seed 1, HI-Small, batch 2048: two `--score-only` runs are identical on validation and test, and match the batch-2048 rescore in rescore_val/ (max |Δ| 8.3e-7). mega_adapter seeds random, numpy, torch and CUDA before scoring.
- **Only the random state changed** (seeds +1000), on validation / test:
  - edges differing by more than 1e-4: 0.05 % / 0.13 %;
  - max |Δ| 0.053 / 0.217; Spearman 0.99968 / 0.99953;
  - top-0.1 % seed edges shared: 966 of 966 / 863 of 864;
  - edge F1: 0.6648 against 0.6648 / 0.7558 against 0.7553;
  - B0 ring-F1: identical, 0.5504 on test.
- The noise comes from neighbour sampling (100 per hop). It is far below the seed-to-seed spread of the detector.
- The shipped GINe scorer (models/score.py) sets no seed.
- GenAgg seed 1's stored validation file is the batch-4096 original (see open_items 21).

Source: results/tables/scoring_noise_hs_genagg_s1.csv; evaluation/scoring_noise.py.
