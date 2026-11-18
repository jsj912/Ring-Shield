# Part B: do the test rings have labelled history? (2026-11-16, post hoc, a count; nothing built)

Pre-registration: paper/PREREG_RECOVERY_2026-11-16.md (sha256 a265194c…).
Script: evaluation/recovery_history.py.
Tables:
- results/tables/recovery_history_counts.csv (per seed and mean)
- recovery_history_per_ring.csv
- recovery_history_cost.json

**Assumption.** Labels of transactions before the window (days 0–7, the train and validation splits)
are known at test time.
**Caveat.** Real laundering labels arrive with a delay. Flag (d) limits history to days 0–5 as a
sensitivity check. Days are `Timestamp // 86400`.

The rings are the 174 primary-window truth rings (test_visible member sets). Loss buckets come from
the shipped full pipeline's Q0 decomposition (results/tables/q0_buckets_per_ring.csv), read rather
than recomputed. Its per-seed means match q0_buckets.csv: 77 / 11.0 / 14.4 / 68.8.

## Rings per seed with history (mean over 5 seeds)
| bucket | rings | (a) ring active before day 8 | (b) a member has illicit history, days 0–7 | (c) as (b), other rings only | (d) as (b), days 0–5 |
|---|---|---|---|---|---|
| matched | 68.8 | 43.8 | 49.4 | 11.4 | 25.4 |
| unobservable, unmatched | 77.0 | 36.0 | 56.0 | 39.0 | 45.0 |
| matchable, untouched | 11.0 | 4.2 | 5.0 | 2.4 | 2.8 |
| recovered too thinly | 14.4 | 9.6 | 12.2 | 6.6 | 7.2 |
| merged / split | 2.8 | 1.4 | 2.4 | 1.6 | 1.6 |
| **target: untouched + too thin** | **25.4** | 13.8 | **17.2** | 9.0 | 10.0 |

(The unobservable row has more rings than its matched subset, because 11.4 of the 77 are still
matched; they are counted under "matched" in Q0's `a_matched`. Here the bucket follows Q0's single
label.)

## Cost side (primary window: 862,792 edges, 956 illicit, 354,447 active accounts)
| history | accounts with history | in-window edges touching them | illicit share of those edges | illicit edges among them | edges per current seed (463) |
|---|---|---|---|---|---|
| (b) days 0–7 | 3,585 | 101,293 | 0.48 % | 484 | 219× |
| (d) days 0–5 | 2,602 | 95,322 | 0.31 % | 296 | 206× |

## Reading against the declared bar
- **The bar is met:** 17.2 of 25.4 target rings per seed have history under (b), against a bar of 8.
- **The sensitivity checks also clear it:**
  - (c), other rings only: 9.0;
  - (d), shorter history: 10.0.
  - Much of (b) is the same attempt straddling the split. 13.8 of the 25.4 target rings were already active before day 8.
- **The cost is large.** A rule that seeds from every in-window edge of a history account would add about 100,000 edges, 219 times the current budget. Their illicit share is 0.48 %, about 4.5 times the window base rate (0.11 %), but far below the precision of the current seeds.
  - Such a rule touches 484 of the 956 illicit in-window edges.
  - A usable method would have to rank inside this set: for example, edges between two history accounts, or history accounts weighted by recency. It cannot take all of it.
- **Verdict per the pre-registration: above the bar → stop for the author's decision.** Nothing was built.
- The history signal is strongest for rings that straddle the split. (b) also holds for 49.4 of the 68.8 rings already matched, so part of it is redundant with what the detector finds.

## Step 0 for Part B2 (amendment d2cfe2fb…): how illicit are the history-touching edges near the top of the detector's ranking?
Shipped Multi-GINe test scores, five-seed mean, primary window (results/tables/recovery_history_topk.csv):

| history | subset of in-window edges touching a history account | edges | illicit | illicit share |
|---|---|---|---|---|
| (b) days 0–7 | all | 101,293 | 484 | 0.48 % |
| (b) days 0–7 | in the detector's top 1 % | 558 | 327 | 59.3 % |
| (b) days 0–7 | in the top 0.5 % | 479 | 316 | 67.0 % |
| (d) days 0–5 | all | 95,322 | 296 | 0.31 % |
| (d) days 0–5 | in the top 1 % | 292 | 157 | 54.1 % |
| (d) days 0–5 | in the top 0.5 % | 245 | 151 | 62.4 % |

Among history-touching edges, the detector's score concentrates the illicit ones. Two thirds of
the illicit edges (316 of 484) sit in the top 0.5 %. History is therefore not useful as a seed source
on its own; the question for B2 is whether reserving part of the budget for it beats spending the
budget by score alone.

## B2 gate and test read (2026-11-16, addendum 4)
- Gate on five completed cells (r50_both did not complete; seed 1 = 0.4821; stopped by author decision after one seed): r25_both 0.5960 > 0.5927, PASS.
- Test, read once (results/tables/b2_test_r25_both.csv, _paired.csv; Q0 results/tables/b2_q0_r25_both*.csv):

| | r25_both full | shipped GINe full |
|---|---|---|
| ring-F1 (5-seed mean) | 0.5924 | 0.5895 |
| ring precision | 0.859 | 0.818 |
| ring recall | 0.453 | 0.461 |
| predicted rings / matched | 92.0 / 78.8 | 98.0 / 80.2 |
| rings touched (174 − a − b) | 84.0 | 86.0 |
| matchable-untouched (b) / too-thin (c1) | 13.0 / 11.6 | 11.0 / 14.4 |
| added-member precision (pooled) | 0.942 (363 edges) | 0.926 (404 edges) |

- Primary paired unit bootstrap (10,000 draws, rng 20261117): ring-F1 Δ +0.0029 [−0.0219, +0.0299], p 0.84. Added-member precision Δ +0.0164 [−0.0095, +0.0489], p 0.22. Neither interval excludes zero.
- Reading: no detectable test gain. The validation lead (+0.0033) carries over as +0.003 on test, within noise; history seeds trade recall for precision and do not reduce untouched-plus-thin (24.6 vs 25.4).
- Label-delay sensitivity (test H = days 0–5, descriptive; results/tables/b2_test_r25_both_testhist05.csv; validation unchanged, H days 0–5 as before): ring-F1 0.5627 (seeds 0.5669, 0.5474, 0.5769, 0.5424, 0.5799), precision 0.801, recall 0.437, 96.4 predicted / 76.0 matched, added-member precision 0.873 (seed 4: 0.619 over 118 added edges). With two fewer days of labelled history, the cell falls below shipped GINe full (0.5895) by 0.027.
