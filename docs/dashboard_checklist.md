# Dashboard requirements checklist (React, `platform/frontend`)

Source: `docs/dashboard_requirements_v1.0.docx`, with the overrides of 2026-10-25 (six roles incl. `undetermined`;
totals from the explanation record with a partial flag; closed-loop closure; hourly drift days 8–9; retrain
wording and R11; R10 registered first; nothing hidden is shown; API field names). Out of scope: all S/C items,
timed performance tests, HTTPS, browser matrix.

One line per requirement: status, then how it was tested.

| ID | Requirement | Status | How tested |
|---|---|---|---|
| FR-D01 | Login form with email and password; on success store the token in memory (not localStor... | PASS | e2e/login.spec.ts FR-D01 (fixtures): sidebar tenant and role |
| FR-D02 | Invalid credentials show one generic error message; no indication whether email or pass... | PASS | e2e/login.spec.ts FR-D02: wrong password and unknown email give the identical message; client.ts maps every login 401 to one string |
| FR-D03 | Expired or rejected token (401 from any call) returns the user to login with a message ... | PASS | e2e/login.spec.ts FR-D03: every API call answered 401 -> /login with 'Session expired' |
| FR-D04 | Sign out clears the token and all cached data | PASS | e2e/login.spec.ts FR-D04: sign out -> /login; Back shows login, no sidebar; useSignOut clears the query cache |
| FR-D05 | Screens the role may not access are not shown in navigation and return &apos;Not permit... | PASS | e2e/login.spec.ts FR-D05 and smoke.spec.ts: analyst has no Drift/Admin links; /drift and /admin say 'Not permitted' with no drift/admin request |
| FR-D10 | Table of rings for the tenant with columns: ring id, type (with probability as a percen... | PASS | e2e/queue.spec.ts FR-D10 (fixtures): all eight columns with values; type shows topology_prob as received (override 3), total with total_currency and (partial) (override 2) |
| FR-D11 | Default sort by confidence descending; sortable by confidence, total amount, start time... | PASS | e2e/queue.spec.ts FR-D11: aria-sort descending on Confidence by default; Confidence, Total, Window, Members headers re-order. API fix 2fa48a7: sort by total uses the displayed explanation total (pytest test_ring_list_api.py) |
| FR-D12 | Filters: status (open / confirmed / rejected / partial, multi-select; default open), to... | PASS | e2e/queue.spec.ts FR-D12: status (104 -> 200), topology, cross-bank, start date, min confidence each narrow; topology + cross-bank combine to none |
| FR-D13 | Pagination using the API cursor, 50 rows per page, with total count shown | PASS | e2e/queue.spec.ts FR-D13: 200 rings, 4 pages of 50 by cursor, distinct first rows, total shown, Next disabled at the end |
| FR-D14 | Clicking a row opens ring detail; the queue remembers filters and page when the user re... | PASS | e2e/queue.spec.ts FR-D14: page 2 with all statuses -> ring -> Back to queue restores page, filters and rows |
| FR-D15 | Empty result shows a reason: &apos;No rings match these filters&apos; or, when the tena... | PASS | e2e/queue.spec.ts FR-D15: search with no match -> 'No rings match these filters'; Bank C (no rings) -> 'No rings have been generated for this tenant yet' |
| FR-D20 | Show the narrative text exactly as received, followed by the ring summary: type and pro... | PASS | e2e/ring.spec.ts FR-D20: narrative textContent === API string; summary has type with topology_prob as received, total, closure %, window, model and aggregator ids; override test: ring -4 shows '(partial)' and 'closed loop', no % |
| FR-D21 | Status badge and, if a verdict exists, the latest verdict with author and time | PASS | e2e/ring.spec.ts FR-D21: confirmed fixture ring shows the status badge and 'Latest verdict ... by <name> at <time>' |
| FR-D30 | Directed graph of the ring subgraph: accounts as nodes, transactions as edges with arro... | PASS | e2e/ring.spec.ts FR-D30-32: every drawn edge goes from from_id to to_id (Cytoscape source/target), arrowheads on target |
| FR-D31 | Node colour by role: source, sink, mule, holder, peripheral, each with a legend entry; ... | PASS | e2e/ring.spec.ts FR-D30-32: undetermined and mule nodes differ in colour, node size follows w_account, legend lists all six roles (fix 6e02f9f) |
| FR-D32 | Edge width by w_total; seed edges drawn solid, expanded edges dashed; legend entry for ... | PASS | e2e/ring.spec.ts FR-D30-32: seed edges solid, expanded dashed, legend entries for both; width by w_total thresholds (ring-graph.test.ts) |
| FR-D33 | Hover on a node shows account id, bank, role, inflow, outflow, hold time; hover on an e... | PASS | e2e/ring.spec.ts FR-D33: node hover shows account, bank, role, inflow, outflow, hold time; edge hover amount, time, payment format, w_total and its three parts |
| FR-D34 | Time slider spanning [start_time, end_time]; edges with timestamp after the slider posi... | PASS | e2e/ring.spec.ts FR-D34: slider at stop 10/20 greys later edges only; Play runs to the end (5 s) and ungreys |
| FR-D36 | For rings above 60 nodes, render the 60 highest w_account nodes and their incident edge... | PASS | e2e/ring.spec.ts FR-D36: 120-account fixture shows 'Showing 60 of 120 accounts' and 60 nodes; Load all draws 120 |
| FR-D40 | Transactions tab: table of member edges sorted by w_total descending, columns: from, to... | PASS | e2e/ring.spec.ts FR-D40-42: all ten columns, rows sorted by w_total desc, bar in w_total cell; conversion rows only with the toggle (override 2) |
| FR-D41 | Accounts tab: table of member accounts sorted by w_account descending, columns: account... | PASS | e2e/ring.spec.ts FR-D40-42: all seven columns, rows sorted by w_account desc |
| FR-D42 | Detector signals tab: horizontal bar chart of the top 10 feature_weights by /mean_shap/... | PASS | e2e/ring.spec.ts FR-D40-42: ten bars labelled with display_name, caption verbatim; sign colours by comparison; fix 4713e27 takes the API's /mean_shap/ ranking as received |
| FR-D50 | Three actions: Confirm ring, Reject ring, Partially correct; note field (optional for c... | PASS | e2e/verdict.spec.ts FR-D50/51: three actions; partial without a note is blocked with 'A note is required for a partial verdict.' |
| FR-D51 | Partially correct opens a member and transaction checklist pre-ticked from the ring; th... | PASS | e2e/verdict.spec.ts FR-D50/51: checklist pre-ticked from the ring; untick all -> 'Keep at least one account', nothing sent; no removal -> blocked |
| FR-D52 | On submit, POST the verdict; on success update the status badge, append to the verdict ... | PASS | e2e/verdict.spec.ts FR-D52: partial removing one account -> status partial, verdict listed, regeneration polled, narrative changes, graph 6 -> 5 nodes, accounts tab one row fewer |
| FR-D53 | Verdict submission is idempotent from the UI&apos;s side: the button disables while the... | PASS | e2e/verdict.spec.ts FR-D53: double click on Confirm sends exactly one POST /verdicts |
| FR-D54 | Simulated verdicts (is_simulated = true) are displayed with a &apos;Simulated&apos; tag... | PASS | e2e/verdict.spec.ts FR-D54: fixture ring -10 lists a verdict tagged 'Simulated' |
| FR-D55 | Admin sees the form disabled with the text &apos;Administrators cannot record verdicts&... | PASS | e2e/verdict.spec.ts FR-D55: admin sees 'Administrators cannot record verdicts.' and all three buttons disabled |
| FR-D60 | Table of the tenant&apos;s verdicts: time, ring id (link), verdict, analyst, simulated ... | PASS | e2e/history-models.spec.ts FR-D60: columns (simulated tag in the verdict cell), newest first; verdict type, simulated/real, date and analyst filters each narrow; row opens the ring. API boundary: tests/isolation/test_verdict_routes_tenant_boundary_real_db.py |
| FR-D70 | Table of model versions for the tenant: component, version tag, trained at, training la... | PASS | e2e/history-models.spec.ts FR-D70: all columns, newest first by trained_at, refused version shows its gate reason, promoted rows highlighted; client-side counts removed (fix b527dc0) |
| FR-D71 | Supervisor only: &apos;Retrain now&apos; button with a confirmation dialog stating whic... | PASS | e2e/history-models.spec.ts FR-D71: no Retrain button for an analyst; supervisor dialog text verbatim (override 5) with R11's two lanes from the new API route 07da6ec (pytest test_retrain_api.py: own tenant only, other tenant 403, analyst/admin 403) |
| FR-D72 | After triggering, show the run in a runs list with status polling every 5 s until finis... | PASS | e2e/history-models.spec.ts FR-D72/73: run shown running with log tail open, polled (refetchInterval 5000) until finished, no polls after it finishes |
| FR-D73 | A refused run shows the gate reason prominently and links to the model version row | PASS | e2e/history-models.spec.ts FR-D72/73: refused candidates shown as alerts with the gate reason; 'Show model version N' highlights that row |
| FR-D80 | Line chart of the daily mean score and daily p99 score over the tenant&apos;s time rang... | TODO | |
| FR-D81 | Table of drift events: detected at, monitor, window, statistic vs threshold, acted on (... | TODO | |
| FR-D82 | A permanent note on the screen: &apos;This monitor detects shifts in the score distribu... | TODO | |
| FR-D90 | Tenant registry table: tenant id, bank code, name, loaded (yes/no), number of rings, nu... | TODO | |
| FR-D91 | Tenant-vs-pooled experiment: a &apos;Run&apos; button that starts the job and polls; re... | TODO | |
| FR-D93 | Every admin view of a tenant&apos;s rings and verdicts is read-only and labelled &apos;... | TODO | |
| FR-D100 | Every screen has a loading state (skeleton or spinner) and an error state that shows th... | TODO | |
| FR-D101 | Every number is displayed exactly as supplied by the API with formatting only: amounts ... | TODO | |
| FR-D102 | The dashboard performs no arithmetic on API data (no sums, no ratios, no re-ranking bey... | TODO | |
| FR-D103 | Cross-bank rings display the counter-party bank name; no other information about the co... | PASS | e2e/ring.spec.ts FR-D103: cross-bank fixture names 'Bank 9101, Bank 9103, Bank 9105' in summary and header badge; nothing else about them |
| FR-D104 | No screen ever displays ground-truth labels, pattern-group ids, or anything not returne... | TODO | |
| NFR-D10 | The token is held in memory only; nothing sensitive in localStorage, sessionStorage, co... | PASS | e2e/login.spec.ts NFR-D10: sessionStorage and cookies empty, localStorage holds only the theme key, URL has no token; session.ts is a module variable |
| NFR-D11 | All API calls carry the token in the Authorization header; the dashboard never embeds t... | PASS | e2e/login.spec.ts NFR-D11: every request after login has Authorization: Bearer and only tenant 1001 in /tenants/{id} |
| NFR-D12 | The dashboard never connects to the database or file store directly | PASS | package.json has no database driver; grep src for pg/sql drivers finds none |
| NFR-D13 | User-supplied text (notes) is rendered as text, never as HTML/Markdown | PASS | e2e/verdict.spec.ts NFR-D13: note with <script>, **md** and <b> shows literally, script not run, no b/strong/script elements |
| NFR-D14 | Session ends on token expiry; no silent refresh | PASS | useExpiryTimer ends the session at expires_at; no refresh call exists (grep); FR-D03 test |
| NFR-D30 | Any API failure degrades to the screen&apos;s error state; the application never shows ... | TODO | |
| NFR-D31 | A failed verdict submission preserves the form contents and offers retry | PASS | e2e/verdict.spec.ts NFR-D31: POST answered 500 -> message with request id, note and unticked box kept, second submit records |
| NFR-D32 | The graph panel failing (for example an oversized ring) does not prevent the narrative ... | PASS | e2e/ring.spec.ts NFR-D32: subgraph answered 500 -> graph panel shows the message and request id, narrative and transactions render |
| NFR-D50 | All API calls go through one client module with the base URL and token handling in one ... | PASS | Code review: fetch() appears only in src/api/client.ts (grep), base URL and token handled there |
| NFR-D51 | Field names from Section 2 are used unchanged; no renaming layer | TODO | |
| NFR-D53 | Formatting functions (amount, percentage, weight, time) have unit tests | TODO | |
| NFR-D55 | A fixtures folder contains one JSON per object type in Section 2 and one full ring per ... | TODO | |
| NFR-D56 | README: how to run against the API, how to run in fixture mode, how to add a screen | TODO | |
