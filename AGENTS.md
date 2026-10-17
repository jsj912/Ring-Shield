# AGENTS.md: standing rules for RingShield platform work (platform/)

## Scope and authority
- Build and change only `platform/` (L5 service and dashboard, L6 feedback loop) plus `.github/`
  and `scripts/` for platform tooling. Never edit research code: `models/`, `ringshield/`,
  `contract/`, `evaluation/`, `preprocessing/`.
- If a spec disagrees with `contract/schema.py`, the schema wins. Record the conflict in
  `platform/DECISIONS.md`.

## Security rules (never weaken)
1. No model logic in platform code. Research calls only through `platform/adapters/`.
   No imports of torch, xgboost, lightgbm, sklearn or `ringshield` outside the adapters.
2. Ground truth (`*ground_truth*`, `labels_*`) is read only by `platform/adapters/ground_truth.py`,
   the verdict simulator and experiment scripts. Never by an API route or the loader.
3. Every tenant table has `tenant_id NOT NULL`, forced RLS and a policy. The app role has no
   BYPASSRLS, is not a table owner and never holds loader credentials. Every tenant query sets
   `app.tenant_id` AND carries an explicit `WHERE tenant_id = :t`.
4. A tenant token on another tenant's path returns 403 before any query. Admin is read-only and
   cannot write verdicts.
5. Errors use `{error_code, message, request_id}`. Never expose absolute paths.
6. Simulated verdicts always have `is_simulated = true`.

## Data rules
- A tenant sees an edge only if `from_bank` or `to_bank` equals the tenant. Hidden edges are
  counted, never shown or mentioned.
- Rings are keyed by `(tenant_id, ring_id)`. A ring_id must never change meaning.
- Never sum raw amounts across currencies; use the converted figure or per-currency totals.
- The loader refuses non-test splits (sibling `.log.json` `split != "test"`) and any
  `labels_*` or ground-truth path. Scores live in `edge_scores`, never in `transactions`.

## Engineering rules
- Migrations are frozen and explicit; never import `db.models` or call `create_all` in them.
  `alembic check` must stay green.
- Never use `result.rowcount` for upserts (it is -1 with ORM inserts). Use `RETURNING`.
- Use `bcrypt` directly (no passlib); reject passwords over 72 bytes.
- Tests that depend on `platform/config.yaml` must use the `repo_platform_config` fixture;
  database tests run in CI and must fail, not skip, when Postgres is unreachable.
- Do not claim database or RLS tests passed unless you ran them. CI is the check.
- Small commits, no pushing, no data files, `.env` or ground truth in Git. Record every
  deviation in `platform/DECISIONS.md`.
- Do not build: schema-per-tenant, Kubernetes, Kafka, Neo4j, Redis, queues, React.