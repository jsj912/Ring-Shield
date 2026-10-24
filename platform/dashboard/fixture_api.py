"""A stand-in for the RingShield API that serves the fixtures folder (NFR-D55).

It answers the routes the dashboard calls with the API's own field names and status codes,
including 401 for a bad or missing token and 403 when a bank user asks for another tenant.
It is test scaffolding for the API, not part of the dashboard's logic: anything it selects or
pages here, the real API does server-side.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

FIXTURE_TOKEN_PREFIX = "fixture-token-"


class FixtureAPI:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.users = self._load("users.json")
        self.tenants = self._load("tenants.json")
        self.request_count = 0

    def _load(self, name: str, default=None):
        path = self.root / name
        if not path.is_file():
            return default if default is not None else []
        return json.loads(path.read_text(encoding="utf-8"))

    def _response(self, status: int, payload=None) -> httpx.Response:
        self.request_count += 1
        request_id = f"fixture-{self.request_count:05d}"
        if isinstance(payload, dict) and status >= 400:
            payload = {**payload, "request_id": request_id}
        return httpx.Response(status, json=payload, headers={"X-Request-ID": request_id},
                              request=httpx.Request("GET", "http://fixture.local"))

    def _error(self, status: int, error: str, message: str) -> httpx.Response:
        return self._response(status, {"error": error, "message": message})

    def _session_user(self, headers: dict) -> dict | None:
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if not token.startswith(FIXTURE_TOKEN_PREFIX):
            return None
        user_id = token.removeprefix(FIXTURE_TOKEN_PREFIX)
        return next((u for u in self.users if str(u["user_id"]) == user_id), None)

    def handle(self, method: str, path: str, *, headers: dict | None = None,
               body: dict | None = None, params=None) -> httpx.Response:
        method = method.upper()
        if method == "POST" and path == "/auth/login":
            return self._login(body or {})
        user = self._session_user(headers or {})
        if user is None:
            return self._error(401, "Unauthorized", "Authentication required")
        tenant_match = re.match(r"^/tenants/(\d+)(/.*)?$", path)
        if tenant_match and user["role"] != "admin" and int(tenant_match.group(1)) != user["tenant_id"]:
            return self._error(403, "Forbidden", "Not permitted")
        if path.startswith("/admin/") and user["role"] != "admin":
            return self._error(403, "Forbidden", "Not permitted")
        if method == "GET" and path == "/admin/tenants":
            return self._response(200, self.tenants)
        return self._error(404, "NotFound", f"No fixture for {method} {path}")

    def _login(self, body: dict) -> httpx.Response:
        user = next((u for u in self.users if u["email"] == body.get("email")
                     and u["password"] == body.get("password")), None)
        if user is None:
            # one generic answer whether the email or the password was wrong (FR-D02)
            return self._error(401, "Unauthorized", "Incorrect email or password")
        return self._response(200, {
            "user_id": user["user_id"], "tenant_id": user["tenant_id"],
            "tenant_name": user["tenant_name"], "role": user["role"],
            "token": f"{FIXTURE_TOKEN_PREFIX}{user['user_id']}",
            "expires_at": "2099-01-01T00:00:00Z",
        })
