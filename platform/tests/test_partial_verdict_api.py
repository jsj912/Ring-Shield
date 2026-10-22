from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal  # noqa: E402
from api.routers import verdicts  # noqa: E402
from api.schemas import VerdictKind, VerdictRequest  # noqa: E402
from db.models import ExplanationJob, Transaction  # noqa: E402


class FakeSession:
    def __init__(self):
        self.ring = SimpleNamespace(
            tenant_id=21, ring_id="ring-1", scope="tenant",
            member_accounts=[1, 2, 3], member_edges=[10, 11], status="open",
        )
        self.added = []
        self.edge_rows = [(10, 1, 2), (11, 2, 3)]
        self.edge_query_count = 0
        self.flush_count = 0

    def get(self, model, key):
        assert key == {"tenant_id": 21, "ring_id": "ring-1"}
        return self.ring

    def execute(self, statement):
        assert Transaction in [item["entity"] for item in statement.column_descriptions]
        self.edge_query_count += 1
        return SimpleNamespace(all=lambda: self.edge_rows)

    def scalar(self, statement):
        return "analyst@example.test"

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flush_count += 1


def _principal():
    return Principal(user_id=7, tenant_id=21, role="analyst", email="analyst@example.test")


def _install(monkeypatch, session, *, regenerate_url, audit_events, verdict_calls,
             launched=None):
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert (tenant_id, role) == (21, "analyst")
        try:
            yield session
        finally:
            session.committed = True

    monkeypatch.setattr(verdicts, "db_session", fake_db_session)
    monkeypatch.setattr(verdicts, "load_platform_config", lambda: {
        "l4": {"regenerate_url": regenerate_url},
    })
    monkeypatch.setattr(verdicts, "current_request_id", lambda: "request-test")
    monkeypatch.setattr(verdicts, "add_audit_event", lambda *args, **kwargs: audit_events.append(kwargs))
    if launched is not None:
        def launch(job_id):
            assert session.committed is True
            launched.append(job_id)
        monkeypatch.setattr(verdicts, "launch_regeneration_process", launch)

    def fake_record_verdict(*args, **kwargs):
        verdict_calls.append(kwargs)
        session.ring.status = kwargs["verdict"]
        return SimpleNamespace(
            verdict_id=42, corrected_members=kwargs["corrected_members"],
            corrected_edges=kwargs["corrected_edges"],
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(verdicts, "record_verdict", fake_record_verdict)


def test_valid_partial_verdict_creates_queued_job_and_safe_audit(monkeypatch):
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    launched = []
    _install(monkeypatch, session, regenerate_url="https://l4.example.test/regenerate",
             audit_events=audit_events, verdict_calls=verdict_calls, launched=launched)

    result = verdicts.submit_verdict(
        21, "ring-1",
        VerdictRequest(verdict="partial", corrected_members=[1, 2], note="Keep the core"),
        _principal(),
    )

    jobs = [row for row in session.added if isinstance(row, ExplanationJob)]
    assert result.verdict == VerdictKind.partial
    assert result.corrected_members == [1, 2]
    assert result.regeneration.status == "queued"
    assert result.regeneration.job_id.startswith("21.")
    assert jobs[0].verdict_id == 42
    assert jobs[0].requested_by == 7
    assert jobs[0].excluded_members == [3]
    assert jobs[0].excluded_edges == []
    assert audit_events[0]["action"] == "explanation.regeneration_requested"
    assert audit_events[0]["details"] == {"status": "queued"}
    assert "note" not in audit_events[0]["details"]
    assert launched == [result.regeneration.job_id]
    assert verdict_calls[0]["corrected_members"] == [1, 2]
    assert session.ring.status == "partial"


def test_unconfigured_l4_records_partial_verdict_without_job(monkeypatch):
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    _install(monkeypatch, session, regenerate_url=None,
             audit_events=audit_events, verdict_calls=verdict_calls, launched=[])

    result = verdicts.submit_verdict(
        21, "ring-1",
        VerdictRequest(verdict="partial", corrected_members=[1, 2], note="Keep the core"),
        _principal(),
    )

    assert result.verdict == VerdictKind.partial
    assert result.regeneration.model_dump() == {"status": "unavailable", "job_id": None}
    assert session.added == []
    assert audit_events == []
    assert len(verdict_calls) == 1


def test_invalid_partial_verdict_returns_422_before_any_write(monkeypatch):
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    _install(monkeypatch, session, regenerate_url="https://l4.example.test/regenerate",
             audit_events=audit_events, verdict_calls=verdict_calls)

    with pytest.raises(HTTPException) as exc_info:
        verdicts.submit_verdict(
            21, "ring-1",
            VerdictRequest(verdict="partial", corrected_members=[1, 2, 8], note="Invalid"),
            _principal(),
        )

    assert exc_info.value.status_code == 422
    assert session.added == []
    assert audit_events == []
    assert verdict_calls == []


@pytest.mark.parametrize(("corrected_members", "corrected_edges"), [
    ([1, 8], None),
    ([1], None),
    ([1, 2, 3], None),
    ([1, 1], None),
    ([1, 2], []),
    ([1, 2], [10, 10]),
    ([1, 2], [99]),
    ([1, 2], [11]),
])
def test_each_partial_validation_failure_returns_422_without_writes(
        monkeypatch, corrected_members, corrected_edges):
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    _install(monkeypatch, session, regenerate_url="https://l4.example.test/regenerate",
             audit_events=audit_events, verdict_calls=verdict_calls, launched=[])
    values = {"verdict": "partial", "corrected_members": corrected_members,
              "note": "Keep the core"}
    if corrected_edges is not None:
        values["corrected_edges"] = corrected_edges

    with pytest.raises(HTTPException) as exc_info:
        verdicts.submit_verdict(21, "ring-1", VerdictRequest(**values), _principal())

    assert exc_info.value.status_code == 422
    assert session.added == []
    assert audit_events == []
    assert verdict_calls == []


@pytest.mark.parametrize("kind", ["confirm", "reject"])
def test_confirm_and_reject_keep_null_regeneration_response(monkeypatch, kind):
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    _install(monkeypatch, session, regenerate_url="https://l4.example.test/regenerate",
             audit_events=audit_events, verdict_calls=verdict_calls, launched=[])

    result = verdicts.submit_verdict(
        21, "ring-1", VerdictRequest(verdict=kind, corrected_members=[1, 2],
                                     corrected_edges=[10]), _principal(),
    )

    assert result.verdict.value == kind
    assert result.regeneration is None
    assert session.added == []
    assert len(verdict_calls) == 1
    assert verdict_calls[0]["corrected_members"] == [1, 2]
    assert verdict_calls[0]["corrected_edges"] == [10]
    assert audit_events == []


def test_partial_verdict_requires_a_nonempty_note_before_route_execution():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VerdictRequest(verdict="partial", corrected_members=[1, 2], note="  ")


@pytest.mark.parametrize("corrected_members", [[True, 2], [1.5, 2]])
def test_partial_member_ids_reject_boolean_and_fractional_values(corrected_members):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VerdictRequest(verdict="partial", corrected_members=corrected_members,
                       note="Keep the core")


def test_worker_launch_oserror_keeps_queued_response_and_logs_safe_event(
        monkeypatch, caplog):
    import logging

    caplog.set_level(logging.INFO)
    session = FakeSession()
    audit_events = []
    verdict_calls = []
    _install(monkeypatch, session, regenerate_url="https://l4.example.test/regenerate",
             audit_events=audit_events, verdict_calls=verdict_calls, launched=[])

    def fail_launch(job_id):
        assert session.committed is True
        raise OSError("secret path must not be logged")

    monkeypatch.setattr(verdicts, "launch_regeneration_process", fail_launch)
    result = verdicts.submit_verdict(
        21, "ring-1",
        VerdictRequest(verdict="partial", corrected_members=[1, 2], note="Keep the core"),
        _principal(),
    )

    assert result.regeneration.status == "queued"
    assert "regeneration_worker_launch_failed" in caplog.text
    assert "secret path" not in caplog.text
