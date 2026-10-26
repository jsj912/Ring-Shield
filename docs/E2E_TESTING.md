# End-to-end testing (branch `jsj-testing1`, 24 Oct 2026)

This branch is `v2` with Kashish's `regen-api` and Ruhani's `explainability-l4` merged in, plus the fixes
below. It is what the end-to-end run used. Nothing here is merged into `v2` or `main`.

## Run it

Three Python environments, because the three parts pin different packages:

| part | venv | install |
|---|---|---|
| research (`ringshield`) | `.venv312` (Python 3.12) | as before |
| XAI (`explainability`) | e.g. `venv-xai` (Python 3.12 works; the README says 3.11.9) | `pip install -r explainability/requirements-test.txt` |
| platform | e.g. `venv-platform` (Python 3.12) | `pip install -r platform/requirements.txt -r requirements-dev.txt` |

Docker Desktop must show **Engine running**. Then, from the repo root:

```powershell
.\scripts\e2e_demo.ps1 -Tenant 12 `
  -ResearchPython <path to .venv312 python.exe> `
  -XaiPython <path to venv-xai python.exe> `
  -PlatformPython <path to venv-platform python.exe>
```

It builds bank 12's rings, explains them, loads the demo database and starts the API
(`http://127.0.0.1:8000`) and dashboard (`http://127.0.0.1:8501`). Logins are written to
`platform/demo-credentials.txt` (use `tenant_12_analyst_*`). Stop with `.\scripts\run-demo.ps1 -Down`.

## What changed on this branch, and why

| file | change | why |
|---|---|---|
| `platform/jobs/load_explanations.py` | v1/v2 ring detection compares against `RINGS_ORDER_V1` and `RINGS_ORDER` | after v2's contract bump `RINGS_ORDER` is the 30-column v2 layout, so every v2 rings file was read as "v1" and the loader refused it whatever the config said |
| `platform/config.yaml` | `l4.rings_schema_version: 2` | the research rings are v2 |
| `platform/jobs/make_demo_fixture.py` | the synthetic demo rings carry the eight v2 currency-aware columns | `load_contract.py` requires v2 rings, so the DB test setup stopped at "missing contract columns" |
| `platform/tests/test_load_explanations.py`, `test_settings_config_cache.py`, `isolation/test_explanation_handoff_real_db.py` | default fixture is v2; the version-mismatch tests are flipped so each still checks the same refusal | the repo config is now v2 |
| `platform/db/migrations/versions/0010_simulator_verdict_returning.py` (new), `platform/db/roles.sql` | grant the simulator `SELECT (verdict_id, created_at)` on `verdicts` | the simulator's verdict insert uses `RETURNING verdict_id, created_at`, which needs `SELECT` on those columns; with `INSERT` only it failed with "permission denied for table verdicts" on any real DB (CI too). Row visibility is unchanged: `verdicts_tenant_read` still limits it to its own tenant |
| `scripts/test-db.ps1` | sets `RINGSHIELD_SIMULATOR_DATABASE_URL` | CI sets it but the local script did not, so the four simulator DB tests could only pass in CI |
| `platform/Dockerfile.test` | Debian packages over HTTPS; pip with a longer timeout and retries | on some networks plain-HTTP apt downloads time out, and slow pip downloads killed the image build |
| `explainability/requirements-test.txt` (new) | serve requirements + `pytest`, `httpx`, `fastapi` | `test_serve.py` imports `httpx` and `test_api.py` imports `fastapi`; neither was listed |
| `scripts/e2e_demo.ps1` (new) | the one-command run above | the steps were spread over two READMEs |

## Setup steps the docs were missing

1. **Docker on a new Windows machine:** a per-user Docker Desktop install fails until WSL is set up:
   `wsl --update --web-download`, then `wsl --install --no-launch` in an admin terminal, then restart.
   Plain `wsl --update` can hang at 0% (it goes through the Microsoft Store).
2. **Which Python environment:** neither README names one; see the table above.
3. **Build the tenant rings first:** `run-demo.ps1` needs them, but the build step is ~370 lines further down
   `platform/README.md`.
4. **Streamlit first-run prompt:** on first run Streamlit waits for an email on the console. Started in the
   background, it never answers, so the dashboard never comes up. `e2e_demo.ps1` writes
   `%USERPROFILE%\.streamlit\credentials.toml` with `email = ""` to skip it.
5. **Stale pinned hashes:** the ring SHA-256s pinned in `results/xai/tenant/inputs/*_sha256.txt` were made
   before v2's ring writer; a v2 rebuild no longer matches them.

## Test results on this branch

| check | result |
|---|---|
| `scripts/e2e_demo.ps1 -Tenant 12` | PASS: 5 rings from 20,039 visible edges, 5/5 explained and reproduced, DB loaded, API `/health` ok, dashboard up; ring, explanation and verdict buttons checked by hand |
| platform unit tests (`pytest platform/tests --ignore=platform/tests/isolation`) | 366 passed, 0 failed |
| platform DB tests (`scripts/test-db.ps1`) | 412 passed, 0 failed (after the simulator grant below; CI on this branch: 411 passed, 1 failed before it) |
| research suite (`pytest tests`) | not re-run here: the research code is identical to `v2`, where it passed 204, 0 failed |
| explainability suite | 192 passed, 86 failed, 8 errors on the same tree before `requirements-test.txt` (see open items) |

On the college network the DB-test image could not download its pip packages even with the retries. To get
the result above, the wheels were downloaded on Windows (`pip download ... --platform manylinux2014_x86_64
--python-version 3.12 --only-binary=:all:`, plus `uvloop`, which Windows skips) and installed in the image with
`--no-index --find-links`. That workaround is not committed.

## Open items (not fixed here)

- **`test_regeneration_routes.py::test_regenerate_route_returns_existing_active_job[queued]`** failed once inside
  a local `test-db.ps1` run (a job launched although a queued one existed), then passed in CI and in the next two
  local runs. Looks order- or timing-dependent; worth a look, not reproducible on demand.
- **Dashboard role label:** the ring graph labels the middle account of a chain "source" while the account
  table and the L4 explanation call it "mule" (seen on bank 12, ring with accounts 99403 → 315365 → 160003).
- **"Partially correct" is disabled:** `l4.regenerate_url` is null, so the regeneration service is not wired
  to the dashboard yet.
- **Explainability tests on v2:** her suite was written against v1 rings. On this branch about 50 tests fail on
  the v2 columns (`conservation_closure_ccy`, `n_currencies`, `rings_schema_version` 1 vs 2) and about 15 need
  generated files that are not in git (`results/xai/review/answer_key.parquet`, the week-3 explanations,
  tenant 20's rings). Updating her code for v2 is her call.

## Which ring types are detected

Test window (days 8–9), five detector seeds summed, final (`full`) ring method, from
`python evaluation/unmatched_rings.py`:

| pattern | found | <3 accounts visible (undetectable) | never flagged | merged / partly found | found, % of detectable |
|---|---|---|---|---|---|
| STACK | 4 | 40 | 46 | 20 | 6% |
| BIPARTITE | 5 | 25 | 41 | 9 | 9% |
| RANDOM | 35 | 25 | 21 | 4 | 58% |
| CYCLE | 42 | 40 | 18 | 10 | 60% |
| FAN-IN | 56 | 21 | 12 | 1 | 81% |
| GATHER-SCATTER | 117 | 43 | 17 | 8 | 82% |
| FAN-OUT | 64 | 24 | 6 | 6 | 84% |
| SCATTER-GATHER | 78 | 25 | 5 | 2 | 92% |

STACK and BIPARTITE are mostly "never flagged": the scoring model does not flag any of their transactions,
so ring building never starts. Same numbers as the 27 Sep run.
