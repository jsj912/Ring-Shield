from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from api.identity import Principal, create_access_token
from api.passwords import password_context
from api.schemas import LoginRequest, SessionResponse
from db.models import Tenant, User
from db.session import auth_db_session

router = APIRouter(prefix="/auth", tags=["authentication"])
# Keep unknown-email and wrong-password login failures on the same bcrypt path.
DUMMY_PASSWORD_HASH = password_context.hash(secrets.token_urlsafe(32))


@router.post("/login", response_model=SessionResponse)
def login(payload: LoginRequest, request: Request) -> SessionResponse:
    # Keep failures indistinguishable for unknown emails and wrong passwords.
    with auth_db_session() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower()))
        tenant = None
        if user is not None and user.tenant_id is not None:
            tenant = session.get(Tenant, user.tenant_id)
        try:
            valid = password_context.verify(payload.password,
                                            user.password_hash if user is not None else DUMMY_PASSWORD_HASH)
        except (ValueError, TypeError):
            valid = False
        if not valid or user is None or user.disabled:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid email or password")
        if user.role != "admin" and tenant is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid email or password")
        principal = Principal(user_id=user.user_id, tenant_id=user.tenant_id,
                              role=user.role, email=user.email)
        token, expires_at = create_access_token(principal)
        request.state.user_id = user.user_id
        request.state.tenant_id = user.tenant_id
        return SessionResponse(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            tenant_name=tenant.name if tenant is not None else "Global administrator",
            role=user.role,
            token=token,
            expires_at=expires_at,
        )
