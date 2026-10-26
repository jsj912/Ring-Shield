"""GET /tenants/{t}/rings/{id}/subgraph takes roles and weights from the tenant's own explanation:
prove one bank never sees another bank's roles, even for a ring id both tenants hold."""

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


def test_a_bank_reads_only_its_own_roles_and_weights_in_the_subgraph(register_db_test_ids):
    marker = f"subgraph-role-{uuid4().hex}"
    register_db_test_ids(marker)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            for tenant_id, role in ((210, "mule"), (220, marker)):
                weights = [{"account_id": 101, "role": role, "inflow": 1.0, "outflow": 1.0,
                            "hold_time_s": None, "w_account": 0.5}]
                connection.execute(text("""
                    UPDATE explanations SET account_weights = CAST(:weights AS jsonb)
                     WHERE tenant_id = :tenant_id AND ring_id = 'demo-cycle'
                """), {"tenant_id": tenant_id, "weights": json.dumps(weights)})
        email = "analyst-210@test.invalid"
        token, _ = create_access_token(Principal(user_id=_user_id(email), tenant_id=210,
                                                 role="analyst", email=email))
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {token}"}

        own = client.get("/tenants/210/rings/demo-cycle/subgraph", headers=headers)
        assert own.status_code == 200
        roles = {node["role"] for node in own.json()["nodes"]}
        assert "mule" in roles and marker not in roles
        assert own.json()["n_accounts"] == len(own.json()["nodes"])

        other = client.get("/tenants/220/rings/demo-cycle/subgraph", headers=headers)
        assert other.status_code == 403
        assert marker not in other.text
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                UPDATE explanations SET account_weights = '[]'::jsonb
                 WHERE tenant_id IN (210, 220) AND ring_id = 'demo-cycle'
            """))
        admin.dispose()
