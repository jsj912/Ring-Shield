from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import ast
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from audit import _audit_insert_statement, add_audit_event  # noqa: E402
from services.verdicts import record_verdict  # noqa: E402


class CaptureSession:
    def __init__(self):
        self.rows = []
        self.statements = []

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        for row in self.rows:
            if getattr(row, "verdict_id", None) is None:
                row.verdict_id = 18

    def execute(self, statement):
        self.statements.append(statement)


def test_audit_helper_accepts_small_safe_details_and_rejects_secrets():
    session = CaptureSession()
    add_audit_event(session, tenant_id=210, actor="user:7", action="drift.acted_on",
                    entity_type="drift_event", entity_id=4,
                    details={"acted_on": True}, request_id="req-1")
    params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert (params["tenant_id"], params["actor"], params["action"],
            params["object_type"], params["object_id"]) == (
        210, "user:7", "drift.acted_on", "drift_event", "4"
    )
    assert params["details"] == {"acted_on": True}
    assert params["request_id"] == "req-1"

    with pytest.raises(ValueError, match="unsupported audit detail"):
        add_audit_event(session, tenant_id=210, actor="user:7", action="user.changed",
                        entity_type="user", entity_id=3, details={"email": "secret@example.test"})
    with pytest.raises(ValueError, match="unsafe audit detail"):
        add_audit_event(session, tenant_id=210, actor="user:7", action="user.changed",
                        entity_type="user", entity_id=3, details={"gate_reason": "C:\\private\\x"})


def test_audit_insert_compiles_without_returning_or_orm_add():
    statement = _audit_insert_statement({
        "tenant_id": 210,
        "actor": "loader",
        "action": "test.insert",
        "object_type": "test",
        "object_id": "marker",
        "details": {},
    })
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "INSERT INTO audit_log" in sql
    assert "RETURNING" not in sql.upper()

    source = (PLATFORM_ROOT / "audit.py").read_text(encoding="utf-8")
    helper = ast.parse(source)
    function = next(node for node in helper.body
                    if isinstance(node, ast.FunctionDef) and node.name == "add_audit_event")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    assert any(isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
               for node in calls)
    assert any(isinstance(node.func, ast.Name) and node.func.id == "_audit_insert_statement"
               for node in calls)
    assert not any(isinstance(node.func, ast.Attribute) and node.func.attr == "add"
                   for node in calls)


def test_verdict_audit_covers_resulting_ring_status_and_simulation_flag():
    session = CaptureSession()
    ring = SimpleNamespace(tenant_id=210, ring_id="ring-1", status="open")
    verdict = record_verdict(session, ring=ring, tenant_id=210, ring_id="ring-1", user_id=5,
                             verdict="confirm", is_simulated=True, actor="simulator")

    audit_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert verdict.is_simulated is True
    assert ring.status == "confirm"
    assert audit_params["action"] == "verdict.recorded"
    assert audit_params["actor"] == "simulator"
    assert audit_params["details"] == {
        "verdict": "confirm", "is_simulated": True, "status": "confirm"
    }


def test_each_business_mutation_module_routes_audit_through_safe_helper():
    expected = {
        "api/routers/admin.py": {"user.created"},
        "api/routers/operations.py": {"drift.acted_on", "retrain.requested", "retrain.failed"},
        "api/scheduler.py": {"retrain.requested", "retrain.failed"},
        "services/verdicts.py": {"verdict.recorded"},
        "jobs/retrain.py": {"model_version.recorded", "model_version.demoted"},
        "jobs/refresh_rings.py": {"rings.refresh_started", "rings.refresh_failed"},
        "jobs/load_contract.py": {"contract.load_completed", "rings.load_completed"},
        "jobs/load_explanations.py": {"explanations.load_completed"},
        "jobs/seed_tenants.py": {"tenants.seed_completed"},
        "jobs/drift_monitor.py": {"drift.events_persisted"},
        "jobs/provision_demo_users.py": {"user.password_reset", "user.credentials_initialized"},
    }
    secret_keys = {"password", "password_hash", "token", "email", "path", "evidence", "narrative"}
    for relative, expected_actions in expected.items():
        path = PLATFORM_ROOT / relative
        source = path.read_text(encoding="utf-8")
        assert "add_audit_event" in source, relative
        assert all(action in source for action in expected_actions), relative
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "add_audit_event":
                continue
            details = next((kw.value for kw in node.keywords if kw.arg == "details"), None)
            if isinstance(details, ast.Dict):
                keys = {key.value for key in details.keys if isinstance(key, ast.Constant)}
                assert not (keys & secret_keys), (relative, keys & secret_keys)
    demo_script = (PLATFORM_ROOT.parent / "scripts" / "run-demo.ps1").read_text(encoding="utf-8")
    assert "platform/jobs/provision_demo_users.py" in demo_script
    assert 'json.dumps({"email"' not in demo_script


def test_admin_user_creation_sets_tenant_context_for_user_and_audit(monkeypatch):
    from api.identity import Principal
    from api.routers import admin
    from api.schemas import UserCreateRequest

    tenant = SimpleNamespace(tenant_id=210, is_loaded=True)
    rows = []
    contexts = []

    class Session:
        def get(self, model, tenant_id):
            assert tenant_id == 210
            return tenant

        def scalar(self, _query):
            return None

        def add(self, row):
            rows.append(row)

        def execute(self, statement):
            rows.append(statement)

        def flush(self):
            for row in rows:
                if hasattr(row, "password_hash"):
                    row.user_id = 810
                    row.created_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
                    row.disabled = False

    @contextmanager
    def fake_db_session(*, tenant_id, role):
        contexts.append((tenant_id, role))
        yield Session()

    monkeypatch.setattr(admin, "db_session", fake_db_session)
    result = admin.create_user(
        UserCreateRequest(tenant_id=210, email="analyst@example.test",
                          password="a sufficiently long password", role="analyst"),
        Principal(user_id=7, tenant_id=None, role="admin", email="admin@example.test"),
    )

    audit_statement = next(row for row in rows
                           if getattr(getattr(row, "table", None), "name", None) == "audit_log")
    audit_params = audit_statement.compile(dialect=postgresql.dialect()).params
    user = next(row for row in rows if hasattr(row, "password_hash"))
    assert contexts == [(210, "admin")]
    assert user.tenant_id == audit_params["tenant_id"] == result.tenant_id == 210
    assert audit_params["action"] == "user.created"
    assert audit_params["details"] == {"role": "analyst"}
    assert "analyst@example.test" not in str(audit_params["details"])
    assert "password" not in str(audit_params["details"]).lower()
