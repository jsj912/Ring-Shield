from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from sqlalchemy.dialects import postgresql

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs import provision_demo_users as provisioning  # noqa: E402


class _Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one(self):
        return self.value


class _FakeConnection:
    def __init__(self):
        self.active = False
        self.current_tenant = None
        self.user_statements = []
        self.user_parameters = []
        self.audit_parameters = []
        self.context_updates = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        assert self.active, "user write and audit must share an active transaction"
        if "INSERT INTO users" in sql:
            self.user_statements.append(sql)
            self.user_parameters.append(parameters)
            return _Result({"user_id": 987 + len(self.user_statements) - 1,
                            "tenant_id": parameters["tenant_id"]})
        if "set_config('app.tenant_id'" in sql:
            self.current_tenant = int(parameters["tenant_id"])
            self.context_updates.append(parameters["tenant_id"])
            return _Result(None)
        if "set_config('app.user_role'" in sql:
            return _Result(None)
        if "INSERT INTO audit_log" in sql:
            compiled = statement.compile(dialect=postgresql.dialect())
            self.audit_parameters.append(compiled.params)
            return _Result(None)
        raise AssertionError(f"Unexpected SQL from provisioning module: {sql}")


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def begin(self):
        return self

    def __enter__(self):
        self.connection.active = True
        return self.connection

    def __exit__(self, *_args):
        self.connection.active = False
        return False

    def dispose(self):
        self.disposed = True


@pytest.mark.parametrize(
    ("password_reset", "expected_action", "expected_update"),
    [
        (False, "user.credentials_initialized", "role=EXCLUDED.role"),
        (True, "user.password_reset", "password_hash=EXCLUDED.password_hash"),
    ],
)
def test_demo_user_provisioning_audits_in_transaction_and_saves_credentials_silently(
        monkeypatch, tmp_path, capsys, caplog, password_reset, expected_action, expected_update):
    password = "demo-test-password-do-not-log"
    email = "analyst-210@example.invalid"
    admin_email = "admin@example.invalid"
    admin_password = "demo-admin-password-do-not-log"
    credentials = {"admin_email": admin_email, "admin_password": admin_password,
                   "tenant_210_analyst_email": email,
                   "tenant_210_analyst_password": password}
    users = [
        {"TenantId": "None", "Email": admin_email, "Password": admin_password, "Role": "admin"},
        {"TenantId": "210", "Email": email, "Password": password, "Role": "analyst"},
    ]
    connection = _FakeConnection()
    engine = _FakeEngine(connection)
    audit_calls = []
    real_add_audit_event = provisioning.add_audit_event

    def track_audit_event(session, **kwargs):
        assert session.active
        assert session.current_tenant == kwargs["tenant_id"]
        audit_calls.append(kwargs)
        return real_add_audit_event(session, **kwargs)

    monkeypatch.setattr(provisioning, "create_engine", lambda _url: engine)
    monkeypatch.setattr(provisioning, "add_audit_event", track_audit_event)
    credentials_path = tmp_path / "demo-credentials.txt"
    monkeypatch.setenv("RINGSHIELD_DEMO_ADMIN_URL", "postgresql://fake")
    monkeypatch.setenv("RINGSHIELD_DEMO_USERS_JSON", json.dumps(users))
    monkeypatch.setenv("RINGSHIELD_DEMO_CREDENTIALS_JSON", json.dumps(credentials))
    monkeypatch.setenv("RINGSHIELD_DEMO_CREDENTIALS_PATH", str(credentials_path))
    monkeypatch.setenv("RINGSHIELD_DEMO_PASSWORD_RESET", "1" if password_reset else "0")

    provisioning.main()

    assert expected_update in connection.user_statements[0]
    assert len(audit_calls) == 2
    assert [event["action"] for event in audit_calls] == [expected_action, expected_action]
    assert [(event["tenant_id"], event["user_id"], event["details"]) for event in audit_calls] == [
        (None, 987, {"role": "admin"}), (210, 988, {"role": "analyst"}),
    ]
    assert connection.context_updates == ["210"]
    assert len(connection.audit_parameters) == 2
    audit_text = repr(audit_calls) + repr(connection.audit_parameters)
    hashes = [parameters["password_hash"] for parameters in connection.user_parameters]
    assert all(secret not in audit_text for secret in (password, admin_password, email, admin_email, *hashes))
    assert credentials_path.read_text(encoding="utf-8") == (
        f"admin_email={admin_email}\nadmin_password={admin_password}\n"
        f"tenant_210_analyst_email={email}\ntenant_210_analyst_password={password}\n"
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert all(secret not in caplog.text for secret in (password, admin_password, *hashes))
    assert engine.disposed
