"""Verdict form in fixture mode: FR-D50-55, NFR-D13 and NFR-D31."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
APP_FILE = DASHBOARD / "app.py"
sys.path.insert(0, str(DASHBOARD))

OPEN_RING = "full-gine_causal-1-0"            # FAN-OUT, open
SIMULATED_RING = "full-gine_causal-1-10"      # filler, rejected by a simulated verdict


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_DASHBOARD_FIXTURES", str(DASHBOARD / "fixtures"))
    import client
    client._fixture_api = None
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("fixture mode called the network"))
    return client


def _open(ring_id: str, email="analyst@bank-a.fixture", password="fixture-only-a1") -> AppTest:
    app = AppTest.from_file(str(APP_FILE), default_timeout=30).run()
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()

    app.query_params["page"] = "rings"
    app.query_params["ring"] = ring_id
    return app.run()


def _button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def _verdict_rows(app: AppTest) -> list[dict]:
    frame = next(f.value for f in app.dataframe if "Investigator" in f.value.columns)
    return frame.to_dict("records")


def _status(app: AppTest) -> str:
    return next(m.value for m in app.markdown if m.value.startswith("**Status:**"))


def _open_partial(app: AppTest) -> AppTest:
    return _button(app, "Partially correct").click().run()


def _account_boxes(app: AppTest):
    return [box for box in app.checkbox if box.key.startswith("partial_keep_account_")]


def test_confirm_updates_the_badge_and_appends_to_the_verdict_list(fixture_mode):
    app = _open(OPEN_RING)
    assert _status(app) == "**Status:** `open`"
    assert not any(f for f in app.dataframe if "Investigator" in f.value.columns)
    app.text_input(key=f"note_1001_{OPEN_RING}").input("Matches the alert")
    app = _button(app, "Confirm ring").click().run()
    assert _status(app) == "**Status:** `confirmed`"
    rows = _verdict_rows(app)
    assert rows[0]["Verdict"] == "confirm" and rows[0]["Note"] == "Matches the alert"
    assert "This ring is no longer open for verdicts." in [item.value for item in app.info]


def test_one_click_records_one_verdict_and_the_buttons_disable_after_it(fixture_mode):
    app = _open(OPEN_RING)
    app = _button(app, "Reject ring").click().run()
    app = app.run()
    assert fixture_mode._fixture_api.verdict_posts == 1
    assert len(_verdict_rows(app)) == 1
    assert not [b for b in app.button if b.label in {"Confirm ring", "Reject ring"}]


def test_partial_without_a_note_is_blocked_with_a_message(fixture_mode):
    app = _open_partial(_open(OPEN_RING))
    _account_boxes(app)[-1].uncheck()
    app = _button(app, "Submit partial verdict").click().run()
    assert "A note is required for a partial verdict." in [item.value for item in app.error]
    assert fixture_mode._fixture_api.verdict_posts == 0


def test_the_checklist_is_pre_ticked_and_unticking_every_account_is_blocked(fixture_mode):
    app = _open_partial(_open(OPEN_RING))
    boxes = _account_boxes(app)
    assert boxes and all(box.value for box in boxes)
    for box in boxes:
        box.uncheck()
    app.text_area[0].input("Nothing is left")
    app = _button(app, "Submit partial verdict").click().run()
    assert "Keep at least one account for a partial correction." in [item.value for item in app.error]
    assert fixture_mode._fixture_api.verdict_posts == 0


def test_a_partial_verdict_regenerates_and_refreshes_all_three_panels(fixture_mode):
    app = _open(OPEN_RING)
    narrative_before = next(t.value for t in app.text)
    accounts_before = len(next(f.value for f in app.dataframe if "w_account" in f.value.columns))
    app = _open_partial(app)
    _account_boxes(app)[-1].uncheck()
    app.text_area[0].input("The last account is a payroll provider")
    app = _button(app, "Submit partial verdict").click().run()

    assert _status(app) == "**Status:** `partial`"
    assert _verdict_rows(app)[0]["Verdict"] == "partial"
    narrative = next(t.value for t in app.text)
    assert narrative != narrative_before and narrative.startswith("Regenerated after")
    accounts = next(f.value for f in app.dataframe if "w_account" in f.value.columns)
    assert len(accounts) == accounts_before - 1
    figure = json.loads(next(c.proto.spec for c in app.get("plotly_chart") if "Account " in c.proto.spec))
    nodes = [text for trace in figure["data"] for text in (trace.get("hovertext") or [])
             if text.startswith("Account ")]
    assert len(nodes) == accounts_before - 1
    assert any("Regenerated" in item.value and "revision 2" in item.value for item in app.caption)


def test_simulated_verdicts_carry_the_simulated_tag(fixture_mode):
    app = _open(SIMULATED_RING)
    assert _verdict_rows(app)[0]["Verdict"] == "reject · Simulated"
    assert any(item.value.startswith("Latest verdict: reject") and item.value.endswith("· Simulated")
               for item in app.caption)


def test_admin_sees_the_form_disabled_with_the_required_text(fixture_mode):
    app = _open(OPEN_RING, "admin@platform.fixture", "fixture-only-admin")
    assert "Administrators cannot record verdicts." in [item.value for item in app.warning]
    for label in ("Confirm ring", "Reject ring", "Partially correct"):
        assert _button(app, label).disabled


def test_a_note_with_markup_is_shown_literally(fixture_mode):
    note = "<script>alert('x')</script> **not bold**"
    app = _open(OPEN_RING)
    app.text_input(key=f"note_1001_{OPEN_RING}").input(note)
    app = _button(app, "Reject ring").click().run()
    assert _verdict_rows(app)[0]["Note"] == note
    assert not [m for m in app.markdown if "<script>" in m.value]


def test_a_failed_submission_keeps_the_form_and_offers_retry(fixture_mode, monkeypatch):
    import fixture_api
    original = fixture_api.FixtureAPI.handle
    failing = {"on": True}

    def flaky(self, method, path, **kwargs):
        if failing["on"] and method == "POST" and path.endswith("/verdicts"):
            return self._error(500, "InternalError", "Database unavailable")
        return original(self, method, path, **kwargs)

    monkeypatch.setattr(fixture_api.FixtureAPI, "handle", flaky)
    app = _open_partial(_open(OPEN_RING))
    _account_boxes(app)[-1].uncheck()
    app.text_area[0].input("Keep this note")
    app = _button(app, "Submit partial verdict").click().run()
    assert any("Database unavailable" in e.value and "request id fixture-" in e.value for e in app.error)
    assert app.text_area[0].value == "Keep this note"
    assert not _account_boxes(app)[-1].value
    assert "The verdict was not recorded. Your entries are kept: submit again to retry." in \
        [item.value for item in app.caption]

    failing["on"] = False
    app = _button(app, "Submit partial verdict").click().run()
    assert _status(app) == "**Status:** `partial`"
