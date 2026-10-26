"""Ring detail in fixture mode: FR-D20-21, D30-34, D36, D40-42, NFR-D32, changes 2 and 3."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
APP_FILE = DASHBOARD / "app.py"
RINGS = DASHBOARD / "fixtures" / "rings"
sys.path.insert(0, str(DASHBOARD))

CYCLE, FAN_IN, RANDOM_UNDETERMINED, LARGE, CROSS_BANK = (f"full-gine_causal-1-{i}" for i in (4, 1, 5, 8, 9))


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_DASHBOARD_FIXTURES", str(DASHBOARD / "fixtures"))
    import client
    client._fixture_api = None
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("fixture mode called the network"))


def _ring_file(ring_id: str, tenant: int = 1001) -> dict:
    return json.loads((RINGS / f"{tenant}_{ring_id}.json").read_text(encoding="utf-8"))


def _open(ring_id: str, email="analyst@bank-a.fixture", password="fixture-only-a1") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()
    app = app.run()
    app.query_params["page"] = "rings"
    app.query_params["ring"] = ring_id
    return app.run()


def _figure(app: AppTest) -> dict:
    return json.loads(next(chart for chart in app.get("plotly_chart")
                           if "Account " in chart.proto.spec).proto.spec)


def _summary(app: AppTest) -> dict:
    table = next(item for item in app.table if "Value" in str(item.value))
    frame = table.value
    return dict(zip(frame.iloc[:, 0], frame["Value"]))


def test_narrative_is_shown_byte_for_byte_with_the_ring_summary(fixture_mode):
    ring = _ring_file(CROSS_BANK)
    app = _open(CROSS_BANK)
    assert ring["explanation"]["narrative"] in [item.value for item in app.text]
    summary = _summary(app)
    assert summary["Type"] == f"SCATTER-GATHER (p = {ring['summary']['topology_prob']})"   # as received
    assert summary["Members"] == str(ring["summary"]["n_members"])
    assert summary["Cross-bank banks"] == ", ".join(ring["summary"]["counterparty_banks"])
    assert "%" in summary["Conservation closure"]
    assert any(f"Model gine_causal · aggregator full" == item.value for item in app.caption)


def test_closed_loop_closure_reads_closed_loop(fixture_mode):
    assert _summary(_open(CYCLE))["Conservation closure"] == "closed loop"


def test_status_badge_and_latest_verdict_with_author_and_time(fixture_mode):
    app = _open(FAN_IN)
    assert "**Status:** `confirmed`" in [item.value for item in app.markdown]
    assert any(item.value.startswith("Latest verdict: confirm by analyst@bank-a.fixture at ")
               for item in app.caption)


def test_graph_has_six_role_legend_entries_line_styles_and_hover_fields(fixture_mode):
    figure = _figure(_open(RANDOM_UNDETERMINED))
    names = {trace.get("name") for trace in figure["data"]}
    assert "undetermined" in names                                   # change 1: sixth role
    assert {"seed transaction", "expanded transaction"} <= names
    dashes = {trace["line"]["dash"] for trace in figure["data"] if trace.get("mode") == "lines" and trace.get("x") != [None]}
    assert dashes == {"solid", "dash"}
    hovers = [text for trace in figure["data"] for text in (trace.get("hovertext") or [])]
    node_hover = next(text for text in hovers if text.startswith("Account "))
    edge_hover = next(text for text in hovers if text.startswith("Transaction "))
    for field in ("Bank:", "Role:", "Inflow:", "Outflow:", "Hold time:"):
        assert field in node_hover
    for field in ("Amount:", "Time:", "Payment format:", "w_total", "w_score", "w_loo", "w_flow"):
        assert field in edge_hover


def test_time_slider_greys_later_edges_and_play_runs_five_seconds(fixture_mode):
    figure = _figure(_open(RANDOM_UNDETERMINED))
    slider = figure["layout"]["sliders"][0]
    play = figure["layout"]["updatemenus"][0]["buttons"][0]
    assert play["label"] == "▶ Play"
    assert play["args"][1]["frame"]["duration"] * len(slider["steps"]) <= 5000
    first = figure["frames"][0]
    colours = [trace["line"]["color"] for trace in first["data"]]
    assert "#d9d9d9" in colours and "#4a4a4a" in colours             # earliest stop greys later edges


def test_large_ring_shows_sixty_of_n_and_loads_all_on_request(fixture_mode):
    app = _open(LARGE)
    assert "Showing 60 of 120 accounts" in [item.value for item in app.info]
    count = lambda fig: sum(1 for trace in fig["data"] for text in (trace.get("hovertext") or [])
                            if text.startswith("Account "))
    assert count(_figure(app)) == 60
    app = next(b for b in app.button if b.label == "Load all accounts").click().run()
    assert count(_figure(app)) == 120


def test_conversions_are_hidden_by_default_and_shown_by_the_toggle(fixture_mode):
    app = _open(CYCLE)
    transactions = next(frame.value for frame in app.dataframe if "Kind" in frame.value.columns)
    assert "conversion" not in set(transactions["Kind"])
    toggle = next(t for t in app.toggle if t.key.startswith("evidence_conversions_"))
    app = toggle.set_value(True).run()
    transactions = next(frame.value for frame in app.dataframe if "Kind" in frame.value.columns)
    assert "conversion" in set(transactions["Kind"])


def test_evidence_tabs_have_their_columns_order_and_signals(fixture_mode):
    app = _open(CROSS_BANK)
    transactions = next(frame.value for frame in app.dataframe if "Kind" in frame.value.columns)
    assert list(transactions.columns) == ["From", "To", "Amount", "Time", "Payment format", "Kind",
                                          "w_total", "w_score", "w_loo", "w_flow"]
    totals = [value for value in transactions["w_total"] if value is not None]
    assert totals == sorted(totals, reverse=True)
    accounts = next(frame.value for frame in app.dataframe if "w_account" in frame.value.columns)
    assert list(accounts.columns) == ["Account", "Bank", "Role", "Inflow", "Outflow", "Hold time", "w_account"]
    assert [float(v) for v in accounts["w_account"]] == sorted((float(v) for v in accounts["w_account"]), reverse=True)
    charts = [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]
    signals = next(chart for chart in charts if chart["data"] and chart["data"][0].get("type") == "bar")
    assert signals["data"][0]["orientation"] == "h"
    assert len(signals["data"][0]["y"]) == 10
    assert "Sender pays many accounts" in signals["data"][0]["y"] or len(set(signals["data"][0]["y"])) == 10
    assert "Signals from the transaction-level detector on the ring's seed transactions" in \
        [item.value for item in app.caption]


def test_a_failing_graph_leaves_the_narrative_and_evidence_on_screen(fixture_mode, monkeypatch):
    import fixture_api
    original = fixture_api.FixtureAPI.handle

    def broken_subgraph(self, method, path, **kwargs):
        if path.endswith("/subgraph"):
            return self._error(500, "InternalError", "Subgraph exploded")
        return original(self, method, path, **kwargs)

    monkeypatch.setattr(fixture_api.FixtureAPI, "handle", broken_subgraph)
    app = _open(CROSS_BANK)
    assert any("Subgraph exploded" in item.value for item in app.error)
    assert _ring_file(CROSS_BANK)["explanation"]["narrative"] in [item.value for item in app.text]
    assert any("Kind" in frame.value.columns for frame in app.dataframe)


def test_another_banks_ring_id_in_the_url_is_not_permitted(fixture_mode):
    app = _open("full-gine_causal-1-500", "analyst@bank-a.fixture", "fixture-only-a1")
    assert not any("Kind" in frame.value.columns for frame in app.dataframe)
    bank_b_ring = _open(CROSS_BANK, "analyst@bank-b.fixture", "fixture-only-b1")
    assert not [item for item in bank_b_ring.text if "Fixture narrative" in item.value]
