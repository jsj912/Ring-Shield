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

from api.identity import Principal
from api.routers import verdicts
from api.schemas import VerdictKind


def _verdict(verdict_id: int, kind: str = "confirm") -> SimpleNamespace:
    return SimpleNamespace(
        verdict_id=verdict_id,
        ring_id="ring-1",
        user_id=14,
        verdict=kind,
        corrected_members=[],
        corrected_edges=[],
        note=f"review {verdict_id}",
        is_simulated=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class _FakeSession:
    def __init__(self, rows: list[tuple[SimpleNamespace, str]], ring=None):
        self.rows = rows
        self.ring = ring if ring is not None else SimpleNamespace(scope="tenant")
        self.executed = False
        self.expected_before = None

    def get(self, model, key):
        assert key == {"tenant_id": 21, "ring_id": "ring-1"}
        return self.ring

    def execute(self, statement):
        self.executed = True
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "ORDER BY verdicts.verdict_id DESC" in compiled
        assert "LIMIT 3" in compiled
        if self.expected_before is not None:
            assert f"verdicts.verdict_id < {self.expected_before}" in compiled
        return self.rows


def _install_session(monkeypatch, fake_session: _FakeSession) -> None:
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role == "analyst"
        yield fake_session

    monkeypatch.setattr(verdicts, "db_session", fake_db_session)


def _principal(tenant_id: int = 21) -> Principal:
    return Principal(user_id=14, tenant_id=tenant_id, role="analyst", email="reviewer@example.test")


def test_verdict_history_returns_newest_first_and_next_cursor(monkeypatch):
    session = _FakeSession([
        (_verdict(31, "reject"), "reviewer@example.test"),
        (_verdict(30), "reviewer@example.test"),
        (_verdict(29, "reject"), "reviewer@example.test"),
    ])
    _install_session(monkeypatch, session)

    result = verdicts.list_verdicts(21, "ring-1", before_id=None, limit=2,
                                    principal=_principal())

    assert [item.verdict_id for item in result.items] == [31, 30]
    assert [item.verdict for item in result.items] == [VerdictKind.reject, VerdictKind.confirm]
    assert result.next_before_id == 30
    assert session.executed


def test_verdict_history_uses_verified_tenant_before_database_access(monkeypatch):
    session = _FakeSession([])
    _install_session(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        verdicts.list_verdicts(21, "ring-1", before_id=None, limit=25,
                               principal=_principal(tenant_id=22))

    assert exc_info.value.status_code == 403
    assert not session.executed


def test_verdict_history_cursor_requests_older_rows(monkeypatch):
    session = _FakeSession([
        (_verdict(29, "reject"), "reviewer@example.test"),
        (_verdict(28), "reviewer@example.test"),
    ])
    session.expected_before = 30
    _install_session(monkeypatch, session)

    result = verdicts.list_verdicts(21, "ring-1", before_id=30, limit=2,
                                    principal=_principal())

    assert [item.verdict_id for item in result.items] == [29, 28]
    assert result.next_before_id is None


def test_verdict_history_hides_missing_or_pooled_ring(monkeypatch):
    session = _FakeSession([], ring=SimpleNamespace(scope="pooled"))
    _install_session(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        verdicts.list_verdicts(21, "ring-1", before_id=None, limit=25,
                               principal=_principal())

    assert exc_info.value.status_code == 404
    assert not session.executed
