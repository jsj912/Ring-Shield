from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.dependencies import require_roles
from audit import add_audit_event
from api.identity import Principal
from api.request_context import current_request_id
from api.passwords import hash_password
from api.schemas import ExperimentJobResponse, TenantResponse, UserCreateRequest, UserResponse
from db.models import ExperimentJob, Tenant, User
from db.session import db_session

router = APIRouter(prefix="/admin", tags=["admin"])
PLATFORM_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_OUTPUT = PLATFORM_ROOT / "out" / "experiments"


@router.get("/tenants", response_model=list[TenantResponse])
def list_tenants(principal: Principal = Depends(require_roles("admin"))) -> list[TenantResponse]:
    with db_session(tenant_id=payload.tenant_id, role=principal.role) as session:
        tenants = session.scalars(
            select(Tenant).where(Tenant.tenant_id != -1).order_by(Tenant.bank_code)
        ).all()
        return [TenantResponse.model_validate(row) for row in tenants]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateRequest,
                principal: Principal = Depends(require_roles("admin"))) -> UserResponse:
    email = payload.email.strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    with db_session(role=principal.role) as session:
        if payload.tenant_id is not None:
            tenant = session.get(Tenant, payload.tenant_id)
            if tenant is None or not tenant.is_loaded:
                raise HTTPException(status_code=404, detail="Loaded tenant not found")
        if session.scalar(select(User.user_id).where(func.lower(User.email) == email)) is not None:
            raise HTTPException(status_code=409, detail="A user with this email already exists")
        user = User(tenant_id=payload.tenant_id, email=email,
                    password_hash=hash_password(payload.password), role=payload.role)
        session.add(user)
        try:
            session.flush()
            add_audit_event(session,
                tenant_id=payload.tenant_id,
                user_id=principal.user_id,
                actor=f"user:{principal.user_id}",
                action="user.created",
                entity_type="user",
                entity_id=user.user_id,
                request_id=current_request_id(),
                details={"role": payload.role},
            )
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A user with this email already exists") from exc
        return UserResponse.model_validate(user)


@router.post("/experiments/tenant-vs-pooled", response_model=ExperimentJobResponse,
             status_code=status.HTTP_202_ACCEPTED)
def start_tenant_vs_pooled(
        principal: Principal = Depends(require_roles("admin"))) -> ExperimentJobResponse:
    job_id = uuid4().hex
    EXPERIMENT_OUTPUT.mkdir(parents=True, exist_ok=True)
    state_path = EXPERIMENT_OUTPUT / f"{job_id}.json"
    state_path.write_text(json.dumps({"job_id": job_id, "status": "queued"}), encoding="utf-8")
    try:
        with db_session(role="admin") as session:
            session.add(ExperimentJob(job_id=job_id, requested_by=principal.user_id,
                                      status="queued"))
            add_audit_event(session, tenant_id=None, user_id=principal.user_id,
                            actor=f"user:{principal.user_id}", action="experiment.requested",
                            entity_type="experiment", entity_id=job_id,
                            request_id=current_request_id(), details={"status": "queued"})
    except Exception as exc:
        state_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="Experiment job could not be recorded") from exc
    try:
        options = {"cwd": str(PLATFORM_ROOT), "stdin": subprocess.DEVNULL,
                   "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                   "close_fds": True}
        if sys.platform == "win32":
            options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        subprocess.Popen([sys.executable, "-m", "jobs.experiment_worker", "r10", job_id], **options)
    except OSError as exc:
        state_path.unlink(missing_ok=True)
        with db_session(role="admin") as session:
            job = session.get(ExperimentJob, job_id)
            if job is not None:
                job.status = "failed"
                job.updated_at = datetime.now(timezone.utc)
            add_audit_event(session, tenant_id=None, actor=f"user:{principal.user_id}",
                            action="experiment.finished", entity_type="experiment",
                            entity_id=job_id, request_id=current_request_id(),
                            details={"status": "failed"})
        raise HTTPException(status_code=503, detail="Experiment worker could not be started") from exc
    return ExperimentJobResponse(job_id=job_id, status="queued")


@router.get("/experiments/tenant-vs-pooled/{job_id}", response_model=ExperimentJobResponse)
def get_tenant_vs_pooled_status(
        job_id: str, principal: Principal = Depends(require_roles("admin"))) -> ExperimentJobResponse:
    if not job_id.isalnum() or len(job_id) != 32:
        raise HTTPException(status_code=404, detail="Experiment job not found")
    with db_session(role="admin") as session:
        job = session.scalar(select(ExperimentJob).where(ExperimentJob.job_id == job_id))
        if job is None:
            raise HTTPException(status_code=404, detail="Experiment job not found")
    state_path = EXPERIMENT_OUTPUT / f"{job_id}.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="Experiment job not found") from exc
    state["status"] = job.status
    return ExperimentJobResponse(**state)
