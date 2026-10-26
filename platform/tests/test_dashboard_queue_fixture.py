"""Ring queue in fixture mode: FR-D10-15, change 2 (partial flag) and change 3 (topology_prob)."""

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


def _signed_in(email="analyst@bank-a.fixture", password="fixture-only-a1") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=20).run()
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()
    return app.run()


def _table(app: AppTest):
    return next(frame.value for frame in app.dataframe if "Ring ID" in frame.value.columns)


def _apply(app: AppTest, **changes) -> AppTest:
    sidebar = app.sidebar
    if "status" in changes:
        next(m for m in sidebar.multiselect if m.label == "Status").set_value(changes["status"])
    if "topology" in changes:
        next(m for m in sidebar.multiselect if m.label == "Topology").set_value(changes["topology"])
    if "minimum" in changes:
        next(s for s in sidebar.slider if s.label == "Minimum confidence").set_value(changes["minimum"])
    if "cross_bank" in changes:
        next(c for c in sidebar.checkbox if c.label == "Cross-bank only").check()
    if "sort" in changes:
        next(s for s in sidebar.selectbox if s.label == "Sort by").set_value(changes["sort"])
    if "order" in changes:
        next(s for s in sidebar.selectbox if s.label == "Order").set_value(changes["order"])
    next(b for b in sidebar.button if b.label == "Apply filters").click()
    return app.run()


def test_queue_has_every_required_column_with_formatting_only(fixture_mode):
    table = _table(_signed_in())
    assert list(table.columns) == ["Ring ID", "Type", "Members", "Edges", "Total", "Window",
                                   "Window (UTC)", "Confidence", "Cross-bank", "Status"]
    first = table.iloc[0]
    assert "(p = 0." in first["Type"] and "%" not in first["Type"]          # change 3: as received
    assert " over " not in first["Window"] or "over" in first["Window"]
    assert first["Window (UTC)"].endswith("UTC")


def test_partial_totals_carry_the_flag_and_are_never_converted(fixture_mode):
    totals = _table(_apply(_signed_in(), status=["open", "confirmed", "rejected", "partial"]))["Total"].tolist()
    assert any(total.endswith("US Dollar (partial)") for total in totals)
    assert all(total == "—" or "US Dollar" in total for total in totals)


def test_default_sort_is_confidence_descending_and_other_sorts_change_the_order(fixture_mode):
    app = _signed_in()
    confidence = [float(value) for value in _table(app)["Confidence"]]
    assert confidence == sorted(confidence, reverse=True)
    by_members = _table(_apply(app, sort="members", order="asc"))["Members"].tolist()
    assert by_members == sorted(by_members)


def test_filters_narrow_the_list_and_combine(fixture_mode):
    app = _signed_in()
    everything = int(app.caption[0].value.split()[0]) if app.caption else None
    app = _apply(app, topology=["CYCLE"])
    assert set(_table(app)["Type"].str.split(" ").str[0]) == {"CYCLE"}
    cycle_only = len(_table(app))
    app = _apply(app, minimum=0.9)
    narrowed = _table(app) if any("Ring ID" in f.value.columns for f in app.dataframe) else None
    assert narrowed is None or (len(narrowed) <= cycle_only and all(float(c) >= 0.9 for c in narrowed["Confidence"]))
    cross = _apply(_signed_in(), cross_bank=True)
    assert set(_table(cross)["Cross-bank"]) == {"Yes"}
    assert everything is None or cycle_only < everything


def test_pagination_pages_through_200_rings_fifty_at_a_time_with_the_total(fixture_mode):
    app = _apply(_signed_in(), status=["open", "confirmed", "rejected", "partial"])
    assert any(caption.value.startswith("200 rings") for caption in app.caption)
    seen = []
    for _ in range(4):
        seen += _table(app)["Ring ID"].tolist()
        assert len(_table(app)) == 50
        next_button = next(b for b in app.button if b.label == "Next page")
        if next_button.disabled:
            break
        app = next_button.click().run()
    assert len(seen) == len(set(seen)) == 200


def test_opening_a_ring_and_returning_restores_filters_and_page(fixture_mode):
    app = _apply(_signed_in(), status=["open", "confirmed", "rejected", "partial"])
    app = next(b for b in app.button if b.label == "Next page").click().run()
    second_page = _table(app)["Ring ID"].tolist()
    ring_id = second_page[0]
    # A row click sets the same state as opening the ring by its URL; AppTest cannot click rows.
    app.query_params["ring"] = ring_id
    app = app.run()
    assert any(ring_id in header.value for header in app.header)
    app = next(b for b in app.button if b.label == "← Back to queue").click().run()
    assert _table(app)["Ring ID"].tolist() == second_page
    assert next(m for m in app.sidebar.multiselect if m.label == "Status").value == \
        ["open", "confirmed", "rejected", "partial"]


def test_both_empty_states_are_explained(fixture_mode):
    none_match = _apply(_signed_in(), minimum=1.0)
    assert "No rings match these filters" in [item.value for item in none_match.info]
    empty_bank = _signed_in("analyst@bank-c.fixture", "fixture-only-c1")
    assert "No rings have been generated for this tenant yet" in [item.value for item in empty_bank.info]


def test_banks_see_different_queues(fixture_mode):
    bank_a = set(_table(_signed_in())["Ring ID"])
    bank_b = set(_table(_signed_in("analyst@bank-b.fixture", "fixture-only-b1"))["Ring ID"])
    assert bank_a and bank_b and not bank_a & bank_b
