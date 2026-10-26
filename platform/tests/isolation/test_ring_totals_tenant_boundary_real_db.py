"""Ring totals now come from the tenant's own latest explanation: prove one bank never sees
another bank's total, even for a ring with the same id in both tenants."""

from __future__ import annotations

import json
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


def _set_total(connection, tenant_id: int, total: float, partial: bool, marker: str) -> None:
    connection.execute(text("""
        UPDATE explanations
           SET provenance = CAST(:provenance AS jsonb),
               evidence_summary = CAST(:summary AS jsonb)
         WHERE tenant_id = :tenant_id AND ring_id = 'demo-cycle'
    """), {"tenant_id": tenant_id,
           "provenance": json.dumps({"flow_total_ccy0": total, "flow_partial": partial}),
           "summary": json.dumps({"values": {"currency_hub_name": f"{marker}-{tenant_id}"}})})


def test_a_bank_reads_only_its_own_explanation_total_for_a_shared_ring_id(register_db_test_ids):
    marker = f"ring-total-{uuid4().hex}"
    register_db_test_ids(marker)            # the session-end leak check proves the restore ran
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            _set_total(connection, 210, 123.45, False, marker)
            _set_total(connection, 220, 999999.99, True, marker)
        email = "analyst-210@test.invalid"
        token, _ = create_access_token(Principal(user_id=_user_id(email), tenant_id=210,
                                                 role="analyst", email=email))
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}

        own = client.get("/tenants/210/rings/demo-cycle", headers=headers)
        assert own.status_code == 200
        assert own.json()["total_amount"] == 123.45
        assert own.json()["total_currency"] == f"{marker}-210"
        assert own.json()["total_partial"] is False

        listed = client.get("/tenants/210/rings", headers=headers, params={"status": "open"})
        assert listed.status_code == 200
        assert all(item["total_amount"] != 999999.99 for item in listed.json()["items"])

        other = client.get("/tenants/220/rings/demo-cycle", headers=headers)
        assert other.status_code == 403
        assert "999999" not in other.text
    finally:
        with admin.begin() as connection:
            for tenant_id in (210, 220):
                connection.execute(text("""
                    UPDATE explanations SET provenance = '{}'::jsonb, evidence_summary = '{}'::jsonb
                     WHERE tenant_id = :tenant_id AND ring_id = 'demo-cycle'
                """), {"tenant_id": tenant_id})
        admin.dispose()
