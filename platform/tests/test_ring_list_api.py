from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from db.models import Ring
from api.routers import rings

RING_SEARCH_MIGRATION = PLATFORM_ROOT / "db" / "migrations" / "versions" / "0008_ring_member_search.py"


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.count_call = 0
        self.row_query = None

    def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "FROM explanations" in sql:
            # the ring total comes from the tenant's own latest explanation
            assert "explanations.tenant_id = 21" in sql
            return None
        assert "rings.tenant_id = 21" in sql
        self.count_call += 1
        return (0, 3)[self.count_call - 1]

    def scalars(self, statement):
        self.row_query = str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        ))
        return self.rows


def test_ring_list_reports_filtered_and_unfiltered_tenant_counts(monkeypatch):
    row = SimpleNamespace(
        ring_id="ring-1", tenant_id=21, topology_type="CYCLE", topology_probs=[0.8],
        member_accounts=[1, 2], member_edges=[10, 11], payload={"n_edges": 2},
        confidence=0.8, start_time=0, end_time=21600, status="open",
    )
    fake = _FakeSession([row])

    @contextmanager
    def fake_session(tenant_id, principal):
        assert tenant_id == 21
        assert principal.role == "analyst"
        yield fake

    monkeypatch.setattr(rings, "_tenant_session", fake_session)
    monkeypatch.setattr(rings, "to_utc", lambda value: datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = rings.list_rings(21, status_filter=["open"], min_conf=None,
                              topology_type=[], limit=50,
                              principal=Principal(
        user_id=1, tenant_id=21, role="analyst", email="analyst@example.test"))

    assert result.total == 0
    assert result.tenant_total == 3
    assert result.items[0].window_text == "over 6 h"


def test_ring_window_text_uses_day_wording_for_multi_day_windows():
    assert rings._window_text(172800) == "over 2 d"


def test_ring_search_compiles_exact_id_or_indexed_account_membership(monkeypatch):
    fake = _FakeSession([])

    @contextmanager
    def fake_session(*, tenant_id, role):
        assert tenant_id == 21
        assert role == "analyst"
        yield fake

    monkeypatch.setattr(rings, "db_session", fake_session)
    result = rings.list_rings(
        21, status_filter=["open"], min_conf=None, topology_type=[], q="12345",
        limit=50,
        principal=Principal(user_id=1, tenant_id=21, role="analyst", email="analyst@example.test"),
    )
    assert result.items == []
    sql = fake.row_query
    assert "rings.tenant_id = 21" in sql
    assert "rings.ring_id = '12345'" in sql
    assert "rings.member_accounts @> CAST(ARRAY[12345] AS BIGINT[])" in sql


def test_ring_account_search_operator_and_gin_index_match_migration():
    """Array containment @> is supported by PostgreSQL's default array_ops GIN class."""
    migration_source = RING_SEARCH_MIGRATION.read_text(encoding="utf-8")
    normalized_migration = re.sub(r"\s+", " ", migration_source)
    assert 'CREATE INDEX ix_rings_member_accounts_gin ON rings USING GIN (member_accounts)' in normalized_migration

    index = next(index for index in Ring.__table__.indexes
                 if index.name == "ix_rings_member_accounts_gin")
    assert index.dialect_options["postgresql"]["using"] == "gin"
    assert [column.name for column in index.expressions] == ["member_accounts"]
    assert "array_ops" not in normalized_migration


def test_ring_search_rejects_cross_tenant_before_opening_session(monkeypatch):
    import pytest
    from fastapi import HTTPException

    opened = False

    @contextmanager
    def fake_session(*, tenant_id, role):
        nonlocal opened
        opened = True
        yield _FakeSession([])

    monkeypatch.setattr(rings, "db_session", fake_session)
    with pytest.raises(HTTPException) as exc_info:
        rings.list_rings(
            21, status_filter=["open"], min_conf=None, topology_type=[], q="12345",
            limit=50,
            principal=Principal(user_id=1, tenant_id=22, role="analyst", email="other@example.test"),
        )
    assert exc_info.value.status_code == 403
    assert not opened
