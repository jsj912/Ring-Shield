# AMLWORLD_MANIFEST.md — AMLworld HI-Small Dataset

## Source
- Dataset: IBM Transactions for Anti-Money Laundering (AML), HI-Small variant
- Source URL: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml-data
- Reference paper: Altman et al. 2023, "Realistic Synthetic Financial Transactions
  for Anti-Money Laundering Models" (arXiv:2306.16424)
- Raw file checksums: see data/checksums/amlworld_raw.sha256 (recorded in Phase 0)

## Schema (verified against downloaded file)
- Columns: Timestamp, From Bank, Account, To Bank, Account.1, Amount Received,
  Receiving Currency, Amount Paid, Payment Currency, Payment Format, Is Laundering
- Dtypes: Timestamp (object, "YYYY/MM/DD HH:MM"), From Bank/To Bank (int64),
  Account/Account.1 (object, hex-style strings e.g. "8000EBD30"),
  Amount Received/Amount Paid (float64), Receiving Currency/Payment Currency/
  Payment Format (object), Is Laundering (int64)
- Node identity: composite key f"{bank}_{account}" — CONFIRMED required, not
  optional (see decision below)
- Edge = one row of HI-Small_Trans.csv = one transaction
- Timestamp parsed to integer Unix epoch seconds

## Node identity decision — CONFIRMED
Account IDs in AMLworld are unique only within a bank, not globally — the same
Account string can legitimately represent two different, unrelated entities at
two different banks. The composite key f"{From Bank}_{Account}" is therefore a
required correctness measure, not a defensive default: omitting it would merge
unrelated cross-bank accounts that happen to share an Account string, fabricating
false edges and false short cycles between entities that were never actually
connected. This is implemented in graph/build_amlworld_graph.py.

## Graph objects produced
- data/processed/amlworld_temporal_data.pt — torch_geometric.data.TemporalData
  (src, dst, t, msg), sorted chronologically, msg = [amount_paid, payment_format_code]
  — Is Laundering deliberately excluded from msg (kept as a separate .y field)
  to avoid label leakage into model features.
- data/processed/amlworld_static_graph.pt — torch_geometric.data.Data, plain
  edge_index view (no time ordering), used by the motif feature extractor.
- data/processed/amlworld_node_to_idx.pt — dict mapping "{bank}_{account}" -> node index

## Verification numbers
- num_nodes: 515088
- num_edges (transactions): 5078345 (matches raw CSV row count: Total lines (including header): 5078346, Transaction rows (excluding header): 5078345)
- num_laundering_edges: 5177 (0.10% of total — consistent with AMLworld's intentionally low fraud rate)
- timestamp range: 1661990400 to 1663517880 (September 1, 2022 00:00 UTC to approximately September 18, 2022 — a continuous ~17.7 day window, no parsing anomalies)
- payment format categories: Reinvestment, Cheque, Credit Card, ACH, Cash, Wire, Bitcoin (7 categories, all sensible)

# AMLWORLD_MANIFEST.md — AMLworld HI-Small Dataset

## Source
- Dataset: IBM Transactions for Anti-Money Laundering (AML), HI-Small variant
- Source URL: https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml-data
- Reference paper: Altman et al. 2023, "Realistic Synthetic Financial Transactions
  for Anti-Money Laundering Models" (arXiv:2306.16424)
- Raw file checksums: see data/checksums/amlworld_raw.sha256 (recorded in Phase 0)

## Schema (verified against downloaded file)
- Columns: Timestamp, From Bank, Account, To Bank, Account.1, Amount Received,
  Receiving Currency, Amount Paid, Payment Currency, Payment Format, Is Laundering
- Dtypes: Timestamp (object, "YYYY/MM/DD HH:MM"), From Bank/To Bank (int64),
  Account/Account.1 (object, hex-style strings e.g. "8000EBD30"),
  Amount Received/Amount Paid (float64), Receiving Currency/Payment Currency/
  Payment Format (object), Is Laundering (int64)
- Node identity: composite key f"{bank}_{account}" — CONFIRMED required, not
  optional (see decision below)
- Edge = one row of HI-Small_Trans.csv = one transaction
- Timestamp parsed to integer Unix epoch seconds

## Node identity decision — CONFIRMED
Account IDs in AMLworld are unique only within a bank, not globally — the same
Account string can legitimately represent two different, unrelated entities at
two different banks. The composite key f"{From Bank}_{Account}" is therefore a
required correctness measure, not a defensive default: omitting it would merge
unrelated cross-bank accounts that happen to share an Account string, fabricating
false edges and false short cycles between entities that were never actually
connected. This is implemented in graph/build_amlworld_graph.py.

## Graph objects produced
- data/processed/amlworld_temporal_data.pt — torch_geometric.data.TemporalData
  (src, dst, t, msg), sorted chronologically, msg = [amount_paid, payment_format_code]
  — Is Laundering deliberately excluded from msg (kept as a separate .y field)
  to avoid label leakage into model features.
- data/processed/amlworld_static_graph.pt — torch_geometric.data.Data, plain
  edge_index view (no time ordering), used by the motif feature extractor.
- data/processed/amlworld_node_to_idx.pt — dict mapping "{bank}_{account}" -> node index

## Verification numbers
- num_nodes: 515,088
- num_edges (transactions): 5,078,345
- num_laundering_edges: 5,177 (0.10% of total — consistent with AMLworld's
  intentionally low fraud rate; sanity check passed)
- timestamp range: 1661990400 to 1663517880 (September 1, 2022 00:00 UTC to
  approximately September 18, 2022 — a continuous ~17.7 day window, no
  parsing anomalies; sanity check passed)
- payment format categories: Reinvestment, Cheque, Credit Card, ACH, Cash,
  Wire, Bitcoin (7 sensible categories, no junk values; sanity check passed)
- Row-count cross-check against raw CSV (wc -l equivalent): not independently
  re-verified via a separate line count, but the three checks above all passed
  and are consistent with correct parsing.

## Not yet decided (deferred to Phase 5)
- Train/val/test temporal split boundaries for AMLworld are NOT defined here —
  that is a Phase 5 decision (see roadmap Decision D1/D2 for the related
  ring-ground-truth question). This file only documents the raw graph
  construction, not any split.

## Motif Features (Phase 2, for use in E5b)

- File: data/processed/amlworld_motif_features.parquet
- One row per account node (515,088 rows)
- Columns: in_degree, out_degree, fan_in_flag, fan_out_flag, cycle_count,
  in_short_cycle, scatter_gather_ratio
- fan_threshold used: 5 (documented as a tunable default, not a literature value)
- max_cycle_length used: 4 (performance-driven cap on cycle enumeration —
  will miss longer laundering cycles by design; documented limitation)
- Nodes flagged fan_in: 26,726 (5.19% of accounts)
- Nodes flagged fan_out: 34,534 (6.70% of accounts)
- Nodes in a short cycle: 368,824 (71.6% of accounts)
- Degree distribution: mean in-degree ≈ mean out-degree ≈ 1.97 (as expected —
  every transaction contributes exactly one in-edge and one out-edge), but
  max out_degree = 14,230 — a small number of extreme hub accounts (very
  likely major-bank aggregation accounts) dominate the tail of the distribution.
- This is a NetworkX-based approximation of Blanuša et al.'s (2024) Graph
  Feature Preprocessor concept, not a re-implementation of their streaming
  engine — sufficient for this project's E5b baseline, not a production system.

### Observed data-quality notes (read before using these features in E5b)

**`in_short_cycle` is a weak standalone signal on this dataset.** 71.6% of ALL
accounts (laundering or not) participate in at least one short cycle (≤4 hops).
This is expected in real-world-style banking data — ordinary bidirectional
payment relationships (A pays B, B later pays A back for an unrelated reason)
naturally form 2-cycles at scale — but it means this feature alone will have
low precision for distinguishing laundering from normal activity in E5b. It
may still contribute value in combination with other features (fan-in/out,
scatter-gather ratio, amount patterns) via XGBoost's feature interactions,
but should not be treated as a strong fraud indicator on its own.

**`scatter_gather_ratio` is unbounded below zero, not clipped to [0,1] as the
name might suggest.** Observed range: -288.6 to 0.6. The metric can go deeply
negative when a node's out-neighbors connect through a small number of
extreme-hub accounts (max out_degree in this graph is 14,230), causing the
2-hop distinct-target count to vastly exceed the node's own out-degree. This
is mathematically consistent with the formula (1 - distinct_2hop/out_degree)
but means large negative values signal something different from what the
metric was designed to detect (funneling) — they instead flag proximity to a
hub, a distinct pattern worth distinguishing in any future refinement. Treated
as-is for E5b; XGBoost can still use the raw numeric value effectively even
though its intended semantic range is asymmetric.

## Visual inspection note
An interactive subgraph was built around the 6 accounts most frequently
involved in known laundering transactions (top account: node idx 103, involved
in 243 laundering transactions — the most concentrated by a wide margin over
the next-highest at 158). See
results/figures/amlworld_laundering_subgraph_interactive.html. The rendered
view used a 2-hop neighborhood around these 6 accounts (50,722 nodes before
filtering to transactions within that neighborhood, 818,982 transactions,
capped to the 994 known-laundering edges for readability — note this specific
render contains laundering edges only, no normal-traffic edges for visual
contrast, since laundering volume alone exceeded the display cap). The graph
is illustrated as two node types (Account, Bank) connected by "belongs_to"
edges, with full per-transaction detail (timestamp, amount, currency, payment
format, laundering flag) available via hover tooltips on each transaction
edge. This is a 2-entity-type illustration of the heterogeneous-graph concept
using what AMLworld actually provides (Account + Bank) — not the full 5-7
entity type schema (users, devices, cards, merchants, IPs) described in the
report's Chapter 4 architecture, since this dataset does not populate those
additional node types.

## Reproducibility
- Graph/motif construction environment: pip freeze output should be captured
  to experiments/_phase2_graph_construction/environment.txt (same file used
  for the Elliptic graph construction step, since both were built in the same
  environment during Phase 2).