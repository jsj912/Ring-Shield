from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
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
    launched = []

    class Session:
        def add(self, row):
            added.append(row)

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
    assert added[0].run_id == result.run_id
    assert added[0].status == "running"
    assert added[0].triggered_by == "supervisor"
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


def test_api_modules_never_read_or_import_loader_credentials():
    import ast

    api_root = PLATFORM_ROOT / "api"
    violations = []
    for path in api_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "RINGSHIELD_LOADER_DATABASE_URL":
                violations.append(f"{path.relative_to(PLATFORM_ROOT)}:{node.lineno}: loader URL reference")
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
