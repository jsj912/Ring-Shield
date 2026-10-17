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
from api.routers import operations
from db.models import DriftEvent

pytestmark = pytest.mark.usefixtures("repo_platform_config")


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, statement):
        self.queries.append(statement)
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "FROM model_versions" in compiled
        assert "model_versions.tenant_id = 21" in compiled
        assert "model_versions.tenant_id IS NULL" in compiled
        assert "model_versions.artifact_path" not in compiled
        return self.rows

    def scalars(self, statement):
        self.queries.append(statement)
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert statement.column_descriptions[0]["entity"] is DriftEvent
        assert "drift_events.tenant_id = 21" in compiled
        return self.rows


def _install_session(monkeypatch, session):
    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role == "supervisor"
        yield session

    monkeypatch.setattr(operations, "db_session", fake_db_session)


def _principal(tenant_id=21):
    return Principal(user_id=14, tenant_id=tenant_id, role="supervisor", email="reviewer@example.test")


def test_model_registry_includes_shared_versions_and_hides_artifact_paths(monkeypatch):
    session = _FakeSession([
        SimpleNamespace(model_version_id=5, tenant_id=21, component="typing",
                        version_tag="typing-v2", trained_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        train_label_count=80, holdout_ring_f1=0.82, promoted=True,
                        artifact_path="private/path"),
        SimpleNamespace(model_version_id=4, tenant_id=None, component="detector",
                        version_tag="shared-v1", trained_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
                        train_label_count=100, holdout_ring_f1=None, promoted=True,
                        artifact_path="private/shared-path"),
        SimpleNamespace(model_version_id=3, tenant_id=21, component="expansion",
                        version_tag="expansion-v1", trained_at=datetime(2025, 11, 1, tzinfo=timezone.utc),
                        train_label_count=70, holdout_ring_f1=0.79, promoted=False,
                        artifact_path="private/old-path"),
    ])
    _install_session(monkeypatch, session)

    result = operations.list_model_versions(21, component=None, before_id=None, limit=2,
                                            principal=_principal())

    assert [item.model_version_id for item in result.items] == [5, 4]
    assert [item.shared for item in result.items] == [False, True]
    assert result.next_before_id == 4
    assert "artifact_path" not in result.items[0].model_dump()
    assert result.active_model_id == "gine_causal"
    assert result.active_seed == 1


def test_drift_history_is_tenant_scoped_and_paged(monkeypatch):
    session = _FakeSession([
        SimpleNamespace(event_id=10, monitor="adwin_score_mean",
                        detected_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
                        window_start=datetime(2026, 1, 2, tzinfo=timezone.utc),
                        window_end=datetime(2026, 1, 3, tzinfo=timezone.utc),
                        statistic=0.4, threshold=0.3, acted_on=False),
        SimpleNamespace(event_id=9, monitor="adwin_score_p99",
                        detected_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        window_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
                        statistic=0.95, threshold=0.9, acted_on=True),
    ])
    _install_session(monkeypatch, session)

    result = operations.list_drift_events(21, monitor=None, before_id=None, limit=1,
                                          principal=_principal())

    assert [item.event_id for item in result.items] == [10]
    assert result.next_before_id == 10
    assert result.items[0].acted_on is False


def test_operations_views_reject_other_tenant_before_query(monkeypatch):
    session = _FakeSession([])
    _install_session(monkeypatch, session)

    with pytest.raises(HTTPException) as exc_info:
        operations.list_drift_events(21, monitor=None, before_id=None, limit=50,
                                     principal=_principal(tenant_id=22))

    assert exc_info.value.status_code == 403
    assert session.queries == []
