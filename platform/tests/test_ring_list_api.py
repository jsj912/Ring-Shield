from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from api.routers import rings


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.count_call = 0
        self.row_query = None

    def scalar(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "rings.tenant_id = 21" in sql
        self.count_call += 1
        return (0, 3)[self.count_call - 1]

    def scalars(self, statement):
        self.row_query = str(statement.compile(compile_kwargs={"literal_binds": True}))
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
