from __future__ import annotations

from pathlib import Path
import sys

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
