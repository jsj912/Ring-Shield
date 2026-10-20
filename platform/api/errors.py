from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        mapping = {
            401: ("AUTHENTICATION_REQUIRED", "Authentication required"),
            403: ("NOT_PERMITTED", "Not permitted"),
            404: ("NOT_FOUND", "Not found"),
            422: ("VALIDATION_ERROR", "Request validation failed"),
        }
        code, default_message = mapping.get(exc.status_code, ("REQUEST_FAILED", "Request failed"))
        message = exc.detail if isinstance(exc.detail, str) else default_message
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"error_code": code, "message": message,
                     "request_id": getattr(request.state, "request_id", "-")},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        safe_errors = [
            {"loc": list(error.get("loc", ())),
             "type": str(error.get("type", "validation_error")),
             "msg": str(error.get("msg", "Invalid value"))}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error_code": "VALIDATION_ERROR", "message": "Request validation failed",
                     "request_id": getattr(request.state, "request_id", "-"),
                     "details": {"errors": safe_errors}},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        principal = getattr(request.state, "principal", None)
        request_id = getattr(request.state, "request_id", "-")
        print(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "ERROR", "event": "http.request.unhandled_error",
            "request_id": request_id,
            "tenant_id": getattr(principal, "tenant_id", getattr(request.state, "tenant_id", None)),
        }, separators=(",", ":")), file=sys.stdout, flush=True)
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content={"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred",
                     "request_id": getattr(request.state, "request_id", "-")},
        )
