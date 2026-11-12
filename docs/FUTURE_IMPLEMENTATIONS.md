# FUTURE IMPLEMENTATIONS — what to build next, and what each one is worth

*Planning document. Nothing here is a result: every number quoted is an existing row of
`docs/FINDINGS.md` and is cited by its id. Each item states the evidence that motivates it, the
cheapest test that could kill it, and an upper bound on what it can buy, so effort goes where the
measured headroom is.*

The rules that apply to everything below are the project's existing ones: every threshold,
operating point and choice is made on **validation**; a hypothesis is written down before its run;
negative outcomes are recorded as claims in `FINDINGS.md`, not dropped.

| # | Item | Targets | Upper bound on the gain | Cost | Status |
|---|---|---|---|---|---|
| **F1** | Similarity-based bridging of disconnected ring parts | under-covered rings, STACK | ≤ 6.8 rings/seed (≈ 3.9 recall points) | diagnostic ≈ 1 day; build ≈ 1 week | **proposed** |
| F2 | Larger seed budget (0.2 %) | untouched rings | union bound 150.8 / 174 rings touched | ≈ 1 day of runs | proposed |
| F3 | Scoped policy relaxation for pass-through accounts | GATHER-SCATTER declines | ≤ 1.6 rings/seed (≈ 0.9 recall points) | ≈ 1 day | proposed |
| F4 | Detector-specific expansion policy; MEGA-GenAgg as a detector | detector swap | small (C6: the budget binds) | ≈ 1 day + ≈ 18 h per detector | proposed |
| F5 | Validation-ring bootstrap for the detector choice | `configs/detector_choice.yaml` | none (a missing interval) | ≈ 1–2 h | open Step 9 item 1 |
| F6 | 30-ring explanation review with Fleiss' κ | L4 claims | — | analyst time | done (internal; `explainability/report/xai_chapter.md` §7.2.4) |
| F7 | Larger AMLworld releases and real data | external validity | — | data access | open |
| F8 | A drift monitor that can fire | L6 drift, R12 | — (the current monitor cannot detect a +3 SD step) | ≈ 1 day + re-register R12 | proposed (R12 stopped, 2026-10-24) |

---

## F1. Linking disconnected ring parts through signals other than transaction paths

### The problem

Seed-adjacent expansion grows a ring by walking **transactions** outward from its seeds. For long
patterns, the transactions that fall inside the evaluation window can form two or more pieces with
no path between them:

```
Full STACK ring (over many days):     A → B → C → D → E → F → G
                                                   ↑
                                 only some of these transfers fall in days 8–9
What the window shows:                A → B → C        E → F → G
                                      (piece 1)        (piece 2)
                                       seeds here       no in-window path from piece 1
```

The pipeline recovers piece 1 cleanly and never sees piece 2. The evidence that this, and not the
policy, is the limit:

| Evidence | Number | Source |
|---|---|---|
| Under-covered predictions are pure but small | purity 1.000 (34/34), median coverage 0.176 (3 of 14 members) | B12 |
| Missing member edges with no in-window path to the fragment | **176 / 216 (81.5 %)**; STACK **140 / 140** | B13 |
| Missing edges never generated as candidates | 85.6 % | B13 |
| Widening to the ten-day window | STACK still 100 % disconnected | B13 |
| Walking the full 18-day history under the expansion's rules | **0 / 140** STACK edges reached (null 0 / 216) | B16 |
| STACK + BIPARTITE share of untouched rings | 52 %, over-represented 2.2× / 2.7× | `CLASS_B_COMPOSITION.md` |

No policy that walks transactions can fix this, because the edge it would need does not exist in
the window or in the history.

### The idea

Add a second, non-transaction graph in which two accounts are linked because they **look like
parts of the same scheme**, and let expansion propose candidates from both graphs. Candidate
signals, in the order to try them:

| Signal | Definition (per account pair, fragment account vs candidate) | Why it might separate rings on AMLworld |
|---|---|---|
| **Amount continuity** | distance between the amount distributions each side sends / receives, after FX conversion (`fx_rates.json`) | layered patterns pass similar sums down the chain, minus small fees |
| **Shared counterparties, any time** | Jaccard of the two accounts' counterparty sets over train + val + test, no Δt limit | schemes reuse sources and cash-out accounts across days |
| **Timing rhythm** | similarity of hour-of-day / inter-arrival histograms | generated attempts run on similar schedules |
| **Payment format** | share of each side's volume per format | ACH carries 83.2 % of laundering at 7.43× the base rate (payment-format report) |
| **Bank / currency signature** | overlap of bank-pair and currency-pair sets | 98.9 % of rings are cross-bank (`ring_scope.json`) |

This is a genuinely different source of evidence from what B16 tested: B16 followed transaction
paths (val-chosen Δt per hop, 2–3 hops); these signals need no path at all.

### Step 1 — the diagnostic (do this before building anything)

`evaluation/bridge_signals.py` (new), no training, no parameter chosen:

1. For every under-covered instance in the shipped `full` runs (5 seeds, primary window), take the
   recovered fragment's accounts and the truth members it misses (`evaluation/under_covered.py`
   already produces both).
2. For each signal, compute the similarity between fragment accounts and **missing members**
   (positives).
3. Compute the same against a **control**: non-ring accounts matched on degree and activity days,
   10 per positive.
4. Report per signal and per pattern: AUC with a bootstrap CI over rings, and the rank of the
   first true missing member among all accounts active in the window.

**Pre-registered decision rule** (write it into this file before the run):

- Any signal with AUC ≥ 0.80 on STACK, CI excluding 0.70 → go to Step 2 with that signal.
- Every signal below 0.70 → stop; record "non-transaction similarity does not identify the
  disconnected part" as a new `FINDINGS.md` B-row. That negative strengthens the ceiling argument
  (B13 / B16) and closes the last untested lever on this class.

### Step 2 — the build (only if Step 1 passes)

- **Candidate generator.** `ringshield/expand/bridge.py`: for each predicted ring, the top-*m*
  accounts by the chosen signal(s) among accounts active in the window, *m* chosen on validation.
  Their in-window edges join the existing `candidates()` output, tagged `source = bridge`.
- **Policy.** Retrain the LightGBM policy on cross-scored train data (`cross_score.py`, unchanged),
  with the bridge signals as a ninth feature group and `source` as a feature, so the policy learns
  how far to trust a bridge candidate.
- **Partition.** No change in code; the affinity model is re-fit with the bridge signals as pair
  features so it can cut a false bridge back out.
- **Contract.** `rings` gains nothing new; bridged members are ordinary members. `rerun_ring`
  must accept the bridge graph as an input or it will not reproduce the aggregator.

### What counts as success, and the bounds

| Quantity | Current | Success | Upper bound |
|---|---|---|---|
| Under-covered rings per seed | 6.8 | ≤ 4.0 | 0 |
| Ring recall, primary | 0.461 [0.393, 0.529] | +0.02 or more | ≈ +0.039 (6.8 / 174) |
| Ring precision, primary | 0.818 | ≥ 0.78 | — |
| Added-member precision | 0.926 | ≥ 0.85 (the bound already used in B15) | — |

### Risks

- **False merges.** Innocent accounts also use ACH, move similar amounts and share busy
  counterparties. B15 shows what a blunt widening costs: dropping the policy floor from 0.7 to 0.3
  buys +1 ring per seed and cuts ring precision 0.653 → 0.509. Bridge candidates must be ranked,
  not admitted.
- **Scope interaction (C9).** Under `test_visible`, a bridged account counts only if it has an
  in-window transaction. Report the result under both scope policies.
- **Generator artefacts.** If a signal works only because AMLworld's generator reuses amounts or
  schedules, it will not transfer to real data. Say so in the write-up, and test on LI-Small's
  scope analysis at minimum.

---

## F2. A larger seed budget (0.2 %)

- **Evidence (C7, B14).** The union of the Multi-GINe and MEGA seed sets touches **150.8 / 174**
  rings, against 129.6 for Multi-GINe alone, but it is a 0.2 %-budget number. At a fixed 0.1 %, an
  ensemble gains only +4.0 rings, because 484 of 864 seed edges are shared at the top of both
  rankings.
- *(Updated 2026-11-12: for `gine_causal` this is already answered — `r4_sweep_val_curve.csv` holds 0.15, 0.20, 0.30 and 0.50 %, and validation chose 0.10 % on every seed. Only MEGA and the min-rank ensemble remain.)*
- **Test.** Add 0.2 % to the validation grid for `full` (both detectors and the min-rank ensemble)
  and let validation choose, as in Step 3c. The precision cost is the open question: at 0.15 %,
  added-member precision already falls to 0.782 (E5/E6).
- **Bound.** At most +21.2 rings touched; how many convert to matches is unmeasured.

## F3. Scoped policy relaxation for pass-through accounts

- **Evidence (B15).** GATHER-SCATTER's 31 missing edges sit exactly one hop from the fragment and
  were declined by the policy. An oracle admitting them turns all 8 instances into perfect matches.
- **Test.** Lower `p_min` only for candidates whose shared account has in-flow ≈ out-flow within
  Δt (a pass-through), with the floor chosen on validation.
- **Bound.** ≤ 1.6 rings per seed (≈ 0.9 recall points), at the precision bound 0.85.

## F4. Detector-specific policy, and MEGA-GenAgg as a detector

- **Policy.** MEGA's `full` runs reuse the Multi-GINe-trained policy (`detector_choice.yaml`; the
  transfer control `mega_noembed` scores 0.5881 against 0.6074). Cross-score MEGA itself and
  retrain the policy and affinity model on its scores.
- **MEGA-GenAgg.** Published at 74.88 ± 0.38 HI-Small edge F1 (Bilgi et al., 2024), the best
  AMLworld number to date. `models/mega_adapter.py` hard-codes the GIN variant in `MEGA_FLAGS`
  (`edge_agg_type="gin"`, `node_agg_type="sum"`). Upstream selects GenAgg with
  `edge_agg_type="genagg"` (multi-edge stage) and `node_agg_type="genagg"` (node stage, GIN model
  only), and needs `pip install -e third_party/mega_gnn/genagg`. Expose both as CLI flags, write to
  `experiments/R6_mega_genagg/`, and everything downstream runs unchanged: the pipeline only
  needs `scores_*_seed<S>.parquet` and `embeddings_*_seed<S>.parquet`, and the embedding features
  are cosine similarities, so the embedding width does not matter.
- **Expectation.** Small. C6 shows a +9.4 edge-F1 gain buys 0.000 B0 ring-F1 at this budget. The
  value is a third detector on the plateau, not a new headline.
- **Rule.** Shipping it requires winning on validation under `detector_choice.yaml`; test rows
  cannot be the reason.

## F5. Validation-ring bootstrap for the detector choice

`detector_choice.yaml` records the margin (0.5927 vs 0.5620, 4 of 5 seeds) without an interval,
because no run wrote a validation `rings.parquet`. *(Corrected 2026-11-12: `experiments_valrings/average/seed1–5` (2026-10-11) are validation rings for `gine_causal`; only the MEGA side is missing.)* Re-run `full` on the val split for both
detectors × 5 seeds (≈ 1–2 h) and bootstrap over val rings. This cannot reverse the decision; it
closes the open Step 9 item 1.

## F6. Explanation review (L4)

The L4 fidelity verdict is negative because the rings saturate (343 of 401 ring-instances hold only
true edges). *(Updated 2026-11-12: the 30-ring internal review is complete — κ 0.60 / 0.86 / 0.72, `xai_chapter.md` §7.2.4. The external study is drafted in `review/`.)* The 30-ring internal review with Fleiss' κ was the next measurement; it is
labelled internal, not an analyst study.

## F7. External validity

All method numbers are on HI-Small. LI-Small has 38 matchable rings, too few to separate methods.
Next: the Medium AMLworld releases (same generator, more rings), then real transaction data under
a privacy agreement, where generator artefacts (C1, C8) cannot help any signal.

## F8. A drift monitor that can fire

**Evidence.** R12 (`docs/R12.md`) stopped at its registered positive control: a synthetic +3 SD step
added to the hourly monitor input from hour 12 of day 9 was **not detected** by the platform's
ADWIN monitor (`platform/jobs/drift_monitor.py`). Two measured causes:

1. **ADWIN tests every 32 updates.** river's `ADWIN(clock=32)` default checks for a change once per
   32 inputs. Over R12's 48 hourly steps that is one test, at step 32, before the step begins; in live
   daily operation it is one test a month, so the monitor cannot fire inside the ten-day test split.
2. **The calibrated 99th percentile is flat.** Isotonic calibration maps the top of the score range
   onto a plateau: the hourly p99 is 0.015064 in all 24 day-8 hours, so its standard deviation is 0
   and the p99 statistic cannot move however the input shifts.

**Build.** Set `clock=1` (test every update) with a minimum window long enough for a stable
reference; replace the calibrated p99 with a statistic that varies (the raw-score p99, or the share
of edges above the seed cutoff); keep the monitor's output as events only, never a retraining trigger.

**Cheapest test that could kill it.** Re-run R12's synthetic control: if a +3 SD step on both
statistics is still not detected within a few hours, the statistic, not the clock, is the problem.
A changed monitor needs **a new R12 registration**; the stopped R12 run stays as reported.

**Upper bound.** None claimable from this data: with ~1 CYCLE transaction per ~24,000 per hour, even
a working score-distribution monitor is not expected to see R12's injected shift. What F8 buys is a
monitor that is able to fire on shifts large enough to matter.

