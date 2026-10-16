# RingShield platform layer

This package is the L5/L6 application layer around the research pipeline. It owns
tenant isolation, authentication, API contracts, verdicts, model operations, drift
events, and the investigator dashboard. Model inference and ring aggregation remain
behind adapters to the existing research CLI and explainability functions.

The implementation is being built in vertical slices, beginning with the API and
database foundation described in `directions/RingShield_L5_L6_Platform_Spec.docx`.

Install the CPU-only API dependencies with `pip install -r requirements-platform.txt`.
For the database-free platform unit tests, install `pip install -r requirements-platform-test.txt`
and run `python -m pytest platform/tests` from the repository root.
Copy `platform/.env.example` to the repository root as `.env` and provision the
database URLs and passwords. Set `RINGSHIELD_MIGRATION_DATABASE_URL` to the schema
owner first, then create the schema and restricted roles in this order:

```powershell
alembic -c platform/alembic.ini upgrade head
psql $env:RINGSHIELD_DATABASE_ADMIN_PSQL_URL -f platform/db/roles.sql
```

Provision the separate runtime/auth/loader/simulator login users and grant them
membership as documented at the end of `platform/db/roles.sql`. The API and auth
URLs must use those restricted non-owner roles. Start the API with:

```powershell
uvicorn api.main:app --app-dir platform --env-file .env --reload
streamlit run platform/dashboard/app.py
```

The initial API slice includes login, admin tenant/user setup, tenant ring list/detail,
paginated ring evidence, confirm/reject verdicts, paginated per-ring verdict history,
read-only model registry and drift history, request IDs, common error responses, and
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
Load contract files with
`python platform/jobs/load_contract.py --scored-edges <path> --rings <path> --scope tenant`.
Create the bank registry from the normalized account map with
`python platform/jobs/seed_tenants.py --account-map data/processed/account_bank.parquet --loaded-bank <code>`;
repeat `--loaded-bank` after the ring-member analysis determines which tenants to load.
The data-loading path duplicates each edge for every loaded endpoint bank and
validates that each tenant ring refers only to edges visible to that tenant. Use
`--scope pooled` for full-graph rows, which are stored under reserved internal
tenant ID `-1` and are only intended for admin/R10 queries.

For a deterministic synthetic smoke dataset, generate and load the two-tenant fixture:

```powershell
python platform/jobs/make_demo_fixture.py --output-dir data/platform_demo
python platform/jobs/seed_tenants.py --account-map data/platform_demo/account_bank.csv --loaded-bank 210 --loaded-bank 220
python platform/jobs/load_contract.py --scored-edges data/platform_demo/scored_edges.parquet --rings data/platform_demo/rings.parquet --scope tenant
```

The fixture has a shared four-edge ring, one edge visible only to bank 220, and one
edge visible to neither loaded tenant. It includes no account numbers or labels. The
`manifest.json` records the expected edge and ring visibility. Once the API is running,
create analyst users for tenants 210 and 220 through `POST /admin/users` using the
admin account; fixture generation does not create passwords or users.

Set `RINGSHIELD_TIME_ORIGIN_UTC` to the UTC instant represented by loader timestamp
zero before using ring routes. The dashboard and L4 explanation adapter wait on
their respective interfaces.
