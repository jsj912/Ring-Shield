# L5/L6 platform build plan

The platform wraps the completed research pipeline with tenant-scoped storage,
investigator workflows, and operational controls. It calls the research CLI and L4
explainability interface; it does not reimplement scoring, feature generation,
ring aggregation, or explanations.

## Decisions carried forward

- An edge is visible to tenant `t` when `from_bank = t OR to_bank = t`. The
  `tenant_id` on `scored_edges` is the sender bank and is not the visibility rule.
- Load one tenant-visible copy per distinct bank in `{from_bank, to_bank}`. Build
  tenant queues only from tenant-scoped ring runs and stamp those rings with the
  tenant that ran them. Pooled rings are for admin/R10 only.
- AMLworld has 30,470 bank codes and no bank-name table. Display `Bank <code>`.
- Never put `account_number` in platform tables or API responses.
- Do not convert currencies. The rings contract supplies `total_amount`,
  `total_currency`, and `n_currencies`; the dashboard only formats those values.
- Keep CLI imports CPU-only. The platform install must not require torch.
- Do not interpret R10 until the bank-size analysis and tenant fixture are ready;
  do not group banks to manufacture tenant size.

## Implementation sequence

### 0. Research and L4 contracts

1. Finalize `contract/schema.py` additions for dominant-currency totals and ship
   deterministic currency/payment-format maps.
2. Add `--tenant-id` to the research `run` command. Make `run` and `eval` work
   without importing torch.
3. Implement genuine retraining in `ringshield train`; verify it refits the
   expansion, affinity, and typing components from approved labels.
4. Commit a fixed `holdout_manifest.json` and deterministic two-tenant fixture pack.
5. Obtain L4's explanation schema, call surface, fixture record, and partial-verdict
   regeneration/failure behavior (see `PLATFORM_INTEGRATION.md`).

### 1. Storage and tenant isolation

1. PostgreSQL schema/Alembic migration for tenants, users, tenant-visible edges,
   rings, explanations, verdicts, model versions, retrain runs, drift events, and
   audit log. Preserve unmodeled contract fields in JSONB.
2. Apply row-level security to every tenant table. Use a non-owner application DB
   role without `BYPASSRLS`; set tenant context with `SET LOCAL` from verified JWT
   claims on every request. Admin reads are explicitly role-gated.
3. Idempotent contract loader keyed by `(tenant_id, edge_id)` and
   `(tenant_id, ring_id)`; reject incompatible files and never load ground truth.

### 2. API and identity

Implement JWT login (bcrypt, 8-hour expiry), role checks, request IDs, common error
shape, tenant-scoped ring list/detail/subgraph, explanation, verdict history,
verdict submission, model/retrain, drift, admin, and health endpoints. Check path
tenant against token before querying. Use cursor pagination and stable filters.

### 3. Workflows and dashboard

Implement confirm/reject/partial verdicts, require a note for partial, audit every
state change, and regenerate ring plus explanation before reporting partial success.
Build Streamlit login, queue, detail/evidence graph, verdict history, models, drift,
and admin screens. UI does no inference or financial arithmetic.

### 4. Operations and experiments

Implement retrain job lifecycle, frozen-holdout promotion gate, only-promoted-model
rescoring, daily ADWIN mean/p99 score events (never auto-retrain), then R10, R11,
and explicitly injected R12. Add Docker Compose, migrations, fixture seeding,
structured logs, scheduler, clean-machine instructions, and CI acceptance tests.

## Raw data needed

API development can proceed against synthetic fixtures. For release-matched tenant
sizes, ground truth and real tenant fixtures, provide `HI-Small_Trans.csv`,
`HI-Small_accounts.csv`, and `HI-Small_Patterns.txt` from the same release, or the
processed ring-ground-truth parquet generated from those exact inputs. The top-bank
ring-member analysis is still pending membership data in `docs/TENANT_SIZES.md`.

## Current state

Implemented so far: SQLAlchemy table definitions, initial Alembic schema/RLS
migration, restricted DB-role grants, transaction-local RLS context helper, JWT
identity/login route, common request IDs and error envelopes, tenant ring list/detail
and paginated evidence-subgraph routes, confirm/reject verdict persistence and audit,
paginated per-ring verdict history, admin tenant/user setup, tenant-registry and
contract-parquet loaders with visibility validation, database health check, and
Streamlit login/queue/detail/evidence UI. A deterministic synthetic two-tenant fixture
generator and visibility manifest are also in place. Read-only model registry and drift
history routes and dashboard screens are in place. Partial verdict regeneration,
explanation, retraining/promotion workflows, drift ingestion/scheduling, Compose wiring,
and end-to-end acceptance checks remain.
`requirements-platform.txt` is the intended CPU-only entry point; dependency
resolution still needs verification.
