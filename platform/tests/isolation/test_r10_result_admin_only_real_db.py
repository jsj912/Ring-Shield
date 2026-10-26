"""GET /admin/experiments/tenant-vs-pooled/latest serves the registered R10 result to the
administrator only: a bank analyst is refused and sees none of the numbers."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token
from api.main import app


def _user_id(email: str) -> int:
    engine = create_engine(os.environ["RINGSHIELD_AUTH_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.user_role', 'auth', true)"))
        user_id = connection.execute(text("SELECT user_id FROM users WHERE email = :email"),
                                     {"email": email}).scalar_one()
    engine.dispose()
    return user_id


def test_only_the_administrator_reads_the_registered_r10_result():
    client = TestClient(app)
    analyst = "analyst-210@test.invalid"
    token, _ = create_access_token(Principal(user_id=_user_id(analyst), tenant_id=210,
                                             role="analyst", email=analyst))
    refused = client.get("/admin/experiments/tenant-vs-pooled/latest",
                         headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403
    assert "0.3588" not in refused.text

    admin = "admin@test.invalid"
    token, _ = create_access_token(Principal(user_id=_user_id(admin), tenant_id=None,
                                             role="admin", email=admin))
    served = client.get("/admin/experiments/tenant-vs-pooled/latest",
                        headers={"Authorization": f"Bearer {token}"})
    assert served.status_code == 200
    assert served.json()["results"]["rows"]["primary"]["tenants"] == [1, 20, 11, 118, 12]
