"""The routes behind the verdict form and verdict history: a bank user can neither read another
bank's verdict history or regeneration jobs nor record a verdict on another bank's ring."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from uuid import uuid4

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


def test_verdict_history_jobs_and_submission_stay_inside_the_tenant(register_db_test_ids):
    marker = f"verdict-note-{uuid4().hex}"
    register_db_test_ids(marker)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    other_user = _user_id("analyst-220@test.invalid")
    try:
        with admin.begin() as connection:
            connection.execute(text("""
                INSERT INTO verdicts (tenant_id, ring_id, user_id, verdict, corrected_members,
                                      corrected_edges, note, is_simulated)
                VALUES (220, 'demo-cycle', :user_id, 'reject', '{}', '{}', :note, false)
            """), {"user_id": other_user, "note": marker})
            before = connection.execute(text(
                "SELECT count(*) FROM verdicts WHERE tenant_id = 220")).scalar_one()
        email = "analyst-210@test.invalid"
        token, _ = create_access_token(Principal(user_id=_user_id(email), tenant_id=210,
                                                 role="analyst", email=email))
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}

        own = client.get("/tenants/210/verdicts", headers=headers)
        assert own.status_code == 200
        assert marker not in own.text
        assert all(item["analyst_id"] != other_user for item in own.json()["analysts"])

        assert client.get("/tenants/220/verdicts", headers=headers).status_code == 403
        assert client.get("/tenants/220/rings/demo-cycle/verdicts", headers=headers).status_code == 403
        assert client.get(f"/tenants/220/rings/demo-cycle/explanation/jobs/{uuid4()}",
                          headers=headers).status_code == 403
        posted = client.post("/tenants/220/rings/demo-cycle/verdicts", headers=headers,
                             json={"verdict": "confirm", "note": "cross-tenant attempt"})
        assert posted.status_code == 403
        assert client.post("/tenants/220/rings/demo-cycle/explanation/regenerate", headers=headers,
                           json={"verdict_id": 1}).status_code == 403
        with admin.begin() as connection:
            after = connection.execute(text(
                "SELECT count(*) FROM verdicts WHERE tenant_id = 220")).scalar_one()
        assert after == before
    finally:
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM verdicts WHERE tenant_id = 220 AND note = :note"),
                               {"note": marker})
        admin.dispose()
