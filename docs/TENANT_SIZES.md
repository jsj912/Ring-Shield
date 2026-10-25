# Tenant size check

Status: partial. Account and edge counts below are computed from the local contract/data files. Ring-member counts by bank are not computed because the ground-truth membership input is missing from this checkout.

## Method and scope

- Account counts: distinct `account_id` values per `bank_code` in `data/processed/account_bank.parquet`.
- Visible test edges: distinct `edge_id` rows in `contract/out/scored_edges_gine_causal_1.parquet` where `from_bank = bank_code OR to_bank = bank_code`. A self-transfer is counted once. This file contains 863,900 test-period edges.
- Primary-window visible edges are also shown for days 8–9, using the configured loader-time window `[691210, 864009]` (`configs/eval_window.yaml`). The full-test count includes days 8–17.
- These are descriptive visibility counts only. No model performance, test-set scoring, threshold selection, or detector comparison was performed.

## Accounts per bank

There are **515,088 mapped accounts** across **30,470 distinct bank codes**. Account counts per bank have mean 16.90, median 4, 25th percentile 2, 75th percentile 7, 90th percentile 13, 95th percentile 30, 99th percentile 371, minimum 1, and maximum 3,158.

| Accounts per bank | Number of banks |
|---:|---:|
| 1 | 6,192 |
| 2–5 | 14,142 |
| 6–10 | 5,954 |
| 11–25 | 2,570 |
| 26–100 | 504 |
| 101+ | 1,108 |

## Top 20 banks by account count

Share is the bank's account count divided by all 515,088 mapped accounts.

| Rank | Bank code | Accounts | Share of accounts | Visible full-test edges | Visible primary-window edges |
|---:|---:|---:|---:|---:|---:|
| 1 | 12 | 3,158 | 0.613099% | 20,039 | 20,009 |
| 2 | 10 | 3,108 | 0.603392% | 20,121 | 20,104 |
| 3 | 15 | 2,872 | 0.557575% | 13,750 | 13,714 |
| 4 | 220 | 2,353 | 0.456815% | 13,407 | 13,385 |
| 5 | 1 | 2,172 | 0.421676% | 15,158 | 15,132 |
| 6 | 3 | 1,775 | 0.344601% | 9,916 | 9,912 |
| 7 | 7 | 1,664 | 0.323052% | 8,789 | 8,785 |
| 8 | 20 | 1,610 | 0.312568% | 10,315 | 10,286 |
| 9 | 28 | 1,541 | 0.299172% | 7,885 | 7,855 |
| 10 | 116 | 1,512 | 0.293542% | 7,850 | 7,847 |
| 11 | 211 | 1,504 | 0.291989% | 8,088 | 8,085 |
| 12 | 1,665 | 1,496 | 0.290436% | 8,017 | 8,006 |
| 13 | 118 | 1,216 | 0.236076% | 6,711 | 6,693 |
| 14 | 6 | 1,166 | 0.226369% | 6,177 | 6,173 |
| 15 | 213 | 1,127 | 0.218798% | 5,482 | 5,482 |
| 16 | 14 | 1,103 | 0.214138% | 6,423 | 6,423 |
| 17 | 214 | 1,101 | 0.213750% | 5,823 | 5,817 |
| 18 | 4 | 1,100 | 0.213556% | 6,060 | 6,059 |
| 19 | 22 | 1,039 | 0.201713% | 7,049 | 7,025 |
| 20 | 1,362 | 1,033 | 0.200548% | 6,261 | 6,259 |

## Top five banks by ring-member count: pending input

This ranking and the requested per-bank counts (visible test edges, in-scope truth rings with at least one visible member, and in-scope truth rings with at least three visible members) cannot be computed from the available files. `data/processed/amlworld_ring_ground_truth.parquet` and the raw `HI-Small_Patterns.txt` are absent. `docs/ring_scope.json` contains aggregate ring counts but not the member account IDs needed to join members to `bank_code`.

To finish this section, provide `amlworld_ring_ground_truth.parquet` from the same data/version as the current account map, or provide the raw pattern and transaction inputs needed to regenerate it. The scope for in-scope truth rings should follow the repository's primary-window `test_visible` definition: a ring is in scope when at least one pattern transaction falls in the window, and its scored members are the endpoints of those in-window transactions.

## Registered 2026-10-22, before any R10 results

Registered on branch `ringshield-train` before any R10 tenant-vs-pooled number was computed.
Nothing below was chosen after seeing an R10 result.

### Counting unit

**Ring-member count = members of in-scope truth rings whose home bank is T**, joined through
`data/processed/account_bank.parquet` (`account_id` -> `bank_code`). In-scope rings: the 174
ground-truth rings in scope of the primary window (days 8-9) under `test_visible`: at least one
pattern transaction in the window, with the endpoints of those in-window transactions as the
scored members. A ring counts toward bank T only when at least one of its scored members has home
bank T.

**How the unit was chosen.** The section above says only that members are joined "to
`bank_code`". It also asks for "in-scope truth rings with at least one visible member", which is
the in-scope ring filter, not the counting unit. Both readings were computed and both top-8 lists
were seen before the unit was fixed. The decision rests on the wording ("join members to
`bank_code`"), and the visibility-based list is kept as a robustness set rather than discarded.

**Tie-break:** visible test edges descending (`from_bank == T or to_bank == T` in
`contract/out/scored_edges_gine_causal_1.parquet`, days 8-17), then bank id ascending.

### Primary tenants: 1, 20, 11, 118, 12

Home-bank count over the 174 in-scope rings:

| rank | bank | ring-member count (home bank) | in-scope rings with >= 1 member at T | with >= 3 | accounts | visible test edges |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | **1** | 20 | 17 | 1 | 2,172 | 15,158 |
| 2 | **20** | 17 | 14 | 1 | 1,610 | 10,315 |
| 3 | **11** | 16 | 14 | 0 | 1,013 | 7,206 |
| 4 | **118** | 15 | 12 | 1 | 1,216 | 6,711 |
| 5 | **12** | 14 | 11 | 1 | 3,158 | 20,039 |
| 6 | 22 | 14 | 12 | 1 | 1,039 | 7,049 |
| 7 | 119 | 14 | 13 | 0 | 977 | 5,285 |
| 8 | 222 | 14 | 14 | 0 | 415 | 2,297 |

Slot 5 is a four-way tie at 14 ring members (12, 22, 119, 222). The registered tie-break gives it to
12, with 20,039 visible test edges against 7,049 for bank 22.

### Robustness set: 70, 12, 11, 1, 10

Ranked by **visible-member count**: members of in-scope rings that are an endpoint of any
primary-window edge with `from_bank == T or to_bank == T`. Same tie-break.

| rank | bank | visible-member count | rings >= 1 | rings >= 3 | visible test edges | home-bank count |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | **70** | 87 | 67 | 4 | 81,371 | 0 |
| 2 | **12** | 72 | 34 | 10 | 20,039 | 14 |
| 3 | **11** | 65 | 27 | 7 | 7,206 | 16 |
| 4 | **1** | 57 | 30 | 7 | 15,158 | 20 |
| 5 | **10** | 56 | 28 | 9 | 20,121 | 13 |
| 6 | 20 | 56 | 25 | 5 | 10,315 | 17 |
| 7 | 119 | 53 | 28 | 5 | 5,285 | 14 |
| 8 | 23 | 46 | 21 | 5 | 6,674 | 11 |

Bank 70 sees the most ring members of any bank, and none of them are its own accounts: its
exposure comes entirely from being a hub (81,371 visible test edges). Slot 5 is a tie at 56
between 10 and 20; the tie-break gives it to 10 (20,121 visible test edges against 10,315).

### R10 analysis

* **Primary: pooled across the five primary tenants.** The unit is a **tenant-ring pair**: a truth
  ring in scope for tenant T counts once for T, so a cross-bank ring visible to two tenants
  contributes two pairs. Uncertainty comes from a **bootstrap over rings, 10,000 resamples**: a
  ring is resampled together with all of its tenant pairs. **Per-tenant numbers are descriptive
  only** and carry no claim.
* **Robustness row:** the same pooled analysis on the robustness set (70, 12, 11, 1, 10), reported
  as a secondary row with no per-tenant claims.
* **Two secondary rows**, registered with the primary:
  1. **Option (a), pooled scores.** Each tenant's rings are built from the pooled scored edges,
     restricted to the tenant's visible edges.
  2. **Budget-matched (b).** Tenant-visible scores (option (b)), with the seed budget matched to
     the pooled seed count on the same visible edges: the top-n tenant-visible edges by
     `score_raw`, where n is the number of pooled seeds (`score_raw > q`) among the tenant's
     visible test edges. This separates "different scores" from "a different number of seeds
     at the fixed cutoff".
* **Not used:** the five tenants proposed in `platform/DECISIONS.md` (12, 20, 21749, 21611,
  11128). They were ranked by **predicted** rings with at least five members from tenant ring
  runs, not by truth ring members. Under the registered unit 21749, 21611 and 11128 rank 40, 65
  and 204.

## Note added 2026-10-22, after the R10 option (b) scores were computed

Not part of the registration above, and it changes no rule there. Observed while producing the
option (b) score files (`experiments/R10_tenant_visible/summary.csv`):

* **Bank 70's laundering edges are all `pattern_type = NONE`.** All 110 laundering edges among its
  81,371 visible test edges are isolated laundering, not ring edges. None of the 174 in-scope truth
  rings has a laundering edge visible to bank 70 (the other six tenants: 11 to 17). Pooled scores
  put those edges around 0.01 (median), so bank 70's edge AP is at chance under both pooled
  scoring and option (b).
* **Option (b) saturates bank 70's scores.** On bank 70's own graph, 491 visible test edges score
  exactly 1.0 in seed 2, rank correlation with pooled is about 0, and the seeds at the fixed cutoff
  swing from 0 to 620 across seeds.
* **How it is reported:** the robustness row is reported **as degenerate**, with bank 70 named as
  the reason. **Bank 70 is excluded from nothing**; the row is computed exactly as registered.
* **What option (b) measures.** It applies weights trained on the pooled graph to each tenant's
  subgraph. Its loss against pooled scoring therefore includes **distribution shift** (the model
  sees a graph unlike the one it was trained on), not only the loss of information from seeing
  fewer edges. The two are not separable in this design.

## R11: registered 2026-10-25, before any R11 run

Registered before any run of the five-seed R11 below. One earlier R11 run exists: detector seed 1
only, 2026-10-24 (`docs/R11.md`, Result). Nothing below was chosen after seeing a result of the
five-seed run. R11 is a demonstration that the feedback loop works end to end, **not an
effectiveness experiment**: verdicts are about 0.06 % of the expansion policy's training rows, and
one bank produces about 5 rings in 48 h.

#### Tenant counts (step a)

Seed-1 tenant rings (`platform/jobs/build_tenant_rings.py`, `--edge-subset`, fixed pooled cutoff, on
each bank's own visible scores) counted when any member edge falls in days 8-9 (loader time
691210-864009). Ties go to more visible test edges.

| rank | bank | rings | rings in days 8-9 | visible test edges |
|---:|---:|---:|---:|---:|
| 1 | **1** | 9 | **7** | 15,158 |
| 2 | 11 | 4 | 4 | 7,206 |
| 3 | 12 | 3 | 3 | 20,039 |
| 4 | 118 | 4 | 3 | 6,711 |
| 5 | 20 | 5 | 2 | 10,315 |

**Chosen tenant: bank 1.**

#### Amendments to spec v1.1 (decided)

1. **Window:** days 8-9 only, as 12 four-hour cycles. No loop over the whole test window.
2. **Inputs:** the tenant's own visible score files; rings from `build_tenant_rings.py`
   (`--edge-subset`, fixed pooled cutoff).
3. **Review:** 100 % of the tenant's rings each cycle. The simulator's queries and verdict rules are
   unchanged.
4. **Retrain:** exactly once, after cycle 6, with `ringshield train` (expansion and affinity) and the
   holdout guard. If the gate accepts, the new model serves cycles 7-12; if it rejects, the old model
   continues.
5. **Typing:** not refit. This is an amendment to v1.1, which refit typing.
6. **Gate rejection test:** a unit test in which flipped verdicts make the holdout score worse, so the
   gate rejects (`platform/tests/test_retrain_job.py::test_gate_rejects_a_retrain_made_worse_by_flipped_verdicts`).
7. **Tenant:** of banks 1, 20, 11, 118 and 12, the one with the most seed-1 tenant rings in days 8-9;
   ties go to more visible test edges. That is bank 1 (table above).

#### Run, fixed now

* **Detector seeds 1-5.** For seed s: bank 1's rings are built from
  `data/tenant_visible/scored_edges_visible_1_gine_causal_{s}.parquet` at seed s's pooled cutoff;
  the base model is `models/artifacts/full_gine_causal_seed{s}`; the gate's holdout inputs are seed
  s's validation scores and embeddings; explanations come from `explainability.tenant` on those
  rings.
* **Simulator accuracy 0.90 and 0.70**, unchanged from v1.1; simulator seed 0 as configured. Every
  verdict is simulated.
* **A fresh demo database per (seed, accuracy)**, with bank 1 reloaded, so every run starts from the
  same baseline.
* **Reported per seed and accuracy:** a per-cycle table of rings, verdicts, retrain (y/n), gate
  decision, holdout ring-F1 before and after, and the serving model version.
* **Day-9 ring metrics, descriptive only:** ring precision, recall, F1 and member coverage at
  Jaccard 0.5 on day 9 (loader time 777610-864009, `test_visible`), against the in-scope truth rings
  with a scored member whose home bank is 1, for the old model and for the model serving cycles
  7-12. If the gate rejects, the serving model is the old model and the two rows are the same by
  construction.
* **Wall time** per run and in total.
* **Output for the Models screen:** JSON in the API's `ModelVersion` and `RetrainRun` field names.
