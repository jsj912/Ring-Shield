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
from api.schemas import DriftActedOnUpdate
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


def test_drift_series_is_supervisor_only_and_tenant_scoped_before_query(monkeypatch):
    session = _FakeSession([])
    _install_session(monkeypatch, session)
    with pytest.raises(HTTPException) as exc_info:
        operations.get_drift_series(
            21, Principal(user_id=14, tenant_id=21, role="analyst", email="analyst@example.test"),
        )
    assert exc_info.value.status_code == 403
    assert session.queries == []


def test_drift_action_update_checks_tenant_and_uses_explicit_predicates(monkeypatch):
    event = SimpleNamespace(
        event_id=9, monitor="adwin_score_mean",
        detected_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        window_start=datetime(2026, 1, 2, tzinfo=timezone.utc),
        window_end=datetime(2026, 1, 3, tzinfo=timezone.utc),
        statistic=0.4, threshold=0.002, acted_on=False,
    )

    class UpdateSession(_FakeSession):
        def scalar(self, statement):
            self.queries.append(statement)
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "drift_events.tenant_id = 21" in compiled
            assert "drift_events.event_id = 9" in compiled
            return event

        def execute(self, statement):
            self.queries.append(statement)
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "drift_events.tenant_id = 21" in compiled
            assert "drift_events.event_id = 9" in compiled
            return None

    session = UpdateSession([])
    _install_session(monkeypatch, session)
    result = operations.set_drift_acted_on(
        21, 9, DriftActedOnUpdate(acted_on=True), principal=_principal(),
    )
    assert result.acted_on is True

    session.queries.clear()
    with pytest.raises(HTTPException) as exc_info:
        operations.set_drift_acted_on(
            21, 9, DriftActedOnUpdate(acted_on=False), principal=_principal(tenant_id=22),
        )
    assert exc_info.value.status_code == 403
    assert session.queries == []


def test_retrain_run_history_is_supervisor_tenant_scoped(monkeypatch):
    rows = [SimpleNamespace(run_id="run-a", status="succeeded",
                            started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                            finished_at=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
                            model_version_id=8)]

    class RunSession:
        def __init__(self):
            self.queries = []

        def scalars(self, statement):
            self.queries.append(statement)
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "retrain_runs.tenant_id = 21" in compiled
            return rows

    session = RunSession()

    @contextmanager
    def fake_session(*, tenant_id=None, role=None):
        assert tenant_id == 21
        assert role == "supervisor"
        yield session

    monkeypatch.setattr(operations, "db_session", fake_session)
    page = operations.list_retrain_runs(21, limit=50, principal=_principal())
    assert page.items[0].run_id == "run-a"
    assert page.items[0].status == "succeeded"

    session.queries.clear()
    with pytest.raises(HTTPException) as exc_info:
        operations.list_retrain_runs(21, limit=50,
                                     principal=_principal(tenant_id=22))
    assert exc_info.value.status_code == 403
    assert session.queries == []


def test_manual_drift_check_launches_separate_tenant_worker_only_for_supervisor(monkeypatch):
    launched = []
    monkeypatch.setattr(operations, "launch_drift_process", lambda tenant: launched.append(tenant))
    result = operations.start_drift_check(21, principal=_principal())
    assert result.status == "queued"
    assert launched == [21]

    analyst = Principal(user_id=14, tenant_id=21, role="analyst", email="analyst@example.test")
    with pytest.raises(HTTPException) as exc_info:
        operations.start_drift_check(21, principal=analyst)
    assert exc_info.value.status_code == 403
    assert launched == [21]

    with pytest.raises(HTTPException) as exc_info:
        operations.start_drift_check(21, principal=_principal(tenant_id=22))
    assert exc_info.value.status_code == 403
    assert launched == [21]
