# Platform integration handoff

The contract files in `contract/` are canonical for scored edges and rings. The
L5/L6 platform spec and dashboard requirements define tenant-facing records.

## Research-layer handoff

- `python -m ringshield run` must accept a tenant-visible edge subset and explicit
  `--tenant-id` attribution.
- `python -m ringshield eval` must accept a frozen holdout manifest and run without
  importing torch.
- Rings need `total_amount`, `total_currency`, and `n_currencies`. Total amount is
  the sum of deduplicated member-edge `amount_received` in the dominant receiving
  currency. No currency conversion is available or implied.
- Ship deterministic currency and payment-format integer-code maps.
- API display labels come from those maps; unknown codes display as `Currency <code>`
  or `Format <code>` until the map is supplied. No exchange-rate conversion is done.
- Commit a fixed `holdout_manifest.json` and fixture-generation script.
- `ringshield train` must actually rebuild/refit requested components. Copying an
  existing model directory is not a retraining implementation.

## L4 explainability handoff needed

No L4 implementation or standalone L4 specification is present in this checkout.
Before wiring explanation endpoints, please provide:

1. L4 spec and exact Python/API call surface, including versioning.
2. A realistic sanitized fixture for the explanation, edge weights, account
   weights, feature weights, and expected narrative.
3. Types, nullability, and meaning of `w_total`, `w_score`, `w_loo`, `w_flow`,
   `w_account`, `mean_shap`, and `top_edge_id`.
4. Explain and partial-verdict regenerate calls, including corrected member/edge
   inputs and ring/model identifiers.
5. Cache key/invalidation rules, determinism expectations, latency target, and
   behavior when features or models are unavailable.
6. Confirmation that flow shares are computed within currency using the same
   dominant-currency rule; AMLworld has no exchange-rate table.
7. Confirmation that account numbers and ground-truth labels never enter
   explanations or API responses.
8. The failure/rollback contract when ring regeneration succeeds but explanation
   regeneration fails after a partial verdict.

The platform owns authorization, tenant scoping, persistence/cache, and HTTP error
translation. L4 owns explanation values and narrative. Partial correction must not
be reported as complete until both ring and explanation regeneration succeed.

## Tenant data flow

1. For each edge, make one tenant-visible copy per distinct code in
   `{from_bank, to_bank}`; a self-bank edge is copied once.
2. Run aggregation on that tenant's edge IDs with `--tenant-id <bank_code>`.
3. Validate ring edge references against that tenant's visible-edge set before
   insert.
4. Enforce tenant predicates in queries and PostgreSQL RLS. Pooled outputs use a
   separate admin/R10 path, never the tenant queue. The initial schema reserves
   internal `tenant_id = -1` for pooled edge and ring rows; it is not a bank tenant
   and cannot be assigned to a user.
5. Display bank labels as `Bank <code>`; never pass `account_number` to the API.
