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
        self.rings = {}
        for path in sorted((self.root / "rings").glob("*.json")):
            ring = json.loads(path.read_text(encoding="utf-8"))
            self.rings[(ring["tenant_id"], ring["summary"]["ring_id"])] = ring
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
        """The API's error body: error_code, message, request_id (platform/api/errors.py)."""
        code = {401: "AUTHENTICATION_REQUIRED", 403: "NOT_PERMITTED", 404: "NOT_FOUND",
                422: "VALIDATION_ERROR"}.get(status, "REQUEST_FAILED")
        return self._response(status, {"error_code": code, "message": message})

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
        if tenant_match:
            tenant_id, rest = int(tenant_match.group(1)), tenant_match.group(2) or ""
            if method == "GET" and rest == "/rings":
                return self._ring_page(tenant_id, _param_dict(params))
            ring_match = re.match(r"^/rings/([^/]+)(/subgraph|/evidence|/explanation|/verdicts)?$", rest)
            if method == "GET" and ring_match:
                ring = self.rings.get((tenant_id, ring_match.group(1)))
                if ring is None:
                    return self._error(404, "NotFound", "Ring not found")
                part = ring_match.group(2)
                if part == "/verdicts":
                    return self._response(200, {"items": ring.get("verdicts", []), "next_before_id": None})
                body = {None: ring["detail"], "/subgraph": ring.get("subgraph"),
                        "/evidence": ring.get("evidence"), "/explanation": ring.get("explanation")}[part]
                if body is None:
                    return self._error(404, "NotFound", "Not found")
                return self._response(200, body)
        return self._error(404, "NotFound", f"No fixture for {method} {path}")

    def _ring_page(self, tenant_id: int, params: dict) -> httpx.Response:
        """The API's GET /tenants/{t}/rings over the fixtures: filters, sort, cursor and counts."""
        tenant_rings = [ring["summary"] for (tenant, _), ring in self.rings.items() if tenant == tenant_id]
        statuses = params.get("status") or ["open"]
        types = params.get("topology_type") or []
        min_conf = float(_one(params, "min_conf") or 0)
        cross_only = (_one(params, "cross_bank_only") or "false") == "true"
        after, before = _one(params, "start_after"), _one(params, "start_before")
        query = (_one(params, "q") or "").strip()
        rows = [r for r in tenant_rings
                if r["status"] in statuses and (not types or r["topology_type"] in types)
                and r["confidence"] >= min_conf and (not cross_only or r["cross_bank"])
                and (not after or r["start_time"] >= after[:19]) and (not before or r["start_time"] <= before[:19])
                and (not query or query == r["ring_id"]
                     or query in {str(a) for a in self.rings[(tenant_id, r["ring_id"])]["detail"]["member_accounts"]})]
        sort = _one(params, "sort") or "confidence"
        key = {"confidence": "confidence", "total_amount": "total_amount", "start_time": "start_time",
               "members": "n_members"}.get(sort, "confidence")
        rows.sort(key=lambda r: (r[key] is None, r[key] or 0, r["ring_id"]),
                  reverse=(_one(params, "order") or "desc") == "desc")
        offset = int(_one(params, "cursor") or 0)
        limit = int(_one(params, "limit") or 50)
        page = rows[offset:offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(rows) else None
        return self._response(200, {"items": page, "next_cursor": next_cursor, "total": len(rows),
                                     "tenant_total": len(tenant_rings)})

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


def _param_dict(params) -> dict[str, list[str]]:
    """httpx-style params (a dict or a list of pairs) as {name: [values]}."""
    out: dict[str, list[str]] = {}
    items = params.items() if isinstance(params, dict) else (params or [])
    for name, value in items:
        out.setdefault(name, []).extend(value if isinstance(value, list) else [value])
    return out


def _one(params: dict, name: str):
    values = params.get(name) or []
    return values[0] if values else None
