from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from api.routers import rings
from db.models import Account, Transaction


class _FakeSession:
    def __init__(self, ring, accounts, transactions):
        self.ring = ring
        self.accounts = accounts
        self.transactions = transactions
        self.queries = []

    def get(self, model, key):
        assert key == {"tenant_id": 21, "ring_id": "ring-1"}
        return self.ring

    def scalars(self, statement):
        self.queries.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        if entity is Transaction:
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "ORDER BY transactions.edge_id DESC" in compiled
            assert "transactions.tenant_id = 21" in compiled
            return self.transactions
        assert entity is Account
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "accounts.tenant_id = 21" in compiled
        return self.accounts


def _install_session(monkeypatch, fake_session):
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role == "analyst"
        yield fake_session

    monkeypatch.setattr(rings, "db_session", fake_db_session)


def _principal(tenant_id=21):
    return Principal(user_id=14, tenant_id=tenant_id, role="analyst", email="reviewer@example.test")


def _ring(member_edges=(11, 12, 13), scope="tenant"):
    return SimpleNamespace(
        scope=scope,
        member_edges=list(member_edges),
        member_accounts=[101, 102, 103],
        payload={"source_accounts": [101], "sink_accounts": [103], "mule_accounts": [102]},
    )


def _transaction(edge_id, from_id, to_id, from_bank=210, to_bank=211):
    return SimpleNamespace(
        edge_id=edge_id,
        from_id=from_id,
        to_id=to_id,
        from_bank=from_bank,
        to_bank=to_bank,
        timestamp=1000 + edge_id,
        amount_sent=12.5,
        amount_received=12.0,
        currency_sent=1,
        currency_received=1,
        payment_format=2,
        score_calibrated=0.92,
        is_seed=edge_id == 11,
    )


def test_ring_evidence_returns_scoped_nodes_edges_and_pagination(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_TIME_ORIGIN_UTC", "2020-01-01T00:00:00Z")
    session = _FakeSession(
        _ring(member_edges=(11, 13, 12)),
        [SimpleNamespace(account_id=101, bank_code=210),
         SimpleNamespace(account_id=102, bank_code=211),
         SimpleNamespace(account_id=103, bank_code=212)],
        [_transaction(13, 102, 103), _transaction(12, 101, 102)],
    )
    _install_session(monkeypatch, session)

    result = rings.get_ring_evidence(21, "ring-1", before_edge_id=None, limit=2,
                                     principal=_principal())

    assert [edge.edge_id for edge in result.edges] == [13, 12]
    assert result.next_before_edge_id == 12
    assert [(node.account_id, node.bank_code) for node in result.nodes] == [
        (101, 210), (102, 211), (103, 212)
    ]
    assert result.nodes[1].is_mule
    assert result.edges[0].source_account == 102
    assert result.edges[0].timestamp is not None
    assert result.missing_edge_ids == []
    assert "account_number" not in str(result.model_dump()).lower()


def test_ring_evidence_reports_contract_edges_missing_from_storage(monkeypatch):
    session = _FakeSession(_ring(member_edges=(13,)), [], [])
    _install_session(monkeypatch, session)

    result = rings.get_ring_evidence(21, "ring-1", before_edge_id=None, limit=10,
                                     principal=_principal())

    assert result.edges == []
    assert result.missing_edge_ids == [13]
    assert result.next_before_edge_id is None


def test_ring_evidence_rejects_cross_tenant_access_before_query(monkeypatch):
    session = _FakeSession(_ring(), [], [])
    _install_session(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        rings.get_ring_evidence(21, "ring-1", before_edge_id=None, limit=10,
                                principal=_principal(tenant_id=22))

    assert exc_info.value.status_code == 403
    assert session.queries == []


def test_ring_summary_never_shows_a_multi_currency_total(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_TIME_ORIGIN_UTC", "2020-01-01T00:00:00Z")
    ring = SimpleNamespace(
        ring_id="multi-currency", tenant_id=21, topology_type="FAN-OUT",
        topology_probs=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        member_accounts=[1, 2], member_edges=[1, 2], confidence=0.8,
        start_time=1, end_time=2, status="open",
        payload={"n_currencies": 2, "total_amount": 999.0, "total_currency": 1},
    )

    result = rings._summary(ring)

    assert result.total_amount is None
    assert result.total_currency is None
    assert result.n_currencies == 2
