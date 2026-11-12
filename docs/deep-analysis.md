# Deep analysis

A running log of follow-up analyses on HI-Small. Each one states the question and method fixed
before it ran, the result in full and the verdict against its bars. None of them changes a
reported number. Where one changes the meaning of a claim, it says which claim, and that change
goes in as a dated note in the owning doc.

| # | Analysis | Status | Verdict |
|---|---|---|---|
| 1 | Window-matched seed budget | **Done 2026-11-11** | Reach ✓, class (b) ✓ (in-window only), **veto tripped** |
| 2 | Precision-aware paired test | **Done 2026-11-11** | **Success**: A5 is significant (p_holm 0.0008); gfpxgb gap now significant on ring-F1 |
| 3 | Consortium-size curve for R10 | **Done 2026-11-11** | Success by the letter (monotone, k=5 excludes k=1), but five banks close only **11 %** of the gap |
| 4 | Component-level scope as a third convention | **Done 2026-11-11** | Ordering held for all pieces; **one swap (proposed > full) with ≥ 3-account pieces only**; 44 % of rings have no piece any method can match |
| 5 | Seed reallocation under `full` | **Done 2026-11-11** | **Failure** for 11c (B14 extends to `full`); ensemble +2.1 F1 inside seed spread; B14's B0 F1 0.4455 is an as-run figure |
| 6 | Drift monitor with a passing positive control (R12b) | **Done 2026-11-12** | **Failure as registered**: raw p99 sits on a tie plateau; day 9 is already +3.2 SD from day 8 |

---

## 1. Window-matched seed budget on HI-Small

**Run 2026-11-11.** Script: `evaluation/window_budget.py`. Tables:
`results/tables/v34_window_budget.csv` (one row per seed and rule), `v34_window_budget.json`
(mean ± SD), `v34_window_budget_classes.csv` (the class of each truth ring).

### Question

Does the test tail absorb about half of the seed budget, so that the primary-window ring numbers
are produced at roughly half the budget validation chose?

### Why it was worth running

The shipped rule takes the k\* = 0.1 % strict quantile over the **whole** test split: 864 seeds,
of which only 463.0 per seed (379–567) fall in the primary window (days 8–9). On validation, all
966 seeds fall in the window (`V3_DIAGNOSTICS.md`, correction note and part c2), so validation
picked k\* at a budget the test window never received. C11 says a global quantile silently
spreads the budget across days. D says the tail inflates edge numbers "not these ring-level
ones", but nobody had tested that from the budget side. B8's untouched 19 % is defined at the
shipped budget.

### Method

The 5 shipped detector seeds (`gine_causal`) were used. Everything except the seed mask is fixed
at the shipped val-chosen cell: k\* = 0.1 %, `min_size`, R3 expansion (`delta_t_h`, `p_min`,
`policy_proposed`) and the R4 `average` partition at its chosen cut. Nothing is re-selected.
Three label-free seed rules:

| rule | seed mask |
|---|---|
| `global` (shipped) | `seed_mask_for_pct` over all test edges |
| `in_window` | the same strict quantile computed over primary-window edges only; no seeds outside the window |
| `per_day` | the same strict quantile computed separately within each test day (8–17) |

Measured in the primary window, with the same definitions as the shipped rows:

- **Rings touched:** truth rings with ≥ 1 in-window seed edge that is one of their member edges
  (B14's definition).
- **Unmatched classes:** `classify()` from `evaluation/unmatched_rings.py`, for B0 and `full`.
- **Ring P/R/F1:** `evaluate_rings` at Jaccard 0.5 on the window-restricted predictions.
- **Added-member precision:** `expanded_member_precision` from `expansion_vs_truth`, i.e. the
  share of expanded edges in the window that are truth member edges.

B0 for a given mask comes from `aggregate_cc` with an explicit threshold on a 0/1 selection
column. Its connected components and size filter are therefore exactly the shipped ones.

Bars, taken from the proposal:

- **Success:** rings touched rise by ≥ 2 seed SDs over 129.6, *and* class (b) falls below
  33.2 ± 3.6.
- **Failure:** both stay inside seed spread.
- **Veto:** added-member precision below 0.85 (the B15 bound).

**Inputs.** RS-react has no detector checkpoints, so `--r1-dir` points at
`RS-e2e/experiments/R1_gine_causal`. Its `scores_test_seed1.parquet` and
`embeddings_test_seed1.parquet` were checked to be byte-identical (sha256) to RS-react's copies.
Runtime is about 4 minutes per seed for all three rules.

```
python evaluation/window_budget.py --r1-dir ../RS-e2e/experiments/R1_gine_causal \
    --out results/tables/v34_window_budget.csv
```

### Reproduction check

The `global` row reproduces the published numbers exactly: 463.0 seeds in window (379–567),
129.6 rings touched (B14) and class (b) 33.2 ± 3.6 (B8). So the new rows use the same
definitions as the published ones.

### Results: mean ± SD over 5 seeds, primary window (174 in-scope truth rings)

| | global (shipped) | in_window | per_day |
|---|---|---|---|
| seeds, total | 864 | 863 | 866.4 ± 3.6 |
| seeds in window | 463.0 ± 84.2 | 863 | 864 |
| **rings touched** | **129.6 ± 4.8** | **148.2 ± 6.2** | **139.8 ± 7.3** |
| class (b), `full` | 33.2 ± 3.6 | 28.0 ± 5.5 | 30.6 ± 3.8 |
| class (b), B0 | 40.2 ± 3.8 | 34.0 ± 5.7 | 37.8 ± 2.6 |
| **added-member precision** | **0.926 ± 0.015** | **0.700 ± 0.137** | **0.738 ± 0.098** |
| matched rings, `full` | 80.2 ± 5.9 | 77.6 ± 5.6 | 75.8 ± 5.3 |
| ring-F1, `full` | 0.589 ± 0.037 | 0.546 ± 0.023 | 0.532 ± 0.032 |
| ring-F1, B0 | 0.521 ± 0.045 | 0.503 ± 0.042 | 0.485 ± 0.036 |

Per seed (`full`):

| seed | rule | seeds in window | touched | class (b) | ring-F1 | added prec |
|---|---|---|---|---|---|---|
| 1 | global | 402 | 123 | 36 | 0.6045 | 0.919 |
| 1 | in_window | 863 | 148 | 26 | 0.5517 | 0.631 |
| 1 | per_day | 864 | 140 | 27 | 0.5529 | 0.652 |
| 2 | global | 429 | 133 | 37 | 0.5978 | 0.931 |
| 2 | in_window | 863 | 152 | 30 | 0.5461 | 0.592 |
| 2 | per_day | 864 | 146 | 32 | 0.5118 | 0.721 |
| 3 | global | 379 | 126 | 32 | 0.5725 | 0.947 |
| 3 | in_window | 863 | 156 | 21 | 0.5636 | 0.586 |
| 3 | per_day | 864 | 148 | 27 | 0.5385 | 0.639 |
| 4 | global | 538 | 134 | 28 | 0.6357 | 0.927 |
| 4 | in_window | 863 | 145 | 27 | 0.5612 | 0.883 |
| 4 | per_day | 864 | 133 | 31 | 0.5673 | 0.855 |
| 5 | global | 567 | 132 | 33 | 0.5368 | 0.907 |
| 5 | in_window | 863 | 140 | 36 | 0.5056 | 0.808 |
| 5 | per_day | 864 | 132 | 36 | 0.4891 | 0.823 |

### Against the bars

| bar | threshold | in_window | per_day |
|---|---|---|---|
| rings touched ≥ 129.6 + 2 × 4.83 | ≥ 139.3 | **148.2 ✓** | 139.8 ✓ (by 0.5) |
| class (b) below 33.2 − 3.6 | < 29.6 | **28.0 ✓** | 30.6 ✗ (inside spread) |
| veto: added-member precision ≥ 0.85 | ≥ 0.85 | **0.700 ✗ veto** | **0.738 ✗ veto** |

**Verdict: VETOED.** Both rules increase reach, and the in-window rule meets both success bars.
Both, however, trip the precision veto. Full ring-F1 also falls on every seed under both rules
(−4.3 and −5.7 points on the mean), and so does the matched-ring count.

### Reading

1. **C1 now has a ring-level consequence.** The tail does take about half the budget (463 of 864
   seeds in window). Giving that half back to the window reaches **+18.6 rings** (in-window rule)
   and shrinks class (b) by 5.2. Part of class (b) is therefore "unreached at this effective
   budget", not "unreachable".
2. **The reach does not become matched rings.** The extra ~400 in-window seeds sit below the
   score level the global cut reached. Expansion then grows from weaker seeds, the precision of
   added members falls 0.93 → 0.70, and over-merging and false members cost more rings than the
   new reach gains. This is the E5/E6 pattern (precision ≈ 0.78 at a doubled budget) seen from
   the allocation side.
3. **B8/C6 "the budget binds" stands, restated with the effective budget.** On test, the binding
   budget is about 463 in-window seeds, not 864. More budget in the window buys reach and loses
   precision. The val-chosen operating point is still the best of the three on ring-F1.
4. **D's sentence becomes a measured claim.** The tail does not inflate the ring-level numbers in
   the direction that matters. The shipped primary-window ring-F1 is not depressed by the budget
   lost to the tail: recovering that budget lowers ring-F1.
5. **The per-day rule behaves like a weaker in-window rule.** Tail days have so few edges that
   their per-day quantile yields 0–8 seeds. Nearly all of the budget lands in days 8–9 anyway, at
   a cut that differs between the two days.

### Caveats

- **Sensitivity row, not a clean pre-registration:** the test window had been examined many
  times before.
- **Veto driven by seeds 1–3:** precision is 0.59–0.65 on seeds 1–3 and 0.81–0.88 on seeds 4–5.
  Seeds 4–5 already put the most global seeds in the window (538 and 567), so moving the budget
  changes them least.
- **L3 cells not re-tuned:** they were kept fixed for the new budgets. A re-tuned `p_min` could
  win back some precision, but that would be a re-selection on test, which this row rules out.

### Where it goes

A dated note in `V3_DIAGNOSTICS.md` (after the correction note on the 863-seed mistake) and a
one-line pointer from FINDINGS C1 and D. No reported number changes.

---

## 2. A precision-aware paired test

**Run 2026-11-11.** Code: a new `paired_unit_bootstrap()` in `evaluation/ring_stats.py` (added;
nothing existing changed) and a driver, `evaluation/precision_paired.py`. Tables:
`results/tables/v35_precision_paired.csv` and `.json`.

### Question

Is the policy's purity advantage over the B1b rule statistically significant under a test that
can see precision?

### Why it was worth running

The only significance test in use is a paired sign-flip permutation on per-ring **matched
indicators** (`r9_significance.csv`). It is blind to precision (`PITFALLS.md` §7): a method that
emits many more rings and matches about as many looks indistinguishable. Two things followed.
A5 (added-member precision 0.926 vs 0.518), which is item 3 of F, rested on two intervals
compared by eye, which §8 warns against. And `gfpxgb/full` sat 13.9 ring-F1 points below ours at
p_holm 0.807.

### Method

A **paired bootstrap on the difference** between two arms, primary window (test days 8–9),
`test_visible` scope, 5 detector seeds, run artefacts as shipped. Nothing is re-run or
re-selected.

**Metrics:**

- **Added-member precision:** in-window expanded edges that are truth member edges, divided by
  all in-window expanded edges, pooled over the 5 seeds. This is exactly A5's definition
  (`r9_robustness.added_member_precision`, `r9_quiet_vs_precision.csv`).
- **Ring-F1:** at Jaccard 0.5, computed per seed and averaged over seeds.

**Resampling unit: the ring, not the edge.** Added edges cluster by ring, so an edge-level
bootstrap would give falsely narrow intervals. Every prediction of every method and seed (after
the window restriction) is assigned to one unit:

| prediction | unit |
|---|---|
| matched at Jaccard ≥ 0.5 | the truth ring it matched |
| unmatched, shares accounts with a truth ring | the truth ring with the largest account overlap (ties: smallest id) |
| shares no account with any truth ring | an **off-ring cluster**: union-find over shared accounts, across all methods and seeds |

This gives 392 units: the 174 in-scope truth rings plus 218 off-ring clusters. Each draw resamples
the 392 units with replacement. Both arms are recomputed on the **same** draw, so the interval is
on the paired difference. Inside a draw, precision is pooled over seeds and ring-F1 is averaged
over them: the "seeds averaged inside" rule of `bootstrap_over_rings`. Because off-ring
predictions are resampled too, ring precision (and so ring-F1) responds to false rings, which the
matched-indicator test cannot see.

Settings: 10,000 draws, RNG seed 20261111. The two-sided p is
2 · min(#(d ≤ 0) + 1, #(d ≥ 0) + 1) / (n + 1), so its floor is 0.0002. **Holm across the four
registered comparisons, separately per metric.**

**Family, fixed before running:**

| comparison | arm A | arm B |
|---|---|---|
| proposed vs B1b | `R3_expansion/runs/proposed` | `R3_expansion/runs/b1b` |
| full vs B1b | `R4_partition/runs/average` | `R3_expansion/runs/b1b` |
| gine/full vs gfpxgb/full | `R4_partition/runs/average` | `R6_full/gfpxgb` |
| mega/full vs gine/full | `R6_full/mega` | `R4_partition/runs/average` |

- **Success:** the proposed vs B1b interval on added-member precision excludes 0.
- **Failure:** it does not.

**Inputs.** RS-react lacks the R3 and R6 run directories, so `--exp-root` points at
`RS-e2e/experiments`. `R4_partition/runs/average/seed1/rings.parquet` was checked to be
byte-identical (sha256) between RS-e2e and RS-react. Runtime is under 2 minutes.

```
python evaluation/precision_paired.py --exp-root ../RS-e2e/experiments \
    --out results/tables/v35_precision_paired.csv
```

### Reproduction check

The point estimates reproduce the published numbers exactly:

| arm | added-member precision | added edges (5 seeds) | ring-F1 | published |
|---|---|---|---|---|
| proposed | 0.9263 | 407 | 0.5819 | A5 0.926, 407 edges; r9 F1 0.5819 |
| B1b | 0.5179 | 894 | 0.5553 | A5 0.518, 894 edges; r9 F1 0.5553 |
| gine/full | 0.9257 | 404 | 0.5894 | 0.589 |
| gfpxgb/full | 0.2600 | 2,419 | 0.4508 | 13.9 points below gine/full ✓ |
| mega/full | 0.9316 | 453 | 0.6074 | — |

### Results: paired differences (A − B), 10,000 paired draws, Holm across four per metric

**Added-member precision**

| comparison | A | B | Δ | 95 % CI | p_raw | p_holm | reject |
|---|---|---|---|---|---|---|---|
| **proposed vs B1b** | 0.926 | 0.518 | **+0.408** | **[0.342, 0.479]** | 0.0002 | **0.0008** | **yes** |
| full vs B1b | 0.926 | 0.518 | +0.408 | [0.341, 0.479] | 0.0002 | 0.0008 | yes |
| gine/full vs gfpxgb/full | 0.926 | 0.260 | +0.666 | [0.557, 0.752] | 0.0002 | 0.0008 | yes |
| mega/full vs gine/full | 0.932 | 0.926 | +0.006 | [−0.042, 0.053] | 0.771 | 0.771 | no |

**Ring-F1**

| comparison | A | B | Δ | 95 % CI | p_raw | p_holm | reject |
|---|---|---|---|---|---|---|---|
| proposed vs B1b | 0.582 | 0.555 | +0.027 | [0.001, 0.052] | 0.042 | 0.093 | no |
| full vs B1b | 0.589 | 0.555 | +0.034 | [0.004, 0.065] | 0.031 | 0.093 | no |
| **gine/full vs gfpxgb/full** | 0.589 | 0.451 | **+0.139** | **[0.083, 0.196]** | 0.0002 | **0.0008** | **yes** |
| mega/full vs gine/full | 0.607 | 0.589 | +0.018 | [−0.016, 0.053] | 0.303 | 0.303 | no |

The p-values of 0.0002 are the resolution floor at 10,000 draws: no draw crossed zero.

### Verdict: **SUCCESS**

The proposed vs B1b interval on added-member precision is [0.342, 0.479]. It excludes 0 by a wide
margin, and the comparison survives Holm (p_holm 0.0008).

### Reading

1. **A5 / F3 become a tested claim.** The policy's purity advantage, +40.8 points of
   added-member precision over B1b, is significant under a ring-level paired test. It no longer
   rests on two intervals compared by eye. The full pipeline inherits it unchanged (+40.8), since
   the partition step does not dilute what expansion added.
2. **A3's "one significant link" becomes two.** `gine/full` vs `gfpxgb/full` was p_holm 0.807
   under the matched-indicator test. Under a test that sees precision it is **significant on both
   metrics**: Δ ring-F1 +0.139 [0.083, 0.196], p_holm 0.0008. The old null came from the test's
   blindness, as `PITFALLS.md` §7 suspected. gfpxgb's full pipeline matches about as many rings
   but adds 2,419 edges at 26 % precision and emits many more false rings.
3. **The policy's ring-F1 gain over B1b is real-looking but not established.** Both raw
   intervals exclude 0 (+2.7 and +3.4 points, p_raw 0.04 and 0.03), but neither survives Holm
   (0.093). The proposal never claimed this, and it stays a "trend" rather than a finding.
4. **MEGA vs gine stays a null on both metrics.** C6's "an edge-F1 gain buys no rings" is now
   backed by a test that would have seen a precision difference: none exists (Δ precision
   +0.006 [−0.042, 0.053]).

### Caveats

- **The off-ring cluster rule is a design choice.** Union-find over shared accounts, across all
  methods and seeds, keeps the draw paired but can produce coarse clusters. Coarser clusters
  widen intervals, so this choice makes the test conservative, not liberal.
- **Unmatched-prediction attribution is approximate.** Assigning an unmatched prediction to its
  max-overlap truth ring ties a false ring's draw to that ring's. Other rules (for example
  always making it its own unit) were not tried.
- **Precision is pooled across seeds:** that is A5's definition. A per-seed-mean variant would
  weight seeds equally rather than edges.
- **Not pre-registered in a document dated before the run.** The family and bar are the ones
  stated in this file's proposal and were not changed after seeing results.

### Where it goes

A dated note in FINDINGS: a test column for A5, and A3's significant-link count going from one
to two. A new row in `r9_significance` or a sibling table, `v35_precision_paired.csv`. A line in
`PITFALLS.md` §7 that the precision-aware test now exists, and that `gfpxgb/full`'s 0.807 was an
artefact of the test. No reported point estimate changes.

---

## 3. Consortium-size curve for R10

**Run 2026-11-11.** Script: `evaluation/r10_consortium.py`. Outputs:
`results/tables/r10_consortium.json` (curve, steps, per tenant), `r10_consortium_pairs.csv`
(one row per tenant-ring pair, with an indicator for each k). The new ring sets are cached under
`experiments/R10_consortium/runs/C<banks>/seed<S>/`.

### Question

How many banks must pool their edges to recover most of the pooled ring recall?

### Why it was worth running

R10 measured only the two ends: one bank alone (tenant recall 0.088) and every bank pooled
(0.359), a difference of 0.271 [0.154, 0.407] (`r10_registered.md`). 98.9 % of in-scope rings are
cross-bank, at 4.626 banks per ring. The `pooled_scores` row (0.121) shows that most of the gap
comes from building rings on a restricted edge set, not from the scores. The open question for a
data-sharing claim (L5/L6) is the shape of the curve between the two ends.

### Method

Everything is R10's registered machinery, unchanged:

- **Unit and evaluation:** tenant-ring pairs of the primary tenants (1, 20, 11, 118, 12): 68
  pairs over 49 rings. Primary window, `test_visible` scope, Jaccard 0.5 via
  `r10_registered.recovered`, and window restriction via `restricted_members`.
- **Seeds:** indicators are averaged over the 5 seeds inside each pair.
- **Bootstrap:** over rings (each ring with all its pairs), 10,000 resamples, RNG seed 0.

**Fixed denominator.** The same 68 pairs are scored at every k, so the steps of the curve are
paired.

**Consortium of size k for a pair (T, r):** T plus the first k − 1 *other* primary tenants in
registered order. The sets are nested within each tenant, and every consortium beyond k = 1
includes bank 1. Ten distinct multi-bank consortia result, from {1, 20} to {1, 11, 12, 20, 118}.

**Ring building:** the registered `pooled_scores` option, secondary (a).

- **Inputs:** pooled scores, pooled GFP and pooled embeddings.
- **Edge subset:** every edge with either endpoint in a consortium bank, passed as
  `ringshield run --edge-subset`.
- **Seeds:** `score_raw` above that detector seed's pooled cutoff q, converted to a percentile by
  `seed_fraction_for_cutoff`.

The visible-edge counts for seed 5 run from 21,869 ({1, 118}) to 57,953 (all five).

**Anchors:**

- **k = 1** is by construction the registered `pooled_scores` row. Those ring sets are the
  registered R10 caches.
- **k = pooled** is the registered all-banks ceiling.

**Bars:**

- **Success:** a monotone curve whose k = 5 interval excludes the k = 1 value.
- **Failure:** a flat curve, meaning five banks are too few.

**Inputs.** RS-react has no R10 caches, no `contract/out` scores for seeds 2–5 and only one
shipped model, so `--src` points at `RS-testing1`. Five files were checked to be byte-identical
(sha256) between the two checkouts: `ringshield/__main__.py`, `run_rings.py`,
`aggregators/full.py`, `platform/jobs/build_tenant_rings.py` and `evaluation/r10_registered.py`.
So were three data files: the GFP features, `account_bank.parquet` and the ring ground truth. The
50 new ring builds (10 consortia × 5 seeds) take about 1 h on CPU.

```
python evaluation/r10_consortium.py --src ../RS-testing1 --out results/tables/r10_consortium
```

### Reproduction check

k = 1 gives **0.121 [0.054, 0.205]** and pooled gives **0.359 [0.240, 0.500]**. Both are
identical to the registered `pooled_scores` and pooled values, and the k = 1 gap of 0.238
matches the registered 0.238 [0.135, 0.363].

### Results: 68 pairs, 49 rings, 5 seeds, 10,000 ring resamples

| banks pooled (k) | recall | 95 % CI | gain vs k = 1 | 95 % CI | share of pooled gap closed | gap to pooled | 95 % CI |
|---|---|---|---|---|---|---|---|
| 1 | 0.121 | [0.054, 0.205] | — | — | 0 % | 0.238 | [0.135, 0.363] |
| 2 | 0.132 | [0.059, 0.228] | +0.012 | [0.000, 0.032] | 5 % | 0.227 | [0.126, 0.349] |
| 3 | 0.135 | [0.061, 0.229] | +0.015 | [0.000, 0.038] | 6 % | 0.224 | [0.125, 0.343] |
| 4 | 0.138 | [0.062, 0.234] | +0.018 | [0.000, 0.041] | 7 % | 0.221 | [0.121, 0.340] |
| **5** | **0.147** | [0.071, 0.244] | **+0.026** | **[0.006, 0.053]** | **11 %** | **0.212** | **[0.113, 0.329]** |
| all (pooled) | 0.359 | [0.240, 0.500] | +0.238 | [0.135, 0.363] | 100 % | 0 | — |

Steps (paired):

| step | Δ recall | 95 % CI | pairs that got worse |
|---|---|---|---|
| 1 → 2 | +0.012 | [0.000, 0.032] | 0 |
| 2 → 3 | +0.003 | [0.000, 0.009] | 0 |
| 3 → 4 | +0.003 | [0.000, 0.010] | 0 |
| 4 → 5 | +0.009 | [0.000, 0.024] | 0 |

Per tenant (descriptive only, no claim):

| tenant | k=1 | k=2 | k=3 | k=4 | k=5 | pooled |
|---|---|---|---|---|---|---|
| 1 | 0.071 | 0.106 | 0.118 | 0.118 | 0.118 | 0.365 |
| 11 | 0.114 | 0.129 | 0.129 | 0.129 | 0.157 | 0.357 |
| 12 | 0.218 | 0.218 | 0.218 | 0.236 | 0.236 | 0.400 |
| 20 | 0.143 | 0.143 | 0.143 | 0.143 | 0.143 | 0.357 |
| 118 | 0.083 | 0.083 | 0.083 | 0.083 | 0.100 | 0.317 |

Pair-level counts:

- **Improved by k = 5:** 6 of 68 pairs.
- **Never worse:** no pair loses recall at any step.
- **Recovered by the pooled ring set but not by the five-bank consortium:** 21 of the 32 pairs
  the pooled set recovers at all.

### Verdict: **SUCCESS by the registered bar, substantively a near-flat curve**

The curve is monotone: every step is ≥ 0 and no pair ever gets worse. The k = 5 gain interval
[0.006, 0.053] excludes 0, which is the k = 1 value. So both bars are met. But five banks close
only **11 %** of the gap to pooled recall. The remaining gap, 0.212 [0.113, 0.329], is still
almost the whole registered difference.

### Reading

1. **Pooling helps monotonically, but five banks are far too few.** Adding banks never hurts a
   pair: a larger consortium only adds edges. But each added bank buys about 0.3–1.2 points of
   recall against a 23.8-point gap. Extrapolating linearly would need on the order of 40+ banks,
   and the curve may well not be linear.
2. **Mechanism: the five banks hold a minority of each ring.** Over the 49 rings, a median of
   **25 %** of in-window members (mean 31 %) bank at one of the five. Only **1 ring** has all its
   members inside the consortium. Rings average 4.6 banks drawn from 30,470, so five fixed banks
   rarely complete a ring. Recall moves only when a consortium happens to own enough of the
   *same* ring to pass Jaccard 0.5.
3. **Which banks matter is idiosyncratic.** Bank 1 gains from adding 20 and 11. Bank 20 gains
   nothing from any partner. Bank 118 gains only when bank 12 joins. The steps depend on which
   rings two banks share, not on consortium size as such.
4. **For L5/L6:** a "data sharing among a few partner banks" claim is not supported at this
   scale. What recovers rings is visibility across the banks a ring actually spans, close to
   whole-network visibility (pooled), not a small fixed club. A targeted consortium chosen by
   shared ring traffic might do much better. That is a different, untested design, and choosing
   it would use labels.

### Caveats

- **Low power:** 49 rings and 68 pairs. Each step's interval touches 0. Only the cumulative
  k = 1 → 5 gain is resolved.
- **The registered order fixes the curve's path.** Every multi-bank consortium contains bank 1,
  so a different order would give a different (though still nested and monotone) path. Averaging
  over orders was not done.
- **`pooled_scores` option only.** Tenant-visible scores (the registered `primary` option, k = 1
  at 0.088) were not re-run for multi-bank consortia. Doing so would need consortium-visible
  re-scoring, GFP and embeddings, which is a GPU job.
- **Five of 30,470 banks is a tiny sample.** The bar ("excludes the k = 1 value") was weak by
  design: it detects *any* gain. The 11 % share is the figure that matters.

### Where it goes

R10 can enter FINDINGS as its own section. The registered k = 1 vs pooled gap goes in as the
claim, and this curve is the qualifier: the gap does not close with a handful of partners. It
belongs in the L5/L6 data-sharing discussion. No registered number changes.

---

## 4. Component-level scope as a third convention

**Run 2026-11-11.** Script: `evaluation/component_scope.py`. Tables:
`results/tables/v36_component_scope.csv` and `.json`.

### Question

How much of the residual loss disappears when each in-window connected piece of a truth ring is
scored as its own target?

### Why it was worth running

B13 found that 176 of 216 missing member edges have no in-window path to the recovered fragment
(STACK 140/140). B16 found that history does not reconnect them. C9 showed that the scope
convention moves ring-F1 about five times more than the whole method, but tested only
`full_membership`, the direction that makes rings *bigger*. `V3_DIAGNOSTICS.md` ends by naming
"a different evaluation unit" as one of two remaining routes. A component-level unit asks the
opposite question: if a ring is not observable as one object in the window, how well does a
method recover the objects that *are* observable? This separates "ring not observable" from
"method missed it", which is what F7 needs.

### Method

These are the same shipped runs and the same seven detector × method rows as
`evaluation/scope_sensitivity.py` (C9), re-scored under three conventions. Nothing is re-run or
re-selected.

| convention | targets |
|---|---|
| `test_visible` (reported) | one per in-scope ring; members = endpoints of its in-window transactions |
| `component` | each **in-window connected piece** of a `test_visible` ring is its own target. Pieces are the ring's in-window truth edges joined when they share an account: the `v3_diagnostics.edge_components` / B13 construction. A one-piece ring is unchanged. |
| `component_ge3` | the same, keeping only pieces with **≥ 3 accounts**, the smallest ring any method emits (`min_size` 3) |

A check asserts that the pieces partition each ring's visible member set.

**Unchanged from C9:**

- **Matching:** greedy one-to-one at Jaccard 0.5, so a prediction spanning two pieces can match
  only one of them.
- **Seeds:** averaged.
- **Intervals:** a 1,000-resample bootstrap over targets (`scope_sensitivity.boot`).

**Bar (C9):** the ring-F1 ordering b0 < b1b < proposed < full holds, for gine (4 methods) and
mega (b0 < proposed < full). If the ordering changes, that is itself a finding.

**Inputs.** RS-react lacks the R2, R3 and R6 runs, so `--exp-root` points at
`RS-e2e/experiments`. Runtime is a few minutes.

```
python evaluation/component_scope.py --exp-root ../RS-e2e/experiments \
    --out results/tables/v36_component_scope.csv
```

### Reproduction check

All seven `test_visible` rows reproduce `r14_scope_sensitivity.csv` exactly: for example gine
full F1 0.5894 [0.5234, 0.6529], b0 0.5213 and mega full 0.6074.

### The targets

| convention | targets | rings represented | median members | targets ≥ 3 members | STACK targets |
|---|---|---|---|---|---|
| test_visible | 174 | 174 | 4 | 114 | 22 |
| component | 254 | 174 | **2** | 108 | 68 |
| component_ge3 | 108 | **97** | 5 | 108 | 15 |

- **Split rings:** 28 of the 174 rings fall into ≥ 2 in-window pieces. Their 108 extra pieces are
  mostly 2-account fragments (STACK alone goes from 22 rings to 68 pieces).
- **Rings with no piece of ≥ 3 accounts:** **77 of 174 (44 %)**.
  - 60 of them have < 3 visible members in total (the existing class (a)).
  - **17** have ≥ 3 visible members, but every piece is under 3. Under `test_visible` they count
    as ordinary misses (class (b) or (c), depending on the seed; the split was not tabulated),
    yet no `min_size`-3 method can match them as a connected object.

### Results: ring-F1 [95 % CI], 5 seeds, primary window

| detector | method | test_visible | component | component_ge3 |
|---|---|---|---|---|
| gine | b0 | 0.521 [0.454, 0.586] | 0.444 [0.386, 0.494] | 0.673 [0.605, 0.738] |
| gine | b1b | 0.555 [0.493, 0.613] | 0.488 [0.433, 0.541] | 0.700 [0.647, 0.753] |
| gine | proposed | 0.582 [0.513, 0.646] | 0.504 [0.444, 0.553] | **0.766** [0.707, 0.826] |
| gine | full | **0.589** [0.523, 0.653] | **0.515** [0.456, 0.567] | 0.740 [0.683, 0.796] |
| mega | b0 | 0.521 [0.451, 0.588] | 0.441 [0.379, 0.492] | 0.674 [0.610, 0.744] |
| mega | proposed | 0.598 [0.528, 0.661] | 0.517 [0.458, 0.565] | **0.777** [0.722, 0.835] |
| mega | full | **0.607** [0.544, 0.669] | **0.530** [0.472, 0.581] | 0.774 [0.725, 0.826] |

Ring recall, precision and matched targets per seed (gine):

| method | test_visible R / P / matched | component R / P / matched | component_ge3 R / P / matched |
|---|---|---|---|
| b0 | 0.384 / 0.814 / 66.8 | 0.294 / 0.909 / 74.6 | 0.593 / 0.781 / 64.0 |
| b1b | 0.463 / 0.702 / 80.6 | 0.356 / 0.787 / 90.4 | 0.726 / 0.683 / 78.4 |
| proposed | 0.446 / 0.838 / 77.6 | 0.344 / 0.944 / 87.4 | 0.711 / 0.830 / 76.8 |
| full | 0.461 / 0.818 / 80.2 | 0.357 / 0.924 / 90.6 | 0.706 / 0.778 / 76.2 |

STACK recall (gine full): 0.036 under `test_visible`, 0.126 under `component`, **0.493** under
`component_ge3`.

### Against the bar

| convention | gine ordering | mega ordering |
|---|---|---|
| test_visible | ✓ | ✓ |
| component | **✓** | **✓** |
| component_ge3 | ✗: **proposed 0.766 > full 0.740** | ✗: proposed 0.777 > full 0.774 (by 0.003) |

**Verdict: mixed.**

- **Every piece as its own target:** the ordering is fully preserved for both detectors, so the
  C9 requirement holds.
- **Only pieces of ≥ 3 accounts:** the ordering changes in exactly one place. The partition step
  (proposed → full) goes from a small gain to a loss: −2.6 points on gine, −0.3 on mega. Every
  other adjacent step keeps its sign.

### Reading

1. **How much residual loss disappears.**
   - *Every piece counted:* the loss does **not** shrink. Recall falls (gine full 0.461 → 0.357)
     because 80 extra 2-account targets join the denominator and are unmatchable at
     `min_size` 3. Meanwhile **+10.4 more targets per seed are matched** (80.2 → 90.6), so
     methods do recover separate pieces of split rings that `test_visible` scores as failures.
   - *Only matchable pieces (≥ 3 accounts):* the loss on what remains falls from **53.9 % to
     29.4 %** (recall 0.461 → 0.706), and STACK recall goes 0.04 → 0.49.
2. **F7 can now be split into two numbers.** **44 % of in-scope rings (77/174) have no in-window
   piece a `min_size`-3 method could match.** Of those, 17 have ≥ 3 visible members and so are
   scored as method misses (class (b) or (c)), although they are unobservable as objects. On the 97 rings that do have such a
   piece, the shipped pipeline recovers 70.6 % of the pieces. So most of the headline 54 % loss
   is "the ring is not observable as a connected object in the window", not "the method missed
   an observable ring".
3. **The partition step's small gain depends on the convention.** Under `test_visible`, full beats
   proposed by only +0.0075 F1, and the step was never significant (`r9_significance`
   full_vs_b2, p_holm 0.49). Under `component_ge3` it reverses (−0.026 gine). The partition splits
   predictions along ring boundaries. That helps when the target is a multi-piece ring but costs
   precision when each piece is already its own target (gine full P 0.778 vs proposed 0.830). The
   claim that is robust across all three conventions is **expansion over B0**: +0.07 to +0.09 F1,
   with the same sign everywhere. The partition step should not be claimed beyond "neutral".
4. **C9 extends to a third convention with one qualification:** "every method ordering is
   preserved" holds for `full_membership` and for all pieces. It does not hold for the
   proposed/full pair when 2-account pieces are excluded.

### Caveats

- **Denominators differ between conventions.** `component_ge3` drops 77 rings outright, so its
  absolute recall is not comparable to `test_visible`'s. It answers "on the observable objects",
  and its numbers must never become a headline (same rule as `full_membership`).
- **The swap was not tested for significance.** The proposed/full intervals overlap almost
  entirely. The paired bootstrap from #2 could test it. The reading above rests on the sign
  flipping, not on a significant reversal.
- **Pieces come from truth edges.** A piece is defined by the ring's own in-window transactions,
  not by everything in the window. Two pieces connected only through non-ring accounts still
  count as separate, as in B13.

### Where it goes

A third row block next to `r14_scope_sensitivity` in C9, plus a qualification to C9's "preserves
every method ordering". F7 gets the observability split: 44 % of rings have no matchable piece,
and 17 rings scored as misses (class (b) or (c)) are unobservable as objects. FINDINGS should note that the partition
step is convention-dependent. No reported number changes.

---

## 5. Seed reallocation evaluated under `full`, not only B0

**Run 2026-11-11.** Script: `evaluation/realloc_full.py`. Tables:
`results/tables/v37_realloc_full.csv` (one row per seed and rule) and `.json` (mean ± SD, and
differences against the global quantile paired by seed).

### Question

Does spreading seeds stop hurting once expansion can re-attach the edges it drops?

### Why it was worth running

B14 concludes that seed allocation is not the binding constraint. But both `R11b_ensemble/` and
`R11c_local/` were evaluated at **B0 only**. B14's second mechanism, that one seed per account
scatters the budget and rings need ≥ 3 members to be matchable, is exactly the limitation
expansion exists to remove. Seeds are concentrated: 2.745 per touched ring, 21.4 % off-ring
(`r6_detector_swap.csv`).

### Method

At a forced k = 0.1 %, 5 detector seeds and the primary window, three seed rules are compared:

| rule | seed mask |
|---|---|
| `global` (shipped) | strict 0.1 % quantile of `gine_causal` `score_raw` |
| `ensemble` (11b) | strict 0.1 % quantile of `R11b_ensemble` scores: best rank over gine_causal and MEGA |
| `local` (11c) | strict 0.1 % quantile of `R11c_local` scores: account local maxima ranked above all other edges |

**Only the seed mask changes.** Everything downstream reads the **original** `gine_causal` scored
edges, embeddings and checkpoint:

- **Expansion:** the R3 `policy_proposed` at the shipped val-chosen (`delta_t_h`, `p_min`).
- **Partition:** R4 `average` at the shipped val-chosen cut, `min_size` 3.

This deliberately answers the proposal's risk. The 11b/11c *scores* are rank transforms
(11c is on [0, 1.5]), and feeding them to a policy trained on raw detector scores would shift its
features out of distribution. Here the policy sees exactly the inputs it was trained on, and
only *where* it starts differs. The L3 cells are the shipped ones, not re-chosen per rule.

The metrics are those of #1 (`window_budget.py`): rings touched (B14's definition), matched rings,
B0 and full ring-F1, class (b), added-member precision, and also off-ring seed share and seeds
per touched ring. B0 for each mask uses `cc_rings_from_mask` (the shipped components and size
filter).

- **Success:** 11c rings touched *or* matched ≥ shipped (129.6 / 80.2).
- **Failure:** still below, which would extend B14 to the full pipeline.

**Inputs:** `--exp-root ../RS-e2e/experiments`, which has the 11b/11c parquets (built from the
MEGA and gine scores) and the R1 checkpoints. The run takes about 15 minutes on CPU.

```
python evaluation/realloc_full.py --exp-root ../RS-e2e/experiments \
    --out results/tables/v37_realloc_full.csv
```

### Reproduction check, and a correction to B14

- **Rings touched reproduces B14 exactly:** global **129.6**, ensemble **133.6**, local **116.2**.
  The `global` row also reproduces #1's shipped row (full F1 0.5895, matched 80.2, class (b) 33.2).
- **B14's B0 ring-F1 figures are *as-run*, not forced-budget.** B14 reports B0 ring-F1 0.5213 /
  0.5317 / **0.4455** in the forced-budget sentence. Here, at forced k = 0.1 %, B0 F1 is 0.5213 /
  0.5146 / **0.5193**. The `b0/seed*/config.yaml` files explain the gap: 11c seeds 2 and 3
  val-chose **0.05 %** (F1 0.313 and 0.344) and 11b seed 4 chose 0.15 %. On every seed whose
  as-run k\* was 0.1 %, the as-run F1 equals the forced F1 here to four decimals. So at an equal
  budget, the local rule does **not** lower B0 ring-F1 (paired Δ −0.002 ± 0.003). The −13.4 rings
  touched stands, but the "0.5213 → 0.4455" drop belongs to the as-run comparison. B14's own
  footnote half-says this. The sentence should be corrected.

### Results: mean ± SD over 5 seeds, primary window, forced k = 0.1 %

| | global (shipped) | ensemble (11b) | local (11c) |
|---|---|---|---|
| seeds in window (of 864) | 463.0 ± 84.2 | 407.4 ± 30.6 | 513.4 ± 79.0 |
| off-ring share of in-window seeds | 0.214 | **0.109** | **0.314** |
| seeds per touched ring | 2.75 | 2.72 | 2.97 |
| **rings touched** (of 174) | **129.6 ± 4.8** | 133.6 ± 8.0 | **116.2 ± 3.7** |
| B0 ring-F1 | 0.521 ± 0.045 | 0.515 ± 0.032 | 0.519 ± 0.044 |
| B0 matched | 66.8 | 64.6 | 68.6 |
| **full ring-F1** | **0.590 ± 0.037** | **0.611 ± 0.014** | 0.575 ± 0.034 |
| **full matched** | **80.2 ± 5.9** | 82.8 ± 2.7 | **79.4 ± 5.2** |
| class (b), full | 33.2 ± 3.6 | 28.2 ± 1.9 | 31.2 ± 2.3 |
| added-member precision | 0.926 ± 0.015 | 0.942 ± 0.016 | 0.899 ± 0.038 |

Paired by detector seed (rule − global), mean ± SD [per seed]:

| | ensemble | local |
|---|---|---|
| rings touched | +4.0 ± 6.9 [+10, +9, −4, −3, +8] | **−13.4 ± 4.6** [−9, −21, −11, −13, −13] |
| full matched | +2.6 ± 6.1 [+5, −1, +3, −5, +11] | −0.8 ± 2.7 [+1, +1, +1, −5, −2] |
| full ring-F1 | +0.021 ± 0.038 [+.021, −.005, +.027, −.018, +.081] | −0.014 ± 0.014 [−.004, −.010, −.003, −.036, −.019] |
| class (b), full | −5.0 ± 5.0 | −2.0 ± 1.9 |
| added-member precision | +0.016 ± 0.019 | −0.027 ± 0.026 |

### Against the bar

| bar | local (11c) | result |
|---|---|---|
| rings touched ≥ 129.6 | 116.2 | ✗ |
| full matched ≥ 80.2 | 79.4 | ✗ (−0.8, inside seed spread) |

**Verdict: FAILURE.** Under the full pipeline, the local budget is still below the global quantile
on both counts. B14 extends to `full`.

### Reading

1. **Expansion repairs most of local's damage, but not all.** At B0, local loses 13.4 touched
   rings, yet *gains* +1.8 matched (it seeds more in-window edges: 513 vs 463). Under `full` the
   gap in matched rings is only −0.8 and ring-F1 −1.4 points. So expansion re-attaches much of
   what scattering drops. What it cannot recover is reach. A seed spent on an off-ring local
   maximum (off-ring share 21 % → 31 %) gives expansion nowhere to grow, and expanding from
   off-ring seeds lowers added-member precision (0.926 → 0.899).
2. **The ensemble benefits more under `full` than at B0.** At B0 it was −0.007 F1. Under `full` it
   is +0.021, with 5 fewer class (b) rings, higher added-member precision (0.942) and an off-ring
   seed share **halved** (0.214 → 0.109). The two-detector agreement concentrates seeds on true
   ring edges, and expansion turns that purity into rings. But +2.1 F1 ± 3.8 and +2.6 matched
   ± 6.1 are inside seed spread (2 of 5 seeds go the other way), so this is a direction, not a
   finding. A paired ring-level test (#2's `paired_unit_bootstrap`) would be the next step if it
   matters.
3. **B14's conclusion survives, sharpened.** The direction of reallocation matters:
   concentrating on agreed edges ≥ shipped ≥ spreading per account. But neither lifts the ceiling
   beyond seed noise under the full pipeline either. "The binding constraint is not how the seed
   budget is allocated" now holds for B0 *and* `full`.
4. **The off-ring seed share is the better predictor than touched-ring count.** Across the three
   rules, full ring-F1 tracks off-ring share (0.109 → 0.611, 0.214 → 0.590, 0.314 → 0.575) more
   tightly than rings touched. Under `full`, a seed's value is mostly whether expansion can grow
   from it.

### Caveats

- **The L3 cells were not re-chosen per rule.** The shipped cells were val-chosen for the global
  mask. Re-tuning `p_min` or the cut per rule on validation would be the stricter version (the
  proposal's "val-chosen L3 cells" could be read either way). Re-tuning could help local recover
  precision, but is unlikely to recover reach.
- **The ensemble mixes in MEGA's ranking for seed choice only.** Expansion and partition use
  gine's context, so this is "gine's pipeline with ensemble-chosen seeds", not a MEGA+gine system.
- **Five seeds only.** The ensemble's seed-4 drop (−0.018) coincides with its as-run k\* of 0.15 %
  on validation, where the transformed scores behave differently.

### Where it goes

- **B14:** a dated note saying the conclusion now covers `full`. The forced-budget B0 ring-F1
  should be corrected from 0.5213 / 0.5317 / 0.4455 to 0.5213 / 0.5146 / 0.5193, with 0.4455
  attributed to the as-run cells.
- **C7:** a pointer that the ensemble's +4 rings becomes +2.6 matched and +2.1 F1 under `full`,
  inside seed spread.
- No other reported number changes.

---

## 6. Drift monitor with a passing positive control (R12b)

### Registration (written 2026-11-12, before any R12b code was run)

**No number in this registration was computed before it was written.** The only R12 numbers seen
beforehand are those already published in `docs/R12.md`: the original and amended runs and their
diagnosis.

**Question.** Can any monitor detect a +3 SD step in hourly score statistics within test days 8–9?

**Why a new registration.** R12 stopped at its positive control, twice.

- **ADWIN's bound:** on 48 hourly points, ADWIN has a data-independent floor of ≥ 0.55 per cut,
  against hourly means of 0.001–0.003.
- **The p99 statistic:** the calibrated p99 is constant at 0.015064, so a "+3 SD" step on it is
  +0.
- **Status:** PR-43 is recorded as not met.

Both failures belong to the monitor and statistic chosen, not to the question. This registration
changes exactly those two things and keeps everything else of R12.

**Kept from R12, unchanged:**

- **Stream:** the 48 hourly steps of test days 8–9 (primary window), from the shipped detector
  seed 1 scored edges (`contract/out/scored_edges_gine_causal_1.parquet`).
- **Injection:** CYCLE truth transactions removed from day 8 by `r12.remove_day8_pattern`. Day 9
  is unchanged.
- **Control timing:** the synthetic step starts at step 37 of 48 (index 36, hour 12 of day 9).
- **Labelling:** drift is injected, not observed, and the control is synthetic. Every output says
  so.

**Statistics.** Two, each computed per hour and then standardised by the mean and SD (ddof 1) of
its 24 day-8 hourly values:

- **S1 = share of edges above the seed cutoff:** the fraction of the hour's edges with `score_raw`
  above seed 1's shipped pooled cutoff q (`seed_rule.q` in the scored-edges log).
- **S2 = raw-score p99:** the 99th percentile of `score_raw` over the hour's edges. It replaces
  the calibrated p99, which is flat.

**Monitors.** Both are applied separately to each standardised statistic, giving four arms. They
watch for an **upward** shift, the direction of the control, and start at **day 9, hour 0**
(index 24), with day 8 as the reference only.

- **CUSUM (one-sided upper):** C₀ = 0, Cₜ = max(0, Cₜ₋₁ + zₜ − k), alarm when Cₜ > h, with
  **k = 0.5, h = 4**. Under i.i.d. N(0, 1) this gives an in-control average run length of about
  168 h (one week) and about 2 h for a +3 SD shift (Siegmund's approximation). These values are
  the textbook choice and are not tuned.
- **Page–Hinkley (upper):** mₜ = Σ(zᵢ − δ), alarm when mₜ − minᵢ≤ₜ mᵢ > λ, with **δ = 0.5,
  λ = 4**. This is the same drift allowance and threshold as the CUSUM, as a cross-check. It is
  not a separate chance to succeed.

**Control ladder.** Starting at index 36, **+1, +3 and +5 SD** of the statistic's own day-8 hourly
SD are added to the real stream. The real stream with no step is the fourth replay.

**False-alarm bound.** An arm is *eligible* only if both checks below give zero alarms:

- **(i) In-sample day 8:** the same monitor run over day 8 (indices 0–23), standardised on day 8.
- **(ii) Pre-onset:** the real stream over day 9 before the onset (indices 24–35).

An alarm in either check disqualifies that arm for every rung. A false alarm cannot be redeemed
by a fast detection.

**Delay.** A detection's delay is the number of shifted hours the monitor has seen when it fires:
an alarm at index t gives a delay of t − 35 h, so an alarm at the onset hour itself is 1 h.

**Bars:**

- **Success:** at least one eligible arm detects the **+3 SD** rung with a delay of **≤ 6 h**
  (alarm at index ≤ 41).
- **Failure:** no eligible arm detects +3 SD within 6 h. Then the two-day window itself is too
  short, or the hourly statistics are too noisy, for this design to resolve the registered
  control.
- **Real stream:** reported descriptively (with the CYCLE return at day 9, hour 0). As in R12, an
  alarm there is not read as a CYCLE detection unless the control passes **and** the alarm falls
  after day 9, hour 0 with no pre-onset false alarm. Even then it is only "the monitor moved", not
  attributed to roughly 1 CYCLE transaction in 24,000 per hour.
- **+1 and +5 SD:** reported as a sensitivity ladder. They are not success criteria.

**Also reported:**

- the lag-1 autocorrelation of each statistic's 24 day-8 hourly values, because positive
  autocorrelation shortens the true in-control run length below the i.i.d. 168 h;
- the hourly series and every alarm.

### Result (run 2026-11-12)

**Drift was injected, not observed; the control is synthetic.** Script:
`platform/experiments/r12b_cusum.py`. Output: `results/platform/r12b/summary.json`, holding the
hourly series, every alarm, and the ladder per arm. It runs in seconds:
`cd platform; python -m experiments.r12b_cusum`.

**Implementation note.** `r12_injected_shift` imports `river`, which the project venv lacks.
R12b does not use ADWIN, so `remove_day8_pattern` is copied verbatim into the script. The script
asserts that it removes exactly the **31** CYCLE transactions R12 recorded, which it does. The
stream has 7,692–41,279 edges per hour (median 24,349). The seed cutoff q is 0.92952.

#### Day-8 reference and day-9 behaviour

| statistic | day-8 mean | day-8 SD | lag-1 autocorr (day 8) | day 9 before onset, mean z | day 9 after onset (real), mean z |
|---|---|---|---|---|---|
| S1 share above cutoff | 3.02 × 10⁻⁴ | 1.82 × 10⁻⁴ | **0.60** | **+3.18** | +4.56 |
| S2 raw p99 | 0.07960 | **0** | undefined | undefined | undefined |

#### Arms

| statistic | monitor | false alarms, day 8 (in-sample) | false alarms, day 9 before onset | eligible | +1 / +3 / +5 SD delay | passes |
|---|---|---|---|---|---|---|
| S1 | CUSUM | index 17 | 26, 29, 32, 34, 35 | **no** | 1 h / 1 h / 1 h | no |
| S1 | Page–Hinkley | index 17 | 26, 29, 32, 34, 35 | **no** | 1 h / 1 h / 1 h | no |
| S2 | CUSUM | — (z undefined) | 34 | **no** | (degenerate) | no |
| S2 | Page–Hinkley | — (z undefined) | — | yes, vacuously | not detected | no |

**Verdict: FAILURE, as registered.** No eligible arm detects the +3 SD rung.

- **S1:** detects every rung within 1 h, but both of its arms are disqualified by the
  false-alarm bound.
- **S2:** both arms are degenerate. Its day-8 SD is 0, so the standardised stream is undefined.
  S2's Page–Hinkley arm is "eligible" only because NaN comparisons never fire, and it detects
  nothing.

#### Why: two mechanisms, both found in the data, neither a window-length problem

1. **The raw p99 sits on a tie plateau, exactly as the calibrated p99 did.** **2.9 % of day 8's
   654,467 raw scores share one identical value, 0.079603.** The plateau spans the 99th *and* the
   99.5th percentile, so the hourly p99 is that constant in all 24 day-8 hours. This is the same
   failure as R12's calibrated p99 (0.015064). It is a property of the detector's output (a large
   block of tied scores), not of calibration. **No percentile statistic in the 97–99.5 range can
   move on this detector.** The registration did not anticipate this. It is now a known
   constraint for any future monitor (and is related to the tie handling in
   `cc.threshold_for_pct`).
2. **Day 9 is a different regime from day 8, by more than the control.** The share of edges above
   the seed cutoff is **0.031 % on day 8 and 0.096 % on day 9**, 3.1× higher. Day 9 also has a
   third of day 8's volume (208,325 vs 654,467 edges). Standardised on day 8, day 9 sits at
   **+3.2 SD before any step is added**, which is larger than the +3 SD control. On top of that,
   S1 has a strong diurnal cycle on day 8 (lag-1 autocorrelation 0.60, with a midday peak of
   7.5 × 10⁻⁴ against overnight 0.8 × 10⁻⁴), which produces the in-sample alarm at hour 17. The
   CUSUM at h = 4 therefore fires on the real day-9 stream from its third hour. The "detections" of
   every rung within 1 h are this pre-existing shift, not the control.

**The real stream** alarms at indices 26, 29, 32, 34, 35 (all before the control's onset), and
36–42. Under the registered reading none of these is a CYCLE detection, because the arm has
pre-onset false alarms. They are the day-8 → day-9 regime change in the ordinary score stream.

### Reading

1. **R12's question can now be answered in a sentence.** On this dataset, an hourly
   score-distribution monitor referenced on test day 8 cannot pass a positive control on day 9,
   and the reason is not the monitor.
   - **S1:** day 9 is already ≥ 3 SD from day 8 (3.1× the above-cutoff share), so any monitor
     sensitive enough to see +3 SD alarms on the real data first.
   - **Percentile statistics:** the detector's tied-score plateau makes them constant.
   ADWIN's 0.55 floor (R12) was a third, independent obstacle. Replacing it with CUSUM removed that
   obstacle and exposed the other two.
2. **The proposal's failure branch, "the two-day window itself is too short", is only half
   right.** The window is too short to estimate a diurnal baseline from a single reference day.
   But more data from the same days would not help: the day-8 / day-9 difference is a real
   level shift (AMLworld's test days differ in volume and in score composition, see
   `TEST_TAIL.md` for the related tail effect). A valid design needs a reference that contains
   the regime it monitors, for example several days with a per-hour-of-day baseline. AMLworld's
   two-day primary window cannot provide that.
3. **PR-43 stays "not met"**, now with a measured reason that survives a change of monitor. R12
   should be closed as "not testable on HI-Small's primary window", not left at "monitor broken".
   F8 should record the two constraints: the plateau and the inter-day level shift.

### Caveats

- **The degenerate S2 should arguably have voided the registration.** It was not anticipated and
  the registration did not say what to do with a zero-SD statistic, so it is reported as written:
  S2's arms fail. Swapping in a different percentile after seeing this would be a new
  registration.
- **One detector seed (seed 1), as in R12.** The plateau value, the day-9 shift and the
  cutoff-share ratio come from seed 1. Other seeds were not checked.
- **The day-9 shift is a property of the scored stream.** Whether it reflects AMLworld's
  generator (pattern density by day) or the detector's behaviour on day 9 was not separated. The
  above-cutoff share rising 3× suggests more high-scoring (likely illicit) activity on day 9, but
  labels were not used here.

### Where it goes

- **`R12.md`:** a dated "R12b" section with this registration and result. R12 is closed as not
  testable on this window, with the two mechanisms.
- **F8:** updated with the constraints, the score plateau and the day-8/day-9 level shift.
- **PR-43:** stays not met, with the reason restated.
- No reported number changes.

---

## 8. Ring-folded cross-scores (B17)

### Registration (written 2026-11-12, before any ring-folded model was trained)

**Why a new registration.** B17 registered this on 2026-10-22 with a 2026-10-28 deadline. It was
closed as "Not fixed", with the feature-group ablation bound ≤ 0.008 on the primary window. The
deadline lapsed, so this is a new registration. **It does not reopen the shipped rings.** The v2
rings stay final whatever this shows. A failure here produces a dated B17 correction and a caveat
on the shipped rings, not a re-ship.

**Question.** Does an expansion policy trained on cross-scores folded by **ring** produce
different rings from the shipped policy, which was trained on cross-scores folded by **day**?

**Fold rule (fixed now).**
- Every edge of a train ring (split parquet `ring_id > 0`, which equals `test_visible` on the train
  window, amendment c) goes to the shipped day fold that holds the plurality of that ring's edges.
  Ties go to the lower fold index.
- Every other edge keeps its shipped day fold: {0}, {1}, {2, 3}, {4}, {5}.
- Fold k's held-out set is `edge_fold == k`. As shipped, it is removed from fold k's training graph
  and labels, and fold k's model scores it with the full train split as causal context.
- So no fold model sees any edge (label or graph) of a ring it scores. The plurality rule moves the
  fewest edges, so the folds stay as close to the shipped ones as possible.
- Assertions: run_fold asserts no held-out edge is a supervised example. `assemble` and
  `make_training_set.py` assert that every ring's edges are scored by its owner fold
  (`ring_folds.parquet`).

**Code.** `ringshield/expand/cross_score.py --ring-folds`. With the flag off, behaviour is
unchanged (the default path is `edge_fold` = day fold, identical to the old `isin(day, held)`). The
re-check in `make_training_set.py` branches on `fold_unit`. Dry run (1 % sample, 1 epoch,
2026-11-12): all 5 folds ran, 0 violations.

**Everything else is shipped, not re-chosen.**
- Fold models: R1 config, seed 1, 30 epochs per fold, checkpoint by val F1.
- Training set: `make_training_set.py`, Δt 72 h, 2 hops, k\* 0.1 % within fold, day-0 candidate
  rows dropped (amendment b), embeddings from the candidate's fold model.
- Policy: `policy.py --seed 1`, same hyperparameters and grouped CV.
- Test runs: `run_expand.py` for detector seeds 1–5 with the **shipped cell fixed** (Δt 24 h,
  p_min 0.7 on every seed, `runs/proposed/seed*/config.yaml`), passed as one-point grids. The
  B0 cell is unchanged.
- Day 0 is handled exactly as shipped: in the graph and in the labels of folds 1–4, its candidate
  rows dropped from the training set (amendment b).

**Outcome.** Primary-window ring-F1 of `proposed`, paired by detector seed, against the shipped
`r3_expansion.csv` row (mean 0.58192).
- **Success:** |mean Δ ring-F1| ≤ 0.008. The B17 bound is confirmed as a measurement.
- **Failure:** |mean Δ| > 0.008. B17 gets a dated correction, and the shipped rings carry the
  caveat.
- Reported beside the verdict, not deciding it:
  - per-seed Δ, and a paired ring-unit bootstrap CI (`paired_unit_bootstrap`);
  - ring precision and recall;
  - the share of shipped rings reproduced exactly (same account set), and the share matched at
    Jaccard ≥ 0.5;
  - the fold models' held-out AP on ring edges against the shipped day-fold models.

**Risk, stated before the result.** A ring's minority-day edges leave their day's fold, so fold k
loses some graph context unevenly. The fold record (`ring_folds` in each `fold.json`) reports how
many rings span day folds and how many edges moved.

---

## 9. Day-0 label exclusion on HI-Small (C10)

### Registration (written 2026-11-12, before training)

**Question.** Does removing day 0 from the supervised edges, while keeping it in the graph, raise
the HI-Small detector's validation AP, as it did on HI-Medium (+46 %, C10)?

**Arm.** The shipped R1 command (`REPRODUCE.md` §2), unchanged except for
`--train-label-days 1 5`: labels on train days 1–5, day 0 kept in the graph. Output goes to
`experiments/R1_gine_causal_c10/`. Seed 1 first.

**Gate (computed before training from the shipped `scores_val_seed*.parquet`).** R1 val AP per
seed is 0.5726 / 0.5183 / 0.5902 / 0.5841 / 0.5017, SD 0.0405. **Seeds 2–5 run only if seed 1's
best-checkpoint val AP > 0.5726 + 0.0405 = 0.6131.**

**Shipping.** The arm ships only under the `configs/detector_choice.yaml` rule (validation
ring-F1). R1 stays as reported regardless of the outcome. C6 predicts no ring gain from a better
edge detector, so the edge-level gate is the result that matters here.

### Result (2026-11-12): gate fails, seeds 2–5 not run

| | val AP |
|---|---|
| Seed 1, C10 arm, selected checkpoint (epoch 8 of 28, chosen by val F1 0.6092) | **0.5455** |
| Seed 1, C10 arm, best epoch by any measure (epoch 22) | 0.5633 |
| Seed 1, R1 shipped | 0.5726 |
| Gate | > 0.6131 |

Early stopping hit at epoch 28. The selected checkpoint scores **0.027 below** shipped R1 seed 1,
not above it. Even the best epoch, which the selection rule did not pick, is below R1 seed 1 and
1.2 SD short of the gate. The checkpoint's own evaluation reports AP 0.5170 at threshold 0.52.

**Verdict.** The HI-Medium C10 effect does not transfer to HI-Small. Day 0 is not the noise source
here. Seeds 2–5 were not run, as registered. Nothing ships, and R1 stays as reported. Artifacts are
in `experiments/R1_gine_causal_c10/` (`training_log_seed1.csv`, `train_seed1.log`).

---

## 10. A ring-identity head on frozen embeddings

### Registration (written 2026-11-12, before any head was trained)

**Question.** Can a contrastive head trained with ring labels make edges of the same ring separable
where the shipped embedding is not? (V3.0 (b): AUC 0.577 / 0.524. V3.0b: AUC-PR 1.85× base, 0 of 11
oracle rings.)

**Training data.** The shipped R1 `gine_causal` 198-dim edge embeddings, **validation split**
(days 6–7: 710 ring edges in 157 truth rings), one head per detector seed on that seed's own
embeddings. The head therefore works in the same embedding space it is evaluated in. Fold-model
embeddings come from different networks and a head on raw coordinates would not transfer. Train
rings are not used, because R1 train embeddings were never exported and the GPU is busy with #9.
Nothing is chosen on test.

**Head.** Frozen input, MLP 198 → 128 → 64 with ReLU, L2-normalised output. Supervised
contrastive loss (Khosla et al. 2020), temperature 0.1, with the ring as the class. The training
set adds non-ring val edges as singleton classes: 20× the ring-edge count, drawn uniformly. That
way the head learns "same ring" against ordinary traffic too. Adam lr 1e-3, weight decay 1e-4,
batch 512, 200 epochs. **Early stopping on a 20 % ring-grouped hold-out of the val rings** (val
loss, patience 20). Fixed RNG seed 20261112. The hyperparameters are standard defaults and are not
tuned.

**Evaluation, Stage 1, reused unchanged from V3.0 (b).** `evaluation/v3_diagnostics.part_b` on the
test primary window, 5 seeds, with `load_embeddings` replaced by "R1 embedding → this seed's head".
The pairs, pools (class (b), under-covered), matched null and AUC code are all unchanged.
**Bars (from `V3_DIAGNOSTICS.md` (b)):**

- same-ring cross-component vs different-ring: **AUC ≥ 0.75**;
- same-ring cross-component vs the score+time-matched null: **AUC ≥ 0.70**.

They are read on the pooled (5-seed mean) AUC for each pool. **Stage 1 passes if both bars hold
for class (b) or for under-covered.** The raw-embedding AUCs are recomputed in the same run as a
reference.

**Stage 2 (V3.0b bars: AUC-PR ≥ 5× base and ≥ 5 oracle rings at ≥ 80 % link precision on the
training window)** runs **only if Stage 1 passes**. If Stage 1 fails, the representation is not
separable, and a linker built on it cannot clear Stage 2's stricter bars.

**Expectation, stated before running:** a negative. The amount-ratio signal already points the
wrong way (0.405), and the generator may not encode ring identity in anything the detector sees.

### Result (run 2026-11-12)

Script: `evaluation/ring_identity_head.py --emb-root ../RS-e2e/experiments/R1_gine_causal`.
Tables: `results/tables/v38_ring_identity_head.csv` (per seed × pool × population) and `.json`.
RS-e2e holds the R1 val and test embeddings; RS-react has only seed 1's. The run took about 10
minutes on CPU.

**Training.** On every seed the head trained and stopped early (33–55 epochs). The hold-out
SupCon loss fell 0.18–0.52 nats per seed, for example 4.60 → 4.09 on seed 1, against a uniform
floor near ln(512) ≈ 6.2. So the head learned *something* on validation rings, which made the
test worth reading.

**Stage 1, test primary window, pooled over 5 seeds (same-ring cross-component pairs):**

| pool | embedding | AUC vs different ring (bar ≥ 0.75) | AUC vs matched null (bar ≥ 0.70) | pairs per seed |
|---|---|---|---|---|
| class (b) | raw (reference) | 0.552 | 0.613 | 146.8 |
| class (b) | **head** | **0.618** | **0.681** | 146.8 |
| under-covered | raw (reference) | 0.526 | 0.614 | 180.8 |
| under-covered | **head** | **0.605** | **0.651** | 180.8 |

**Reproduction note.** The raw reference is close to, but not identical with, V3.0's published
0.577 (class b) and 0.524 (under-covered). Pair sampling uses the same RNG seed, but V3.0's `main`
consumes RNG draws in part (a) first, so different pairs are drawn here. Both runs here use
identical pairs, so the raw → head comparison is paired.

**Verdict: Stage 1 FAILS on both pools.** The head lifts AUC vs different ring by +0.07 to +0.08
and vs the matched null by +0.04 to +0.07, but stays far below both bars (0.62 vs 0.75; 0.68 vs
0.70). **Stage 2 is not run**, as registered.

### Reading

1. **A representation trained for ring identity does not make split rings linkable.** With
   ring labels, a head on the frozen detector embedding moves the class (b) AUC from 0.55 to 0.62.
   The registration expected a negative, and the gain is too small to clear either bar.
2. **This closes the last open row of V3.0's ceiling table** ("a representation trained for ring
   identity"), at least for a frozen-input head. Fragments of one ring are not separable from other
   rings in anything the detector's embedding encodes, even when supervised to be. Combined with
   V3.0b (observable signals: AUC-PR 1.85× base, 0 of 11 oracle rings), the ~7.8 class (b) rings
   per seed whose accounts are already selected stay unrecoverable by grouping.
3. **What remains untested** is end-to-end fine-tuning of the detector with a ring-identity loss
   (≥ 3.14 GPU-h per seed). The proposal treats that as a separate decision. A +0.07 AUC from a
   frozen head does not make a strong case for it.

### Caveats

- **Trained on validation rings (157), not train rings.** R1 train embeddings were never exported.
  A larger training set could do better, but the hold-out loss had already flattened by epoch
  ~20–35.
- **Hyperparameters were registered defaults and not tuned.** A tuned head is a different
  experiment with its own garden of choices.
- **Few distinct rings.** The cross-component pairs come from 16–20 class (b) rings and 3–6
  under-covered rings per seed, so the under-covered AUC rests on very few rings.

### Where it goes

V3_DIAGNOSTICS' "what is not done" list and the ceiling table: the ring-identity representation
row is closed as "frozen head, not separable (AUC 0.62 / 0.68 vs bars 0.75 / 0.70)". FINDINGS F7
(observability) gains it as further support. No reported number changes.

---

## 11. L4: a fidelity measure that can fail, and a ranking that surfaces quiet members

### Registration (written 2026-11-12, before any number below was computed)

**Question.** On rings that mix true and false transactions, does any ranking beat score-only?
And can leave-one-out lift recovered quiet members above random?

**Background.** 343 of 395 matched ring-instances saturate fidelity, because every ordering scores
1. Expanded recall@5 is 0.724 against random 0.873. The tuned mix (α 0.6 score, β 0 leave-one-out,
γ 0.4 flow) gave leave-one-out weight 0 (`xai_chapter.md` §7.2, §8.2).

**Data.** Shipped gine_causal rings, 5 seeds, policy `converted`, matching as in L4 (Jaccard 0.5,
`test_visible`). Leave-one-out uses non-degraded reruns, exactly as `explainability.edge_weights`
computes them.

**(i) A fidelity that can fail.** fidelity@5 restricted to **mixed** matched ring-instances: those
whose in-window evidence edges contain both true and false transactions
(0 < |evidence ∩ T| < |evidence|). Saturated rings are excluded from this metric.

**(ii) Retuned mix.** The same 66-triple (α, β, γ) grid at step 0.1, chosen on **validation only**
(val rings, val window). **Objective: expanded recall@5**, the mean over val matched rings with
≥ 1 true expanded edge. Ties go first to the higher val mixed-ring fidelity@5, then to the
triple closest to the shipped (0.6, 0, 0.4).

**(iii) Abstention on `topology_prob`.** The narrative's shape sentence is stated only when the
ring's `topology_prob ≥ t`. **t is chosen on validation** as the smallest value on the grid
{0.30, 0.35, …, 0.95} at which the stated-type accuracy on val matched rings is ≥ 0.80. If no t
reaches 0.80, the t with the highest accuracy at ≥ 20 % coverage is used. Reported on test:
accuracy on stated rings, coverage, and accuracy without abstention.

**Bars (test, primary window, statistics over truth rings with seeds averaged, 1,000 bootstrap
resamples):**

- **Success:** expanded recall@5 of the retuned mix **≥ random** (point estimate), **and**
  mixed-ring fidelity@5 of the retuned mix **not lower than** the shipped mix. "Not lower" means
  the paired bootstrap CI of (retuned − shipped) has its upper bound ≥ 0.
- **Failure:** expanded recall@5 still below random.

The abstention result is reported beside the bars and does not enter them.

**Expected power problem, stated up front:** only about 52 mixed ring-instances across 5 seeds.

### Result (run 2026-11-12)

Script: `explainability/mixed_ring_eval.py`. Output: `results/xai/mixed_ring_eval.json` and
`mixed_ring_eval_test_rows.csv`.

**Inputs.** The L4 week-3 explanation parquets were never kept, so leave-one-out was recomputed
for every matched ring (val and test), exactly as `edge_weights.w_loo` does it.

- **Test rings and scored edges:** `RS-ccy-valrings/contract/out` (schema v2; seed 1 is
  byte-identical to the shipped `9d1e0b9e…` rings). RS-e2e's copies are schema v1.
- **Val rings:** `RS-ccy-valrings/experiments_valrings`.
- **Embeddings:** `RS-e2e`.

The run took about 1 h on CPU.

**Reproduction.** On test: 401 matched ring-instances, **343 saturating** and **52 mixed** (the
chapter: 343 of 395 with a true ranked transaction; 52 mixed). Expanded recall@5 is 0.724 for
the shipped mix and 0.729 for score-only, both matching the chapter. Random comes out at 0.870
against the published 0.873 (different per-ring shuffle salt).

**Validation choice.** Val has 431 matched rings, 89 mixed and 111 with true expanded edges. The
expanded-recall objective chooses **(α, β, γ) = (0, 0, 1): flow only**, with val expanded recall@5
**0.876** against 0.670 for the shipped mix. Every top-5 triple has α = 0, and leave-one-out gets
at most 0.4. The cost was already visible on validation: mixed-ring fidelity@5 falls from 0.799
(shipped) to 0.698.

**Test, primary window (per truth ring, seeds averaged, 95 % bootstrap CI):**

| ranking | expanded recall@5 (159 rings) | mixed-ring fidelity@5 (52 instances) |
|---|---|---|
| retuned (0, 0, 1) | **0.875** [0.804, 0.936] | 0.719 [0.594, 0.837] |
| shipped (0.6, 0, 0.4) | 0.724 [0.616, 0.825] | 0.840 [0.743, 0.922] |
| score only | 0.729 [0.622, 0.830] | **0.898** [0.824, 0.960] |
| random | 0.870 [0.820, 0.918] | 0.764 [0.672, 0.850] |

Paired differences:

| comparison | Δ | 95 % CI |
|---|---|---|
| expanded recall@5: retuned − random | +0.004 | [−0.040, +0.047] |
| mixed fidelity@5: retuned − shipped | **−0.122** | **[−0.241, −0.019]** |
| mixed fidelity@5: score only − shipped | **+0.058** | **[+0.010, +0.133]** |

**Verdict: FAILURE.**

- **First bar met:** expanded recall@5 reaches random (0.875 vs 0.870 by point estimate).
- **Second bar fails:** the retuned mix is **significantly worse** than the shipped one on mixed
  rings, and its whole CI is below 0.

**Abstention.** The registered rule takes the smallest t whose val accuracy is ≥ 0.80. That
picked **t = 0.90**, at only 2.6 % val coverage, because accuracy is 0.45–0.66 at every lower t.
On test, the stated type is right in **36 of 36** stated rings (accuracy 1.0, coverage 9.0 %),
against **0.599** with no abstention.

### Reading

1. **No single ranking does both jobs, and the two jobs pull in opposite directions.**
   - *What helps quiet members:* ranking by money flow lifts them to random level (+0.15 over the
     shipped mix), because quiet members carry the ring's money but have low scores by
     construction.
   - *What wins on mixed rings:* separating true from false transactions is best done by the
     detector score alone (0.898), which significantly beats the shipped mix (+0.058).
   So the shipped mix is a compromise that is second-best at both. The finding is that **the two
   L4 questions need two rankings**, not one tuned mix.
2. **Leave-one-out still earns no weight.** It gets at most 0.4 in the top triples and 0 in the
   chosen one. Structural importance does not separate quiet members better than flow, which
   closes §8.2's "leave-one-out exists but received no weight" as a measured negative, not a tuning
   accident.
3. **The fidelity that can fail does fail, informatively.** On the 52 mixed instances, score-only
   is significantly better than the shipped mix. That is a positive result for score ranking and
   a negative one for mixing. The chapter's "indistinguishable from score-only" came from the 343
   saturated rings.
4. **Abstention works, but at very low coverage.** Stating the shape only when
   `topology_prob ≥ 0.9` makes every stated shape right on test, but covers 9 % of rings. Most
   rings get no shape sentence at that bar. A lower bar does not help: val accuracy stays at
   0.45–0.66 from t = 0.30 to 0.85.

### Caveats

- **Power:** 52 mixed instances (about 40 truth rings). The CIs are wide, but the two key paired
  intervals exclude 0.
- **Very small abstention sample:** the threshold is chosen on 11 val rings at t = 0.9, and its
  test accuracy rests on 36 rings.
- **The retuned mix was chosen on one objective by registration.** A two-objective choice (for
  example, maximise expanded recall subject to mixed fidelity ≥ shipped) was not registered and
  was not run.

### Where it goes

The XAI chapter §7.2 and §8.2. The negative fidelity result is restated as "score-only is
significantly better on mixed rings; flow-only reaches random on quiet members; one mix cannot do
both". §8.2's leave-one-out line becomes measured. Abstention at 0.9 goes in as an option at
9 % coverage. No shipped L4 output changes.

---

## 7. Close out the HI-Medium pre-registration

### Execution note (written 2026-11-12, before any close-out run)

Everything is run as `docs/V3_HIMEDIUM_PREREG.md` registers it: P1–P4, Amendments 13 (five
2-day blocks) and 14 (per-day budget beside the global cut), and the val-chosen configuration of
`v33_a12_val_chosen.json`:

- **Expansion:** policy variant `no_detector`, `p_min` 0.9, Δt 48 h.
- **Seeds and partition:** k\* 0.1 %, `min_size` 3, `average` cut 0.3.
- **Detector:** C1′ seeds 1–3.

Nothing is re-chosen on test.

**Two execution details the registration does not fix, decided now:**

1. **B1b on HI-Medium has no recorded cell.** Following the registration's own rule ("everything
   is re-chosen on HI-Medium validation"), B1b's Δt is chosen **per seed on HI-Medium validation**
   from the registered grid {24, 48, 72} h. The highest val ring-F1 wins; ties go to the smaller
   Δt.
2. **Blocks are run "exactly as validation is run".** Each block's graph context is the block's
   own edges, and k\* is taken within the block. The 10-day primary run uses the whole test split
   as context, with the registered global quantile over the split.

**Detector gate (Amendment 4).** C1′ fails the 0.45 adequacy gate (mean val AP 0.4049 over three
seeds), so **P1 is computed but not interpreted as a containment test**, as registered. That
caveat is reported beside every verdict. P4's mandatory caveat (synthetic seeds 0.93 precise vs
real 0.29) is reported beside every P4 number.

Script: `evaluation/hm_closeout.py`, with the rings written per window, rule, method and seed
under `experiments_hi_medium/closeout/`. A report script computes P1–P3 from those rings. P4
uses `evaluation/p4_arms.py`.

---

## 14. External analyst study for L4 (materials drafted, not run)

**2026-11-12.** This study needs outside reviewers, so only its materials can be prepared here.
They are in `review/`:
- `analysis_plan.md`: becomes the registration once committed, before any reviewer sees a case;
- `protocol.md`: roles, recruiting, materials, pilot, session script, data handling;
- `reviewer_instructions.md`;
- `answer_sheet_template.csv`.

Design in one paragraph:
- Within-subject crossover, narrative + evidence (N) against evidence only (E).
- 40 cases from seed-1 `full` rings on the primary window: 28 matched true rings, stratified by
  pattern, and 12 rings matching no truth ring. The internal review showed only true rings, so
  "enough to investigate" was 100 % and could not measure accuracy.
- At least 3 outside reviewers, target 6, in two counterbalanced groups. Ground truth is hidden
  from reviewers and the facilitator.
- Verdicts go through the dashboard form with `simulated = false`.
- Primary endpoints: decision accuracy and log time, N − E, Holm-corrected.
- The precision of about ±0.10 in accuracy is stated up front.

**Blocking before the first session:**
- people: reviewers, and an ethics check with the institution;
- two code items: a `case_opened` audit event for timing, and an N/E rendering in a study tenant
  with a leak test;
- `sample_external.py` and `aggregate_external.py`, still to write.

Until the study runs, L4 stays "a delivered capability, not a validated explanation".
