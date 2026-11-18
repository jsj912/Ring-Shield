# Matcher tie-break: measurement (2026-11-16). AUTHOR DECISION NEEDED; default unchanged

**Question.** The greedy one-to-one matcher (`evaluation.ring_metrics.match_rings`) breaks equal-Jaccard
ties by the prediction's position in the rings file. The Q track found a case where this changes which
truth ring is matched (`results/notes/q_track.md`, Q6: seed 4, truth rings 243 and 259 tie at Jaccard 0.667).
How many scored cells would change under a deterministic rule?

**Deterministic rule tested** (opt-in `match_rings(..., tie_break="deterministic")`). Candidates are sorted by:
1. Jaccard, descending;
2. truth ring id, smaller first (numeric ids sort numerically);
3. the predicted ring's sorted member tuple.

The default stays `"file_order"`, the shipped rule `(-J, prediction index, str(truth id))`.
Test: `tests/test_matcher_tiebreak.py` uses a 2-truth, 2-prediction tie.
- The order-independence check is strict-xfail under `file_order`: listing order changes the match count from 1 to 2.
- It passes under `deterministic`.
- A further test checks that the default output is unchanged.

**Scope.** `evaluation/matcher_tiebreak_audit.py` ran over all 487 `rings.parquet` under `experiments/` and
`../RS-e2e/experiments/` (482 runs, 106 run directories). The runs behind r9, r14, v39–v45, the sb2048 rows and
m1_primary are all among them.
- Test split, restricted exactly as the scorer does (`score_external.load_predictions` → `restrict_rings`).
- Grid: 3 windows (primary, whole, tail) × 4 truth conventions (test_visible, full_membership, component, component_ge3) × τ ∈ {0.3, 0.5, 0.7}.
- That gives 17,532 run-cells and 3,816 table-like cells (5-seed means). 0 load errors.
- Output: `results/tables/matcher_tiebreak_audit.csv`.

## Result
| scope | cells | match count changes | matched truth set changes | largest shift in a 5-seed-mean ring-F1 |
|---|---|---|---|---|
| **primary, test_visible, τ 0.5** (all headline tables) | 482 runs / 106 cells | **0** | 5 runs (all seed 4: R4_partition average ×2 files, R4_sweep cc_partition and full, R7_l3only_bipartite full) | **0** |
| everything else (whole, tail, τ 0.3 / 0.7, other conventions) | 17,050 / 3,710 | 55 run-cells, each ±1 match | 168 | 0.0032 (louvain_r2, primary, component_ge3, τ 0.3) |

- **Headline cells (primary window, test_visible, τ 0.5): nothing changes.** In 5 runs a different truth ring
  is matched, the Q6 mechanism, but never a different number of rings. Ring precision, recall and F1, and every
  paired difference computed from counts, are identical. Q7 found the same with 200 random orders (SD 0).
- **Secondary cells** (the whole and tail windows used by r9_robustness and the tail tables, the τ 0.3 / 0.7
  appendix): 18 runs gain or lose exactly one match under one or more settings. The runs that move:
  - the shipped full pipeline, R4_partition average seed 4: −1, whole window;
  - the M1 arms at seed 4;
  - Q6 at seeds 2 and 4;
  - R13 louvain_r2 at seed 3: +1, primary window, τ 0.3;
  - the R7 and R4_sweep full runs.

  The largest shift in any 5-seed-mean cell is 0.0032 of ring-F1. No headline number moves.
- **The deterministic rule is not better, only order independent.** It loses a match in 16 of the 18 runs and
  gains one in 2: the rule is greedy and blind to the alternatives a tie leaves open. An optimal matching
  (maximum cardinality, as in Q7) is the only rule that cannot undercount. In Q7, optimal and greedy differ only
  for full, by +0.003 (0.5924 against 0.5894).
- **Paired intervals.** Bootstraps over per-truth-ring matched indicators can shift where the matched *set*
  changes (the 5 seed-4 runs above). Q7 bounded such shifts at 0.0013 at either end, with no verdict changing.

## Options for the author (nothing rescored)
1. **Keep `file_order` as the default** and document the dependence; report identical arms as Δ = 0 with no interval (Q6 practice).
2. **Make `deterministic` the default** for new scoring only. No headline cell changes; 55 secondary run-cells move by one match. Frozen tables stay as shipped.
3. **Use optimal (maximum-cardinality) matching.** This changes the metric definition, so it would need a PREREG amendment.

Recommendation: option 1 for this paper, since no headline cell changes and frozen tables stay as shipped. Option 2 or 3 could follow as a separate change.
