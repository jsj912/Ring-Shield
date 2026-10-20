"""Per-request metadata shared by API routes and structured error responses."""

from __future__ import annotations

import json
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str | None:
    value = request_id_var.get()
    return value if value != "-" else None


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(UUID(supplied_id)) if supplied_id else str(uuid4())
        except ValueError:
            request_id = str(uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            principal = getattr(request.state, "principal", None)
            route = request.scope.get("route")
            route_template = getattr(route, "path", "<unmatched>")
            tenant_id = getattr(principal, "tenant_id", None)
            if tenant_id is None:
                tenant_id = getattr(request.state, "tenant_id", None)
            user_id = getattr(principal, "user_id", None)
            if user_id is None:
                user_id = getattr(request.state, "user_id", None)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO" if status_code < 500 else "ERROR",
                "event": "http.request.completed",
                "request_id": request_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "method": request.method,
                "route": route_template,
                "status": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            print(json.dumps(record, separators=(",", ":"), default=str), file=sys.stdout, flush=True)
            request_id_var.reset(token)
