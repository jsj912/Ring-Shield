"""Authentication and database dependencies shared by API routers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.identity import InvalidToken, Principal, decode_access_token
from db.models import User
from db.session import auth_db_session, db_session

bearer = HTTPBearer(auto_error=False)


def get_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        principal = decode_access_token(credentials.credentials)
    except InvalidToken as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session expired or invalid", headers={"WWW-Authenticate": "Bearer"}) from exc
    # This identity is cryptographically verified; logging can safely attach its
    # tenant even if the subsequent live-account check rejects the request.
    request.state.principal = principal

    # Reject a signed token's cross-tenant path before issuing its account-state
    # lookup. The token's tenant claim is already cryptographically verified;
    # same-tenant and admin requests still pass through the live account check.
    requested_tenant = request.path_params.get("tenant_id")
    if requested_tenant is not None:
        require_tenant_access(int(requested_tenant), principal)

    # Re-check account state and authorization on every request so disabled users
    # and changed roles lose access before any tenant-scoped query is made.
    with auth_db_session() as session:
        user = session.scalar(select(User).where(User.user_id == principal.user_id))
        if user is None or user.disabled:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session expired or invalid", headers={"WWW-Authenticate": "Bearer"})
        if user.tenant_id != principal.tenant_id or user.role != principal.role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session expired or invalid", headers={"WWW-Authenticate": "Bearer"})
        if user.email.lower() != principal.email.lower():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session expired or invalid", headers={"WWW-Authenticate": "Bearer"})
    return principal


def require_roles(*roles: str):
    def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> Principal:
        # Reject role-ineligible signed tokens before opening the auth database.
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
        try:
            signed_principal = decode_access_token(credentials.credentials)
        except InvalidToken as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session expired or invalid", headers={"WWW-Authenticate": "Bearer"}) from exc
        request.state.principal = signed_principal
        if signed_principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
        principal = get_principal(request, credentials)
        if principal.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
        return principal
    return dependency


def require_tenant_access(tenant_id: int, principal: Principal) -> None:
    if principal.role != "admin" and principal.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")


@contextmanager
def tenant_session(principal: Principal) -> Iterator[Session]:
    if principal.tenant_id is None:
        # Global administrators must select an explicit tenant before using a
        # tenant-scoped route; global access belongs in admin endpoints only.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Select a tenant for this operation")
    with db_session(tenant_id=principal.tenant_id, role=principal.role) as session:
        yield session


@contextmanager
def tenant_session_for(tenant_id: int, principal: Principal) -> Iterator[Session]:
    """Set RLS for an authorized tenant route, including admin read access."""
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        yield session
