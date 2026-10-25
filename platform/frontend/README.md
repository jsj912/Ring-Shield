# RingShield investigator dashboard (React)

The React front end for the RingShield API. It replaces the Streamlit dashboard in
`platform/dashboard/` screen for screen; the API does not change. Like the Streamlit version it is a
thin client: it shows what the API returns, formatted, and computes nothing (FR-D102). It never
talks to a database (NFR-D12), and the session token lives in memory only (NFR-D10), so reloading
the page signs you out.

Stack: Vite, React, TypeScript, Tailwind, shadcn/ui, React Router, TanStack Query, react-plotly.js,
Cytoscape.js.

## Run it

You need Node 20 or later (`node -v`) and the platform Python environment.

```bash
cd platform/frontend
npm install
```

### Fixture mode (no Postgres)

`platform/frontend/fixtures/` holds the front end's own fixtures (one ring per pattern type, a
120-account ring, a cross-bank ring and 200 rings to page through; regenerate with
`fixtures/make_fixtures.py`). `fixtures/fixture_server.py` serves them through `FixtureAPI` over HTTP.
They started as a copy of the Streamlit dashboard's fixtures; `platform/dashboard/` is frozen and is
not used:

```bash
python platform/frontend/fixtures/fixture_server.py --port 8001
```

```bash
VITE_API_URL=http://127.0.0.1:8001 npm run dev
```

Open http://localhost:5173. On PowerShell set the variable with `$env:VITE_API_URL = "http://127.0.0.1:8001"`
first. Fixture logins (from `fixtures/users.json`):

| Role | Email | Password |
|---|---|---|
| Analyst, Bank A | `analyst@bank-a.fixture` | `fixture-only-a1` |
| Supervisor, Bank A | `supervisor@bank-a.fixture` | `fixture-only-a2` |
| Analyst, Bank B | `analyst@bank-b.fixture` | `fixture-only-b1` |
| Admin | `admin@platform.fixture` | `fixture-only-admin` |

The fixtures have no drift routes, so in fixture mode the Drift page shows its error state.
`POST /__reset` on the fixture server reloads the fixtures (the smoke test uses it).

### Against the real API

Start the API (it allows CORS from http://localhost:5173; set `RINGSHIELD_CORS_ORIGINS` for other
origins), then:

```bash
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

`VITE_API_URL` defaults to `http://127.0.0.1:8000`. For a deployment, `npm run build` writes static
files to `dist/`; the API URL is fixed at build time.

## Tests

```bash
npm test
```

Vitest: the API client, formatters, ring-graph logic, R10 tables, query building, and the verdict
form. `src/lib/formatters.python-cases.json` holds outputs of the Python formatters
(`platform/dashboard/formatters.py`); the test checks that every value prints identically here.
Regenerate it after changing either formatter:

```bash
python platform/frontend/scripts/make_formatter_cases.py
```

```bash
npm run test:e2e
```

Playwright smoke test (login, queue, ring detail, verdict) against its own fixture server and dev
server on ports 8011 and 5174. It uses the installed Microsoft Edge (`PLAYWRIGHT_CHANNEL=chrome` for
Chrome), so no browser download is needed. The fixture server needs a Python with FastAPI: the config
uses `PYTHON` if set, else `../venv-platform/Scripts/python.exe` next to the repo
(`E:/JSJ/venv-platform`), else `python` on PATH. `scripts/run-demo.ps1` picks its Python the same way.

## Layout

| Path | What |
|---|---|
| `src/api/` | The one API client (`client.ts`), the in-memory session, types from `platform/api/schemas.py`, one function per route (`endpoints.ts`) |
| `src/lib/` | Formatters (port of `formatters.py`), ring-graph logic (port of `ring_graph.py`), R10 tables, polling deadline, CSV |
| `src/app/` | Shell (sidebar, top bar, tenant switcher), role gating (`pages.ts` is `pages_for`), session-scoped UI state |
| `src/pages/` | One module per screen; the ring detail panels are in `src/pages/ring/` |
| `src/components/` | Shared pieces (badges, error and empty states, KPI cards, the graph, charts) and `ui/` (shadcn/ui) |

## Add a screen

1. Add the route's function to `src/api/endpoints.ts` and its response type to `src/api/types.ts`,
   with the field names exactly as `platform/api/schemas.py` has them.
2. Add the slug, label and roles to `src/app/pages.ts`; the sidebar and the "Not permitted" guard
   follow from it. Give it an icon in `src/app/Layout.tsx`.
3. Write `src/pages/YourPage.tsx`: read with `useQuery`, show `TableSkeleton` while loading,
   `ErrorState` (message, request id, Retry) on failure, and `EmptyState` when there is nothing.
   Format every number with `src/lib/formatters.ts`; do no arithmetic on API values.
4. Add the `<Route>` in `src/App.tsx`, wrapped in `<RequirePage slug=...>`.
