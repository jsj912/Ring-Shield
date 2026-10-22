from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert, Update

from jobs import regenerate_worker as worker


TENANT_ID = 20
RING_ID = "repeated-ring-id"
JOB_ID = f"{TENANT_ID}.{uuid4().hex}"
FX_HASH = "a" * 64
CONFIG = {"fx_rates_sha256": FX_HASH, "l4": {"rings_schema_version": 1,
                                                 "regenerate_url": "https://l4.invalid",
                                                 "regenerate_timeout_seconds": 120}}


def _result():
    return {
        "tenant_id": TENANT_ID, "ring_id": RING_ID, "explainer_version": "0.5.0-review",
        "edge_weights": [{"edge_id": 17, "weight": 0.6}],
        "account_weights": [{"account_id": 2, "weight": 1.0}],
        "feature_weights": [], "narrative": "Corrected ring narrative",
        "evidence_summary": '{"template":"cycle"}', "latency_ms": 12,
        "provenance": (
            '{"scope":"tenant","tenant_id":20,"feature_scope":"tenant_view",'
            f'"fx_rates_sha256":"{FX_HASH}","rings_schema_version":1,'
            '"explainer_version":"0.5.0-review","regenerated":true,'
            '"excluded_members":[3],"excluded_edges":[9]}'
        ),
    }


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, state):
        self.state = state

    def scalar(self, statement):
        self.state["claim_statement"] = statement
        job = self.state["job"]
        if job.status != "queued":
            return None
        return job

    def execute(self, statement):
        if isinstance(statement, Insert):
            table = statement.table.name
            self.state["inserts"].append(table)
            if table == "explanations":
                self.state.setdefault("insert_statements", []).append(statement)
                outcomes = self.state["revision_insert_outcomes"]
                return _ScalarResult(outcomes.pop(0) if outcomes else None)
            return _ScalarResult(None)
        if isinstance(statement, Update):
            self.state["updates"].append(statement)
            values = statement.compile().params
            self.state["job"].status = values.get("status", self.state["job"].status)
            if "result_revision" in values:
                self.state["job"].result_revision = values["result_revision"]
            if "error" in values:
                self.state["job"].error = values["error"]
            return _ScalarResult(None)
        raise AssertionError(f"unexpected statement type: {type(statement)}")

    def flush(self):
        return None


def _install(monkeypatch, *, response=None, revision_insert_outcomes=None):
    job = SimpleNamespace(
        tenant_id=TENANT_ID, job_id=JOB_ID, ring_id=RING_ID,
        excluded_members=[3], excluded_edges=[9], status="queued", started_at=None,
        error=None, result_revision=None,
    )
    state = {"job": job, "inserts": [], "updates": [],
             "revision_insert_outcomes": list([2] if revision_insert_outcomes is None
                                               else revision_insert_outcomes)}
    session = _FakeSession(state)

    @contextmanager
    def fake_session(*, tenant_id):
        assert tenant_id == TENANT_ID
        yield session

    monkeypatch.setattr(worker, "loader_db_session", fake_session)
    monkeypatch.setattr(worker.xai, "regenerate", lambda *args, **kwargs: response or _result())
    monkeypatch.setattr(worker, "add_audit_event", lambda *args, **kwargs: state.setdefault("audit", []).append(kwargs))
    safe_error = worker._safe_error

    def capture_error(exc):
        state["exception"] = repr(exc)
        return safe_error(exc)

    monkeypatch.setattr(worker, "_safe_error", capture_error)
    return state


def test_valid_result_stores_revision_two_and_succeeds(monkeypatch):
    state = _install(monkeypatch)

    assert worker.run_job(JOB_ID, config=CONFIG), state

    assert state["job"].status == "succeeded"
    assert state["job"].result_revision == 2
    assert "explanations" in state["inserts"]
    assert [event["action"] for event in state["audit"]] == [
        "explanation.regeneration_succeeded",
    ]
    claim_sql = str(state["claim_statement"].compile(dialect=postgresql.dialect())).upper()
    assert "FOR UPDATE" in claim_sql and "SKIP LOCKED" in claim_sql


def test_optional_health_version_mismatch_warns_without_failing_job(monkeypatch, caplog):
    state = _install(monkeypatch)
    monkeypatch.setattr(worker.xai, "health", lambda **_kwargs: {
        "status": "ok", "explainer_version": "newer-version",
    })
    config = {**CONFIG, "l4": {**CONFIG["l4"], "check_health_version": True}}

    with caplog.at_level("WARNING", logger=worker.__name__):
        assert worker.run_job(JOB_ID, config=config), state

    assert state["job"].status == "succeeded"
    assert "differs from stored explanation row" in caplog.text


@pytest.mark.parametrize(
    ("error_type", "safe_code", "safe_message"),
    [
        (worker.xai.XaiBadRequestError, "bad_request", "L4 rejected the regeneration request"),
        (worker.xai.XaiInternalError, "internal_error", "L4 explanation service failed"),
    ],
)
def test_bad_request_and_internal_error_fail_jobs_without_body_text(
        monkeypatch, error_type, safe_code, safe_message):
    state = _install(monkeypatch)
    monkeypatch.setattr(
        worker.xai, "regenerate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error_type("private response body")),
    )

    assert not worker.run_job(JOB_ID, config=CONFIG)
    assert state["job"].status == "failed"
    assert state["job"].error == safe_message
    assert "private response body" not in state["job"].error
    assert state["audit"][0]["details"] == {"error_code": safe_code}

def test_revision_insert_uses_tenant_scoped_max_and_retries_one_collision(monkeypatch):
    state = _install(monkeypatch, revision_insert_outcomes=[None, 3])
    assert worker.run_job(JOB_ID, config=CONFIG), state
    assert state["job"].result_revision == 3
    assert state["inserts"].count("explanations") == 2
    compiled = state["insert_statements"][0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    lowered = sql.lower()
    assert "coalesce(max(explanations.revision)" in lowered
    assert "where explanations.tenant_id =" in lowered
    assert "from explanations" in lowered
    assert lowered.count("from explanations") == 1


@pytest.mark.parametrize(
    ("location", "updates", "message"),
    [
        ("row", {"tenant_id": 21}, "tenant_id"),
        ("provenance", {"scope": "pooled"}, "scope"),
        ("provenance", {"feature_scope": "all"}, "feature_scope"),
        ("provenance", {"fx_rates_sha256": "b" * 64}, "fx_rates_sha256"),
        ("provenance", {"regenerated": False}, "regenerated"),
        ("provenance", {"excluded_members": [8]}, "excluded_members"),
        ("provenance", {"excluded_edges": [8]}, "excluded_edges"),
        ("provenance", {"rings_schema_version": 2}, "rings_schema_version"),
        ("row", {"narrative": ""}, "narrative"),
        ("row", {"edge_weights": [{"weight": float("nan")}]}, "non-finite"),
    ],
)
def test_invalid_result_fails_with_safe_message(monkeypatch, location, updates, message):
    import copy
    import json

    result = copy.deepcopy(_result())
    if location == "row":
        result.update(updates)
    else:
        provenance = json.loads(result["provenance"])
        provenance.update(updates)
        result["provenance"] = json.dumps(provenance)
    state = _install(monkeypatch, response=result)

    assert not worker.run_job(JOB_ID, config=CONFIG)

    assert state["job"].status == "failed"
    assert state["job"].error
    assert state["job"].error == "L4 explanation result failed tenant validation"
    assert message not in state["job"].error
    assert "edge_weights" not in state["job"].error
    assert state["inserts"] == []
    assert state["audit"][-1]["action"] == "explanation.regeneration_failed"


def test_adapter_422_and_missing_configuration_fail_the_job(monkeypatch):
    state = _install(monkeypatch)
    monkeypatch.setattr(worker.xai, "regenerate", lambda *a, **k: (_ for _ in ()).throw(
        worker.xai.XaiInvalidEditError("At least two accounts must remain")))
    assert not worker.run_job(JOB_ID, config=CONFIG)
    assert "At least two accounts" in state["job"].error

    state = _install(monkeypatch)
    monkeypatch.setattr(worker.xai, "regenerate", lambda *a, **k: (_ for _ in ()).throw(
        worker.xai.XaiNotConfiguredError()))
    assert not worker.run_job(JOB_ID, config=CONFIG)
    assert state["job"].error == worker.xai.XaiNotConfiguredError.safe_message


def test_worker_does_not_write_other_tenants_or_forbidden_tables(monkeypatch):
    state = _install(monkeypatch)
    assert worker.run_job(JOB_ID, config=CONFIG), state
    assert set(state["inserts"]) <= {"explanations", "audit_log"}
    for statement in state["updates"]:
        assert "tenant_id" in str(statement.whereclause)
    with pytest.raises(AssertionError):
        worker.run_job(f"21.{uuid4().hex}", config=CONFIG)
    with pytest.raises(ValueError, match="job_id"):
        worker.tenant_from_job_id("opaque-job-id")
