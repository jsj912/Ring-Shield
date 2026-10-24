"""Admin screen in fixture mode: FR-D90-93 with change 6 (the registered R10 table)."""

from __future__ import annotations

from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
APP_FILE = DASHBOARD / "app.py"
sys.path.insert(0, str(DASHBOARD))


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_DASHBOARD_FIXTURES", str(DASHBOARD / "fixtures"))
    import client
    client._fixture_api = None
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("fixture mode called the network"))


def _admin(page="admin") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input("admin@platform.fixture")
    app.text_input[1].input("fixture-only-admin")
    app.button[0].click()
    app = app.run()
    app.query_params["page"] = page
    return app.run()


def _table(app: AppTest, column: str):
    return next(f.value for f in app.dataframe if column in f.value.columns)


def test_tenant_registry_renders(fixture_mode):
    registry = _table(_admin(), "Bank code")
    assert list(registry.columns) == ["Tenant ID", "Bank code", "Name", "Loaded", "Rings", "Verdicts"]
    assert len(registry) >= 2


def test_primary_set_has_one_row_per_tenant_and_the_ci_on_the_pooled_row(fixture_mode):
    primary = _table(_admin(), "Budget-matched")
    assert list(primary.columns) == ["Tenant", "Kind", "Rings", "Pooled", "(a) pooled scores, own edges",
                                     "(b) own scores, own edges", "Budget-matched", "Pooled − (b)"]
    assert list(primary["Tenant"]) == ["1", "20", "11", "118", "12", "All five"]
    assert set(primary["Kind"][:5]) == {"per tenant (descriptive)"}
    pooled_row = primary.iloc[5]
    assert pooled_row["Kind"] == "pooled across tenants (95% CI)"
    assert pooled_row["(b) own scores, own edges"] == "0.088 [0.031, 0.161]"
    assert pooled_row["Pooled"] == "0.359 [0.239, 0.500]"
    assert pooled_row["Pooled − (b)"] == "0.271 [0.154, 0.407]"
    bank_1 = primary.iloc[0]
    assert (bank_1["(b) own scores, own edges"], bank_1["(a) pooled scores, own edges"],
            bank_1["Budget-matched"], bank_1["Pooled"]) == ("0.035", "0.071", "0.035", "0.365")
    assert "[" not in bank_1["(b) own scores, own edges"]          # no CI on per-tenant rows


def test_robustness_set_is_separate_and_marks_bank_70_degenerate(fixture_mode):
    robustness = _table(_admin(), "Note")
    assert list(robustness["Tenant"]) == ["70", "12", "11", "1", "10", "All five"]
    bank_70 = robustness.iloc[0]
    assert bank_70["Note"] == "degenerate: no ring edges visible"
    assert bank_70["(b) own scores, own edges"] == "—"
    assert robustness.iloc[5]["Pooled"] == "0.425 [0.284, 0.589]"


def test_cross_bank_summary_and_chart_above_and_beside_the_tables(fixture_mode):
    app = _admin()
    assert ("**Cross-bank rings:** 172 of 174 (98.9%) · **mean banks per ring** 4.626"
            in [m.value for m in app.markdown])
    assert any(c.proto.spec and "Ring recall" in c.proto.spec for c in app.get("plotly_chart"))


def test_run_polls_and_then_shows_the_result(fixture_mode):
    app = _admin()
    app = next(b for b in app.button if b.label == "Run").click().run()
    assert "Status: running" in [c.value for c in app.caption]
    app = app.run()
    assert "Status: succeeded" in [c.value for c in app.caption]
    assert _table(app, "Budget-matched").iloc[5]["Pooled"] == "0.359 [0.239, 0.500]"


def test_bank_users_cannot_open_the_admin_page(fixture_mode):
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input("supervisor@bank-a.fixture")
    app.text_input[1].input("fixture-only-a2")
    app.button[0].click()
    app = app.run()
    app.query_params["page"] = "admin"
    app = app.run()
    assert not [f for f in app.dataframe if "Budget-matched" in f.value.columns]


def test_admin_views_of_rings_are_labelled_read_only(fixture_mode):
    app = _admin("rings")
    assert "Read-only (administrator)" in [i.value for i in app.info]
