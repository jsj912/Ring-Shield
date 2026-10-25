"""Dev-only HTTP wrapper around FixtureAPI, so the React front end can run without Postgres (NFR-D55).

The React front end's own copy, taken from platform/dashboard/ (frozen) on 2026-10-25; the fixtures
are this folder.

    python platform/frontend/fixtures/fixture_server.py --port 8001
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_api import FixtureAPI  # noqa: E402

FIXTURES = Path(os.environ.get("RINGSHIELD_FRONTEND_FIXTURES_DIR", Path(__file__).resolve().parent))
ORIGINS = os.environ.get("RINGSHIELD_CORS_ORIGINS", "http://localhost:5173").split(",")

app = FastAPI(title="RingShield fixture API (dev only)")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"],
                   allow_headers=["Authorization", "Content-Type"], expose_headers=["X-Request-ID"])
fixtures = FixtureAPI(FIXTURES)


@app.post("/__reset")
def reset() -> dict:
    """Reload the fixtures, dropping verdicts and jobs made in this run (used by the smoke test)."""
    global fixtures
    fixtures = FixtureAPI(FIXTURES)
    return {"status": "ok"}


@app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])
async def passthrough(path: str, request: Request) -> Response:
    raw = await request.body()
    body = json.loads(raw) if raw else None
    headers = {"Authorization": request.headers.get("authorization", "")}
    answer = fixtures.handle(request.method, f"/{path}", headers=headers, body=body,
                             params=list(request.query_params.multi_items()))
    return Response(content=answer.content, status_code=answer.status_code,
                    media_type="application/json",
                    headers={"X-Request-ID": answer.headers.get("X-Request-ID", "")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
