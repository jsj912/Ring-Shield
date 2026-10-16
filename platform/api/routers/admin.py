from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from api.dependencies import require_roles
from api.identity import Principal
from api.passwords import hash_password
from api.schemas import TenantResponse, UserCreateRequest, UserResponse
from db.models import AuditLog, Tenant, User
from db.session import db_session

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tenants", response_model=list[TenantResponse])
def list_tenants(principal: Principal = Depends(require_roles("admin"))) -> list[TenantResponse]:
    with db_session(role=principal.role) as session:
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
            session.add(AuditLog(
                tenant_id=payload.tenant_id,
                user_id=principal.user_id,
                action="user.created",
                object_type="user",
                object_id=str(user.user_id),
                details={"email": email, "role": payload.role},
            ))
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="A user with this email already exists") from exc
        return UserResponse.model_validate(user)
