from __future__ import annotations

from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from dashboard import app as dashboard


class _FakeStreamlit:
    def __init__(self, role):
        self.session_state = {"role": role}
        self.infos = []
        self.buttons = []
        self.charts = []

    def header(self, *_args, **_kwargs): pass
    def caption(self, *_args, **_kwargs): pass
    def dataframe(self, *_args, **_kwargs): pass
    def info(self, value): self.infos.append(value)
    def selectbox(self, _label, options): return options[0]
    def plotly_chart(self, value, **_kwargs): self.charts.append(value)
    def button(self, label, **_kwargs):
        self.buttons.append(label)
        return False


@pytest.fixture
def view(monkeypatch):
    def install(role, api):
        fake_st = _FakeStreamlit(role)
        monkeypatch.setattr(dashboard, "st", fake_st)
        monkeypatch.setattr(dashboard, "_api", api)
        return fake_st
    return install


def test_models_page_smoke_for_analyst(view):
    calls = []

    def api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"items": [{"component": "affinity", "version_tag": "v1", "trained_at": "2026-01-01",
                           "train_label_count": 10, "holdout_ring_f1": 0.8, "promoted": True,
                           "shared": False}], "next_before_id": None}

    fake_st = view("analyst", api)
    dashboard._model_versions(210)
    assert calls[0][:2] == ("GET", "/tenants/210/models")
    assert "Retrain now" not in fake_st.buttons


def test_models_page_empty_state_and_supervisor_control(view):
    fake_st = view("supervisor", lambda *_args, **_kwargs: {"items": [], "next_before_id": None})
    dashboard._model_versions(210)
    assert any("No model versions" in message for message in fake_st.infos)
    assert any("No retraining runs yet" in message for message in fake_st.infos)
    assert "Retrain now" in fake_st.buttons


def test_drift_page_empty_states_and_tenant_specific_calls(view):
    calls = []

    def api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/series"):
            return {"tenant_id": 210, "active_model_id": "gine_causal", "active_seed": 1,
                    "items": [{"day": "2026-01-01T00:00:10Z", "mean": 0.2, "p99": 0.3}]}
        return {"items": [], "next_before_id": None}

    fake_st = view("supervisor", api)
    dashboard._drift_events(210)
    assert [path for _method, path, _kwargs in calls] == [
        "/tenants/210/drift/series", "/tenants/210/drift",
    ]
    assert any("No drift events" in message for message in fake_st.infos)
    assert fake_st.charts


def test_analyst_drift_page_is_read_only_and_shows_permission_empty_state(view):
    calls = []
    fake_st = view("analyst", lambda *args, **kwargs: calls.append((args, kwargs)))
    dashboard._drift_events(210)
    assert calls == []
    assert any("supervisors" in message for message in fake_st.infos)
