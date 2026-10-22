# RingShield platform layer

This package is the L5/L6 application layer around the research pipeline. It owns
tenant isolation, authentication, API contracts, verdicts, model operations, drift
events, and the investigator dashboard. Model inference and ring aggregation remain
behind adapters to the existing research CLI and explainability functions.

## Run the demo

On Windows, install and start Docker Desktop, and ensure `python` is on `PATH`. The
runner installs the pinned platform/test requirements. The input folders must contain the tenant rings and
edge-ID files produced for the active detector, plus the verified L4 explanation
parquets. The runner checks every file and log before starting Docker and rejects
label or ground-truth paths. The scored-edges sibling `.log.json` must declare
`split=test`; rings and explanations are passed through the existing tenant loaders.

From the repository root, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-demo.ps1 `
  -Tenants 12,20 `
  -TimeOriginUtc '2022-08-31T23:59:50Z' `
  -RingsDir .\data\platform_tenant_runs\gine_causal_seed1 `
  -EdgeIdsDir .\data\platform_tenant_runs\gine_causal_seed1 `
  -ScoredEdges .\contract\out\scored_edges_gine_causal_1.parquet `
  -ExplanationsDir .\data\platform_explanations
```

`-TimeOriginUtc` is required. It is the UTC instant represented by loader
timestamp 0: the first transaction day's 00:00 UTC minus 10 seconds. Supply a
full ISO-8601 instant with `Z` or an explicit UTC offset, for example
`2022-08-31T23:59:50Z`. The runner prints the chosen origin in its summary, and
the dashboard sidebar displays the same value for screenshots.

The compose project is separate from the test database and uses its own persistent
volume. Its default host port is `55433`; set `RINGSHIELD_DEMO_POSTGRES_PORT` to
change it. The script runs migrations and `alembic check`, creates the restricted
app/loader logins, seeds selected tenants and counterparties, then loads only
endpoint-visible transactions and scores. Tenant rings use `scope=tenant`; the L4
loader checks each explanation log, rings-log tenant rule, artifact hash, active
model/seed, and the pinned FX hash. The API process uses the restricted app and auth
roles with dotenv loading disabled, so it never inherits loader credentials.

For banks 12 and 20, the expected visible edge-ID and database transaction/score
counts are **20,039** and **10,315** respectively, with **5 rings per tenant**.
The runner verifies those counts and checks the loaded explanation count against
the ring count. It prints per-tenant counts for every table with a `tenant_id`.
The API is at `http://127.0.0.1:8000` and the Streamlit dashboard is at
`http://127.0.0.1:8501`. Demo analyst, supervisor, and admin emails/passwords are
written once to the ignored file `platform/demo-credentials.txt`; passwords are
never printed in the console or service logs. Log in with an analyst or supervisor
to see tenant rings; use the admin account for the global admin views.

To rotate all demo-user passwords without removing demo data, run the demo with
`-ResetPasswords`. The runner updates the existing bcrypt hashes and rewrites
`platform/demo-credentials.txt`; the new credentials are never printed. Only
`-Down -DropVolume` removes the database volume.

To check arguments, input paths, and PowerShell automatic-variable assignments
without starting Docker, run the six database-free PowerShell checks, or invoke
the runner with `-ValidateOnly`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\run-demo-validation.tests.ps1
```

To stop the API, dashboard, and
containers while keeping the database volume and credentials, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-demo.ps1 -Down
```

To reset the demo completely, including the persistent database volume and stored
credentials, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-demo.ps1 -Down -DropVolume
```

## L6-B drift monitoring and scheduling

River is pinned at `river==0.22.0` in `platform/requirements.txt` (the project
dependency file included by `requirements-platform.txt`). Run one tenant's score
monitor manually with `python -m jobs.drift_monitor_worker <tenant-id>` from
`platform/`, or use `python platform/jobs/drift_monitor.py <tenant-id>` from the
repository root. The job reads calibrated scores for the active model and seed in
`platform/config.yaml`, groups by the simulated day `(timestamp - 10) // 86400`,
and independently monitors each day's mean and 99th percentile. It stores
informational events only; a detection never starts retraining.

The API exposes the supervisor-only daily series at
`GET /tenants/{tenant_id}/drift/series`, the event history at
`GET /tenants/{tenant_id}/drift`, and the supervisor-only review toggle at
`PATCH /tenants/{tenant_id}/drift/{event_id}` with `{"acted_on": true|false}`.
Supervisors can trigger a manual monitor run with
`POST /tenants/{tenant_id}/drift/check`; it starts a separate tenant worker and
returns `{"status": "queued"}`. This worker only records drift events and never
starts retraining.
The dashboard charts the two series and marks detected windows; supervisors can
review events. Analysts can view the model registry but cannot start retraining
or change drift review state. Drift event inserts are deduplicated on
`(tenant_id, monitor, window_end)` by a database unique constraint.

Supervisors also see recent tenant retraining runs and their status. An empty
history is shown as “No retraining runs yet.” The API lists runs only for the
requested tenant and keeps log tails on the individual run status endpoint.

APScheduler is part of the pinned runtime dependencies. The API's scheduler is
disabled by default (`scheduler.enabled: false` in `platform/config.yaml`). To
enable daily drift checks and nightly per-tenant gated retraining, set that value
to `true` and restart the API. The scheduler launches separate worker processes;
drift and retraining remain separate jobs. Scheduled retraining records
`triggered_by=schedule`. The scheduler was smoke-tested with APScheduler's date
trigger; production cron times are 02:00 UTC for retraining and 03:00 UTC for
drift.

Current input status: drift needs loaded `transactions` and `edge_scores` rows
for the configured active model/seed. Real retraining still needs the validation
GFP, validation embeddings and validation ground-truth parquet; the holdout
manifest must be generated from that supplied truth file. Missing inputs fail
with their configured key/path rather than substituting fixture numbers.

### R10 tenant versus pooled experiment

The repeatable CLI is `python -m experiments.r10_tenant_vs_pooled --truth <test-truth.parquet>`
from the `platform/` directory. R10 requires an operational score source to be
selected explicitly: `r10.tenant_score_source` is `null` by default, or pass
`--tenant-score-source pooled` / `--tenant-score-source tenant_visible` for a run.
The research choice remains unresolved. Pooled scores are always the comparison
baseline; the selected operational source determines which scores build each
tenant's rings. `pooled` uses the pooled score file for every tenant before the
tenant visibility filter; `tenant_visible` requires one test score file per bank
with a log matching that tenant, model, seed and test split. Selecting either
option for a run does not settle the research decision. An optional `--account-map`
selects the account-to-bank mapping, and repeated `--seed N` limits which detector seeds are considered.
Without explicit seed flags, it checks seeds 1 through 5 and runs only seeds with
the test scores/log, full model directory, GFP file and matching embeddings file;
the selected seed list and count are recorded. It also requires loaded tenants in
PostgreSQL. `POST /admin/experiments/tenant-vs-pooled` starts the same job in a
background process; poll `GET /admin/experiments/tenant-vs-pooled/{job_id}`.

For each tenant, truth rings containing at least one account mapped to that bank
form the shared evaluation subset. Both the tenant and pooled ring files are
evaluated against that same subset through the research CLI adapter. The report
contains per-tenant and mean recall/member coverage, ring-bootstrap 95% intervals
from 1000 seeded resamples, tenant truth cross-bank share, and overall truth
cross-bank fraction and average banks per ring. Outputs are
`results/platform/r10/r10_table.csv`, `r10_table.md`, and `run.json`; run
provenance records the Git commit plus config and input SHA-256 hashes.

This checkout has test scores for seeds 1-5, but a full model directory and test
embeddings are available only for seed 1. The test truth path is still unset and
no AMLWorld ground-truth parquet is present. R10 therefore cannot yet produce
real comparison metrics; it fails clearly until you provide that test truth path,
select an operational score source, and provide any missing seed inputs. No
values are filled from the fixture.

### R11 gated retraining experiment

Run one accuracy condition on a dedicated loaded experiment tenant with:

```powershell
python -m experiments.r11_gated_retrain --tenant-id 210 --accuracy 0.90
python -m experiments.r11_gated_retrain --tenant-id 210 --accuracy 0.70
```

Each command replays test-window days 8-17, calls the existing simulated analyst
cycle for open tenant rings, and invokes the existing holdout-gated retrain job
once per day. It records cycle verdict counts, holdout F1, promotions/refusals,
and a static no-retrain control that keeps the initial promoted holdout F1. If
the tenant has no promoted baseline yet, the control evaluates the configured
base artifact through the research adapter; it never runs training. Reports and
`run.json` go to
`results/platform/r11/accuracy_<condition>/`. `run.json` hashes the configured
truth, holdout, validation, model and config inputs. The committed holdout
manifest/checksum are read-only.

Use a dedicated, disposable experiment tenant and restore its known baseline
before running the second accuracy condition; the simulator and retrain job
intentionally write simulated verdicts and model history. The report begins
with **“Retraining was not real in this run; no improvement is claimed.”** if
the research train adapter reports `retrained: false`. This experiment needs
the real test truth, validation truth, validation GFP/embeddings and manifest
inputs in `platform/config.yaml`, plus `RINGSHIELD_SIMULATOR_DATABASE_URL`,
app and loader credentials. Those artifacts are not all present in this
checkout, so no R11 result is claimed yet.

### R12 injected-shift replay

Run the fixture dry path with `python -m experiments.r12_injected_shift --dry`
from `platform/`. If `r12.model_dir` is unset or unavailable, the command
automatically uses that same clearly labeled dry fixture. It writes
`results/platform/r12/dry_fixture/recall.csv`, `recall.md`, and `run.json`.
The report says **“drift was injected, not observed”**, identifies itself as a
fixture dry run, reports simulated ADWIN detection delay, and leaves the
post-retrain recall blank because dry mode does not execute a model or DB job.

Real replay requires a research-supplied full model trained with the configured
pattern held out (`r12.model_dir`, default pattern `BIPARTITE`), the test truth,
active test scores, matching GFP/embeddings, validation/holdout retrain inputs,
and a dedicated loaded tenant with no existing transactions or rings in a
disposable PostgreSQL database. Run, for example,
`python -m experiments.r12_injected_shift --tenant-id 210`. It moves matching
first-half pattern transactions into the second half, builds tenant rings
before and after insertion through the existing builder, loads only the chosen
tenant, replays daily ADWIN statistics, simulates analyst review for open rings
on detected days, and invokes the gated retrain once. Do not point this at a
production tenant: real mode writes test transactions, scores, rings,
simulated verdicts and retraining history. Reports live under
`results/platform/r12/<run-id>/` with config and input hashes.

The implementation is being built in vertical slices, beginning with the API and
database foundation described in `directions/RingShield_L5_L6_Platform_Spec.docx`.

Install the exact pinned platform dependencies with `python -m pip install -r platform/requirements.txt`.
For database-free unit tests, install `python -m pip install -r requirements-dev.txt` and run
`python -m pytest platform/tests --ignore=platform/tests/isolation` from the repository root.

### PostgreSQL tenant-isolation acceptance

The Windows path requires Docker Desktop running with Linux containers and Python 3.12+
available on `PATH`. From the repository root, run the Windows test script; it installs the pinned dependencies:

```powershell
.\scripts\test-db.ps1
```

The script starts the disposable `postgres-test` service in `docker-compose.test.yml`,
waits for `pg_isready` with a timeout, bootstraps migrations, switches later migrations
to the restricted migration role, provisions app/auth/loader roles, seeds the tenant and
contract fixtures, and runs `pytest platform/tests -rA`. It tears down the test container
and volume even when setup or tests fail. The negative-control test creates an
unprotected tenant table in a transaction and proves discovery reports it. A database
integration test also loads the same ring ID in two tenants and verifies each API read
returns that tenant's ring.

GitHub Actions runs the same schema, role, seed, fixture, and test steps against a
Postgres 16 service container on every push and pull request. A configured but
unreachable database fails with a clear error; isolation tests are not silently skipped.

A good local or CI result ends with a summary similar to:

```text
Platform test summary: total passed=50; RLS tests executed against PostgreSQL=19
```

**RLS acceptance is verified only when the summary reports a non-zero RLS test count.**
Database-free unit tests alone do not verify tenant isolation policies.

Copy `platform/.env.example` to the repository root as `.env` and provision the
database URLs and passwords. On a clean database, use a temporary database
administrator URL for the first migration; it creates `ringshield_owner` and transfers
table ownership. Provision a non-superuser login as a member of that no-login role for
subsequent migrations. The application, auth, and loader logins must use their separate
restricted roles. The disposable test command provisions these roles automatically.

```powershell
alembic -c platform/alembic.ini upgrade head
psql $env:RINGSHIELD_DATABASE_ADMIN_PSQL_URL -f platform/db/roles.sql
```

Provision the separate runtime/auth/loader/simulator login users and grant them
membership as documented at the end of `platform/db/roles.sql`. The API and auth
URLs must use those restricted non-owner roles. Start the API with:

```powershell
uvicorn api.main:app --app-dir platform --env-file .env --reload --no-access-log
streamlit run platform/dashboard/app.py
```

The API writes one JSON object per request to stdout with an ISO-8601 UTC timestamp,
level, event, request ID, verified tenant/user IDs (or null when unauthenticated),
HTTP method, route template, status and duration in milliseconds. Request bodies,
query strings, authorization headers, passwords, evidence, narratives and local file
paths are not logged. Uvicorn access logging is disabled to avoid duplicate
unstructured request lines; the Windows demo launcher uses the same setting.

`GET /health` is unauthenticated and returns component status only. It checks the
database through the restricted application role with a three-second connection
timeout and checks artifact-store readability. A failed component returns a safe
503 error body with the request ID; it does not include database details or paths.

Database-backed business state changes append an `audit_log` event in the same
database transaction as the change. Actions include `user.created`, `user.password_reset`,
`user.credentials_initialized`, `verdict.recorded`, `drift.acted_on`,
`drift.events_persisted`, `retrain.requested`, `retrain.started`, `retrain.succeeded`,
`retrain.failed`, `model_version.recorded`, `model_version.demoted`,
`rings.load_completed`, `rings.refresh_started`, `rings.refresh_completed`,
`rings.refresh_failed`, `contract.load_completed`, and
`explanations.load_completed`. Audit details are restricted to safe counts and gate/status
metadata; credentials, hashes, email addresses, evidence and paths are excluded.
Audit records are append-only to application, loader and simulator roles, with
tenant-bound insert policies for tenant events.

R10 experiment status remains in JSON files under `platform/out/experiments`.
Its `experiment.requested`, `experiment.started`, and `experiment.finished` events
are structured JSON process logs, not audit rows: an R10 job has no tenant identity,
and the audit log does not use a pseudo-tenant for global work.

The initial API slice includes login, admin tenant/user setup, tenant ring list/detail,
paginated ring evidence, confirm/reject verdicts, paginated per-ring verdict history,
tenant-wide verdict history, read-only model registry and drift history, request IDs, common error responses, and
a database health check. Evidence contains
member account IDs, bank codes, and transaction fields; it does not return account
numbers. The dashboard renders the evidence subgraph and the latest verdict history on
each ring detail page. The evidence endpoint is
`GET /tenants/{tenant_id}/rings/{ring_id}/evidence`; use `limit` (1–500) and the returned
`next_before_edge_id` as `before_edge_id` to fetch older edge IDs. The history endpoint is
`GET /tenants/{tenant_id}/rings/{ring_id}/verdicts`; use `limit` (1–100) and the returned
`next_before_id` as `before_id` to page backward. The operations endpoints are
`GET /tenants/{tenant_id}/models` and `GET /tenants/{tenant_id}/drift`; both are read-only
and tenant-scoped. Model responses omit artifact paths. Drift events never trigger
retraining. Partial verdicts remain unavailable until the L4 regeneration interface is
wired.

The ring queue distinguishes a tenant with no generated rings from filters with no
matches, displays API-provided window text (such as `over 6 h`), and supports exact
ring-ID or account-ID search. Account membership search uses the GIN index added by
migration 0008. The dashboard's Verdicts page links to ring detail, filters by verdict,
analyst, date range, and simulated/real status, shows counts supplied by the API, and
can export all matching rows to CSV. The tenant-wide history endpoint is
`GET /tenants/{tenant_id}/verdicts`; analyst labels use IDs so email addresses are not
exposed.

Load a verified L4 explanation batch after loading its rings:

```powershell
python platform/jobs/load_explanations.py --explanations <explanations.parquet> --run-log <explanations.parquet.log.json> --rings-log <tenant-rings.parquet.log.json>
```

The loader requires the adjacent L4 and tenant-rings logs, the configured rings schema
version (`l4.rings_schema_version`, currently version 1 for this repository's exact
22-column `contract/schema.py` contract), an explicit tenant-scoped ring run, matching
model/seed/aggregator, converted-currency policy, and complete ring reproduction. It
rejects unknown ring column layouts, global or stub outputs, and any
batch with non-reproduced rings. It matches each explanation to an existing tenant
ring and checks that weighted edges and accounts are members before upserting. The
API exposes the newest saved explanation at
`GET /tenants/{tenant_id}/rings/{ring_id}/explanation`; model/map file paths in
the source provenance remain private.

Explanation regeneration is handled by a separate loader-role worker. The
`l4.regenerate_url` setting is `null` by default, which disables regeneration;
`l4.regenerate_timeout_seconds` defaults to 120. The adapter reads its bearer
token from `RINGSHIELD_XAI_TOKEN`. Worker job IDs use the form
`<tenant_id>.<uuidhex>` so the worker can set tenant context and scope every
query before it loads a job. The fake-server demo is planned for Part C.

Load contract files with
`python platform/jobs/load_contract.py --scored-edges <path> --rings <path> --scope tenant`.
Each parquet must have a sibling `.log.json` declaring `split: test`; label and
ground-truth paths are rejected. The active detector pair comes from
`platform/config.yaml`. Scores are stored in `edge_scores`, keyed by tenant, edge,
model ID, and seed, so loading another model cannot replace an earlier model's scores.
Create the bank registry from the normalized account map with
`python platform/jobs/seed_tenants.py --account-map data/processed/account_bank.parquet --loaded-bank <code>`;
repeat `--loaded-bank` after the ring-member analysis determines which tenants to load.
The data-loading path duplicates each edge for every loaded endpoint bank and
validates that each tenant ring refers only to edges visible to that tenant. Use
`--scope pooled` for full-graph rows, which are stored under reserved internal
tenant ID `-1` and are only intended for admin/R10 queries.

Build tenant-scoped rings from the active pair in `platform/config.yaml` through the
existing research CLI. The configured pooled score cutoff is applied unchanged to each
tenant; the wrapper derives the CLI percentile needed to express that exact score cut.

```powershell
python platform/jobs/build_tenant_rings.py `
  --tenant-id <bank-code> --tenant-id <bank-code> `
  --output-dir data/platform_tenant_runs/gine_causal_seed1
```

The job writes a visible-edge ID subset and one tenant ring parquet plus its run log
for each bank. It checks that every member, seed, and expanded edge has an endpoint at
that tenant. The schema's pooled rule stamps the sender bank of the earliest seed edge;
tenant-scoped runs intentionally stamp the requested tenant ID because a cross-bank
edge is visible to both endpoint banks. Feed tenant ring files to L4; global `rings_full`
outputs do not satisfy tenant isolation.

Survey the top banks by incident visible-edge count and the banks with the most seed
edges at the active detector cutoff, without loading anything into the database:

```powershell
python scripts/survey_tenants.py --top 30
python scripts/survey_tenants.py --top 100 --output reports/tenant_survey_top100.csv
```

The CSV includes the union of the top N banks by visible-edge count and the top N by
seed-edge count under the active cutoff, with the selection reason for each bank. The
exact rules, ranked bank IDs, active model/cutoff, and selected union are written beside
the CSV in its `.log.json` file. Ties break by ascending bank ID.

For a deterministic synthetic database test fixture, generate and load the two-tenant fixture:

```powershell
python platform/jobs/make_demo_fixture.py --output-dir data/platform_demo
python platform/tests/isolation/attach_fixture_logs.py data/platform_demo
## Set RINGSHIELD_PLATFORM_CONFIG=platform/tests/isolation/config.test.yaml for these demo rows.
python platform/jobs/seed_tenants.py --account-map data/platform_demo/account_bank.csv --loaded-bank 210 --loaded-bank 220
python platform/jobs/load_contract.py --scored-edges data/platform_demo/scored_edges.parquet --rings data/platform_demo/rings.parquet --scope tenant
```

The fixture has a shared four-edge ring, one edge visible only to bank 220, and one
edge visible to neither loaded tenant. It includes no account numbers or labels. The
`manifest.json` records the expected edge and ring visibility. Once the API is running,
create analyst users for tenants 210 and 220 through `POST /admin/users` using the
admin account; fixture generation does not create passwords or users.

Set `RINGSHIELD_TIME_ORIGIN_UTC` to the UTC instant represented by loader timestamp
zero before using ring routes. L4 explanations are available after the verified batch
loader runs; partial verdict regeneration still needs a callable L4 regeneration
interface before the platform can safely make that workflow atomic.

### Simulated verdict cycles (L6-A)

The simulator uses the configured `l6.simulator` values and test-visible truth.
Review intervals must fit completely inside the permitted test window, days 8–17;
validation truth (`val`, days 6–7) is rejected for test-window reviews. With the
configured one-day cycle, a valid command shape is:

```powershell
python platform/jobs/simulate_verdicts.py --tenant-id 210 --cycle-day 8 --truth-window whole
```

This is CLI syntax, not a claim that the command was executed. It requires a
configured test truth parquet, a seeded per-tenant
`simulated.analyst@tenant<ID>.local` account, and
`RINGSHIELD_SIMULATOR_DATABASE_URL` configured for the restricted
`ringshield_simulator` role. Optional `--seed`, `--accuracy`, and
`--review-fraction` override configured defaults. The simulator role is separate
from the API and its RLS policy binds simulated inserts to the active tenant
context. The Postgres acceptance test verifies cross-tenant writes are rejected.

### L6-A retraining

Retraining can be started with `POST /tenants/{tenant_id}/retrain` by a supervisor of that tenant. Poll `GET /tenants/{tenant_id}/retrain/{run_id}` for status and the most recent log lines. Administrators cannot start or inspect tenant retraining runs. API responses omit model artifact paths, and log lines replace absolute paths with file names.

The job verifies the committed holdout checksum before using labels. It promotes a candidate only when `ring_f1 >= current_ring_f1 - l6.retrain.epsilon`; a research CLI result with `retrained: false` is always stored as unpromoted and is not evaluated. A promoted candidate refreshes open tenant rings through the existing tenant builder; rings with verdict history remain unchanged.

The real holdout is not included in this checkout. Before running L6, supply the validation GFP file, the active detector/seed's validation embeddings file, and `amlworld_ring_ground_truth.parquet`; set their exact paths in `platform/config.yaml`, then run `python platform/scripts/make_holdout_manifest.py --truth <actual-truth-file>`. The script refuses to overwrite a manifest or checksum. The checked-in test manifest is a fixture only.
