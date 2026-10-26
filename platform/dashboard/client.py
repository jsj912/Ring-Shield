"""The dashboard's one API client (NFR-D50): base URL, token header and fixture mode in one place.

Set RINGSHIELD_DASHBOARD_FIXTURES to a fixtures folder to run every screen without the API
(NFR-D55); the folder is served by fixture_api.FixtureAPI, a stand-in that answers the same
routes with the same field names. The dashboard never talks to the database (NFR-D12).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

API_BASE = os.environ.get("RINGSHIELD_API_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_fixture_api = None


def fixture_dir() -> Path | None:
    value = os.environ.get("RINGSHIELD_DASHBOARD_FIXTURES")
    if not value:
        return None
    return DEFAULT_FIXTURES if value.strip().lower() in {"1", "true", "yes"} else Path(value)


def send(method: str, path: str, *, token: str | None = None, body: dict | None = None,
         params=None, timeout: float = 20.0) -> httpx.Response:
    """One request with the session token in the Authorization header (NFR-D11)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    folder = fixture_dir()
    if folder is not None:
        global _fixture_api
        from fixture_api import FixtureAPI
        if _fixture_api is None or _fixture_api.root != folder:
            _fixture_api = FixtureAPI(folder)
        return _fixture_api.handle(method, path, headers=headers, body=body, params=params)
    return httpx.request(method, f"{API_BASE}{path}", headers=headers, json=body,
                         params=params, timeout=timeout)
