"""Verdict history in fixture mode: FR-D60 (with FR-D54's tag and NFR-D13's notes as text)."""

from __future__ import annotations

from datetime import date
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


def _history(email="analyst@bank-a.fixture", password="fixture-only-a1") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()
    app = app.run()
    app.query_params["page"] = "verdicts"
    return app.run()


def _table(app: AppTest):
    return next(f.value for f in app.dataframe if "Analyst" in f.value.columns)


def _total(app: AppTest) -> int:
    return int(next(c.value for c in app.caption if c.value.endswith("verdicts match these filters")).split()[0])


def _apply(app: AppTest, *, kinds=None, analyst=None, simulated=None, dates=None) -> AppTest:
    if kinds is not None:
        next(f for f in app.multiselect if f.label == "Verdict type").set_value(kinds)
    if analyst is not None:
        next(f for f in app.selectbox if f.label == "Analyst").select(analyst)
    if simulated is not None:
        next(f for f in app.selectbox if f.label == "Simulated or real").select(simulated)
    if dates is not None:
        next(f for f in app.date_input if f.label == "Verdict date range").set_value(dates)
    return next(b for b in app.button if b.label == "Apply verdict filters").click().run()


def test_the_table_has_the_required_columns_newest_first(fixture_mode):
    app = _history()
    table = _table(app)
    assert list(table.columns) == ["When", "Ring ID", "Verdict", "Analyst", "Note"]
    assert list(table["When"]) == sorted(table["When"], reverse=True)
    assert any(value.endswith(" · Simulated") for value in table["Verdict"])
    assert set(table["Note"]) == {"<b>fixture</b> note, shown as text"}       # literal text
    assert "96 verdicts match these filters" in [c.value for c in app.caption]


@pytest.mark.parametrize("filters, check", [
    ({"kinds": ["reject"]}, lambda t: set(v.split(" · ")[0] for v in t["Verdict"]) == {"reject"}),
    ({"analyst": "Analyst 2"}, lambda t: set(t["Analyst"]) == {"Analyst 2"}),
    ({"simulated": "Real"}, lambda t: not any("Simulated" in v for v in t["Verdict"])),
    ({"simulated": "Simulated"}, lambda t: all(v.endswith("· Simulated") for v in t["Verdict"])),
    ({"dates": (date(2022, 9, 10), date(2022, 9, 10))},
     lambda t: {v[:10] for v in t["When"]} == {"2022-09-10"}),
])
def test_each_filter_narrows_the_table(fixture_mode, filters, check):
    before = _total(_history())
    app = _apply(_history(), **filters)
    assert 0 < _total(app) < before
    assert check(_table(app))


def test_counts_follow_the_filter(fixture_mode):
    app = _apply(_history(), kinds=["partial"])
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Confirmed"] == "0" and metrics["Rejected"] == "0" and metrics["Partial"] != "0"


def test_another_banks_verdicts_are_not_listed(fixture_mode):
    bank_b = _history("analyst@bank-b.fixture", "fixture-only-b1")    # bank B has no verdicts
    assert _total(bank_b) == 0 and not [f for f in bank_b.dataframe if "Analyst" in f.value.columns]
