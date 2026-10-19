# Platform Requirements Status

**Part 1 complete: PR-01 through PR-52 reviewed against the repository.** Statuses describe source and test presence; they do not claim that tests or CI were run.

| ID | Requirement | Status | Evidence | Gap / next step |
|---|---|---|---|---|
| PR-01 | Tenant registry and five loaded tenants selected by ring-member count | PARTIAL | `platform/jobs/seed_tenants.py::seed_tenants`; `scripts/survey_tenants.py::survey`; `platform/DECISIONS.md` | The survey ranks candidates reproducibly, but there is no configured five-tenant selection/loaded set based on ring-member count. Choose and load the five after the survey. |
| PR-02 | PostgreSQL schema managed by Alembic | TESTED | `platform/db/migrations/versions/0001_platform_schema.py`–`0006_explanation_fx_hash.py`; `platform/tests/isolation/test_migration_chain_real_db.py::test_migration_chain_round_trips_and_enforces_forced_rls` | Test exists for CI; database execution was not performed in this audit. |
| PR-03 | Preserve unmodelled contract columns in payload JSONB | IMPLEMENTED | `platform/db/models.py` (`Transaction`, `EdgeScore`, `Ring` payloads); `platform/jobs/load_contract.py` | JSONB payloads are stored; no explicit lossless round-trip test was found. Add one covering unknown contract fields. |
| PR-04 | Section 4 indexes | PARTIAL | `platform/db/models.py` indexes for accounts, transactions, scores, rings, verdicts, model versions, retrains, drift and audit log | Core indexes exist, but the verdict index is tenant/time rather than the specified tenant/ring lookup index, and the complete Section 4 index set is not shown as matched. Compare each index to the spec and add missing ones. |
| PR-05 | JWT login with tenant/role claims, eight-hour expiry, bcrypt | IMPLEMENTED | `platform/api/identity.py::create_access_token`; `platform/api/routers/auth.py::login`; `platform/api/routers/auth.py` uses bcrypt | Login and bcrypt exist. I found no automated test asserting the exact claims and eight-hour expiry; add token contract coverage. |
| PR-06 | Set tenant and role context on each request | TESTED | `platform/db/session.py::db_session`; `platform/api/dependencies.py::tenant_session`; `platform/tests/isolation/test_rls_real_db.py::test_tenant_a_cannot_read_tenant_b_and_no_context_fails_closed` | Real-Postgres test exercises tenant context; not run here. |
| PR-07 | Application role has no BYPASSRLS | TESTED | `platform/db/migrations/versions/0002_role_ownership_force_rls.py`; `platform/tests/isolation/test_rls_real_db.py::test_app_role_is_restricted_and_not_a_table_owner` | Test exists for CI; not run here. |
| PR-08 | Forced RLS for every tenant table, admin read clause, verdict write denial | TESTED | `platform/db/migrations/versions/0002_role_ownership_force_rls.py`; `platform/tests/isolation/test_rls_real_db.py::test_every_tenant_table_has_enabled_and_forced_rls`, `::test_admin_reads_across_tenants_but_cannot_mutate_verdicts` | Dynamic real-Postgres coverage exists; not run here. |
| PR-09 | Cross-tenant path/token mismatch returns 403 before queries | TESTED | `platform/api/dependencies.py::require_tenant_access`; `platform/tests/isolation/test_api_tenant_boundary_real_db.py::test_tenant_a_token_is_rejected_before_tenant_query_and_admin_can_read` | Test exists for CI; not run here. |
| PR-10 | Audit every state change | PARTIAL | `platform/api/routers/admin.py::create_user`; `platform/api/services/verdicts.py`; `platform/jobs/retrain.py`; `platform/jobs/drift_monitor.py` | User creation/password reset and verdict writes are audited, but not every state mutation (for example drift acted-on changes and all job/model transitions). Define and test complete audit coverage. |
| PR-11 | All Section 6 endpoints, pagination and error shape | PARTIAL | `platform/api/main.py`; routers in `platform/api/routers/`; `platform/api/errors.py` | Existing routes cover core ring, evidence, verdict, model, drift and retrain flows, but Section 6 endpoint parity is incomplete (including regeneration); audit the specification endpoint-by-endpoint. |
| PR-12 | Explanation endpoints call L4 and cache results | PARTIAL | `platform/api/routers/rings.py::get_ring_explanation`; `platform/jobs/load_explanations.py::load_explanations`; `platform/db/models.py::Explanation` | Loader persists verified L4 output and the API serves the newest stored row. The endpoint does not call L4 or populate a response cache. Add the specified call/cache path if required. |
| PR-13 | Regenerate explanation after partial verdict | MISSING | `platform/api/routers/verdicts.py::submit_verdict` returns 503 for partial verdicts; dashboard disables partial correction | No regeneration job table, worker, adapter, endpoint or working dashboard flow exists. Implement the atomic partial-verdict/regeneration workflow. |
| PR-14 | Verdict updates ring status; partial requires note and corrected members | PARTIAL | `platform/api/routers/verdicts.py::submit_verdict`; `platform/api/schemas.py`; `platform/api/services/verdicts.py` | Confirm/reject update status. Partial verdicts are refused pending regeneration; corrected-member workflow is not implemented. |
| PR-15 | `is_simulated` is stored and simulator never marks a human verdict simulated | TESTED | `platform/jobs/simulate_verdicts.py::simulate_cycle`; `platform/api/services/verdicts.py`; `platform/tests/test_simulate_verdicts.py::test_shared_verdict_service_marks_simulated_row_and_updates_ring` | Automated test covers simulated flag behavior. |
| PR-16 | Model-version history includes gate outcomes | TESTED | `platform/api/routers/operations.py::list_model_versions`; `platform/tests/test_operations_views.py::test_model_registry_includes_shared_versions_and_hides_artifact_paths` | API exposes model-version records; dashboard presentation omits some gate detail (see PR-26/FR-D70). |
| PR-17 | Supervisor retrain trigger with run status and log | TESTED | `platform/api/routers/operations.py::start_retrain`, `::get_retrain_status`; `platform/tests/test_retrain_api.py::test_retrain_post_creates_a_run_and_starts_a_separate_worker` | Trigger and separate worker/status path have tests. |
| PR-18 | Admin R10 job endpoint and result retrieval | IMPLEMENTED | `platform/api/routers/admin.py::start_tenant_vs_pooled`, `::get_tenant_vs_pooled_status`; `platform/jobs/experiment_worker.py::main` | Job launcher/status API and worker exist, but I found no automated test for these R10 endpoints. Real R10 output also remains blocked by inputs listed under PR-32. |
| PR-19 | Health endpoint | IMPLEMENTED | `platform/api/main.py` health route | Route exists; no dedicated health endpoint test was found. |
| PR-20 | Structured JSON logs include request and tenant IDs | PARTIAL | `platform/api/middleware.py::RequestContextMiddleware`; `platform/api/errors.py` | Request IDs and tenant context are attached to requests/errors, but a structured JSON application logger carrying both fields is not implemented. |
| PR-21 | Login shows tenant name and role | IMPLEMENTED | `platform/dashboard/app.py::_login`, `::main` | Login/session UI and tenant/role sidebar exist; no successful-login UI test was found. |
| PR-22 | Ring queue filters and sorting | IMPLEMENTED | `platform/dashboard/app.py::_queue`; `platform/api/routers/rings.py::list_rings` | Status, topology, confidence, date, cross-bank, sort and order controls are present; no dedicated queue-control UI test was found. |
| PR-23 | Ring detail narrative, graph roles/weights/time slider, evidence tabs and verdict form | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/rings.py::get_ring_evidence` | Summary, basic graph, evidence tables, explanation and confirm/reject form exist. Role/weight encoding, timeline slider, tabs and partial form are missing. |
| PR-24 | Render up to 60 graph nodes under two seconds; truncate larger graphs with count | MISSING | `platform/dashboard/app.py::_ring_detail` renders returned graph evidence without the required node limit/benchmark | Add deterministic 60-node rendering, larger-ring banner/load-all behavior and a performance test. |
| PR-25 | Verdict history screen | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/verdicts.py::list_verdicts` | History is shown within ring detail; a dedicated history screen with filters/export is absent. |
| PR-26 | Models screen with supervisor retrain button | TESTED | `platform/dashboard/app.py::_model_versions`; `platform/tests/test_dashboard_l6.py::test_models_page_empty_state_and_supervisor_control` | Screen and supervisor control are tested. Confirmation dialog and gate-reason presentation remain gaps. |
| PR-27 | Drift screen | TESTED | `platform/dashboard/app.py::_drift_events`; `platform/tests/test_dashboard_l6.py::test_drift_page_empty_states_and_tenant_specific_calls` | Screen and tenant-specific calls have a test. |
| PR-28 | Admin tenant-vs-pooled screen | MISSING | Admin R10 API exists in `platform/api/routers/admin.py`; dashboard navigation in `platform/dashboard/app.py::main` has no admin experiment page | Build the admin UI to start/poll R10 and render its results. |
| PR-29 | UI does no arithmetic on API metrics | IMPLEMENTED | `platform/dashboard/app.py`; grep check recorded in closing section | No ring metric arithmetic found; the only `+`/`-` expressions in the requested grep are page-index/cursor navigation. No dedicated static test was found. |
| PR-30 | Cross-bank ring shows counter-party bank name only | PARTIAL | `platform/api/routers/rings.py::_summary`; `platform/dashboard/app.py::_ring_detail` | UI shows counterparty labels such as `Bank <id>` and does not expose hidden activity; verified counterparty names are unavailable in the current registry response. |
| PR-31 | Empty states explain why there is no data | PARTIAL | `platform/dashboard/app.py::_queue`, `::_ring_detail`, `::_model_versions`, `::_drift_events` | Most screens have empty states, but the queue combines “no match” and “no rings loaded” instead of distinguishing them. |
| PR-32 | R10 tenant/pooled harness, five seeds and confidence intervals | BLOCKED | `platform/experiments/r10_tenant_vs_pooled.py`; `platform/README.md` R10 section | Harness and seeded bootstrap CI exist. Real run needs `amlworld_ring_ground_truth.parquet`; test scores exist for seeds 1–5, but full model and matching test embeddings are available only for seed 1. |
| PR-33 | R10 cross-bank fraction and banks-per-ring over all rings | BLOCKED | `platform/experiments/r10_tenant_vs_pooled.py`; `platform/README.md` R10 section | Report calculation is implemented; real report is blocked by the R10 ground-truth parquet and missing full-model/test-embedding inputs for seeds 2–5. |
| PR-34 | Configurable verdict simulator; simulated flag always true | TESTED | `platform/jobs/simulate_verdicts.py`; `platform/config.yaml::l6.simulator`; `platform/tests/test_simulate_verdicts.py::test_shared_verdict_service_marks_simulated_row_and_updates_ring` | Simulator behavior/configuration has automated coverage; the real truth-driven cycle still needs its external truth input. |
| PR-35 | Retraining job uses research train/evaluate CLIs | BLOCKED | `platform/jobs/retrain.py`; `platform/adapters/research_cli.py`; `platform/config.yaml::l6.retrain` | Job/gate tests exist, but real training needs validation GFP, validation embeddings and ground-truth parquet; configured GFP/embeddings paths are not supplied and truth is null. |
| PR-36 | Frozen holdout manifest and immutable hash | BLOCKED | `platform/holdout/holdout_manifest.json`; `platform/tests/test_holdout_manifest.py`; `platform/config.yaml::l6.retrain` | Checked-in manifest is explicitly a fixture. Generate the immutable production manifest from the supplied ground-truth parquet before real retraining. |
| PR-37 | Configured promotion gate; record refusal reason | TESTED | `platform/jobs/retrain.py`; `platform/config.yaml::l6.retrain.epsilon`; `platform/tests/test_retrain_job.py::test_gate_refuses_candidate_below_epsilon_with_a_specific_reason`, `::test_gate_promotes_at_epsilon_boundary_or_above` | Gate and refusal reason have tests. |
| PR-38 | Only promoted model re-scores open rings | TESTED | `platform/jobs/refresh_rings.py`; `platform/tests/test_retrain_job.py::test_retrain_job_gates_candidate_and_runs_refresh_as_a_separate_step`; `platform/tests/isolation/test_refresh_rings_real_db.py::test_refresh_updates_open_preserves_verdict_rings_and_isolates_tenant_rows` | Separate refresh and ring-preservation tests exist; Postgres test was not run here. |
| PR-39 | R11 tables for a=0.90/0.70 plus no-retrain control | BLOCKED | `platform/experiments/r11_gated_retrain.py`; `platform/tests/test_r11_gated_retrain_experiment.py` | Experiment logic and fixture test exist, but a real report requires truth, validation GFP/embeddings and real model runs. |
| PR-40 | Replay test period as simulated days with held-out rings removed/reinserted | BLOCKED | `platform/experiments/r12_injected_shift.py`; `platform/config.yaml::r12.model_dir` | Replay code exists. Real run is blocked because `r12.model_dir` is null and ground-truth parquet is absent. |
| PR-41 | Per-tenant ADWIN on daily mean/p99 with configured delta | TESTED | `platform/jobs/drift_monitor.py::DriftStream`; `platform/config.yaml::l6.drift`; `platform/tests/test_drift_monitor.py::test_each_adwin_series_detects_one_step_change_after_shift` | Monitor and configured delta are covered by tests. |
| PR-42 | Drift events never trigger retraining automatically | TESTED | `platform/jobs/drift_monitor.py`; `platform/tests/test_drift_monitor.py::test_drift_monitor_has_no_retrain_dependency_or_call` | Test checks no retrain dependency/call. |
| PR-43 | R12 detection delay and three-column recall report with control | BLOCKED | `platform/experiments/r12_injected_shift.py`; `platform/tests/test_r12_injected_shift.py::test_fixture_dry_mode_reports_injected_drift_and_never_claims_a_retrain` | Fixture dry report is tested; real report needs truth and the real `r12.model_dir`/research model inputs. |
| PR-44 | Compose Postgres/API/dashboard and make up/migrate/seed/load targets | PARTIAL | `docker-compose.dev.yml`; `docker-compose.test.yml`; `scripts/run-demo.ps1`; `scripts/test-db.ps1`; `Makefile` | Dev Compose runs Postgres only; API and Streamlit dashboard start as host processes. Test Compose has Postgres/test-runner. Make targets are `test-db` and `test-db-down`; there are no `up`, `migrate`, `seed` or `load` targets. |
| PR-45 | Idempotent contract loader keyed by tenant/id with model and aggregator provenance | TESTED | `platform/jobs/load_contract.py`; `platform/tests/test_load_contract.py`; `platform/tests/isolation/test_ring_composite_key_real_db.py` | Loader and real-DB identity/upsert tests exist; database tests were not run here. |
| PR-46 | Nightly retrain and daily drift scheduler; manual trigger | TESTED | `platform/api/scheduler.py::start_scheduler`; `platform/tests/test_drift_monitor.py::test_scheduler_disabled_by_default_and_date_trigger_dispatches_jobs` | Scheduler/manual paths exist; scheduler is disabled by default in config. |
| PR-47 | Laptop run without GPU on stub files | PARTIAL | `platform/jobs/make_demo_fixture.py`; `platform/README.md`; `scripts/run-demo.ps1` | Synthetic fixture is available for database testing, but the end-to-end demo runner requires supplied real tenant ring/L4 inputs; a complete stub-only laptop workflow is not documented or tested. |
| PR-48 | All Section 11 tests in CI | IMPLEMENTED | `.github/workflows/platform-tests.yml` | Workflow provisions Postgres and runs platform tests; this audit did not inspect a successful CI result or run tests. |
| PR-49 | No model logic outside adapters | TESTED | `platform/tests/test_research_boundary.py::test_platform_research_import_and_ground_truth_boundary`; grep result in closing section | Boundary test exists and requested forbidden-import grep returned no matches. |
| PR-50 | Ground truth never exposed by endpoint | TESTED | `platform/tests/test_research_boundary.py::test_platform_research_import_and_ground_truth_boundary`; API search in closing section | Boundary test exists; requested API ground-truth/label grep returned no matches. |
| PR-51 | README covers architecture, run, add tenant, R10–R12 | PARTIAL | `platform/README.md` | Architecture, running, tenant loading, R10 and L6 flows are documented. Dedicated R11/R12 run instructions and a complete real-data runbook are incomplete. |
| PR-52 | Demo shows two tenants, ring detail, verdict, gate refusal and R10 table | PARTIAL | `scripts/run-demo.ps1`; `platform/README.md` | Script loads tenants 12/20 and starts API/dashboard; it does not stage a walkthrough of ring detail/verdict, gate refusal or the R10 results table. |
## Dashboard Requirements Status

**Part 2 complete: every FR-D ID present in the dashboard specification was reviewed.** Automated-test status means a matching test exists in the repository; no tests were run for this audit.

| ID | Requirement | Status | Evidence | Gap / next step |
|---|---|---|---|---|
| FR-D01 | Login form; keep token in memory; show tenant and role | IMPLEMENTED | `platform/dashboard/app.py::_login`, `::main` | Token is in Streamlit session state and tenant/role appear in sidebar; no successful-login UI test was found. |
| FR-D02 | Generic invalid-credentials message | TESTED | `platform/dashboard/app.py::_api`, `::_login`; `platform/tests/test_dashboard_auth_feedback.py::test_login_401_shows_generic_error_and_preserves_unrelated_session_state`, `::test_login_error_does_not_depend_on_response_message` | Generic message does not distinguish unknown email/password and has automated tests. |
| FR-D03 | Expired/rejected 401 returns to login with message | TESTED | `platform/dashboard/app.py::_api`, `::_login`; `platform/tests/test_dashboard_auth_feedback.py::test_authenticated_401_is_shown_as_notice_after_login_rerun` | Session expiry notice survives rerun; automated test exists. |
| FR-D04 | Sign out clears token and cached data | IMPLEMENTED | `platform/dashboard/app.py::main` | Sign-out deletes all Streamlit session keys; no dedicated sign-out test was found. |
| FR-D05 | Role-restricted screens hidden and direct URL says Not permitted | PARTIAL | `platform/dashboard/app.py::main`, `::_api`; API role dependencies in `platform/api/dependencies.py` | API enforces role access and UI displays “Not permitted”; navigation is not filtered by role, and the dashboard is a single-page app without per-screen URL routes. |
| FR-D10 | Ring queue required columns and formatted summary | PARTIAL | `platform/dashboard/app.py::_queue` | Queue includes type/probability, members, edges, amount/currency, start/end, confidence, cross-bank and status; window duration is not rendered as “over …”. |
| FR-D11 | Default confidence-desc sort; sortable by specified fields | IMPLEMENTED | `platform/dashboard/app.py::_queue`; `platform/api/routers/rings.py::list_rings` | UI exposes confidence, amount, start-time and member sorts plus order; no automated queue sorting test was found. |
| FR-D12 | Queue status/type/confidence/date/cross-bank filters | IMPLEMENTED | `platform/dashboard/app.py::_queue`; `platform/api/routers/rings.py::list_rings` | All listed filter controls and API parameters exist; no dedicated filter UI test was found. |
| FR-D13 | API cursor pagination, 50 rows and total count | IMPLEMENTED | `platform/dashboard/app.py::_queue`; `platform/api/routers/rings.py::list_rings` | Requests limit 50, displays total and tracks next cursor; no queue pagination UI test was found. |
| FR-D14 | Open ring and retain queue filters/page on return | IMPLEMENTED | `platform/dashboard/app.py::_queue`, `::_ring_detail`, `::main` | Filter/page state remains in session while opening and returning to detail; no dedicated navigation test was found. |
| FR-D15 | Distinct empty-state reasons for no matches vs no rings | PARTIAL | `platform/dashboard/app.py::_queue` | Current message combines the two conditions; use the returned total/tenant ring count to distinguish them. |
| FR-D16 | Search ring ID and account ID | MISSING | No search control in `platform/dashboard/app.py::_queue`; ring-list API has no matching search parameter | Add indexed API search and queue controls. |
| FR-D17 | Confirm/reject quick actions with confirmation | MISSING | `platform/dashboard/app.py::_queue` only opens detail | Add row actions and confirmation prompt. |
| FR-D20 | Exact narrative then full ring summary/provenance | PARTIAL | `platform/dashboard/app.py::_ring_detail` | Narrative and most summary fields are shown, but ring summary precedes explanation narrative and required window/conservation/counterparty formatting is not complete. |
| FR-D21 | Status and latest verdict author/time | PARTIAL | `platform/dashboard/app.py::_ring_detail` | Status and verdict history appear, but latest verdict author/time is not presented as the specified summary next to the badge. |
| FR-D22 | Copy narrative button | MISSING | No copy control in `platform/dashboard/app.py::_ring_detail` | Add clipboard action. |
| FR-D30 | Directed payer-to-payee graph | IMPLEMENTED | `platform/dashboard/app.py::_ring_detail` | Graphviz `digraph` edges are directed from source account to target account; no graph UI test was found. |
| FR-D31 | Role colors, legend, node size by account weight | PARTIAL | `platform/dashboard/app.py::_ring_detail` | Source/sink/mule flags affect labels and mule color; holder/peripheral roles, role legend and `w_account` node sizing are absent. |
| FR-D32 | Edge width/seed style/expanded style and legend | PARTIAL | `platform/dashboard/app.py::_ring_detail` | Edges show direction and ID labels only; weights, seed/expanded styling and legend are absent. |
| FR-D33 | Node and edge hover details | MISSING | Static Graphviz graph in `platform/dashboard/app.py::_ring_detail` | No hover details or weight components are exposed in the graph. |
| FR-D34 | Time slider and five-second playback | MISSING | No timeline controls in `platform/dashboard/app.py::_ring_detail` | Add slider/playback and edge visibility state. |
| FR-D35 | Cross-highlight graph selections and evidence rows | MISSING | Graph and evidence are rendered separately in `platform/dashboard/app.py::_ring_detail` | Add linked selection state. |
| FR-D36 | Show highest-weight 60 nodes and load-all option | MISSING | `platform/dashboard/app.py::_ring_detail` shows API evidence page and a generic first-250-edges caption | Implement node-weight truncation, count banner and load-all control. |
| FR-D37 | Deterministic layout for a ring | PARTIAL | `platform/dashboard/app.py::_ring_detail` uses Graphviz `dot` | A graph layout exists, but fixed-seed/deterministic behavior is not configured or tested. |
| FR-D38 | PNG graph and CSV subgraph downloads | MISSING | No download buttons in `platform/dashboard/app.py::_ring_detail` | Add graph and subgraph exports. |
| FR-D40 | Transaction evidence table with weights and sorting | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/rings.py::get_ring_evidence` | Table has transaction basics and calibrated score/seed but not `w_total`, its components, requested sort or tab layout. |
| FR-D41 | Account evidence table with bank, roles, flows, hold time and weight | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/rings.py::get_ring_evidence` | Accounts are displayed as a raw list/basic graph nodes; required account-weight evidence table is absent. |
| FR-D42 | Top-10 feature-weight bar chart by absolute mean SHAP | PARTIAL | `platform/dashboard/app.py::_ring_detail` displays `feature_weights` as a dataframe | No top-10 ranking/bar chart or required transaction-detector caption. |
| FR-D43 | CSV export on each evidence tab | MISSING | No evidence tabs/download controls in `platform/dashboard/app.py::_ring_detail` | Add CSV export for each evidence view. |
| FR-D44 | Explanation version and latency footer | IMPLEMENTED | `platform/dashboard/app.py::_ring_detail` | Shows explainer version and latency in milliseconds; no dedicated footer test was found. |
| FR-D50 | Confirm, reject, partial actions and note rules | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/verdicts.py::submit_verdict` | Confirm/reject and optional note exist; partial action is disabled and backend returns 503. |
| FR-D51 | Partial checklist and at least one retained member | MISSING | No partial checklist in `platform/dashboard/app.py::_ring_detail` | Implement member/edge checklist and validation alongside regeneration. |
| FR-D52 | Successful submission updates UI; partial regenerates all panels | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/verdicts.py::submit_verdict` | Confirm/reject success reruns the page; partial and explanation regeneration are absent. |
| FR-D53 | Disable verdict button during submission | MISSING | Confirm/reject button handlers in `platform/dashboard/app.py::_ring_detail` have no in-flight guard | Add request-state disabling/idempotent UI guard. |
| FR-D54 | Tag simulated verdicts | IMPLEMENTED | `platform/dashboard/app.py::_ring_detail` verdict history table | History includes a Simulated column; no dedicated display test was found. |
| FR-D55 | Admin sees disabled form and specified warning | IMPLEMENTED | `platform/dashboard/app.py::_ring_detail` | Admin receives the “Administrators cannot record verdicts.” warning and returns before the form. |
| FR-D60 | Standalone tenant verdict table with filters | PARTIAL | `platform/api/routers/verdicts.py::list_verdicts`; `platform/dashboard/app.py::_ring_detail` | Paged API history exists inside ring detail; separate table, filters and simulated/real filter are absent. |
| FR-D61 | Filtered verdict counts | MISSING | No verdict counts in dashboard | Add count summary to history view. |
| FR-D62 | CSV export of verdict history | MISSING | No verdict export in dashboard | Add filtered CSV download. |
| FR-D70 | Model versions with gate outcomes and promoted highlight | PARTIAL | `platform/dashboard/app.py::_model_versions`; `platform/api/routers/operations.py::list_model_versions` | Table shows component/version/time/labels/F1/promoted; gate reason and promoted-per-component highlight are not shown. |
| FR-D71 | Supervisor retrain with confirmation of components/gate | PARTIAL | `platform/dashboard/app.py::_model_versions` | Button exists for supervisor, but no confirmation dialog or component/gate explanation. |
| FR-D72 | Poll run every five seconds and show expandable log tail | PARTIAL | `platform/dashboard/app.py::_model_versions`; `platform/api/routers/operations.py::get_retrain_status` | Status is fetched on render and logs shown; no five-second polling or expandable log area. |
| FR-D73 | Prominent gate refusal reason linked to model row | PARTIAL | `platform/dashboard/app.py::_model_versions` | Run/model rows are shown, but the refusal reason is not displayed/prominently linked in the dashboard table. |
| FR-D80 | Daily mean/p99 chart with drift-event markers and hover details | IMPLEMENTED | `platform/dashboard/app.py::_drift_events` | Plotly line series and event markers with hover data exist; no chart UI test was found. |
| FR-D81 | Drift table and supervisor acted-on toggle with note | PARTIAL | `platform/dashboard/app.py::_drift_events`; `platform/api/routers/operations.py::set_drift_acted_on` | Events and toggle exist; no note is collected or persisted. |
| FR-D82 | Permanent explanation that drift does not establish laundering or retrain | PARTIAL | `platform/dashboard/app.py::_drift_events` | Informational/no-auto-retrain caption exists, but omits the specified score-distribution versus laundering-behavior distinction. |
| FR-D90 | Admin tenant registry table | MISSING | `platform/api/routers/admin.py::list_tenants`; no admin page in `platform/dashboard/app.py::main` | Add dashboard registry view and ring/verdict counts. |
| FR-D91 | Admin tenant-vs-pooled run, results and aggregate metrics | MISSING | Admin R10 API exists in `platform/api/routers/admin.py`; no dashboard screen | Add run/poll/results table and aggregate metrics. |
| FR-D92 | Tenant-versus-pooled recall bar chart | MISSING | No dashboard R10 visualization in `platform/dashboard/app.py` | Add chart to admin experiment page. |
| FR-D93 | Admin ring/verdict views visibly read-only | PARTIAL | `platform/dashboard/app.py::_ring_detail`; `platform/api/routers/verdicts.py::submit_verdict` | Admin cannot submit verdicts and sees a warning, but no admin tenant ring/verdict view or “Read-only (administrator)” label exists. |
| FR-D100 | Loading/error state with API message, request ID and retry | PARTIAL | `platform/dashboard/app.py::_api` | Errors are displayed, but no consistent loading skeleton/retry control or request-ID presentation is provided for every screen. |
| FR-D101 | API values formatted as specified, local time with UTC hover | PARTIAL | `platform/dashboard/app.py::_queue`, `::_ring_detail`, `::_drift_events` | Some amount/percentage formatting exists; times remain raw UTC strings, without user-local conversion/UTC hover, and field-specific formatting is inconsistent. |
| FR-D102 | No dashboard arithmetic on API values | IMPLEMENTED | `platform/dashboard/app.py`; exact grep/result in closing section | No sums, ratios or derived ring metrics found; only page-index navigation arithmetic appears. No dedicated arithmetic regression test was found. |
| FR-D103 | Show counterparty bank name only | PARTIAL | `platform/api/routers/rings.py::_summary`; `platform/dashboard/app.py::_ring_detail` | Current display uses bank labels/IDs; actual bank names are not available through the current registry payload. |
| FR-D104 | Never show ground truth, pattern IDs or unreturned values | TESTED | `platform/tests/test_research_boundary.py::test_platform_research_import_and_ground_truth_boundary`; API grep in closing section | Boundary test exists and API ground-truth/label search returned no matches. |
| FR-D105 | Help definitions for listed terms and each weight | MISSING | No glossary/help controls in `platform/dashboard/app.py` | Add two-sentence definitions for each requested term/weight. |
## Audit commands and source-level checks

**Part 3 complete: audit results, gap priority, blockers, risks, handoff facts, and execution scope are recorded below.**

The source documents used were `directions/RingShield_L5_L6_Platform_Spec.docx` and `directions/RingShield_Dashboard_Requirements.docx`. IDs and requirement meanings come from those documents, not the abbreviated task summaries.

### Required grep checks

- FR-D102 / PR-29 command: `git grep -n -E 'sum\(|[[:alnum:]_)] *[-+*/] *[[:alnum:]_(]' -- platform/dashboard/app.py`. Result: only `platform/dashboard/app.py:166`, `:171`, and `:175`, all page/cursor navigation arithmetic (`page + 1`, `page - 1`). No sum, ratio or derived ring metric arithmetic was found.
- PR-49 command: `git grep -n -E '(^|[[:space:]])(import|from)[[:space:]]+(torch|xgboost|lightgbm|sklearn|ringshield)([.]|[[:space:],]|$)' -- platform ':!platform/adapters'`. Result: no matches.
- PR-50 command: `git grep -n -i -E 'ground.?truth|labels_' -- platform/api`. Result: no matches.

### FR-D02, FR-D03 and FR-D05 message/search check

Command run exactly as requested:

```text
git grep -n -i -E "session expired|not permitted|ResetPasswords|invalid (username|credentials)|wrong password|incorrect password" -- platform scripts
```

Relevant hits, grouped by source type:

- Code: `platform/api/dependencies.py` (API session-expiry and Not permitted responses); `platform/api/errors.py` (Not permitted code/message); `platform/api/routers/auth.py` (comment preserving indistinguishable wrong-password behavior); `platform/api/routers/verdicts.py` (session-expiry response); `platform/dashboard/app.py` (generic login error, session-expiry notice, role warning); `scripts/run-demo.ps1` (`-ResetPasswords`, conflict validation and reset path).
- Tests: `platform/tests/test_auth_bcrypt.py::test_bad_login_credentials_keep_indistinguishable_api_401_contract`; `platform/tests/test_dashboard_auth_feedback.py::test_login_401_shows_generic_error_and_preserves_unrelated_session_state`, `::test_authenticated_401_is_shown_as_notice_after_login_rerun`, `::test_403_warns_and_keeps_authenticated_session`, `::test_login_error_does_not_depend_on_response_message`; `scripts/tests/run-demo-validation.tests.ps1` checks switch declaration, `-Down` conflict and that password values are not printed.

Findings: visible wrong-password feedback exists as the generic `Incorrect email or password.` message and has tests; “Session expired. Please sign in again.” exists and has a test; “Not permitted: your role cannot do this.” exists and has a test; `-ResetPasswords` exists and has static script tests.

## Top gaps by importance

| Rank | Requirement IDs | Why it matters | Estimate |
|---|---|---|---|
| 1 | PR-13, PR-14, FR-D50–53 | Partial correction is refused; the member checklist, corrected-member persistence and post-verdict L4 regeneration are absent. | L |
| 2 | PR-28, FR-D90–93 | Admin R10 API exists but the dashboard has no tenant registry or tenant-versus-pooled workflow/results view. | L |
| 3 | PR-24, FR-D31–38 | The required graph interaction, role/weight encodings, timeline, cross-highlighting, large-ring handling and exports are mostly absent. | L |
| 4 | PR-10 | State changes are not consistently represented in the audit log; this weakens change accountability. | M |
| 5 | PR-32, PR-33, PR-35, PR-36, PR-39, PR-40, PR-43 | Real R10–R12 evidence and retraining cannot be completed with the external truth and validation/model artifacts currently missing. | L |

## Blocked items and who unblocks them

- PR-32/33 R10 and PR-39 R11: the data owner must provide `amlworld_ring_ground_truth.parquet`; the model/artifact owner must provide complete full-model and matching test-embedding inputs for seeds 2–5 if all five seeds are required.
- PR-35/36 real retraining and frozen production holdout: provide the ground-truth parquet, validation GFP and matching validation embeddings; the platform owner can then create the immutable holdout manifest and run the job.
- PR-40/43 real R12: provide the ground-truth parquet and a real configured `r12.model_dir`/research model inputs; the experiment owner can then execute replay and produce the report.
- R10–R12 status is blocked by external artifacts, not by a claim that CI/database tests failed. No such runs were performed in this audit.

## Bugs or risks noticed while reading

- Partial verdict requests currently return 503, while the dashboard shows a disabled partial button. This is safe against silently recording an incomplete correction, but leaves the analyst workflow unfinished (PR-13/14).
- Queue empty state merges “no rings match” with “no rings generated”, which can mislead a newly provisioned tenant (PR-31 / FR-D15).
- Drift events can be marked reviewed without the required supervisor note (FR-D81).
- The verdict index is on `(tenant_id, created_at)`; the queried ring history is filtered by `(tenant_id, ring_id)` and no matching index was found (PR-04 performance risk).
- Database and RLS tests are present for CI, but were not run for this audit. No test or CI success is asserted here.

## Handoff facts check

| Fact | Check |
|---|---|
| Tenant ring builder cutoff `0.9295209672451074` | OK — `platform/config.yaml::seed_score_cutoff`; source says pooled test log `seed_rule.q`. |
| Pinned FX SHA-256 `ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6` | OK — `platform/config.yaml::fx_rates_sha256`. |
| `l4.rings_schema_version = 1` | OK — `platform/config.yaml`. |
| Migration revisions 0001–0006 and next free number | OK — `platform/db/migrations/versions/0001_platform_schema.py` through `0006_explanation_fx_hash.py` exist; next free revision number is `0007`. |
| Retraining gate epsilon `0.005` | OK — `platform/config.yaml::l6.retrain.epsilon`. |
| App, loader, simulator and owner roles; API process has no loader credentials | OK — roles are created in `0002_role_ownership_force_rls.py`; the API module boundary test is `platform/tests/test_retrain_api.py::test_api_modules_never_read_or_import_loader_credentials`. `platform/api` has no direct loader URL import/read. |
| Explanation primary key and revision column | OK — primary key is `(tenant_id, ring_id, explainer_version)` in `platform/db/models.py::Explanation` and migration 0001. There is no `revision` column. |
| Roles with INSERT/UPDATE on explanations | OK — `ringshield_api` and `ringshield_loader` each have INSERT and UPDATE grants in `platform/db/roles.sql`; auth and simulator roles do not. |

## Execution scope

This was a source/document audit. No code, tests, migrations or configuration were changed. No unit tests, database tests, Docker services, demo, CI workflow or real R10–R12 run were executed. Test names in the tables indicate available automated coverage only.
