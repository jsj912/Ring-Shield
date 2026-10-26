"""API cross-tenant authorization checks against the real seeded database."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token
from api.main import app
from api import dependencies
from api.routers import rings


def _user_id(email: str) -> int:
    url = os.environ["RINGSHIELD_AUTH_DATABASE_URL"]
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.user_role', 'auth', true)"))
        user_id = connection.execute(text("SELECT user_id FROM users WHERE email = :email"),
                                     {"email": email}).scalar_one()
    engine.dispose()
    return user_id


def _token(email: str, tenant_id: int | None, role: str) -> str:
    token, _ = create_access_token(Principal(
        user_id=_user_id(email), tenant_id=tenant_id, role=role, email=email,
    ))
    return token


def test_tenant_a_token_is_rejected_before_tenant_query_and_admin_can_read(monkeypatch):
    attempted_query = False

    @contextmanager
    def forbidden_auth_query(*args, **kwargs):
        nonlocal attempted_query
        attempted_query = True
        raise AssertionError("account-state query ran before cross-tenant authorization")
        yield

    def forbidden_tenant_query(*args, **kwargs):
        nonlocal attempted_query
        attempted_query = True
        raise AssertionError("tenant query ran before authorization")

    monkeypatch.setattr(dependencies, "auth_db_session", forbidden_auth_query)
    monkeypatch.setattr(rings, "db_session", forbidden_tenant_query)
    client = TestClient(app)
    tenant_a = _token("analyst-210@test.invalid", 210, "analyst")
    response = client.get("/tenants/220/rings", headers={"Authorization": f"Bearer {tenant_a}"})
    assert response.status_code == 403
    assert response.json().keys() == {"error_code", "message", "request_id"}
    assert response.json()["error_code"] == "NOT_PERMITTED"
    assert response.json()["request_id"]
    assert attempted_query is False

    monkeypatch.undo()
    admin = _token("admin@test.invalid", None, "admin")
    response = client.get("/tenants/220/rings", headers={"Authorization": f"Bearer {admin}"})
    assert response.status_code == 200
