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
