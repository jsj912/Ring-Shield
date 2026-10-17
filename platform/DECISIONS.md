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

## Migration chain correction — 2026-10-16

- Confirmed the CI collision: `0001_platform_schema` imported `db.models` and called `Base.metadata.create_all()`, which built the current `edge_scores` table; `0003_edge_scores` then attempted to create the same relation.
- Replaced `0001` with explicit, frozen `op.create_table` and index declarations; it no longer imports ORM models. `0003` now owns the score-table addition, creates it once with forced RLS and grants, and removes the four detector-cache columns from `transactions`. The ORM and loader no longer write those moved columns.
- Ring evidence now reads calibrated score and seed flags from the active `(model_id, seed)` row in `edge_scores`, keeping the API aligned with the storage move.
- Added a disposable-Postgres migration integration test. It migrates to 0002 and head, downgrades to base, upgrades to head again, runs `alembic check`, and checks every tenant table has enabled and forced RLS. CI runs `alembic check` after `upgrade head` and before roles/fixture seeding.
- Collision review: no duplicate table, index, constraint, or policy names remain across 0001–0003. Revision 0002 creates `ringshield_api` and `ringshield_loader` conditionally; the later `roles.sql` conditionally creates those same roles, so it does not issue duplicate `CREATE ROLE` statements. `roles.sql` repeats the grants for `edge_scores` after 0003; PostgreSQL grants are additive/idempotent, so this is redundant but not a failing collision. 0003's table/index/policy names are unique to that revision. The `edge_scores_tenant_id_seq` owner alteration was removed because this table has no serial column or sequence.
- PostgreSQL migration/RLS execution was unavailable locally; CI must pass before acceptance is verified.

## Authentication dependency correction — 2026-10-16

- Removed Passlib and use bcrypt directly for password hashing and verification. Passwords over 72 UTF-8 bytes are rejected with a clear validation error at login and user creation; values are never truncated.
- The auth router creates its short-secret dummy bcrypt hash at import time so unknown users still exercise a bcrypt check. The RLS fixture seeder now creates bcrypt-compatible fixture hashes.
- Added exact platform dependency pins, including `bcrypt==5.0.0`, and separate pinned pytest/httpx development dependencies. CI, Docker test image, and the Windows database test script install from `requirements-dev.txt`.
- Added a database-free test that imports `api.main`, hashes and verifies a password, and checks the 72-byte boundary.
- `python -m compileall platform` passed. The available virtual environment lacks SQLAlchemy, so pytest collection could not run locally; CI must execute the new test.

## L6-A retraining and simulator setup - 2026-10-17

### Findings

- `ringshield/__main__.py::cmd_train` validates the documented label columns, copies the base model, appends confirmed labels to `extra_labels.parquet`, increments the version, and writes `version.json` with `retrained: false`; it does not learn new weights. Any platform candidate from this command must remain unpromoted.
- The research CLI `run` accepts `--scores`, `--model-dir`, `--aggregator full`, `--gfp`, `--embeddings`, and `--out`; its run log is JSON. `eval` accepts `--rings`, `--truth`, `--holdout`, `--window`, `--scope`, and `--out`, and writes a metrics JSON containing `ring_f1`. The holdout filter uses truth ring IDs.
- `ModelVersion` has a partial unique index on `(tenant_id, component)` where `promoted IS TRUE`. `Verdict` and `Ring` use tenant-scoped keys; the loader uses `RETURNING` to count preserved non-open rings.
- The active pair remains `gine_causal` / seed `1`. The repository contains `contract/out/scored_edges_gine_causal_1_val.parquet` and its sibling log, whose split is `val`. It does not contain a validation GFP parquet, validation embeddings for seed 1, or an `amlworld_ring_ground_truth.parquet` file. The base model configured for this pair exists at `models/artifacts/full_gine_causal_seed1`.
- Typing is excluded from retraining because verdict rows do not carry a pattern-type label.

### Changes

- Added the `l6` config values from the task. Unavailable validation GFP, validation embeddings, and truth paths are explicit `null` values. The holdout manifest targets are configured but will not be created until the real validation truth file is available.
- Added `load_l6_config`, which validates required numeric settings, supported components, required evaluation window/scope, and presence of each artifact path without guessing or silently substituting a different input.

### Verification and blockers

- No ground-truth file was found in the repository, so `platform/holdout/holdout_manifest.json` and its checksum have not been generated. The exact missing files are listed above; no placeholder manifest is treated as the dataset holdout.
- Postgres is unavailable in this environment. L6 database integration tests will be written for CI and are not claimed to have run here.

## L6-A adapters - 2026-10-17

### Changes

- Added typed, subprocess-only wrappers for research `run`, `train`, and `eval`. Each fails on a nonzero exit, validates its JSON artifact, and returns a dataclass; training reads the actual `version.json.retrained` flag rather than assuming success means learning occurred.
- Added a read-only validation truth adapter using the existing days 6-7 `val` window and `test_visible` rule, plus deterministic best-Jaccard matching. The adapter returns corrected truth members and the true simulator label without putting truth access in API code.
- Added database-free tests for the three CLI wrappers, their failure behavior, the `retrained=false` result, and truth matching.

### Verification

- `platform/tests/test_l6_adapters.py` and full database-free platform tests are pending the current implementation pass; no Postgres execution is claimed.

## L6 truth holdout preparation - 2026-10-17

- Added `platform/scripts/make_holdout_manifest.py`. It uses the truth adapter's val-window/test-visible ring IDs, sorts IDs, records source name and count, writes a SHA-256 sidecar, and refuses to overwrite either output.
- The real manifest and checksum were not created because the required validation truth parquet is absent. Added a clearly labeled fixture manifest/checksum and database-free tests for digest integrity, overwrite refusal, and missing-input behavior; the fixture is not a substitute for the AMLWorld holdout.

## L6 research import boundary - 2026-10-17

- Added a source scanner that rejects research-library imports and literal ground-truth paths outside `platform/adapters/`, `platform/jobs/simulate_verdicts.py`, `platform/experiments/`, and `platform/scripts/`. Its negative-control test verifies it catches both kinds of violation.
- `platform/jobs/build_tenant_rings.py` previously imported the research CC module for a constant and a one-line NumPy percentile calculation. It now uses the same score column and NumPy linear percentile locally, keeping output behavior unchanged while satisfying the requested boundary.
- The scanner test is database-free; the Postgres suite remains unavailable locally.

## L6 simulated verdict cycle - 2026-10-17

### Changes

- Added a deterministic `simulate_cycle` job. It selects open tenant rings whose start times fall in the configured cycle day, orders by confidence descending, reviews `ceil(review_fraction * open_count)`, matches only through the ground-truth adapter, and applies seeded accuracy noise. Partial corrections use truth members intersected with the ring and keep only member edges whose two endpoints are corrected.
- Added a dedicated per-tenant simulated analyst account to the tenant seeder. The CLI requires that account and a tenant-matching non-admin actor; its function rejects admins before reading truth or opening a DB session.
- Refactored API verdict persistence into `platform/services/verdicts.py`; API and simulator share status update, verdict insert, and audit-log behavior.
- Added a separate simulator connection URL and no-login simulator role. It can select tenant-scoped ring/transaction data, select limited analyst identity columns, update only `rings.status`, and insert verdict rows. Migration 0004 tightens `verdicts_simulator_insert` so both `app.tenant_id` and analyst role are required in addition to the simulator role and `is_simulated=true`.
- Added database-free tests for perfect/noisy outcomes, deterministic seeds, review rounding, simulator flags, shared persistence, and admin rejection. Added a real-Postgres test that proves the simulator can write simulated verdicts only for its transaction-local tenant; CI provisions its restricted login.

### Security review and verification

- The first simulator grant draft was rejected by automatic review because its simulated insert policy was not tenant-bound. The final migration adds the tenant check and analyst-role check to the policy before granting the role; the former broad simulator policy is not retained.
- `pytest platform/tests --ignore=platform/tests/isolation -q` passed: **52 passed**. `python -m compileall platform -q` and `git diff --check` passed. Postgres checks have not run locally.

## L6-A retraining job and API - 2026-10-17

### Changes

- Added a tenant advisory lock, fixed holdout SHA verification, validation split/model/seed provenance checks, latest-per-ring verdict selection (including simulated rows), and verdict-specific label export.
- Per component, the job records a baseline if no promoted version exists, skips below `min_new_labels`, calls the adapter, refuses any `retrained=false` candidate without evaluation, and gates learned candidates at `candidate_f1 >= current_f1 - epsilon`. A successful promotion demotes the prior row and inserts the new promoted row in one database transaction.
- At the time of the initial retraining implementation, promoted candidates were also run through the tenant ring builder. The 2026-10-17 credential/tenant-boundary change below removes that write from the retrain job so its DB write set stays limited to model versions and retrain run state.
- Added supervisor-only POST and GET routes. Cross-tenant and admin requests are rejected before retrain-run queries. Status returns only the last 50 redacted log lines and never exposes artifact or absolute log paths.
- The existing supervisor app role is read-only on `model_versions`; this implementation writes model-version rows through the already-provisioned restricted loader role, while retrain-run state changes use the supervisor role. No new model-registry RLS policy or grant was added. This is an implementation deviation from a supervisor-only DB workflow; it uses the current schema's established model-version writer.
- Added database-free tests for holdout verification, gate boundaries, false retraining, label construction, roll-forward identity, API authorization, log redaction, and the simulator's shared verdict service. Added a real-Postgres concurrency test for the partial unique promoted-version index.

### Verification and blockers

- Database-free suite: **65 passed**. `python -m compileall platform -q` and `git diff --check` passed.
- Postgres was unavailable. The new simulator cross-tenant write test and concurrent model-promotion test are written for CI but have not run locally.
- The default L6 job currently fails fast at `l6.retrain.val_gfp`, because that input path is not supplied. No model training or promotion was run.

### L6-A final verification note

- Added fake-adapter orchestration tests for accepted, refused, and `retrained=false` candidates. At that point accepted promotion invoked tenant roll-forward; the later credential/tenant-boundary change below removes that write from this job.
- The first full test attempt had one incorrect test assertion key (`holdout_ring_f1` instead of the helper argument `f1`); that assertion was corrected. The final database-free suite passed **68 tests**. Windows pytest's default temp folder was access denied in this sandbox, so test runs used the workspace-local ignored `platform/out/pytest-tmp` directory.
- `python -m compileall platform -q` and `git diff --check` passed. No Postgres tests executed here; the RLS and concurrent-promotion checks remain CI-only.

## L6 retraining credential and tenant boundary - 2026-10-17

- The supervisor runtime role has SELECT-only access to `model_versions`, while the established restricted loader role has the grants required to insert candidate versions and atomically demote the previous promoted version. Retaining that split is a deliberate deviation from a supervisor-only retraining workflow; no verdict or ring write grants were added to the loader role.
- Retraining now uses tenant-bound loader sessions and supervisor sessions. Tenant predicates appear on every tenant-table read and update, and inserted registry/run rows carry `tenant_id`. The tenant advisory lock carries the same tenant context and is released before the pooled connection is reset.
- The API writes the initial `retrain_runs` row with its restricted app role and launches `jobs.retrain_worker` as a separate process. API modules do not import loader sessions or read `RINGSHIELD_LOADER_DATABASE_URL`; the child process uses its own runtime environment and API database sessions use `RINGSHIELD_DATABASE_URL` (the app role). The API boundary test scans all API modules for loader credential reads and imports.
- Added database-free checks for the API credential boundary and child-process handoff. Added a PostgreSQL acceptance test that runs an accepted tenant A promotion with tenant B fixture data present, compares tenant B row JSON before/after, checks protected table rows and observed tenant-bound SQL, verifies run/model-version changes, checks active DB roles, and confirms the loader role cannot insert verdicts.
- The real-Postgres checks are written for CI and were not run locally because PostgreSQL is unavailable. Database-free test results are recorded with this change; they do not establish the Postgres acceptance.
- At this point in the earlier change, promoted model rows did not automatically refresh rings. The PR-38 section below supersedes that behavior by adding a separate refresh process after promotion.

## PR-38 promoted-model ring refresh - 2026-10-17

- Added `jobs.refresh_rings` as a separate child process started only after a promoted model-version row has committed. It reads the promoted artifact for the requested tenant with the supervisor role, builds only that tenant's rings through the existing tenant builder, and writes through `load_rings` using the loader role in a separate transaction.
- Moved roll-forward identity assignment into `jobs.ring_roll_forward` for shared use and tests. Only open rings with no verdict can be matched, at member Jaccard >= 0.5; each old identity is assigned at most once. New IDs use `full-<model>-<seed>-v<version>-<idx>` and skip every ID already present. Verdict-bearing ring IDs are reserved and their rows are protected by the loader's open-status upsert condition.
- Existing identities other than a matched open ring are asserted unchanged by their full row JSON in the Postgres refresh acceptance. The acceptance also checks the promoted ring's Jaccard, every tenant B row across tables with `tenant_id`, and that an unmatched ring gets a fresh ID. `load_rings` reports writes with `RETURNING`, not `rowcount`.
- Retraining does not write rings itself. It invokes the refresh child as a second process step after promotion and records success/failure in the retrain log. A refresh failure sets the retrain run to failed while the earlier committed promotion remains present. No refresh process starts for a rejected or `retrained=false` candidate.
- The API credential boundary test is extended to reject any loader URL read or loader-session import under `platform/api`. The API launcher does not explicitly pass loader credentials; deployment must make the worker's own environment available to the child process without adding loader-credential reads to API code.
- Added database-free matcher/orchestration/boundary tests and `tests/isolation/test_refresh_rings_real_db.py` for the database acceptance. PostgreSQL is unavailable in this environment, so that acceptance was written but not run. The accepted-promotion real-DB retrain test stubs the child launcher to keep its test focused on retrain's tenant-scoped registry write set; the refresh behavior is exercised by its own PostgreSQL test.
- Builder compatibility constraint: the existing tenant builder requires a full-aggregator model artifact matching `active_model_id` and `active_seed` in `platform/config.yaml`. A promoted artifact that fails this existing contract causes refresh to fail with a reason in the retrain log; the model promotion remains committed. This check is retained rather than bypassed.
- Verification for this change: database-free suite **74 passed**; compileall and `git diff --check` passed. Three PostgreSQL cases were written/updated for CI (one refresh test and two retrain outcomes); none ran locally.

## CI #12 retrain isolation test cleanup - 2026-10-17

- Confirmed the reported leak: the retrain test's `finally` removed the two baseline rows by their `retrain-test-...` tags, but the promoted candidate uses `v2-{run_id[:8]}`. That candidate remained promoted for tenant 210, causing the next parameter case to violate `uq_model_versions_promoted`. The cleanup also only knew the retrain run IDs it expected and could not detect unexpected rows left by a failing job.
- Added defensive pre-test cleanup for this test's owned expansion baselines, interrupted retrain runs, and candidate artifacts, scoped by tenant/component and creation/run metadata. The test snapshots all tenant table primary keys for tenants 210 and 220 and unconditionally removes rows added during the test in foreign-key order, beginning with `retrain_runs` and deleting `model_versions` after their references.
- Added a session-end isolation fixture that scans rows for registered test run identifiers and fails the pytest session if any remain. The retrain cases register their full IDs and candidate tag token; the refresh, composite-ring, and concurrent-promotion tests register their identifiers too. The concurrent-promotion test now deletes by returned model-version ID, and ring composite-key tests clean up in `finally` even if loading or API assertions fail.
- To run one retrain parameter case in CI, use the full pytest node ID, for example `pytest 'platform/tests/isolation/test_retrain_tenant_binding_real_db.py::test_retrain_job_is_tenant_bound_and_loader_cannot_write_verdicts[0.45-False]'`. The promoted case is `[0.95-True]`; each test uses a unique run ID and performs setup cleanup, so it can run alone or in either order.
- Postgres was unavailable for this change. Database cleanup and session-leak checks are written for CI and were not run locally.

## L6-B daily drift monitoring and scheduler - 2026-10-17

- `DriftEvent` already constrained `monitor` to `adwin_score_mean` and `adwin_score_p99`; no change to the frozen `0001_platform_schema` check was needed. River `0.22.0` was already pinned in `platform/requirements.txt`. PyPI records this release as uploaded on 2024-11-25, so it is well beyond the requested two-week age requirement.
- Added separate ADWIN detectors for calibrated score daily mean and p99, using the configured active model/seed and `(timestamp - 10) // 86400`. The monitor uses the tenant-scoped app session for reads and the loader role only for event inserts. Events are informational and this module has no retrain import or call.
- Added a unique `(tenant_id, monitor, window_end)` constraint in migration `0005_drift_event_dedupe`; this closes the concurrent-run race that a read-before-write idempotence check alone would leave open. The ORM constraint matches the migration for `alembic check`.
- Added supervisor-only series and acted-on endpoints, a supervisor drift chart/review control, and the supervisor retrain button/status tail. Analysts retain read-only model registry access. APScheduler stays disabled by default; when enabled it launches separate per-tenant worker processes for nightly retraining and daily drift. Drift scheduling does not trigger a retrain.
- The scheduler enumerates loaded tenants with a transaction-local reserved tenant context (`tenant_id=-1`) and an explicit positive `tenant_id` predicate, then creates jobs under a supervisor DB context scoped to each tenant. It does not load or inspect the loader URL in API modules.
- Database-free tests cover step-change detection, flat series, skipped days, retrain boundary, scheduler default/date dispatch, dashboard empty states and API authorization. A real-Postgres integration test covers writer-role idempotence and tenant isolation; it was written for CI and not run locally. PostgreSQL was unavailable.
- No experiment reports are claimed in this section; the actual truth parquet and retraining validation artifacts remain required inputs for the upcoming experiment steps.

## L6-B R10 tenant versus pooled experiment - 2026-10-17

- Added the `r10_tenant_vs_pooled` runner, an admin-only background-job/status API, and an allow-listed separate worker. The runner gets loaded banks from the tenant registry, builds tenant rings through the established tenant job, runs pooled rings through `adapters.research_cli`, and calls the eval adapter for both outputs against the same per-bank test-truth subset.
- Truth membership and account-bank joins use only the ground-truth adapter and the account map's `account_id`/`bank_code` columns. No account-number column is read. Bootstrap intervals use 1000 deterministic resamples over truth rings and the canonical one-to-one Jaccard matcher through `adapters.experiment_metrics`.
- The candidate scan checks configured model/GFP/embedding paths and sibling test logs for seeds 1-5. The current checkout is complete only for seed 1: the other seeds lack matching model directories and embeddings. `amlworld_ring_ground_truth.parquet` is absent and config `l6.retrain.truth_parquet` remains null, so no real R10 table/run manifest was produced.
- Added a cross-bank fixture test where the bank's subset contains the spanning truth ring, pooled recall recovers it, and tenant recall misses exactly that one ring. The experiment reports missing real inputs rather than using fixture metrics.
- API status hides machine paths. The admin endpoint relies on `l6.retrain.truth_parquet` from the single platform config; set that exact test truth path before launching it.
