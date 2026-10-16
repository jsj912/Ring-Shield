"""FastAPI application entry point for the RingShield platform."""

from fastapi import FastAPI

from api.request_context import RequestContextMiddleware
from api.routers.auth import router as auth_router
from api.routers.rings import router as rings_router
from api.routers.admin import router as admin_router
from api.routers.verdicts import router as verdicts_router
from api.routers.operations import router as operations_router
from api.errors import install_error_handlers
from db.session import check_database
from pathlib import Path
import os

app = FastAPI(
    title="RingShield Platform API",
    version="0.1.0",
    description="Tenant-scoped ring investigation and model operations API.",
)
app.add_middleware(RequestContextMiddleware)
app.include_router(auth_router)
app.include_router(rings_router)
app.include_router(admin_router)
app.include_router(verdicts_router)
app.include_router(operations_router)
install_error_handlers(app)


@app.get("/health", tags=["health"])
def health() -> dict[str, object]:
    """Report database and model-artifact store reachability."""
    try:
        check_database()
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    artifact_root = Path(os.environ.get("RINGSHIELD_ARTIFACT_DIR", "models/artifacts"))
    if not artifact_root.is_absolute():
        artifact_root = Path(__file__).resolve().parents[2] / artifact_root
    if not artifact_root.is_dir() or not os.access(artifact_root, os.R_OK):
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Model artifact store unavailable")
    return {"status": "ok", "database": "ok", "file_store": "ok"}

