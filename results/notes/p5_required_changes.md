# T-P5 — required changes recorded ahead of the paper sync

## R1 (author round 4, 2026-11-14): leak-free precision values first

Wherever **added-member precision**, **ring precision** or the **paired precision gain** (vs B1b)
appears in the paper (text, tables, figures, captions, abstract), report the leak-free
ring-folded value. Give the shipped value beside it, identified as measured under day folds.
Source: docs/deep-analysis.md §15; results/tables/v39_ringfold_*.

| Quantity | Report (ring folds) | Beside it (day folds, shipped) |
|---|---|---|
| added-member precision | 0.819 | 0.926 |
| precision gain vs B1b | +0.301 [+0.235, +0.366] | +0.408 [+0.342, +0.479] (v35) |
| ring precision, proposed | 0.784 [0.666, 0.898] | 0.838 [0.706, 0.960] |

Also:
- The T-P2 ring-F1 result is INCONCLUSIVE (+0.0028 [−0.0137, +0.0211]). No equivalence wording.
- All ring-folded follow-ups are labelled post hoc / exploratory.
- LaTeX is not edited until T-P5.
- (Closed 2026-11-14: ring-folded `full` run done — added-member precision 0.817, ring precision 0.760; see amendment addendum A.) Former gap: no ring-folded `full` run existed (expansion + partition), so `full`'s ring precision
  (0.818) and added-member precision (0.926) have no leak-free value. T-P5 must say they were
  measured under day folds, or the author can approve a ring-folded `full` run.

## Status after T-P5 pass 1 (2026-11-14)
- R1 applied in: results text (policy purity paragraph), precision table (leak-free block),
  ring-methods table (ring-folded rows beside the day-folded ones), the quiet-vs-precision
  figure caption, detector-swap / robustness / window-budget captions, limitations.
- Not done in pass 1 (pass 2): the scope figure with baseline rows (`make_figs.py`), the two-panel
  HI-Medium figure `fig_hm_audit.png`, the edge-vs-ring figure's T-P7 point, and the
  internal-code clean-up inside table cells (B0/B1b/proposed labels in older tables).

## Required change R-LA: within-batch look-ahead (author decision 2026-11-15, item 6)
Source: `results/notes/p7_genagg.md` ("Scoring-batch sensitivity: cause"), `results/notes/p7_batch_span.json`.
- **Wherever the paper says the detector, the sampling or the scoring is causal** (now:
  `data.tex` l.72-74 "Neighbourhood sampling is causal ...", `method.tex` l.17 figure node
  "causal Multi-GINe", l.36 "under causal neighbour sampling", `results.tex` l.134 "causal
  sampling"; grep again at pass 2), state the within-batch look-ahead. An edge can see neighbour
  edges, and the other edges of its own batch, up to 1,800 s later than itself. Give the median and
  p95 at the scoring batch used:
  batch 2048 (all MEGA-family scores): median 180 s, p95 720 s;
  batch 8192 (shipped Multi-GINe scores): median 600 s, p95 1,440 s.
  Say it applies to all three neural detectors (Multi-GINe, MEGA-GIN, MEGA-GenAgg). The data.tex
  sentence "never sees an edge later than the batch's latest seed" is literally true but must not be
  read as per-edge causality; reword it.
- **Limitations: new paragraph** with the look-ahead table (batch 2048 / 4096 / 8192: batch span
  median and max; look-ahead median / p95 / max; share of edges with look-ahead > 0). Add the measured
  MEGA-GIN test edge-F1 shift from scoring batch 8192 to 2048, per seed −0.0126, −0.0029, −0.0013,
  +0.0049, −0.0069 (mean 0.6893 → 0.6856). Also say GINe was not rescored.

## R-SB2048 — MEGA-GNN numbers to batch 2048 (pass 2; decision C-7, 2026-11-15)
- Done in pass 1: the footnote in results.tex (§ detector swap) and the appendix table `paper/tables/val_test_gap.tex` (input in appendix.tex).
- Pass 2: switch every MEGA-GNN number to batch 2048 from results/tables/r6_detector_swap_sb2048.csv. These are: edge F1 0.6893 → 0.6856 ± 0.0447; "9.4 points" of edge F1 → recompute against 0.5957 (8.99 points); B0 ring-F1 0.5208 → 0.5179; full 0.6074 → 0.6023; no-embedding 0.5881 → 0.5776; untouched rings 24.0 (check against the sb2048 class-b column); Jaccard 0.415 and 128.8 rings touched (recompute from v42 pairs at global 0.10). Also update paper/tables/detector_swap.tex, fig_edge_vs_ring (make_figs.py source), and introduction.tex:33 ("9.4 points").
- Wording rule (author, 2026-11-15): the budget is 0.1 % because the pre-registration fixes it. No sentence may say the test results confirm or justify that choice. The validation-picked sensitivity is reported only as a finding that validation-chosen budgets are unstable.
