from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))
APP_FILE = PLATFORM_ROOT / "dashboard" / "app.py"


class FakeResponse:
    status_code = 200
    is_success = True
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _ring(ring_id="ring-1"):
    return {
        "ring_id": ring_id, "topology_type": "CYCLE", "topology_prob": 0.9,
        "n_members": 3, "n_edges": 3, "total_amount": 1200.0,
        "total_currency": "USD", "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-01T01:00:00Z", "confidence": 0.8,
        "cross_bank": True, "status": "open",
    }


def _queue_payload(cursor=None):
    return {"total": 73, "items": [_ring()], "next_cursor": cursor}


def _api_response(url, params):
    if url.endswith("/rings"):
        cursor = dict(params or ()).get("cursor")
        return FakeResponse(_queue_payload("cursor-next" if cursor is None else None))
    if url.endswith("/explanation"):
        response = FakeResponse({})
        response.status_code = 404
        response.is_success = False
        return response
    if url.endswith("/verdicts"):
        return FakeResponse({"items": [], "next_before_id": None})
    if url.endswith("/evidence"):
        return FakeResponse({"edges": [], "nodes": [], "missing_edge_ids": []})
    return FakeResponse({
        **_ring(), "member_accounts": [], "member_edges": [], "n_currencies": 1,
        "counterparty_banks": [], "conservation_closure": None,
        "model_id": "model", "aggregator_id": "aggregator",
    })


def _signed_in_app(monkeypatch, calls):
    def request(_method, url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return _api_response(url, kwargs.get("params"))

    monkeypatch.setattr(httpx, "request", request)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "token"
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "North Bank"
    app.session_state["role"] = "analyst"
    return app


def test_queue_filters_sort_page_size_total_and_cursor_are_sent(monkeypatch):
    calls = []
    app = _signed_in_app(monkeypatch, calls).run()
    app.multiselect[0].set_value(["open", "confirmed"])
    app.multiselect[1].set_value(["CYCLE"])
    app.slider[0].set_value(0.4)
    app.checkbox[0].check()
    next(box for box in app.selectbox if box.label == "Sort by").select("total_amount")
    next(box for box in app.selectbox if box.label == "Order").select("asc")
    app.date_input[0].set_value((date(2026, 1, 1), date(2026, 1, 3)))
    next(button for button in app.button if button.label == "Apply filters").click().run()

    params = dict(calls[-1][1])
    assert params["status"] == "confirmed"
    assert ("status", "open") in calls[-1][1]
    assert params["topology_type"] == "CYCLE"
    assert params["min_conf"] == "0.4"
    assert params["cross_bank_only"] == "true"
    assert params["sort"] == "total_amount"
    assert params["order"] == "asc"
    assert params["start_after"].startswith("2026-01-01T00:00:00")
    assert params["start_before"].startswith("2026-01-03T23:59:59")
    assert params["limit"] == "50"
    assert "73 rings match these filters" in [item.value for item in app.caption]

    next(button for button in app.button if button.label == "Next page").click().run()
    assert dict(calls[-1][1])["cursor"] == "cursor-next"
    assert dict(calls[-1][1])["limit"] == "50"


def test_opening_and_returning_to_ring_keeps_filter_and_page_state(monkeypatch):
    calls = []
    app = _signed_in_app(monkeypatch, calls)
    app.session_state["ring_filter_values"] = {
        "status": ["confirmed"], "topology_type": ["CYCLE"], "min_conf": 0.4,
        "cross_bank_only": True, "sort": "members", "order": "asc",
        "start_after": None, "start_before": None,
    }
    app.session_state["ring_cursors"] = [None, "cursor-page-2"]
    app.session_state["ring_page"] = 1
    app.run()
    queue_params = dict(calls[-1][1])
    assert queue_params["cursor"] == "cursor-page-2"
    assert queue_params["status"] == "confirmed"

    app.session_state["open_ring"] = {"tenant_id": 210, "ring_id": "ring-1"}
    app.run()
    assert "Ring ring-1" in [item.value for item in app.header]

    app.session_state["open_ring"] = None
    app.run()
    assert "Ring queue" in [item.value for item in app.header]
    returned_params = dict(calls[-1][1])
    assert returned_params["cursor"] == "cursor-page-2"
    assert returned_params["status"] == "confirmed"
    assert returned_params["topology_type"] == "CYCLE"
    assert returned_params["sort"] == "members"
    assert returned_params["order"] == "asc"
