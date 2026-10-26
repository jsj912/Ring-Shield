from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from api.identity import create_access_token
from api.routers import operations


def _principal(role="supervisor", tenant_id=21):
    return Principal(user_id=8, tenant_id=tenant_id, role=role, email="lead@example.test")


def test_cross_tenant_retrain_post_returns_403_before_any_query(monkeypatch):
    queried = False

    @contextmanager
    def forbidden_query(**kwargs):
        nonlocal queried
        queried = True
        raise AssertionError("database must not be queried")
        yield

    monkeypatch.setattr(operations, "db_session", forbidden_query)

    with pytest.raises(HTTPException) as exc_info:
        operations.start_retrain(22, _principal())

    assert exc_info.value.status_code == 403
    assert not queried


def test_cross_tenant_retrain_status_returns_403_before_any_query(monkeypatch):
    queried = False

    @contextmanager
    def forbidden_query(**kwargs):
        nonlocal queried
        queried = True
        raise AssertionError("database must not be queried")
        yield

    monkeypatch.setattr(operations, "db_session", forbidden_query)

    with pytest.raises(HTTPException) as exc_info:
        operations.get_retrain_status(22, "run-id", _principal())

    assert exc_info.value.status_code == 403
    assert not queried


@pytest.mark.parametrize("role", ["analyst", "admin"])
def test_non_supervisor_retrain_post_returns_403_before_any_query(monkeypatch, role):
    @contextmanager
    def forbidden_query(**kwargs):
        raise AssertionError("database must not be queried")
        yield

    monkeypatch.setattr(operations, "db_session", forbidden_query)

    with pytest.raises(HTTPException) as exc_info:
        operations.start_retrain(21, _principal(role=role, tenant_id=None if role == "admin" else 21))

    assert exc_info.value.status_code == 403


def test_retrain_post_creates_a_run_and_starts_a_separate_worker(monkeypatch):
    added = []
    executed = []
    launched = []

    class Session:
        def add(self, row):
            added.append(row)

        def execute(self, statement):
            executed.append(statement)

        def flush(self):
            pass

    @contextmanager
    def fake_db_session(*, tenant_id, role):
        assert tenant_id == 21
        assert role == "supervisor"
        yield Session()

    monkeypatch.setattr(operations, "db_session", fake_db_session)
    monkeypatch.setattr(operations, "launch_retrain_process", lambda *args: launched.append(args))
    result = operations.start_retrain(21, _principal())

    assert len(added) == 1
    run_row = next(row for row in added if hasattr(row, "run_id"))
    audit_statement = next(row for row in executed
                           if getattr(getattr(row, "table", None), "name", None) == "audit_log")
    audit_params = audit_statement.compile().params
    assert run_row.run_id == result.run_id
    assert run_row.status == "running"
    assert run_row.triggered_by == "supervisor"
    assert audit_params["action"] == "retrain.requested"
    assert audit_params["details"] == {"status": "running"}
    assert launched == [(21, result.run_id)]


def test_retrain_launcher_starts_a_child_without_reading_job_credentials(monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(operations.subprocess, "Popen", fake_popen)
    operations.launch_retrain_process(21, "run-a")

    assert captured["command"][-3:] == ["jobs.retrain_worker", "21", "run-a"]
    assert "env" not in captured  # child gets its own process environment from the runtime
    assert captured["stdin"] is operations.subprocess.DEVNULL
    assert captured["stdout"] is operations.subprocess.DEVNULL


def test_supervisor_mode_keeps_retrain_run_without_spawning_child(monkeypatch, caplog):
    caplog.set_level("INFO")
    added = []

    class Session:
        def add(self, row):
            added.append(row)

        def execute(self, _statement):
            pass

        def flush(self):
            pass

    @contextmanager
    def fake_db_session(*, tenant_id, role):
        assert (tenant_id, role) == (21, "supervisor")
        yield Session()

    def forbidden_popen(*_args, **_kwargs):
        raise AssertionError("supervisor mode must not spawn from the API")

    monkeypatch.setattr(operations, "db_session", fake_db_session)
    monkeypatch.setattr(operations.subprocess, "Popen", forbidden_popen)
    monkeypatch.setenv("RINGSHIELD_WORKER_MODE", "supervisor")

    result = operations.start_retrain(21, _principal())

    row = next(row for row in added if hasattr(row, "run_id"))
    assert row.run_id == result.run_id
    assert row.status == "running"
    assert '"outcome":"deferred_to_supervisor"' in caplog.text


def test_api_modules_never_read_or_import_loader_credentials():
    import ast

    api_root = PLATFORM_ROOT / "api"
    violations = []
    forbidden_environment = {
        "RINGSHIELD_LOADER_DATABASE_URL", "RINGSHIELD_XAI_TOKEN",
        "RINGSHIELD_DATABASE_ADMIN_URL", "RINGSHIELD_SIMULATOR_DATABASE_URL",
    }
    for path in api_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in forbidden_environment:
                violations.append(f"{path.relative_to(PLATFORM_ROOT)}:{node.lineno}: restricted worker credential reference")
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("db.session"):
                if any(alias.name in {"loader_db_session", "get_loader_engine"} for alias in node.names):
                    violations.append(f"{path.relative_to(PLATFORM_ROOT)}:{node.lineno}: loader session import")
    assert violations == []


def test_retrain_log_output_redacts_windows_and_unix_absolute_paths():
    path = PLATFORM_ROOT / "out" / "retrain" / f"{uuid4().hex}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("failed C:\\private\\model\\weights.bin and /srv/private/data.parquet\n", encoding="utf-8")
    try:
        lines = operations.retrain_log_lines(f"platform/out/retrain/{path.name}")
    finally:
        path.unlink(missing_ok=True)

    assert len(lines) == 1
    assert "C:\\private" not in lines[0]
    assert "/srv/private" not in lines[0]
    assert "weights.bin" in lines[0]
    assert "data.parquet" in lines[0]


@pytest.mark.parametrize("role", ["analyst", "supervisor"])
def test_r10_admin_endpoint_rejects_other_roles_before_auth_query(monkeypatch, role, repo_platform_config):
    from api import dependencies
    from api.main import app

    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    token, _ = create_access_token(_principal(role=role))

    @contextmanager
    def fail_auth_query():
        raise AssertionError("ineligible R10 role must be rejected before the auth query")
        yield

    monkeypatch.setattr(dependencies, "auth_db_session", fail_auth_query)
    response = TestClient(app).post(
        "/admin/experiments/tenant-vs-pooled",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert set(response.json()) >= {"error_code", "message", "request_id"}


def test_r10_admin_start_and_status_use_file_state_and_structured_logs(monkeypatch, tmp_path, capsys, repo_platform_config):
    from api import dependencies
    from api.main import app
    from api.routers import admin

    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    principal = _principal(role="admin", tenant_id=None)
    token, _ = create_access_token(principal)
    user = SimpleNamespace(user_id=principal.user_id, tenant_id=None,
                           role="admin", email=principal.email, disabled=False)

    class AuthSession:
        def scalar(self, _query): return user
        def get(self, *_args): return None

    @contextmanager
    def fake_auth_session():
        yield AuthSession()

    @contextmanager
    def fake_db_session(*, role, tenant_id=None):
        raise AssertionError("R10 job state is file-backed and must not open a DB session")
        yield None

    launched = []
    monkeypatch.setattr(dependencies, "auth_db_session", fake_auth_session)
    monkeypatch.setattr(admin, "db_session", fake_db_session)
    monkeypatch.setattr(admin, "EXPERIMENT_OUTPUT", tmp_path)
    monkeypatch.setattr(admin.subprocess, "Popen", lambda command, **kwargs: launched.append((command, kwargs)))

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    started = client.post("/admin/experiments/tenant-vs-pooled", headers=headers)
    assert started.status_code == 202
    payload = started.json()
    assert payload["status"] == "queued"
    assert launched and launched[0][0][-3:-1] == ["jobs.experiment_worker", "r10"]
    assert "env" not in launched[0][1]
    state_path = tmp_path / f"{payload['job_id']}.json"
    assert "ground_truth" not in state_path.read_text(encoding="utf-8").lower()

    state_path.write_text(json.dumps({"job_id": payload["job_id"], "status": "succeeded",
                                      "results": {"csv": "reports/r10.csv"}}), encoding="utf-8")
    status_response = client.get(
        f"/admin/experiments/tenant-vs-pooled/{payload['job_id']}", headers=headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "succeeded"
    assert "ground_truth" not in status_response.text.lower()
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(row["event"] == "experiment.requested" and row["job_id"] == payload["job_id"] for row in logs)


@pytest.mark.parametrize("role", ["analyst", "supervisor"])
def test_latest_r10_result_is_refused_to_bank_users(monkeypatch, role, repo_platform_config):
    from api import dependencies
    from api.main import app

    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    token, _ = create_access_token(_principal(role=role))

    @contextmanager
    def fail_auth_query():
        raise AssertionError("a bank user must be rejected before the auth query")
        yield

    monkeypatch.setattr(dependencies, "auth_db_session", fail_auth_query)
    response = TestClient(app).get("/admin/experiments/tenant-vs-pooled/latest",
                                   headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "0.0882" not in response.text


def _r11_lane(root, name, tenant_id, accuracy):
    lane = root / name
    lane.mkdir()
    (lane / "run.json").write_text(json.dumps({
        "tenant_id": tenant_id, "accuracy": accuracy, "created_utc": "2026-10-24T11:03:07+00:00", "cycles": 12,
        "cycle_hours": 4, "retrain_after_cycle": 6, "components": ["expansion", "affinity"],
        "typing": "not refit; R5 head fixed"}), encoding="utf-8")
    (lane / "cycles.md").write_text(
        "| accuracy | cycle | retrain_status | candidates |\n| --- | --- | --- | --- |\n"
        f"| {accuracy} | 6 | succeeded | affinity 0.6556 refused |\n", encoding="utf-8")


@pytest.fixture
def r11_root(tmp_path, monkeypatch):
    from jobs import experiment_worker
    _r11_lane(tmp_path, "accuracy_0.90", 21, 0.9)
    _r11_lane(tmp_path, "accuracy_0.70", 21, 0.7)
    _r11_lane(tmp_path, "accuracy_0.80", 22, 0.8)            # another bank's run
    monkeypatch.setattr(experiment_worker, "R11_DIR", tmp_path)
    return tmp_path


def test_r11_results_return_only_the_supervisors_own_tenant(r11_root):
    result = operations.get_r11_results(21, _principal())
    assert [lane.accuracy for lane in result.items] == [0.7, 0.9]
    assert {lane.tenant_id for lane in result.items} == {21}
    assert result.items[0].cycle_rows == [{"accuracy": "0.7", "cycle": "6", "retrain_status": "succeeded",
                                           "candidates": "affinity 0.6556 refused"}]
    assert "simulated" in result.statement


def test_r11_results_of_another_tenant_are_refused(r11_root):
    with pytest.raises(HTTPException) as exc_info:
        operations.get_r11_results(22, _principal(tenant_id=21))
    assert exc_info.value.status_code == 403


def test_r11_results_hold_nothing_for_a_bank_without_an_r11_run(r11_root):
    assert operations.get_r11_results(23, _principal(tenant_id=23)).items == []


@pytest.mark.parametrize("role", ["analyst", "admin"])
def test_r11_results_are_for_supervisors_only(r11_root, role):
    with pytest.raises(HTTPException) as exc_info:
        operations.get_r11_results(21, _principal(role=role))
    assert exc_info.value.status_code == 403


def test_r11_route_is_registered_on_the_app():
    from api.main import app
    assert "/tenants/{tenant_id}/experiments/r11" in [route.path for route in app.routes]
