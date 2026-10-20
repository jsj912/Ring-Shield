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

## Frozen production validation holdout - 2026-10-20

- Adopted the research lead's `platform/holdout/production/holdout_manifest.json` unchanged. Its file SHA-256 is `32f7443a4dc5c6d3658f668bc269620cb2a284bb94d3e0197a651232cb267686`; its canonical `content_sha256` is `a1e1c13c5588407ac31fb1f6b13745b25bec94bbc699a699a8e678ead4795f06`. The file contains 114 unique validation-window truth IDs for days `[6, 7]`.
- Added the matching file-hash sidecar and production-only verifier checks: canonical content digest over the specified nine keys, required hashed keys, exactly 114 unique IDs, and days `[6, 7]`. The three-ID fixture and its existing tests remain unchanged and continue to use the original file-hash verification.
- `l6.retrain` now defaults to the frozen production manifest and sidecar. No ground-truth parquet, validation features, embeddings or other truth data were added, and no production holdout was regenerated.
- `platform/scripts/make_holdout_manifest.py` remains for disposable tests only and continues to refuse overwriting either output. Never use it to regenerate the frozen production holdout. This decision supersedes earlier entries stating that the production manifest was absent.
- Database-free production/fixture verifier tests were added. Docker/PostgreSQL and the retrain database tests were not run in this environment.

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
- Added supervisor-only series, manual check, and acted-on endpoints, a supervisor drift chart/review control, retrain-run history with a “No retraining runs yet” empty state, and the supervisor retrain button/status tail. Analysts retain read-only model registry access. APScheduler stays disabled by default; when enabled it launches separate per-tenant worker processes for nightly retraining and daily drift. Drift scheduling does not trigger a retrain.
- The scheduler enumerates loaded tenants with a transaction-local reserved tenant context (`tenant_id=-1`) and an explicit positive `tenant_id` predicate, then creates jobs under a supervisor DB context scoped to each tenant. It does not load or inspect the loader URL in API modules.
- Database-free tests cover step-change detection, flat series, skipped days, retrain boundary, scheduler default/date dispatch, dashboard empty states and API authorization. A real-Postgres integration test covers writer-role idempotence and tenant isolation; it was written for CI and not run locally. PostgreSQL was unavailable.
- No experiment reports are claimed in this section; the actual truth parquet and retraining validation artifacts remain required inputs for the upcoming experiment steps.

## L6-B R10 tenant versus pooled experiment - 2026-10-17

- Added the `r10_tenant_vs_pooled` runner, an admin-only background-job/status API, and an allow-listed separate worker. The runner gets loaded banks from the tenant registry, builds tenant rings through the established tenant job, runs pooled rings through `adapters.research_cli`, and calls the eval adapter for both outputs against the same per-bank test-truth subset.
- Truth membership and account-bank joins use only the ground-truth adapter and the account map's `account_id`/`bank_code` columns. No account-number column is read. Bootstrap intervals use 1000 deterministic resamples over truth rings and the canonical one-to-one Jaccard matcher through `adapters.experiment_metrics`.
- The candidate scan checks configured model/GFP/embedding paths and sibling test logs for seeds 1-5. The current checkout is complete only for seed 1: the other seeds lack matching model directories and embeddings. `amlworld_ring_ground_truth.parquet` is absent and config `l6.retrain.truth_parquet` remains null, so no real R10 table/run manifest was produced.
- Added a cross-bank fixture test where the bank's subset contains the spanning truth ring, pooled recall recovers it, and tenant recall misses exactly that one ring. The experiment reports missing real inputs rather than using fixture metrics.
- API status hides machine paths. The admin endpoint relies on `l6.retrain.truth_parquet` from the single platform config; set that exact test truth path before launching it.

## L6-B R11 gated retraining experiment - 2026-10-17

- Added the R11 runner for exactly ten simulated test days (8 through 17) at one requested accuracy, with one existing simulator call and one existing gated retrain job per day. Supported accuracy values are 0.90 and 0.70; run each against a restored disposable tenant to keep conditions independent.
- Extended the simulator with an optional `truth_window` argument; its default remains the original validation behavior. R11 explicitly uses the test `whole` window to simulate feedback for the replayed test days, while the retrain job still evaluates against the unchanged validation holdout.
- The no-retrain control is a static lane that repeats the initial promoted holdout F1. If the tenant has no promoted baseline, it evaluates the configured base artifact through the research adapter. It does not execute any train job and is labeled static in `run.json`.
- Per-cycle rows record reviewed/open ring counts, simulated verdicts, retrain status, current holdout F1, control F1, promotions, refusals, and `retrained=false` candidates. If any train adapter output says `retrained=false`, the Markdown report begins with “Retraining was not real in this run; no improvement is claimed.”
- The runner validates all retrain artifacts before creating simulated verdicts and never writes the holdout manifest or checksum. This checkout still lacks truth parquet, validation GFP/embeddings, and the real holdout manifest, so no R11 cycles were run and no result numbers are reported. The database-backed simulation/retraining path also requires Postgres and the isolated app/loader/simulator credentials.

## L6-B R12 injected-shift replay - 2026-10-17

- Added pattern-scoped truth transaction access through the ground-truth adapter, a deterministic first-half removal/second-half reinsertion transformer, and incremental ADWIN replay that shares the production drift detector implementation. The output table compares the pre-insertion rings, post-insertion rings without retraining, and rings after one gated retrain; it includes an explicit no-retrain control row and the required statement “drift was injected, not observed”.
- Real mode requires `r12.model_dir`, an empty dedicated loaded tenant, test scores/truth, matching GFP/embeddings, validation holdout inputs, and the isolated app/loader/simulator roles. It uses the tenant-filtered loader path, builds through the existing tenant ring builder, persists detected events through the loader role, restricts simulated reviews to open rings on detected days, and calls the existing retrain worker once. It writes no data to any other tenant.
- Added `tenant_id` filtering to the contract edge loader so an R12 replay updates only the selected test tenant. Added an optional ring ID filter to the simulated cycle so reviews are limited to flagged-day open rings.
- The current config has `r12.model_dir: null`; the real truth parquet and validation inputs are also missing. The required run for this checkout is therefore `--dry` on a clearly labeled fixture. The fixture's synthetic delay and recall are not AMLWorld/model results and are reported as such; the after-retrain cell is null because no training runs in dry mode.
- Real R12 database mutations and the real gated retrain cannot be executed or verified here. They require Postgres plus the missing research-supplied held-out model and truth/validation artifacts. No real-drift or model-improvement claim is made.

## Tenant-scoped L4 explanation handoff - 2026-10-17

- Updated the explanation loader for the tenant log contract. It now obtains aggregator, model, seed, rings schema version, and currency policy from each row's provenance and requires those identity fields to agree across rows and with the source tenant rings log. The L4 log must declare tenant scope, matching tenant ID, `tenant_view`, full reproduction counts, and an empty `not_reproduced` list. The source rings log must declare the test split, `command=run`, an edge subset, and an explicit tenant rule.
- The loader verifies SHA-256 of the source rings parquet named by the source rings log's `out` (resolved beside that log) against `input_sha256.rings.sha256`. `platform/config.yaml` pins the supplied FX table digest. Both the row provenance JSON and `explanations.fx_rates_sha256` retain that digest; migration 0006 backfills the column from existing provenance when present. New explanation loads bind the loader-role transaction to the single tenant in the handoff.
- The old pooled log shape has no required tenant scope and remains refused. Label and ground-truth path screening now also scans nested log values and row provenance. Currency policy must be `converted`; no raw cross-currency totals are introduced by this loader.
- Ring identity remains the composite `(tenant_id, ring_id)`: `rings` and `explanations` use composite primary keys, and explanations/verdicts carry composite foreign keys. Ring detail, explanation and verdict API routes constrain both keys, while dashboard calls include tenant ID in each ring URL. The isolation test now loads the same ring ID for two tenants with distinct explanations and verdicts and checks each tenant's API response.
- Added database-free handoff acceptance/refusal cases and a real-Postgres synthetic handoff load test that checks stored provenance and FX hash. The Postgres tests, including the cross-tenant ring collision/API case, were not run locally because PostgreSQL is unavailable. Database-free suite: **110 passed**; compileall and `git diff --check` passed.
- No research data was added to Git. The database acceptance uses a generated synthetic handoff; no claim is made about executing the received bank 20 or bank 12 artifacts in this environment.

## Windows local demo runner - 2026-10-18

- Added `scripts/run-demo.ps1` and a separate `docker-compose.dev.yml` project/volume, using port 55433 by default so the test Postgres port remains separate. The runner reuses the test harness migration-role and login-role SQL, `roles.sql`, `seed_tenants.py`, `load_contract.py`, and `load_explanations.py`; it runs `alembic check` before loading.
- Each bank's edge load is invoked separately with `--tenant-id`, so the loader transaction has that tenant context and explicit tenant selection. Cross-bank edges are copied to each listed endpoint tenant by the existing loader. Rings and L4 handoffs are then loaded with the tenant-specific source logs. The runner checks source edge-ID counts, five rings per tenant, matching explanation counts, and the stored row counts for each selected tenant across every table with `tenant_id`.
- API child environment is built from the restricted app and auth URLs; migration, admin, simulator, and loader URLs are removed, and `PYTHON_DOTENV_DISABLED=1` prevents a local `.env` file from injecting them. Application analyst/supervisor/admin passwords are generated once and stored in ignored `platform/demo-credentials.txt`; passwords are not printed. `-Down` keeps the volume and credentials; `-Down -DropVolume` removes both.
- Added a standalone Windows PowerShell validation test for valid inputs, a missing required input directory, non-positive tenant IDs, `labels_*`, and `ground_truth` paths. Five checks passed locally. Database-free platform suite: **110 passed**; compileall and `git diff --check` passed.
- Made the migration-role provisioning repeatable and the runner inspect the existing Alembic revision before bootstrapping, so reruns do not attempt to move a populated demo database backwards. Existing demo credentials are retained and extended if more tenants are selected later.
- Docker Desktop and Postgres were unavailable in this environment. The compose startup, migrations, role checks, data loads/count expectations, API health check, dashboard startup, and `-Down` behavior are implemented but were not run. The expected counts in the README come from the supplied target values and are enforced at run time; they are not locally verified. No research data was added.

## PowerShell demo runner correction - 2026-10-18

- Renamed the `$host` and `$args` locals that collided case-insensitively with PowerShell's read-only automatic variables, changed the input iteration local, and removed explicit use of the automatic `$Matches` value by parsing credential lines with `Regex.Match`. Removed direct assignments to `$ErrorActionPreference`; file operations that must stop now use explicit `-ErrorAction Stop`.
- Added a PowerShell AST validation that parses both the runner and validation script and rejects assignment targets matching automatic or preference variable names without regard to case. The existing input/path checks remain in the validation script.
- Audited external process calls: Python and Docker commands check `$LASTEXITCODE` and identify their step on failure; Postgres readiness polls `pg_isready` inside the demo container with a timeout. Compose calls continue to pass the quoted compose path as a single argument, with the isolated `ringshield-demo` project and its own named volume.
- Reruns now continue migrations from any recognized/intermediate revision by upgrading to head, and idempotent loaders, seed upserts, persistent credentials, and prior-process cleanup are retained. The API child environment removes loader and administrative credentials before launch.
- Docker/Postgres was not run. Static parsing and database-free validation are the only checks for these Windows runtime paths.

## L4 source ring schema version correction - 2026-10-18

- The earlier expectation that tenant explanation provenance must declare ring schema version 2 was incorrect for this checkout. `contract/schema.py` defines the shipped 22-column `RINGS_ORDER`, which is schema version 1; the real L4 rows correctly declare version 1. `platform/config.yaml` now requires `l4.rings_schema_version: 1`.
- The explanation loader derives the source ring version from the source parquet: exact `RINGS_ORDER` is version 1, a unique 30-column layout is version 2, and other layouts are refused. The detected source version must equal configuration and every explanation row's version. Mismatch errors report both versions; the previous tenant, hash, active model/seed, FX, reproduction, and label-path checks remain.
- Updated the database-free handoff fixtures and the CI-only real-Postgres fixture from assumed version 2 to the exact version 1 ring shape. Added cases for v2 rows against v1 rings, mixed row versions, v1 rows against 30-column rings, and an unknown ring column set. The older pooled-format refusal remains covered.
- Database-free suite: **120 passed**; `compileall` and `git diff --check` passed. Docker/Postgres was not run; CI remains responsible for the database-backed handoff test.

## Tenant L4 UNKNOWN topology values and read-only preflight - 2026-10-18

- The received tenant L4 files have no typing head: their source rows use `topology_type=UNKNOWN` and `topology_prob=NaN`. The loader now accepts null/NaN probability only for `UNKNOWN`; infinities are always refused, and every named topology still requires a finite probability in `[0, 1]`. For `UNKNOWN`, it does not compare or persist that explanation topology value; the loaded ring's topology remains authoritative. Existing optional nested numeric handling continues to convert NaN values such as optional account hold time to JSON null.
- Added database-free tests for UNKNOWN with NaN and null, named topology with NaN, positive/negative infinity, and out-of-range probabilities. Existing pooled and other handoff refusal cases remain in place.
- Explanation handoff tests: **32 passed**. Docker/Postgres was not run.

## Read-only L4 handoff preflight - 2026-10-18

- Added `platform/jobs/check_explanations.py`, which invokes the loader's `read_handoff` validator for one or more explanation/run-log/rings-log triples and prints `OK <n> rows` or `REFUSED <reason>`. It performs no database access. `scripts/run-demo.ps1` runs this check after file preflight and before checking/starting Docker, so invalid real handoffs fail before the demo database is touched.
- Read-only check run against the provided local files: bank 12 `OK 5 rows`; bank 20 `OK 5 rows`. This validates the handoff files only; the demo load, Docker and PostgreSQL were not run.
- Added database-free CLI tests for success and refusal output. Full database-free suite: **129 passed**; PowerShell path validation: **6 passed**; compileall passed. No relaxation was made to tenant scope/identity, source-ring SHA-256/schema, active model/seed, FX pin, reproduction, pooled-log, or label-path checks.

## Demo dataset time origin - 2026-10-19

- Removed the demo's implicit `2020-01-01` time anchor. Normal and `-ValidateOnly` runs require `-TimeOriginUtc`, an ISO-8601 instant with an explicit UTC offset or `Z`. It represents loader timestamp 0: first transaction day 00:00 UTC minus 10 seconds. The demo passes this exact value to the API, displays it in its startup summary, and the dashboard sidebar displays the inherited value. `-Down` remains available without an origin so teardown does not depend on application data configuration.
- The fixed `2020-01-01T00:00:00+00:00` value remains only in `scripts/test-db.ps1`, labeled as a deterministic test-only anchor.
- Added PowerShell validation for a missing origin, an origin without a UTC offset, and valid `Z`/offset formats. Updated the documented demo invocation and definition in `platform/README.md`.
- Validation: PowerShell checks **8 passed**; database-free platform suite **129 passed**; `compileall` passed. Docker and PostgreSQL were not run.

## Dashboard auth feedback and demo password reset - 2026-10-19

- Dashboard login 401s are now handled by request path and show the generic `Incorrect email or password.` error without clearing session state or rerunning. Other 401s clear the authenticated keys, preserve a one-time session-expiry notice across rerun, and show it at the login screen. The API's indistinguishable 401 response for unknown email and wrong password is unchanged.
- Dashboard 403s consistently show `Not permitted: your role cannot do this.` and append a request ID only when the API response includes one. They retain the session; the explicit administrator verdict warning remains. Quiet 404s, 204s, and API-unavailable messaging retain their behavior.
- Added `-ResetPasswords` to the demo runner, reusing `Write-DemoUsers` and its existing local admin database connection and direct bcrypt hashing. Reset upserts change only `password_hash` for existing users, with no role/tenant/disabled-state changes; the database transaction writes `user.password_reset` audit rows without credentials. Rotated secrets are persisted to the gitignored credentials file after the DB update and are never printed. No API/app-role permission or API loader credential changes were made. `-ResetPasswords` is rejected with `-Down` and `-ValidateOnly`; `-Down -DropVolume` remains the data wipe path.
- Added database-free Streamlit tests for login failure, session expiry, 403 request-ID behavior, quiet 404, and 204, plus an API-level no-DB test preserving indistinguishable bad-login 401s. Added static PowerShell checks for reset switch/conflict/password output.
- Docker, PostgreSQL, and the demo were not run. Test counts are recorded in the completion report.

## Platform requirements status audit - 2026-10-19

- Added `docs/REQUIREMENTS_STATUS.md`, mapping every PR-01–PR-52 and every FR-D ID in the source specification to code/test evidence, status, remaining work, blocked inputs, and the requested handoff checks.
- Audit is read-only for implementation: no code, tests, migrations or configuration were changed. Status `TESTED` means a named automated test exists; it does not mean that this audit ran the test or verified CI. Database/RLS and R10–R12 execution were not performed.
- Source specs used: `directions/RingShield_L5_L6_Platform_Spec.docx` and `directions/RingShield_Dashboard_Requirements.docx`. No requirement IDs were invented.

## Retrain handoff WP9-WP12 audit - 2026-10-19

- The authoritative 114-ring validation holdout was not present in the checked-in repository or the supplied handoff directory. The three-ID fixture remains test-only; it was not used to produce research results or replace the manifest. Retrain now rejects training labels that overlap holdout ring IDs or contain any edge ID in the configured validation scored-edge file. Candidate evaluation removes every `version.json.training_labels.rings` ID from both prediction and truth allowlists. R12 applies the same exclusion to pattern metrics and computes CYCLE recall only on CYCLE truth IDs left after that exclusion; an empty denominator is reported as undefined.
- Tenant ring edge subsets now deduplicate and sort edge IDs. Identical duplicate rows are accepted; conflicting endpoint or score values for the same edge ID fail closed. Member, seed, and expanded edges are checked against the visible subset and tenant endpoint ownership.
- R10's score-file meaning is unresolved by the research lead. `r10.tenant_score_source` is intentionally null. A run must explicitly select `pooled` or `tenant_visible` in config or with `--tenant-score-source`; tenant-visible mode requires `{tenant_id}`, `{model_id}`, and `{seed}` placeholders and validates each bank's test log against its tenant, active model, seed, and test split. The pooled ring comparison always uses the pooled score file. This is a configurable experiment choice, not a claim that either score interpretation is scientifically correct.
- The repository's actual `ringshield train` CLI accepts only component, labels, base model directory, and output model directory. It does not accept scores, rings, GFP, or embeddings, and its current implementation copies the model with `retrained=false`. The platform adapter therefore cannot truthfully pass those required inputs or claim genuine WP11 retraining. No research code was changed. WP11 remains blocked until the research CLI supports the handoff inputs or the research lead supplies a corrected CLI contract. Platform retraining keeps the existing `retrained=false` gate behavior and refuses to evaluate/promote such a candidate.
- The verdict simulator validates the actual half-open timestamp interval before truth access or either CLI/direct-path database session. Day offsets are computed independently of cycle duration. The default truth window is `whole`; explicitly selected `primary` or `tail` windows are allowed only when the complete review interval fits their configured test bounds. `val` remains unchanged and is refused for simulated test reviews because it is a validation split. The existing epsilon gate tests cover acceptance at the 0.005 boundary and refusal below it; those are code-contract tests, not measured model updates.
- Database-free tests cover these validation paths. PostgreSQL integration, real R10/R11/R12 runs, and research retraining were not run: Postgres, the authoritative holdout, validation features, truth inputs, and supported train CLI are not available in this environment. No holdout, training result, or model improvement was fabricated.

## WP9-WP12 audit corrections - 2026-10-19

- Each retrain run now writes a run-local `promotion-manifest.json`. It records only promoted component versions, each version's training ring IDs, and the exact refreshed ring parquet returned by the separate refresh worker. Refresh output uses a version-specific run key, avoiding artifact overwrites when multiple components promote. A declined candidate is not attached to promotion metrics; failed refresh output fails the job; the DB run's `model_version_id` points only to the last promoted version (or is explicitly cleared to null when none promoted).
- R12 consumes that manifest, verifies tenant/run/status, verifies each promoted DB row and its component/tag, compares the version artifact's training IDs to the run record, and evaluates each version against its own existing refreshed parquet after excluding its training IDs from both prediction and truth sets. Missing output is an error. A successful run with no promotion reports an explicit no-promotion row and leaves post-retrain metrics undefined; it never substitutes pre-retrain rings. Multiple promotions are reported per component/version. No research training claim is made; current research CLI reports `retrained=false`.
- R10 validates all three documented tenant-visible template placeholders and checks the tenant ID in each tenant-specific test log. Pooled selection continues to pass the pooled score parquet for every tenant; `tenant_score_source` remains unresolved and null by default.
- Simulator cycle bounds now follow queried timestamps (`start = day-zero + cycle_day * seconds_per_day`) and are checked as complete intervals against days 8-17. It uses the configured `whole` test window by default. Compatible explicit test windows (`primary`, `tail`, `whole`) remain selectable; the unchanged `val` window is refused for test-period reviews. The CLI performs both interval and truth-window validation before opening its analyst session.
- Synthetic tests exercise A/B visibility for their shared edge, absence from C, per-tenant ring stamping, deterministic duplicate handling, and conflicting duplicate refusal. These are unit tests; no Postgres or real experiment was run.
- The simulator CLI now validates the interval and truth-window before even checking whether the configured truth parquet exists. R10 converts malformed tenant IDs in score logs into `ExperimentInputError`. Config wording distinguishes the pooled comparison baseline from the unresolved operational score source, which remains null until the research lead decides.
# PR-04, PR-10, PR-11, PR-19 and PR-20 release hardening - 2026-10-20

R10 experiment jobs remain file-backed under `platform/out/experiments`; they do not
create a database job table. R10 lifecycle events use structured JSON process logs,
not `audit_log`: an experiment has no tenant, while the audit contract requires a
tenant-bound business event and must not use a pseudo-tenant. This preserves the
committed endpoint behavior and avoids broadening audit privileges or RLS policies.

## State-change inventory and audit coverage

The code-path inventory was checked with searches for ORM adds/merges, SQL inserts and
updates, subprocess job status, and direct user credential writes. Database-backed
business changes below append safe audit events in the same transaction. R10 job state
remains in the existing JSON files under `platform/out/experiments`; migration 0007
does not create an R10 job table. Downgrade restores the prior audit read/insert
policies and removes the added indexes and columns; audit UPDATE/DELETE remain revoked
as a security invariant.

| Path | State changed | Audit status / action |
|---|---|---|
| `platform/api/routers/admin.py` | Creates a user | Yes, `user.created`; role only, no email or password data |
| `scripts/run-demo.ps1` | Initializes or resets demo user credentials | Yes, `user.credentials_initialized` / `user.password_reset`; role only |
| `platform/services/verdicts.py` | Inserts verdict and updates ring status | Yes, `verdict.recorded`; includes resulting status and simulated flag |
| `platform/api/routers/operations.py` | Changes drift `acted_on`; requests retraining; marks launch failure | Yes, `drift.acted_on`, `retrain.requested`, `retrain.failed` |
| `platform/api/scheduler.py` | Creates scheduled retrain run and records launch failure | Yes, `retrain.requested`, `retrain.failed` |
| `platform/jobs/retrain.py` | Run state transitions; candidate model insert and prior promotion demotion | Yes, `retrain.started/succeeded/failed`, `model_version.recorded`, `model_version.demoted`; gate outcome is retained |
| `platform/jobs/refresh_rings.py` / `platform/jobs/load_contract.py` | Tenant ring refresh/upsert | Yes, `rings.refresh_started/completed/failed`, completion in the loader transaction |
| `platform/jobs/load_contract.py` | Transactions, edge scores, accounts, rings | Yes, one count summary per affected tenant: `contract.load_completed`, `rings.load_completed` |
| `platform/jobs/load_explanations.py` | Explanation upserts | Yes, one summary per tenant: `explanations.load_completed` |
| `platform/jobs/seed_tenants.py` | Tenant registry and simulated user seed | Yes, one global `tenants.seed_completed` summary; no user identifiers or credentials |
| `platform/jobs/drift_monitor.py` | Inserts detected drift events | Yes, one tenant summary `drift.events_persisted` per run |
| `platform/jobs/simulate_verdicts.py` | Simulated verdicts and ring status through shared service | Yes, `verdict.recorded`, actor `simulator`, `is_simulated=true` |
| `platform/api/routers/admin.py` / `platform/jobs/experiment_worker.py` | R10 requested/running/succeeded/failed state in JSON job files | Structured JSON process events; no tenantless audit row or database job table |
| Password reset API | No such API endpoint exists | Not applicable; demo reset path above is audited |

Audit rows now record `tenant_id`, actor, dotted action, entity type/ID, UTC DB time,
optional request ID, and a strict allow-listed scalar JSON detail. The helper rejects
unknown fields, unsafe strings, paths and email-shaped values. Existing rows receive a
Historic audit rows get actor `legacy:unknown` via the column default; their `user_id` is preserved. App, loader and simulator roles
have INSERT only; UPDATE/DELETE are explicitly revoked and no such grants are added.
Loader and simulator grants were already present in the earlier role SQL/migration;
0007 adds the narrow API/loader insert and sequence privileges required by the new
events. The audit INSERT policy now requires tenant context to match the row, with a
separate null-tenant administrator clause. Audit SELECT is tenant-bound except for
administrator context.

## Section 4 index comparison

Compared each specified index against frozen migration 0001 and ORM metadata:

| Required index | Before 0007 | Decision |
|---|---|---|
| `transactions(tenant_id, timestamp)` | Present: `ix_transactions_tenant_time` | Keep |
| `transactions(tenant_id, from_id)` | Present: `ix_transactions_tenant_from` | Keep |
| `transactions(tenant_id, to_id)` | Present: `ix_transactions_tenant_to` | Keep |
| `rings(tenant_id, status, confidence DESC)` | Columns existed, but confidence direction was ascending | Recreate as explicit DESC in 0007 and match model metadata |
| `verdicts(tenant_id, ring_id)` | Missing; only tenant/created time existed | Add `ix_verdicts_tenant_ring_created` with `created_at DESC`, covering the required leading pair and history order |

The existing `rings(tenant_id, start_time)` and `verdicts(tenant_id, created_at)`
indexes are retained because they support other current queries. Migration 0007 uses
transactional explicit SQL and contains no `CREATE INDEX CONCURRENTLY` or model imports.

## API, logging and health

- `RequestContextMiddleware` writes one JSON request-completion record to stdout with
  UTC timestamp, level, event, request ID, verified tenant/user IDs, method, route
  template, status and duration. It does not log raw path values, query strings,
  headers, bodies, email, credentials, evidence or local paths. Unhandled errors produce
  a separate safe JSON event without exception text or traceback. Demo Uvicorn access
  logging is disabled.
- `/health` remains unauthenticated and returns only component statuses. Database
  reachability uses the restricted application connection with a three-second
  connect timeout; failures return the standard safe 503 error envelope.
- `require_roles` now rejects a valid but disallowed role claim before opening the live
  account-state query, then validates allowed principals against the database.
- Section 6 route parity, including deferred regeneration routes, is recorded in
  `docs/ENDPOINT_PARITY.md`; missing endpoints were not implemented in this task.

Database-backed audit privilege/RLS, index round-trip, and unknown-column JSONB tests
were added for CI but were not run locally because Docker and PostgreSQL are unavailable.

## Audit migration role ordering

The fresh CI bootstrap creates `ringshield_owner`, `ringshield_api`,
`ringshield_loader`, and `ringshield_simulator` in migration 0002. The migration
login is `ringshield_test_migrator`, granted membership in `ringshield_owner`, and
Alembic runs with `SET ROLE ringshield_owner`. After Alembic upgrades to head,
`platform/db/roles.sql` creates `ringshield_auth`; the test-role provisioning then
creates `ringshield_test_app`, `ringshield_test_auth`, `ringshield_test_loader`,
and `ringshield_test_simulator` (and idempotently ensures the migrator login).
Thus all roles created by the fresh CI flow are `ringshield_owner`,
`ringshield_api`, `ringshield_loader`, `ringshield_simulator`, `ringshield_auth`,
`ringshield_test_migrator`, `ringshield_test_app`, `ringshield_test_auth`,
`ringshield_test_loader`, and `ringshield_test_simulator`. Tables are owned by
`ringshield_owner`; migrations connect as `ringshield_test_migrator` and execute
as that owner. Migration 0007 grants audit INSERT only to the API and loader
roles already created in 0002. Its UPDATE/DELETE revokes explicitly cover PUBLIC
and loop over existing `ringshield_*` roles, excluding the table owner, so the
migration does not depend on `ringshield_auth` existing before the later role SQL.
The downgrade conditionally removes only the API/loader grants and leaves the
append-only revokes in effect.

## Audit writes use INSERT without RETURNING

The CI seed failure was caused by ORM flush semantics, not a missing INSERT grant:
`platform/db/roles.sql` grants INSERT on `audit_log` to the loader and simulator,
`0004_simulator_access.py` grants it to the simulator, and `0007_audit_indexes.py`
grants it to the API and loader. The ORM path could emit `INSERT ... RETURNING`
for generated `log_id` and server-default `at`; PostgreSQL then also requires
SELECT privilege on the returned columns. Loader and simulator intentionally have
no SELECT privilege on the audit table. `add_audit_event` now uses a Core table
INSERT with no RETURNING and does not return a generated primary key. The audit
mapping remains unchanged and matches the migration schema. `audit_log.log_id`
is an autoincrementing sequence-backed column (`audit_log_log_id_seq`), so its
existing sequence USAGE privilege supports inserts without table read access.

| Caller | Effective DB role | Tenant context and insert policy | Audit readback in the write path |
|---|---|---|---|
| Contract and explanation loaders | `ringshield_loader` | `loader_db_session` sets tenant ID and role `loader`; tenant ID must match the row | None |
| Drift monitor persistence | `ringshield_loader` | Same tenant-bound loader session | None |
| Retrain worker | `ringshield_loader` for model-version writes; API role for supervisor run-state writes | Loader path sets tenant ID/`loader`; supervisor path sets tenant ID/`supervisor` | None |
| Ring refresh worker | API role for supervisor start event; `ringshield_loader` for failure/contract-load writes | Both sessions carry the tenant ID; supervisor or loader policy branch must match | None |
| Tenant seeding | API role with `admin` context | Global event has `tenant_id IS NULL` and uses the administrator insert-policy clause | None |
| Simulated verdicts | `ringshield_simulator` | `simulator_db_session` sets tenant ID and `analyst`; simulator-specific policy requires both | None |
| API operations, verdicts, and user creation | API role | Tenant-bound context for tenant events; administrator clause for global admin events | These write paths do not query audit rows; the separate API SELECT grant is not used by these paths |
| Scheduler | API role | Supervisor context and tenant ID for each scheduled-run event | None |

Database-free coverage compiles the audit Core INSERT with the PostgreSQL dialect
and checks that the helper does not use `session.add`. The CI PostgreSQL test
checks loader/simulator tenant-bound inserts, denied cross-tenant inserts, denied
audit-table SELECT/UPDATE/DELETE, and API visibility limited to its tenant.

## Dashboard error feedback and UI regression coverage

Generic API failures now display the API message and request ID (body first,
`X-Request-ID` header as fallback) with a Retry control; network failures keep
their existing unavailable message and also offer Retry. Login/session 401s,
403 wording, quiet 404s, and 204 responses retain their established behavior.
Dashboard tests cover login and sign-out feedback, queue filters/pagination,
ring detail rendering, drift chart traces, and API error feedback. Sign-out clears
application-owned session data while leaving Streamlit's internal `$$` widget
state alone. The AST guard permits only page-counter navigation arithmetic and
the `REPO_ROOT / ".env"` pathlib join; dashboard amount/time formatting remains
unchanged pending the separate timezone decision.
The drift chart currently renders drift events as diamond marker traces; it does
not yet implement the specification's vertical event lines and hover details.
The AppTest queue round-trip sets the existing open-ring navigation state to
render detail and then returns to the queue; it does not click the conditional
View ring/Back controls because AppTest 1.44 raises a missing-widget-state error
when those widgets disappear during the page switch.
