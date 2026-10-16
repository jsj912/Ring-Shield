# Platform decisions and implementation record

This file records findings and changes in the order requested for the platform hardening work.

## Part 1 — real PostgreSQL tenant isolation

### Findings

- The existing 20 platform tests did not connect to PostgreSQL, so they did not exercise RLS.
- Migration `0001_platform_schema` enables and forces RLS for its current static tenant table list. The tests need to discover tenant tables from PostgreSQL so a future table cannot silently escape coverage.
- The current role provisioning script creates the API role group, but the migration did not create a dedicated table-owner/migration role.
- Docker/PostgreSQL executables are not installed in this environment. The database suite will fail clearly when run without its database instead of skipping; an actual real-Postgres result cannot be claimed here.

### Changes

- Added migration `0002_role_ownership_force_rls`, which provisions a no-login/no-superuser/non-BYPASSRLS table-owner role, transfers public table ownership, and dynamically enables and forces RLS on all public base tables with `tenant_id`.
- Added migration `0003_edge_scores`; it is tenant-scoped and model-specific. The app role has read access, while the loader role owns ingestion writes.
- Added `scripts/test-db.ps1` for Windows Docker Desktop and `.github/workflows/platform-tests.yml` for Postgres 16 CI. Both bootstrap the schema, switch subsequent migrations to the restricted owner role, provision app/auth/loader roles, seed tenants and fixture data, and run `pytest platform/tests -rA`.
- Added a session-level connection guard and a pytest summary counter. The runner reports how many `test_rls_real_db.py` call phases actually ran and exits nonzero when that count is zero.
- Added dynamic real-Postgres isolation tests. They discover all tenant tables from `information_schema`, require seeded rows for A and B in each, check tenant and unset-context reads, forced RLS and app-role flags/ownership, write checks, admin restrictions, cross-bank visibility, score retention, and the API authorization boundary.
- Added a negative-control test that creates an unprotected tenant table in a transaction, asserts discovery names its missing policy, and rolls the transaction back.
- Updated API 403 responses to use `{error_code, message, request_id}` and reject signed cross-tenant paths before the live account lookup or tenant query.
- Added explicit fixture sidecar logs so the loader's test-split requirement is exercised.

### Verification

- Docker/PostgreSQL tests have not run: `docker --version` reports that the command is unavailable in this environment. Therefore **0 real-Postgres RLS tests have executed here**; the acceptance criterion is still pending a machine with Docker.
- The current schema has 12 tables with `tenant_id`; pytest expands the table checks from the database-discovered list. The real Postgres suite remains unrun here; the RLS count is **0** in this environment.

## Part 2 — tenant ring job and ingestion audit

### Findings

- The research CLI computes its seed quantile after applying `--edge-subset`; the prior bank 20 run used a tenant-local cut `q=0.986814`, selected 11 seeds, and produced 3 rings.
- The CLI already stamps `tenant_id` from the explicit tenant argument, rather than the pooled schema rule (sender bank of earliest seed edge).
- The prior job checked member edges against the input edge-ID subset, but did not verify endpoint-bank visibility for all three edge lists.
- Previous platform ingestion stored detector scores on the transaction row and overwrote them on another model load. There was no test-split sidecar enforcement or path-level labels/ground-truth guard.

### Changes

- Added `platform/config.yaml` as the single source for active model `gine_causal`, seed `1`, fixed score cutoff `0.9295209672451074`, and its source (`contract/out/scored_edges_gine_causal_1.parquet.log.json:seed_rule.q`). The loader, tenant builder, and model API use this active pair.
- The tenant builder no longer applies a per-tenant top-percentile rule. It adapts the existing CLI percentile input to the fixed cutoff and checks that the resulting seed edge IDs exactly match `score_raw > seed_score_cutoff`. Tenants whose maximum visible score is below the cutoff get zero seeds. The run log records the configured cutoff, source, CLI quantile, effective percentile, model pair, and tenant assignment deviation.
- Every produced ring is checked for the requested `tenant_id`; `member_edges`, `seed_edges`, and `expanded_edges` are checked both against the tenant input subset and for endpoint visibility.
- Tenant runs explicitly stamp the requested tenant. This is the documented deviation from `contract/schema.py`'s earliest-seed sender-bank rule, needed because a visible cross-bank ring is run independently for both endpoint tenants.
- Ring identity is composite. `Ring` uses `(tenant_id, ring_id)` as its primary key; explanation and verdict foreign keys include both columns; ring, explanation, evidence, and verdict API queries use both values. Dashboard API paths already include the active tenant, and its open-ring and note state now retain tenant ID with ring ID.
- Added a real-DB integration test that loads the same ring ID for tenants 210 and 220, checks neither upsert overwrites the other, and reads each tenant's version through its API.
- Added model-specific `edge_scores` storage so another model load cannot overwrite existing scores. Loaders require sibling `.log.json` metadata with `split=test`, and reject `labels_*` and `*ground_truth*` paths. Cross-currency ring totals are suppressed instead of summed; API responses only expose a total for one currency.
- Added the tenant survey script and its deterministic PR-01 candidate selection rule.

### Verification

- Fixed-cutoff bank 20 rerun: 10,315 visible edges, 21 seeds, 5 rings. The earlier tenant-local quantile run had 11 seeds and 3 rings; under the fixed threshold this changes by +10 seeds and +2 rings.
- `python -m pytest platform/tests --ignore=platform/tests/isolation -q`: **29 passed**.
- Top-30 tenant survey completed and wrote `reports/tenant_survey.csv` plus its selection log. Top results by ring count: banks 1, 12, and 20 each have 5 rings; bank 119 has 4; banks 23, 118, and 220 have 3.
- Local DB-free tests do not replace Part 1's missing PostgreSQL verification.

## Part 3 — tenant survey

### Findings and changes

- Added `scripts/survey_tenants.py`. It independently ranks banks by visible-edge count and by visible seed-edge count at the active fixed cutoff, breaks ties by ascending numeric bank ID, and surveys the union of each top-N list. It reports visible edges, seed edges, ring counts, rings with at least five members, unique member accounts, and the share of ring-member edge appearances that are cross-bank. It writes CSV and a JSON provenance log, and does not write to the database.

### Verification

- The top-30 survey completed with the active model/seed and fixed cutoff. It printed the top 10 banks by ring count and produced `reports/tenant_survey.csv`.
- Bank 213 had no scores above the fixed cutoff and correctly produced zero seeds and zero rings.
- The top-100 survey covered 157 banks: 100 selected by visible-edge count and 100 by seed-edge count at the active cutoff, with 43 shared between lists. The CSV and log are `reports/tenant_survey_top100.csv` and its `.log.json` sidecar.
- Proposed demo tenants, ranked by rings with at least five members descending, then total ring count descending, visible-edge count descending, and bank ID ascending: **12 (2 qualifying / 5 total rings), 20 (2 / 5), 21749 (2 / 2), 21611 (2 / 2), 11128 (2 / 2)**. These are proposals only; none were loaded into the database.

## Part 4 — commit hygiene

### Findings

- Commits follow the requested order, with migrations/RLS last; no push is being made. Each commit is preceded by a database-free test run, `git status`, staged path hygiene check, and `git diff --check`.
- `.gitignore` and `.dockerignore` exclude local data, parquet sidecars, credentials, and temporary test dependencies from staging and Docker build context.
- Postgres RLS acceptance is not verified here because Docker/Postgres are unavailable; only a nonzero database-backed count from the Windows script or CI verifies that acceptance.
