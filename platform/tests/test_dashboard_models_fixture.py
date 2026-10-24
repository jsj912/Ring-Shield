"""Models and retrain in fixture mode (R11's refused run): FR-D70-73 and change 5."""

from __future__ import annotations

from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
APP_FILE = DASHBOARD / "app.py"
sys.path.insert(0, str(DASHBOARD))

SCOPE = ("Retrains the expansion and affinity models; the typing model is fixed. "
         "The result is promoted only if it passes the holdout gate.")


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_DASHBOARD_FIXTURES", str(DASHBOARD / "fixtures"))
    import client
    client._fixture_api = None
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("fixture mode called the network"))
    return client


def _models(email="supervisor@bank-a.fixture", password="fixture-only-a2") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()
    app = app.run()
    app.query_params["page"] = "models"
    return app.run()


def _versions(app: AppTest):
    return next(f.value for f in app.dataframe if "Gate reason" in f.value.columns)


def _button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def test_version_table_has_the_columns_and_the_refused_reason(fixture_mode):
    table = _versions(_models("analyst@bank-a.fixture", "fixture-only-a1"))
    assert list(table.columns) == ["Version ID", "Component", "Version", "Trained at", "Training labels",
                                   "Holdout ring-F1", "Promoted", "Gate reason", "Shared"]
    refused = table[table["Version ID"] == 13].iloc[0]
    assert refused["Promoted"] == "No"
    assert refused["Gate reason"] == "holdout ring_f1 0.6612 < current 0.6883 - 0.005"
    assert refused["Holdout ring-F1"] == "0.6612"                    # as received
    assert list(table["Version ID"]) == sorted(table["Version ID"], reverse=True)


def test_promoted_versions_are_highlighted(fixture_mode):
    app = _models("analyst@bank-a.fixture", "fixture-only-a1")
    frame = next(f for f in app.dataframe if "Gate reason" in f.value.columns)
    assert "rgba(46, 160, 67" in str(frame.proto)                  # styled promoted rows
    assert "Green rows are the versions currently promoted for each component; newest first." in \
        [c.value for c in app.caption]


def test_analyst_sees_no_retrain_button(fixture_mode):
    app = _models("analyst@bank-a.fixture", "fixture-only-a1")
    assert not [b for b in app.button if b.label == "Retrain now"]
    assert not [f for f in app.dataframe if "Run ID" in f.value.columns]


def test_the_refused_r11_run_shows_its_reasons_and_links_to_the_row(fixture_mode):
    app = _models()
    errors = [e.value for e in app.error]
    assert ("Run r11a0090-cycle6: expansion refused by the holdout gate: "
            "holdout ring_f1 0.6612 < current 0.6883 - 0.005") in errors
    assert any(e.startswith("Run r11a0090-cycle6: affinity refused") for e in errors)
    runs = next(f.value for f in app.dataframe if "Run ID" in f.value.columns)
    assert runs.iloc[0]["Promoted version"] == "—"
    app = _button(app, "Show model version 13").click().run()
    frame = next(f for f in app.dataframe if "Gate reason" in f.value.columns)
    assert "rgba(255, 196, 0" in str(frame.proto)


def test_retrain_asks_for_confirmation_with_the_scope_then_polls_to_the_result(fixture_mode):
    app = _models()
    app = _button(app, "Retrain now").click().run()
    assert SCOPE in [m.value for m in app.markdown]
    assert fixture_mode._fixture_api.models["1001"]["runs"][0]["run_id"] == "r11a0090-cycle6"
    app = _button(app, "Start retraining").click().run()
    assert any(m.value == "**Run fixture-run-2:** `running`" for m in app.markdown)
    assert any("expansion: training" in c.value for c in app.code)
    app = app.run()                                               # the next poll finds it finished
    errors = [e.value for e in app.error]
    assert any(e.startswith("Run fixture-run-2: expansion refused by the holdout gate") for e in errors)
    runs = next(f.value for f in app.dataframe if "Run ID" in f.value.columns)
    assert runs.iloc[0]["Run ID"] == "fixture-run-2" and runs.iloc[0]["Status"] == "succeeded"


def test_cancel_starts_nothing(fixture_mode):
    app = _button(_models(), "Retrain now").click().run()
    app = _button(app, "Cancel").click().run()
    assert len(fixture_mode._fixture_api.models["1001"]["runs"]) == 1
