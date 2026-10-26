# R10: per-tenant vs pooled ring recall (registered in docs/TENANT_SIZES.md)

Primary window (days 8-9), `test_visible`, Jaccard 0.5, seeds [1, 2, 3, 4, 5], unit = tenant-ring pair, 95 % CI = bootstrap over rings (10,000). Created 2026-10-24T09:14:20+00:00.

Cross-bank rings: **172 of 174 (98.9%)**; mean banks per ring 4.626.

| row | tenants | pairs | rings | tenant recall | pooled recall | pooled − tenant |
|---|---|---:|---:|---|---|---|
| primary | 1, 20, 11, 118, 12 | 68 | 49 | 0.088 [0.031, 0.161] | 0.359 [0.239, 0.500] | 0.271 [0.154, 0.407] |
| pooled_scores | 1, 20, 11, 118, 12 | 68 | 49 | 0.121 [0.054, 0.205] | 0.359 [0.239, 0.500] | 0.238 [0.135, 0.363] |
| budget_matched | 1, 20, 11, 118, 12 | 68 | 49 | 0.076 [0.020, 0.151] | 0.359 [0.239, 0.500] | 0.282 [0.167, 0.417] |
| robustness (degenerate: bank 70 has no visible ring laundering edge) | 70, 12, 11, 1, 10 | 55 | 40 | 0.066 [0.011, 0.137] | 0.425 [0.284, 0.589] | 0.360 [0.215, 0.530] |

Per tenant (descriptive only, no claim):

| row | tenant | rings | tenant recall | pooled recall |
|---|---:|---:|---:|---:|
| primary | 1 | 17 | 0.035 | 0.365 |
| primary | 11 | 14 | 0.100 | 0.357 |
| primary | 12 | 11 | 0.127 | 0.400 |
| primary | 20 | 14 | 0.157 | 0.357 |
| primary | 118 | 12 | 0.033 | 0.317 |
| pooled_scores | 1 | 17 | 0.071 | 0.365 |
| pooled_scores | 11 | 14 | 0.114 | 0.357 |
| pooled_scores | 12 | 11 | 0.218 | 0.400 |
| pooled_scores | 20 | 14 | 0.143 | 0.357 |
| pooled_scores | 118 | 12 | 0.083 | 0.317 |
| budget_matched | 1 | 17 | 0.035 | 0.365 |
| budget_matched | 11 | 14 | 0.100 | 0.357 |
| budget_matched | 12 | 11 | 0.145 | 0.400 |
| budget_matched | 20 | 14 | 0.086 | 0.357 |
| budget_matched | 118 | 12 | 0.033 | 0.317 |
| robustness | 1 | 17 | 0.035 | 0.365 |
| robustness | 10 | 13 | 0.015 | 0.600 |
| robustness | 11 | 14 | 0.100 | 0.357 |
| robustness | 12 | 11 | 0.127 | 0.400 |
