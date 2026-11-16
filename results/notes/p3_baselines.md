# T-P3 — classical baselines under the protocol (2026-11-14)

Gate: **METHOD_SUPERIORITY=ON**. The best baseline (`lpa_on_expansion`, 0.5550) is below full's
0.5894. Bar (A): **met, but only narrowly** (see below). Bar (B): **not competitive**.

Checks: B0 seed 1 reproduced (0.5391, same chosen cell). CSGM `--bank-seed 0` reproduced 0.1224.
Identity checks on all 5 seeds: components on the flagged graph reproduce B0 per seed, and
components on the expanded subgraph reproduce proposed per seed, both to 4 dp.
`tests/test_community_baselines.py` (3) passes. Runtime ≈ 1 h, inside the 8 h limit.

Ring-F1 at Jaccard 0.5, primary window, 5 runs each (`results/tables/v40_external_baselines.csv`,
bd63558b…; json 24acac82…; CIs and τ 0.3 / 0.7 in the csv):

| Method | kind | test_visible [95 % CI] | full_membership | component | component_ge3 |
|---|---|---|---|---|---|
| full | ours | 0.5894 [0.523, 0.653] | 0.2428 | 0.5145 | 0.7397 |
| proposed | ours | 0.5819 [0.513, 0.646] | 0.2297 | 0.5041 | 0.7656 |
| B1b | ours | 0.5553 [0.493, 0.613] | 0.2073 | 0.4878 | 0.7001 |
| LPA on expansion | partition alt. | 0.5550 [0.486, 0.620] | 0.1762 | 0.5001 | 0.7483 |
| Louvain r1 on expansion | partition alt. | 0.5292 [0.466, 0.590] | 0.1555 | 0.4833 | 0.7349 |
| B0 | ours | 0.5213 [0.454, 0.586] | 0.1437 | 0.4436 | 0.6731 |
| Louvain r0.5 | community | 0.5151 [0.451, 0.578] | 0.1289 | 0.4451 | 0.6738 |
| LPA | community | 0.5091 [0.443, 0.572] | 0.1258 | 0.4428 | 0.6659 |
| Louvain r1 | community | 0.4830 [0.418, 0.543] | 0.1055 | 0.4298 | 0.6560 |
| Louvain r2 | community | 0.1066 [0.075, 0.136] | 0.0162 | 0.1021 | 0.1819 |
| CSGM (bank seeds 0–4) | external | 0.0834 [0.050, 0.113] | 0.0477 | 0.0597 | 0.0855 |

**Bar (A)**, adjacent pairs in the test_visible order that swap under another convention:
- full ↔ proposed under `component_ge3`. This is the known partition result.
- B0 ↔ Louvain r0.5 under `component` (0.4436 vs 0.4451) and `component_ge3` (0.6731 vs 0.6738).
- Louvain r2 ↔ CSGM under `full_membership`.

The bar is met. But the B0/Louvain swap is a difference of 0.0015 and 0.0007, well inside any
interval, and the other new swap is between the two weakest methods. **Reading:** the conventions
re-rank methods that are already near-tied, and do not reorder methods that are clearly apart. The
paper should say exactly that, not "conventions re-rank methods" without qualification.

**Bar (B):** the best community baseline is Louvain r0.5, chosen by mean validation ring-F1 (0.5265,
not on test). Test 0.5151 < 0.5213, so it is **not competitive**. Paired unit bootstrap (10,000
draws, seed 20261114), Holm over two comparisons:
- vs B0: Δ −0.0062 [−0.0140, +0.0002], p 0.072, p_Holm 0.072.
- vs full: Δ −0.0743 [−0.1178, −0.0355], p 0.0002, p_Holm 0.0004.

Other notes:
- Louvain at resolution 2 shatters rings: val-chosen 0.1066. CSGM sits far below everything,
  consistent with the shipped 0.1224 being its best bank seed. Its 5 runs are random
  two-institution splits: 0.122, 0.076, 0.099, 0.042, 0.078.
- Partition alternatives on the policy's subgraph (nothing tuned): LPA 0.5550, Louvain 0.5292.
  Both are below the expansion's own components (0.5819) and the shipped average-linkage
  partition (0.5894). `r4_partition.csv` b4 (Louvain, mean-affinity weights) recorded 0.582.

**Not run (logged):**
- Leiden: installing `leidenalg` + `igraph` was refused by this session's permission classifier.
  Skipped per runbook.
- FlowScope (optional): not attempted, to keep T-P3 inside its budget while T-P4 ran.

Supports / weakens: *supports* "the reference pipeline is not a strawman's opponent".
Community detection on the same flagged edges does no better than connected components (B0), and
full beats the best one by 0.074 [0.036, 0.118]. *Weakens slightly* "conventions re-rank methods":
apart from the partition swap, the re-rankings are between near-ties.

Code: `evaluation/community_baselines.py`, `evaluation/baselines_table.py`. Runs:
`experiments/R13_baselines/<method>/seed{1..5}`, scored outputs in `experiments/R13_baselines/scored/`.
Reproduction inputs come from `../RS-e2e/experiments` (scores, B0/B1b/proposed/full rings) and
`E:\JSJ\Ring-Shield\external\Collaborative-AML` (CSGM, upstream 2db6537).
