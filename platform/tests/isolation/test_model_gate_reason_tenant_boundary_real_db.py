"""GET /models now returns gate_reason and retrain_run_id, and retrain runs list their candidates:
prove a bank sees its own refused candidates and never another bank's versions or runs."""

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


def _headers(tenant_id: int, role: str, marker: str = "") -> dict:
    email = (f"supervisor-{tenant_id}-{marker}@test.invalid" if role == "supervisor"
             else f"analyst-{tenant_id}@test.invalid")
    token, _ = create_access_token(Principal(user_id=_user_id(email), tenant_id=tenant_id,
                                             role=role, email=email))
    return {"Authorization": f"Bearer {token}"}


def test_gate_reasons_and_run_candidates_stay_inside_the_tenant(register_db_test_ids):
    marker = f"gate-{uuid4().hex}"
    run_id = f"run-{uuid4().hex[:12]}"
    register_db_test_ids(marker, run_id)
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    try:
        with admin.begin() as connection:
            for tenant_id in (210, 220):                       # the seed has analysts only
                connection.execute(text("""
                    INSERT INTO users (tenant_id, email, password_hash, role)
                    VALUES (:tenant_id, :email, 'not-a-login', 'supervisor')
                """), {"tenant_id": tenant_id, "email": f"supervisor-{tenant_id}-{marker}@test.invalid"})
            connection.execute(text("""
                INSERT INTO retrain_runs (run_id, tenant_id, triggered_by, status, started_at, finished_at)
                VALUES (:run_id, 220, 'supervisor', 'succeeded', now(), now())
            """), {"run_id": run_id})
            connection.execute(text("""
                INSERT INTO model_versions (tenant_id, component, version_tag, trained_at,
                                            train_label_count, holdout_ring_f1, promoted,
                                            gate_reason, retrain_run_id)
                VALUES (220, 'expansion', :tag, now(), 7, 0.6612, false, :reason, :run_id)
            """), {"tag": marker[:40], "reason": marker, "run_id": run_id})
        client = TestClient(app)

        own_runs = client.get("/tenants/220/retrain", headers=_headers(220, "supervisor", marker))
        assert own_runs.status_code == 200
        run = next(item for item in own_runs.json()["items"] if item["run_id"] == run_id)
        assert run["model_version_id"] is None                     # refused: nothing promoted
        assert [c["gate_reason"] for c in run["candidates"]] == [marker]
        own_models = client.get("/tenants/220/models", headers=_headers(220, "analyst"))
        assert any(item["gate_reason"] == marker and item["retrain_run_id"] == run_id
                   for item in own_models.json()["items"])

        other = _headers(210, "supervisor", marker)
        assert marker not in client.get("/tenants/210/models", headers=other).text
        assert marker not in client.get("/tenants/210/retrain", headers=other).text
        assert client.get("/tenants/220/models", headers=other).status_code == 403
        assert client.get("/tenants/220/retrain", headers=other).status_code == 403
        assert client.get(f"/tenants/220/retrain/{run_id}", headers=other).status_code == 403
    finally:
        with admin.begin() as connection:
            connection.execute(text("DELETE FROM model_versions WHERE tenant_id = 220 AND gate_reason = :m"),
                               {"m": marker})
            connection.execute(text("DELETE FROM retrain_runs WHERE run_id = :r"), {"r": run_id})
            connection.execute(text("DELETE FROM users WHERE email LIKE :e"),
                               {"e": f"supervisor-%-{marker}@test.invalid"})
        admin.dispose()
