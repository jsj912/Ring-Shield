# RingShield API endpoint parity (Section 6)

Compared against `directions/RingShield_L5_L6_Platform_Spec.docx`, Section 6, and
the registered FastAPI routes in `platform/api`. Path parameters `{t}`, `{r}` and
`{job}` below correspond to `{tenant_id}`, `{ring_id}` and `{job_id}` in code.
“Differs” means a related route exists but does not implement the specified route or
behavior. Deferred endpoints are listed only; they are not implemented here.

| Spec path | Method | Status | Implementation / note |
|---|---|---|---|
| `/auth/login` | POST | Present | `platform/api/routers/auth.py::login` |
| `/tenants/{t}/rings?status=&min_conf=&type=&sort=&q=` | GET | Differs | `platform/api/routers/rings.py::list_rings`; cursor pagination and `q` search exist, but the `type` filter is named `topology_type` in the API. The response includes filtered `total` and unfiltered `tenant_total`. Page size is capped at 100, within the documented maximum of 200. |
| `/tenants/{t}/rings/{r}` | GET | Present | `platform/api/routers/rings.py::get_ring` |
| `/tenants/{t}/rings/{r}/subgraph` | GET | Differs | Related graph data is returned by `/tenants/{tenant_id}/rings/{ring_id}/evidence`; no dedicated `subgraph` route (`platform/api/routers/rings.py`) |
| `/tenants/{t}/rings/{r}/explanation` | GET | Differs | Present at `platform/api/routers/rings.py::get_ring_explanation`; serves previously loaded L4 output and now adds `regenerating` while a job is queued or running |
| `/tenants/{t}/rings/{r}/evidence/edges` | GET | Differs | Related combined `/evidence` route returns edge and graph data (`platform/api/routers/rings.py`) |
| `/tenants/{t}/rings/{r}/evidence/accounts` | GET | Differs | Related combined `/evidence` route returns account and graph data (`platform/api/routers/rings.py`) |
| `/tenants/{t}/rings/{r}/explanation/regenerate` | POST | Present | `platform/api/routers/rings.py::regenerate_ring_explanation`; accepts `{verdict_id}`, returns an existing active job idempotently, creates a replacement after failure, and relaunches queued jobs older than 30 seconds |
| `/tenants/{t}/rings/{r}/explanation/jobs/{job}` | GET | Present | `platform/api/routers/rings.py::get_explanation_job`; returns safe status, revision, error, and timestamps |
| `/tenants/{t}/rings/{r}/verdicts` | POST | Present | `platform/api/routers/verdicts.py::submit_verdict`; valid partial corrections are recorded, with additive `regeneration` status and optional `job_id`; unavailable L4 no longer causes a 503 |
| `/tenants/{t}/verdicts?since=` | GET | Present | Tenant-wide filtered history is implemented by `platform/api/routers/verdicts.py::list_tenant_verdicts` |
| `/tenants/{t}/models` | GET | Present | `platform/api/routers/operations.py::list_model_versions` |
| `/tenants/{t}/retrain` | POST | Present | `platform/api/routers/operations.py::start_retrain` |
| `/tenants/{t}/retrain/{run_id}` | GET | Present | `platform/api/routers/operations.py::get_retrain_status` |
| `/tenants/{t}/drift` | GET | Present | `platform/api/routers/operations.py::list_drift_events` |
| `/admin/tenants` | GET | Present | `platform/api/routers/admin.py::list_tenants` |
| `/admin/experiments/tenant-vs-pooled` | POST | Present | `platform/api/routers/admin.py::start_tenant_vs_pooled`; status is stored in a JSON file, with no R10 database job table |
| `/admin/experiments/{job}` | GET | Differs | Current status path is `/admin/experiments/tenant-vs-pooled/{job_id}` (`platform/api/routers/admin.py::get_tenant_vs_pooled_status`); reads the file-backed status |
| `/health` | GET | Present | `platform/api/main.py::health`; returns database and file-store component statuses |

This report is route parity documentation, not a claim that all Section 6 acceptance
criteria (including pagination limits or synchronous L4 invocation) pass.

Migration 0008 adds the GIN index used by tenant ring account-id search.
