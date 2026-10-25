"""The hourly drift route and the administrator's R12 panel: bank users never see the R12
experiment tenant (900001) or the synthetic positive control."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal, create_access_token
from api.routers import admin, operations
from jobs import experiment_worker

pytestmark = pytest.mark.usefixtures("repo_platform_config")


def _hour(h):
    return f"2022-09-{9 + h // 24:02d}T{h % 24:02d}:00:00+00:00"


def _tenant(tenant_id, extra=None):
    return {"tenant_id": tenant_id, "active_model_id": "gine_causal", "active_seed": 1, "step_seconds": 3600,
            "items": [{"day": _hour(h), "mean": 0.001, "p99": 0.01, **(extra or {})} for h in range(48)],
            "adwin": [{"hour": _hour(h), "adwin_mean_width": h + 1, "adwin_mean_drift": False,
                       "adwin_p99_width": h + 1, "adwin_p99_drift": False} for h in range(48)],
            "events": [], **({"control": {"step": 3}} if extra else {})}


@pytest.fixture
def r12_files(tmp_path, monkeypatch):
    (tmp_path / "tenant_hourly.json").write_text(json.dumps({
        "statement": "real scores, no synthetic step; ADWIN as in R12 amendment A (clock=1)",
        "adwin": {"delta": 0.002, "clock": 1},
        # a stray experiment-tenant entry and a synthetic field must never reach a bank user
        "tenants": [_tenant(21), _tenant(900001), _tenant(22, extra={"synthetic_step": 0.5})],
    }), encoding="utf-8")
    (tmp_path / "panel.json").write_text(json.dumps({
        "statement": "drift was injected, not observed",
        "synthetic_control": "SYNTHETIC POSITIVE CONTROL: a step added to the monitor input, not data",
        "experiment_tenant_id": 900001,
    }), encoding="utf-8")
    monkeypatch.setattr(experiment_worker, "R12_AMENDED", tmp_path)
    return tmp_path


def _principal(role="supervisor", tenant_id=21):
    return Principal(user_id=8, tenant_id=tenant_id, role=role, email="lead@example.test")


ADMIN = Principal(user_id=1, tenant_id=None, role="admin", email="admin@example.test")


def test_a_supervisor_gets_only_their_own_real_hourly_series(r12_files):
    result = operations.get_drift_hourly(21, _principal())
    assert result.tenant_id == 21
    assert len(result.items) == 48 and len(result.adwin) == 48
    assert "900001" not in result.model_dump_json()


def test_synthetic_fields_in_a_tenant_entry_are_not_passed_on(r12_files):
    text = operations.get_drift_hourly(22, _principal(tenant_id=22)).model_dump_json()
    assert "synthetic_step" not in text and "control" not in text


def test_a_bank_user_cannot_read_the_experiment_tenant(r12_files):
    with pytest.raises(HTTPException) as exc_info:
        operations.get_drift_hourly(900001, _principal())
    assert exc_info.value.status_code == 403


def test_the_experiment_tenant_is_never_served_on_a_tenant_route_even_to_the_admin(r12_files):
    with pytest.raises(HTTPException) as exc_info:
        operations.get_drift_hourly(900001, ADMIN)
    assert exc_info.value.status_code == 404


def test_the_admin_reads_a_banks_hourly_series(r12_files):
    assert operations.get_drift_hourly(21, ADMIN).tenant_id == 21


def test_analysts_and_other_tenants_are_refused(r12_files):
    for principal, tenant in ((_principal(role="analyst"), 21), (_principal(tenant_id=22), 21)):
        with pytest.raises(HTTPException) as exc_info:
            operations.get_drift_hourly(tenant, principal)
        assert exc_info.value.status_code == 403


def test_no_file_means_404(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment_worker, "R12_AMENDED", tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        operations.get_drift_hourly(21, _principal())
    assert exc_info.value.status_code == 404


def test_the_admin_reads_the_r12_panel(r12_files):
    assert admin.get_r12_panel(ADMIN).results["experiment_tenant_id"] == 900001


@pytest.mark.parametrize("role", ["analyst", "supervisor"])
def test_bank_users_are_refused_the_r12_panel_before_any_lookup(monkeypatch, role, r12_files):
    from api import dependencies
    from api.main import app

    monkeypatch.setenv("RINGSHIELD_JWT_SECRET", "x" * 48)
    token, _ = create_access_token(_principal(role=role))

    @contextmanager
    def fail_auth_query():
        raise AssertionError("a bank user must be rejected before the auth query")
        yield

    monkeypatch.setattr(dependencies, "auth_db_session", fail_auth_query)
    response = TestClient(app).get("/admin/experiments/r12", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert "SYNTHETIC" not in response.text and "900001" not in response.text
