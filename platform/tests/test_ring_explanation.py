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
from api.routers import rings
from db.models import Explanation
from db.models import ExplanationJob


class _FakeSession:
    def __init__(self, ring, explanation):
        self.ring = ring
        self.explanation = explanation
        self.query = None

    def get(self, model, key):
        assert key == {"tenant_id": 21, "ring_id": "ring-1"}
        return self.ring

    def scalar(self, statement):
        self.query = statement
        if ExplanationJob in [description["entity"]
                              for description in statement.column_descriptions]:
            return None
        assert Explanation in [description["entity"]
                               for description in statement.column_descriptions]
        return self.explanation


def _principal(tenant_id=21):
    return Principal(user_id=14, tenant_id=tenant_id, role="analyst", email="reviewer@example.test")


def _install_session(monkeypatch, session):
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role == "analyst"
        yield session

    monkeypatch.setattr(rings, "db_session", fake_db_session)


def test_explanation_is_tenant_scoped_and_hides_artifact_paths(monkeypatch):
    explanation = SimpleNamespace(
        explainer_version="0.4.0-narrative", revision=1, edge_weights=[{"edge_id": 11}],
        account_weights=[{"account_id": 101}], feature_weights=[],
        narrative="Example", evidence_summary={"template": "FAN-OUT"}, latency_ms=12,
        provenance={"aggregator_id": "full", "model_id": "gine_causal",
                    "feature_scope": "tenant_view", "fx_rates_sha256": "a" * 64,
                    "feature_model": "private/model.json", "name_maps": {"bank": "private/map.json"}},
        fx_rates_sha256="a" * 64,
        created_at=datetime.now(timezone.utc),
    )
    _install_session(monkeypatch, _FakeSession(SimpleNamespace(scope="tenant"), explanation))

    result = rings.get_ring_explanation(21, "ring-1", _principal())

    assert result.narrative == "Example"
    assert result.revision == 1
    assert result.regenerated is False
    assert result.edge_weights == [{"edge_id": 11}]
    assert result.provenance == {
        "aggregator_id": "full", "model_id": "gine_causal",
        "feature_scope": "tenant_view", "fx_rates_sha256": "a" * 64,
    }


def test_latest_explanation_uses_creation_time_then_revision_not_version_text(monkeypatch):
    now = datetime.now(timezone.utc)
    candidates = [
        SimpleNamespace(explainer_version="0.4.0", revision=1, created_at=now,
                        provenance={"regenerated": False}),
        SimpleNamespace(explainer_version="0.5.0-review", revision=1,
                        created_at=now, provenance={"regenerated": False}),
        SimpleNamespace(
            tenant_id=21, ring_id="ring-1", explainer_version="0.5.0-review",
            revision=2, created_at=now, edge_weights=[], account_weights=[],
            feature_weights=[], narrative="Corrected explanation", evidence_summary={},
            latency_ms=2, provenance={"regenerated": True}, fx_rates_sha256=None,
        ),
    ]

    class LatestSession(_FakeSession):
        def scalar(self, statement):
            self.query = statement
            if ExplanationJob in [description["entity"]
                                  for description in statement.column_descriptions]:
                return None
            ordering = statement._order_by_clauses
            assert len(ordering) == 3
            assert "min(" in str(ordering[0]).lower()
            assert "revision DESC" in str(ordering[1])
            assert "created_at DESC" in str(ordering[2])
            sql = str(statement.compile())
            assert "explanations.tenant_id =" in sql
            assert "explanations.ring_id =" in sql
            return candidates[2]

    session = LatestSession(SimpleNamespace(scope="tenant"), None)
    _install_session(monkeypatch, session)

    result = rings.get_ring_explanation(21, "ring-1", _principal())

    assert (result.explainer_version, result.revision, result.regenerated) == (
        "0.5.0-review", 2, True,
    )


def test_explanation_rejects_cross_tenant_access_before_database_query(monkeypatch):
    session = _FakeSession(SimpleNamespace(scope="tenant"), None)
    _install_session(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        rings.get_ring_explanation(21, "ring-1", _principal(tenant_id=22))

    assert exc_info.value.status_code == 403
    assert session.query is None
