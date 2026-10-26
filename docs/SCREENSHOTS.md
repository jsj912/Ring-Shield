# What RingShield looks like

Captured on 2026-10-26 from the **real demo** (`scripts/demo.ps1 -FromProcessedData`: seed-1 rings
built from `data/processed/`, L4 explanations, seeded demo users), not from the fixture server.
Re-capture with `npm run screenshots` in `platform/frontend` against a fresh demo
(`e2e/screenshots.spec.ts`), then `python scripts/compress_screenshots.py`. Each dashboard screen
exists in light and dark (`-light.png` / `-dark.png`); the light one is shown. Verdict times are
greyed out because they change on every run.

Layers: **L3** builds the rings (seeds, expansion, partition, roles, typing); **L4** explains them;
**L5/L6** is the platform (database, API, workers, dashboard).

## Dashboard

### 01 Sign in
![Login](screenshots/01-login-light.png)
The sign-in page. The session lives in memory only, so reloading the page signs you out (L5/L6).

### 02 Ring queue
![Ring queue](screenshots/02-ring-queue-light.png)
An analyst at bank 12 sees only bank 12's rings, with topology, size, total, window and confidence,
and the filters above the table. The rings are L3's output for the bank's visible edges; the queue
is the platform's (L5/L6).

### 03 Ring detail: the graph
![Graph](screenshots/03-ring-detail-graph-light.png)
Bank 12's top ring, a FAN-OUT: one source paying four sinks. Node roles come from L3; edge width is
L4's edge weight; the slider replays the transactions in time order.

### 04 Ring detail: the evidence
![Evidence](screenshots/04-ring-detail-evidence-light.png)
The transactions behind the ring with amounts in their own currency, times and payment formats,
plus tabs for accounts and the detector's signals. Rows and weights come from L4.

### 05 Ring detail: the narrative
![Narrative](screenshots/05-ring-detail-narrative-light.png)
L4's narrative: a fixed template in which every number traces to a stored value (shape and its
probability, accounts, transactions, money moved, strongest evidence, detector signals), above
the ring's facts.

### 06 Recording a verdict
![Verdict form](screenshots/06-verdict-form-light.png)
The verdict form with a note typed in, before submitting: confirm, reject, or correct the ring
partially (L5/L6).

### 07 Quick verdict
![Quick verdict](screenshots/07-quick-verdict-light.png)
Confirming straight from the queue asks first; a quick verdict carries no note (L5/L6).

### 08 A partial verdict regenerates the narrative
![Regeneration](screenshots/08-regeneration-light.png)
After a partial verdict removes one account, the platform asks L4 to explain the corrected ring:
"Explanation regenerated for the corrected ring", the narrative and graph now describe the
remaining accounts, and the header reads "n of N members (corrected)". The dark shot does the same on
bank 20's nine-member ring.

### 09 Verdict history
![Verdicts](screenshots/09-verdicts-light.png)
A supervisor at bank 12 sees every verdict recorded at the bank, with filters and CSV export.

### 10 Models
![Models](screenshots/10-models-light.png)
The bank's model versions and retrain runs, with the holdout gate's reason for each candidate
(L6). A refused retrain needs R11's history; see `README`, "Running the demo".

### 11 Drift
![Drift](screenshots/11-drift-light.png)
The score-drift monitor's chart and its permanent note (L6). Bank 12 has no drift event, which is
what R12 found on the real stream.

### 12 Administrator: tenant vs pooled (R10)
![Admin](screenshots/12-admin-light.png)
The administrator's view of the cross-tenant experiment, R10: one bank's view against a pooled
model, per bank and pooled across the primary set, with the cross-bank ring share above it. The
tenant registry sits above this section.

### 13 Tenant isolation
![Bank 20](screenshots/13-tenant-isolation-light.png)
The same queue for an analyst at bank 20: different rings, and none of bank 12's (L5/L6 row-level
security).

### 14 API
![Swagger](screenshots/14-api-docs.png)
The FastAPI documentation at `/docs` on the demo API.

### Phone width (390 x 844)
| Queue | Ring detail |
|---|---|
| ![Mobile queue](screenshots/15-mobile-queue-light.png) | ![Mobile ring](screenshots/16-mobile-ring-detail-light.png) |

The sidebar folds into a menu and the panels stack.

## Research figures

Copied from `results/figures/` (not regenerated; `evaluation/make_figures.py` builds them).

| Figure | What it shows |
|---|---|
| ![](screenshots/research/f1_val_ringf1_vs_seedfrac.png) | Ring-F1 collapses as the seed budget grows: the seed budget is chosen on val, not on test |
| ![](screenshots/research/r9_quiet_vs_precision.png) | Quiet-member recall against added-member precision: what the learned policy buys is purity (FINDINGS A5) |
| ![](screenshots/research/f2_per_pattern_recall.png) | Recall is pattern-bound: BIPARTITE and STACK stay near the floor (B6, B13) |
| ![](screenshots/research/f3_quiet_member_recall.png) | The central claim, quiet-member recall, with its interval |

There is no committed figure of the test-split tail (C1); it is a table (`docs/test_tail.json`).

## Elliptic baselines (E1–E3)

| | |
|---|---|
| ![](screenshots/elliptic/elliptic_timestep1_subgraph.png) | Elliptic, timestep 1 subgraph (`elliptic/graph/viz_elliptic.py`) |
| ![](screenshots/elliptic/elliptic_illicit_ego_network.png) | An illicit transaction's ego network |

The interactive pyvis visualisations (`elliptic/graph/viz_*_interactive.py`) were not captured:
pyvis is not installed on the machine these were taken on, and no generated HTML exists.

## Earlier versions

![Mockup](screenshots/history/dashboard-mockup-lakshmishree.png)
Lakshmishree's dashboard mockup (`docs/archive/dashboard-mockup/`), which the React dashboard
replaced. It loads its styles from public CDNs; its sample rows did not render here. The frozen
Streamlit dashboard (tag `streamlit-frozen-2026-10-25`) was not captured.
