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


def _row(verdict_id, *, kind="confirm", created_at=None, note="checked"):
    return SimpleNamespace(
        verdict_id=verdict_id,
        ring_id=f"ring-{verdict_id}",
        user_id=17,
        verdict=kind,
        is_simulated=True,
        note=note,
        created_at=created_at or datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self):
        self.scalar_calls = []
        self.execute_calls = []
        self.scalar_result = 3
        self.page_rows = [_row(30, kind="reject"), _row(29), _row(28, kind="partial")]

    def scalar(self, statement):
        self.scalar_calls.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
        return self.scalar_result

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.execute_calls.append(sql)
        return _Result([("confirm", 1), ("reject", 1), ("partial", 1)])

    def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.execute_calls.append(sql)
        if "DISTINCT verdicts.user_id" in sql:
            return _Scalars([17, 18])
        return _Scalars(self.page_rows)


def _principal(tenant_id=21):
    return Principal(user_id=17, tenant_id=tenant_id, role="analyst", email="private@example.test")


def test_tenant_verdict_list_applies_filters_counts_and_cursor(monkeypatch):
    session = _FakeSession()

    @contextmanager
    def fake_session(*, tenant_id, role):
        assert tenant_id == 21
        assert role == "analyst"
        yield session

    monkeypatch.setattr(verdicts, "db_session", fake_session)
    result = verdicts.list_tenant_verdicts(
        21, since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 1, 3, tzinfo=timezone.utc), verdict_filter=["confirm", "reject"],
        analyst_id=17, simulated=True, limit=2, principal=_principal(),
    )

    assert result.total == 3
    assert result.counts.confirmed == 1
    assert result.counts.rejected == 1
    assert result.counts.partial == 1
    assert [item.verdict_id for item in result.items] == [30, 29]
    assert result.next_cursor
    assert result.items[0].analyst_label == "Analyst 17"
    assert "private@example.test" not in str(result.model_dump())
    page_sql = session.execute_calls[-1]
    assert "verdicts.tenant_id = 21" in page_sql
    assert "verdicts.verdict IN ('confirm', 'reject')" in page_sql
    assert "verdicts.user_id = 17" in page_sql
    assert "verdicts.is_simulated IS true" in page_sql
    assert "verdicts.created_at >= '2026-01-01 00:00:00+00:00'" in page_sql
    assert "verdicts.created_at <= '2026-01-03 00:00:00+00:00'" in page_sql
    assert "ORDER BY verdicts.created_at DESC, verdicts.verdict_id DESC" in page_sql

    session.page_rows = [_row(27)]
    older = verdicts.list_tenant_verdicts(
        21, verdict_filter=None, analyst_id=None, cursor=result.next_cursor,
        limit=2, principal=_principal(),
    )
    assert [item.verdict_id for item in older.items] == [27]
    cursor_query = session.execute_calls[-1]
    assert "verdicts.created_at <" in cursor_query
    assert "verdicts.verdict_id < 29" in cursor_query


def test_tenant_verdict_list_rejects_other_tenant_before_query(monkeypatch):
    opened = False

    @contextmanager
    def fake_session(*, tenant_id, role):
        nonlocal opened
        opened = True
        yield _FakeSession()

    monkeypatch.setattr(verdicts, "db_session", fake_session)
    with pytest.raises(HTTPException) as exc_info:
        verdicts.list_tenant_verdicts(21, principal=_principal(22))
    assert exc_info.value.status_code == 403
    assert not opened
