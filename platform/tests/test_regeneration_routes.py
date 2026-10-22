from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal  # noqa: E402
from api.routers import rings  # noqa: E402
from api.schemas import RegenerateExplanationRequest  # noqa: E402
from db.models import Explanation, ExplanationJob, Ring, Transaction, Verdict  # noqa: E402


NOW = datetime.now(timezone.utc)


def _ring():
    return SimpleNamespace(
        tenant_id=21, ring_id="ring-1", scope="tenant",
        member_accounts=[1, 2, 3], member_edges=[10, 11],
    )


def _verdict():
    return SimpleNamespace(
        tenant_id=21, ring_id="ring-1", verdict_id=41, verdict="partial",
        is_simulated=False, corrected_members=[1, 2], corrected_edges=[],
    )


def _job(status="queued", *, age_seconds=1):
    return SimpleNamespace(
        job_id="21." + "a" * 32, tenant_id=21, ring_id="ring-1", verdict_id=41,
        status=status, result_revision=3 if status == "succeeded" else None,
        error=None, created_at=NOW - timedelta(seconds=age_seconds), finished_at=None,
    )


class FakeSession:
    def __init__(self, *, job_results=(), explanation=None):
        self.ring = _ring()
        self.verdict = _verdict()
        self.job_results = list(job_results)
        self.explanation = explanation
        self.added = []
        self.edge_rows = [(10, 1, 2), (11, 2, 3)]
        self.scalar_calls = 0
        self.statements = []
        self.flushes = 0

    def get(self, model, key):
        assert model is Ring
        assert key == {"tenant_id": 21, "ring_id": "ring-1"}
        return self.ring

    def execute(self, statement):
        assert Transaction in [item["entity"] for item in statement.column_descriptions]
        return SimpleNamespace(all=lambda: self.edge_rows)

    def scalar(self, statement):
        self.scalar_calls += 1
        self.statements.append(statement)
        sql = str(statement.compile())
        if "FROM explanation_jobs" in sql:
            return self.job_results.pop(0) if self.job_results else None
        if "FROM verdicts" in sql:
            return self.verdict
        assert "FROM explanations" in sql
        return self.explanation

    def add(self, row):
        self.added.append(row)
        if isinstance(row, ExplanationJob):
            row.created_at = NOW

    def flush(self):
        self.flushes += 1


def _principal(role="analyst", tenant_id=21):
    return Principal(user_id=7, tenant_id=tenant_id, role=role,
                     email="analyst@example.test")


def _install(monkeypatch, session, *, launched=None, audit=None):
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role in {"analyst", "supervisor", "admin"}
        yield session

    monkeypatch.setattr(rings, "db_session", fake_db_session)
    monkeypatch.setattr(rings, "load_platform_config", lambda: {
        "l4": {"regenerate_url": "https://l4.example.test/regenerate"},
    })
    monkeypatch.setattr(rings, "current_request_id", lambda: "request-test")
    if launched is not None:
        monkeypatch.setattr(rings, "launch_regeneration_process", launched.append)
    if audit is not None:
        monkeypatch.setattr(rings, "add_audit_event", lambda *args, **kwargs: audit.append(kwargs))


@pytest.mark.parametrize("status", ["queued", "running", "succeeded"])
def test_regenerate_route_returns_existing_active_job(monkeypatch, status):
    existing = _job(status, age_seconds=1)
    session = FakeSession(job_results=[existing])
    launched, audit = [], []
    _install(monkeypatch, session, launched=launched, audit=audit)

    result = rings.regenerate_ring_explanation(
        21, "ring-1", RegenerateExplanationRequest(verdict_id=41), _principal(),
    )

    assert result.job_id == existing.job_id
    assert result.status == status
    assert launched == []
    assert audit == []
    assert session.added == []


def test_regenerate_route_relaunches_queued_job_older_than_thirty_seconds(monkeypatch):
    existing = _job("queued", age_seconds=31)
    session = FakeSession(job_results=[existing])
    launched = []
    _install(monkeypatch, session, launched=launched, audit=[])

    result = rings.regenerate_ring_explanation(
        21, "ring-1", RegenerateExplanationRequest(verdict_id=41), _principal(),
    )

    assert result.job_id == existing.job_id
    assert launched == [existing.job_id]


def test_regenerate_route_creates_new_job_after_failed_job(monkeypatch):
    failed = _job("failed")
    session = FakeSession(job_results=[None, failed])
    launched, audit = [], []
    _install(monkeypatch, session, launched=launched, audit=audit)

    result = rings.regenerate_ring_explanation(
        21, "ring-1", RegenerateExplanationRequest(verdict_id=41), _principal(),
    )

    jobs = [row for row in session.added if isinstance(row, ExplanationJob)]
    assert result.status == "queued"
    assert result.job_id.startswith("21.")
    assert result.job_id != failed.job_id
    assert jobs[0].excluded_members == [3]
    assert jobs[0].excluded_edges == []
    assert launched == [result.job_id]
    assert audit[0]["action"] == "explanation.regeneration_requested"


@pytest.mark.parametrize("role,tenant", [("analyst", 22), ("admin", None)])
def test_regenerate_route_rejects_other_tenant_and_admin_before_query(
        monkeypatch, role, tenant):
    session = FakeSession()
    _install(monkeypatch, session)
    principal = _principal(role=role, tenant_id=tenant)

    with pytest.raises(HTTPException) as exc_info:
        rings.regenerate_ring_explanation(
            21, "ring-1", RegenerateExplanationRequest(verdict_id=41), principal,
        )

    assert exc_info.value.status_code == 403
    assert session.scalar_calls == 0


def test_job_status_is_404_when_job_is_not_visible_to_tenant(monkeypatch):
    session = FakeSession(job_results=[None])
    _install(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        rings.get_explanation_job(21, "ring-1", "21." + "b" * 32, _principal())

    assert exc_info.value.status_code == 404
    assert any("explanation_jobs.tenant_id =" in str(statement.compile())
               and "explanation_jobs.job_id =" in str(statement.compile())
               for statement in session.statements)


def test_job_status_sanitizes_unsafe_error(monkeypatch):
    job = _job("failed")
    job.error = "failed at C:\\private\\worker.py https://secret.test"
    session = FakeSession(job_results=[job])
    _install(monkeypatch, session)

    result = rings.get_explanation_job(21, "ring-1", job.job_id, _principal())

    assert result.error == "Explanation regeneration could not be completed"


def test_explanation_response_marks_active_job_as_regenerating(monkeypatch):
    explanation = SimpleNamespace(
        tenant_id=21, ring_id="ring-1", explainer_version="0.5.0", revision=1,
        edge_weights=[], account_weights=[], feature_weights=[], narrative="N",
        evidence_summary={}, latency_ms=1, provenance={}, fx_rates_sha256=None,
        created_at=NOW,
    )
    session = FakeSession(job_results=["active-job"], explanation=explanation)
    _install(monkeypatch, session)

    result = rings.get_ring_explanation(21, "ring-1", _principal())

    assert result.regenerating is True
