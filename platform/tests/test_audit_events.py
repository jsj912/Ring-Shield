from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import ast

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from audit import add_audit_event  # noqa: E402
from services.verdicts import record_verdict  # noqa: E402


class CaptureSession:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        for row in self.rows:
            if getattr(row, "verdict_id", None) is None:
                row.verdict_id = 18


def test_audit_helper_accepts_small_safe_details_and_rejects_secrets():
    session = CaptureSession()
    event = add_audit_event(session, tenant_id=210, actor="user:7", action="drift.acted_on",
                            entity_type="drift_event", entity_id=4,
                            details={"acted_on": True}, request_id="req-1")
    assert event in session.rows
    assert (event.actor, event.action, event.object_type, event.object_id) == (
        "user:7", "drift.acted_on", "drift_event", "4"
    )
    assert event.details == {"acted_on": True}
    assert event.request_id == "req-1"

    with pytest.raises(ValueError, match="unsupported audit detail"):
        add_audit_event(session, tenant_id=210, actor="user:7", action="user.changed",
                        entity_type="user", entity_id=3, details={"email": "secret@example.test"})
    with pytest.raises(ValueError, match="unsafe audit detail"):
        add_audit_event(session, tenant_id=210, actor="user:7", action="user.changed",
                        entity_type="user", entity_id=3, details={"gate_reason": "C:\\private\\x"})


def test_verdict_audit_covers_resulting_ring_status_and_simulation_flag():
    session = CaptureSession()
    ring = SimpleNamespace(tenant_id=210, ring_id="ring-1", status="open")
    verdict = record_verdict(session, ring=ring, tenant_id=210, ring_id="ring-1", user_id=5,
                             verdict="confirm", is_simulated=True, actor="simulator")

    audit = next(row for row in session.rows if hasattr(row, "action"))
    assert verdict.is_simulated is True
    assert ring.status == "confirm"
    assert audit.action == "verdict.recorded"
    assert audit.actor == "simulator"
    assert audit.details == {"verdict": "confirm", "is_simulated": True, "status": "confirm"}


def test_each_business_mutation_module_routes_audit_through_safe_helper():
    expected = {
        "api/routers/admin.py": {"user.created", "experiment.requested", "experiment.finished"},
        "api/routers/operations.py": {"drift.acted_on", "retrain.requested", "retrain.failed"},
        "api/scheduler.py": {"retrain.requested", "retrain.failed"},
        "services/verdicts.py": {"verdict.recorded"},
        "jobs/retrain.py": {"model_version.recorded", "model_version.demoted"},
        "jobs/refresh_rings.py": {"rings.refresh_started", "rings.refresh_failed"},
        "jobs/load_contract.py": {"contract.load_completed", "rings.load_completed"},
        "jobs/load_explanations.py": {"explanations.load_completed"},
        "jobs/seed_tenants.py": {"tenants.seed_completed"},
        "jobs/drift_monitor.py": {"drift.events_persisted"},
        "jobs/experiment_worker.py": {"experiment.started", "experiment.finished"},
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
    assert "user.password_reset" in demo_script
    assert "user.credentials_initialized" in demo_script
    assert 'json.dumps({"email"' not in demo_script
