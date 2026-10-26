"""JWT identity and role definitions for authenticated API requests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME = timedelta(hours=8)


@dataclass(frozen=True)
class Principal:
    user_id: int
    tenant_id: int | None
    role: str
    email: str


class InvalidToken(Exception):
    pass


def _secret() -> str:
    secret = os.environ.get("RINGSHIELD_JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("RINGSHIELD_JWT_SECRET must be set to at least 32 characters")
    return secret


def create_access_token(principal: Principal, *, now: datetime | None = None) -> tuple[str, datetime]:
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + TOKEN_LIFETIME
    claims = {
        "sub": str(principal.user_id),
        "tenant_id": principal.tenant_id,
        "role": principal.role,
        "email": principal.email,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM), expires_at


def decode_access_token(token: str) -> Principal:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
        user_id = int(claims["sub"])
        role = str(claims["role"])
        if role not in {"analyst", "supervisor", "admin"}:
            raise InvalidToken("unsupported role")
        tenant_raw = claims.get("tenant_id")
        tenant_id = None if tenant_raw is None else int(tenant_raw)
        if (role == "admin") != (tenant_id is None):
            raise InvalidToken("role and tenant claims do not agree")
        email = str(claims["email"])
        return Principal(user_id=user_id, tenant_id=tenant_id, role=role, email=email)
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidToken("invalid or expired token") from exc
