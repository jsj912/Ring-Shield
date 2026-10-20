from __future__ import annotations

from pathlib import Path
import sys
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))


def test_api_imports_and_bcrypt_hashes_password_without_database():
    from api.main import app
    from api.passwords import hash_password, verify_password

    password = "correct horse battery staple"
    encoded_hash = hash_password(password)

    assert app is not None
    assert verify_password(password, encoded_hash)
    assert not verify_password("a different password", encoded_hash)


def test_password_byte_limit_is_enforced_at_creation_and_login():
    from api.routers.auth import login
    from api.schemas import LoginRequest, UserCreateRequest

    too_long = chr(233) * 37  # 74 UTF-8 bytes, despite only 37 characters.
    with pytest.raises(ValidationError, match="at most 72 UTF-8 bytes"):
        UserCreateRequest(tenant_id=210, email="user@example.test", password=too_long,
                          role="analyst")

    with pytest.raises(HTTPException) as exc_info:
        login(LoginRequest(email="unknown@example.test", password=too_long), request=object())
    assert exc_info.value.status_code == 422
    assert "at most 72 UTF-8 bytes" in exc_info.value.detail


def test_bad_login_credentials_keep_indistinguishable_api_401_contract(monkeypatch):
    from api import passwords
    from api.routers import auth
    from api.schemas import LoginRequest

    user = type("UserRow", (), {
        "user_id": 5,
        "tenant_id": None,
        "email": "demo@example.test",
        "password_hash": passwords.hash_password("the correct password"),
        "role": "admin",
        "disabled": False,
    })()

    class FakeSession:
        selected_user = None

        def scalar(self, _query):
            return self.selected_user

        def get(self, _model, _key):
            return None

    fake_session = FakeSession()

    @contextmanager
    def fake_auth_session():
        yield fake_session

    monkeypatch.setattr(auth, "auth_db_session", fake_auth_session)
    failures = []
    for selected_user, email, submitted_password in (
        (None, "unknown@example.test", "whatever password"),
        (user, "demo@example.test", "wrong password"),
    ):
        fake_session.selected_user = selected_user
        with pytest.raises(HTTPException) as exc_info:
            auth.login(LoginRequest(email=email, password=submitted_password), request=object())
        assert exc_info.value.status_code == 401
        failures.append(exc_info.value.detail)

    assert failures == ["Invalid email or password", "Invalid email or password"]


def test_jwt_contract_contains_tenant_role_and_exact_eight_hour_expiry(monkeypatch):
    from datetime import datetime, timezone
    from jose import jwt
    from api.identity import Principal, create_access_token, decode_access_token, InvalidToken

    secret = "fixed-test-secret-with-at-least-thirty-two-bytes"
    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", secret)
    issued = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    token, expiry = create_access_token(
        Principal(user_id=81, tenant_id=210, role="supervisor", email="supervisor@example.test"),
        now=issued,
    )
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False})
    assert claims["sub"] == "81"
    assert claims["tenant_id"] == 210
    assert claims["role"] == "supervisor"
    assert claims["iat"] == int(issued.timestamp())
    assert int(claims["exp"]) - int(claims["iat"]) == 8 * 60 * 60
    assert expiry.timestamp() == claims["exp"]
    assert decode_access_token(token).tenant_id == 210
    with pytest.raises(InvalidToken):
        decode_access_token("invalid.token.value")
