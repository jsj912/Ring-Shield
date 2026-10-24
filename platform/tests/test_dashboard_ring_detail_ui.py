from __future__ import annotations

from pathlib import Path
import sys

import json

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    status_code = 200
    is_success = True
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _ring_payload():
    return {
        "ring_id": "ring-1", "topology_type": "CYCLE", "n_members": 2, "n_edges": 1,
        "status": "open", "total_amount": 125.0, "total_currency": "USD",
        "n_currencies": 1, "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-01T00:01:00Z", "window_text": "over 1 min", "confidence": 0.9,
        "cross_bank": False, "counterparty_banks": [], "conservation_closure": 0.2,
        "model_id": "gine_causal", "aggregator_id": "aggregator-v1",
        "member_accounts": [1, 2], "member_edges": [10],
        "topology_prob": 0.8, "total_partial": False, "seed_edges": [10], "expanded_edges": [],
        "source_accounts": [], "sink_accounts": [], "mule_accounts": [],
    }


def _evidence_payload():
    return {
        "missing_edge_ids": [], "next_before_edge_id": None,
        "nodes": [
            {"account_id": 1, "is_source": True, "is_sink": False,
             "is_mule": False, "bank_label": "Bank A"},
            {"account_id": 2, "is_source": False, "is_sink": True,
             "is_mule": False, "bank_label": "Bank A"},
        ],
        "edges": [{"source_account": 1, "target_account": 2, "edge_id": 10,
                   "timestamp": "2026-01-01T00:00:00Z", "amount_sent": 125.0,
                   "currency_sent": "USD", "amount_received": 125.0,
                   "currency_received": "USD", "payment_format": "wire",
                   "calibrated_score": 0.9, "is_seed": True}],
    }


def _subgraph_payload():
    return {
        "tenant_id": 210, "ring_id": "ring-1", "n_accounts": 2,
        "nodes": [{"account_id": 1, "role": "source", "bank_code": 1, "bank_label": "Bank 1",
                   "inflow": 0.0, "outflow": 125.0, "hold_time_s": None, "w_account": 0.9},
                  {"account_id": 2, "role": "sink", "bank_code": 1, "bank_label": "Bank 1",
                   "inflow": 125.0, "outflow": 0.0, "hold_time_s": None, "w_account": 0.8}],
        "edges": [{"edge_id": 10, "from_id": 1, "to_id": 2, "timestamp": "2026-01-01T00:00:00Z",
                   "amount": 125.0, "currency": "USD", "amount_received": 125.0,
                   "currency_received": "USD", "payment_format": "wire", "is_seed": True,
                   "is_conversion": False, "w_total": 0.7, "w_score": 0.9, "w_loo": 0.5, "w_flow": 0.4}],
    }


def _detail_app(monkeypatch, role, history, tmp_path, calls=None):
    def request(method, url, **_kwargs):
        if calls is not None:
            calls.append((method, url))
        if method == "POST":
            return FakeResponse({"verdict_id": 1})
        if url.endswith("/evidence"):
            return FakeResponse(_evidence_payload())
        if url.endswith("/subgraph"):
            return FakeResponse(_subgraph_payload())
        if url.endswith("/explanation"):
            return FakeResponse({
                "narrative": "Two accounts exchange funds.",
                "explainer_version": "l4-v7", "revision": 1, "regenerated": False,
                "regenerating": False, "latency_ms": 18.5,
                "evidence_summary": {}, "edge_weights": [], "account_weights": [],
                "feature_weights": [], "provenance": {},
            })
        if url.endswith("/verdicts"):
            return FakeResponse({"items": history, "next_before_id": None})
        return FakeResponse(_ring_payload())

    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "ring_detail.py"
    script.write_text(
        "import streamlit as st\n"
        "from dashboard.app import _ring_detail\n"
        "_ring_detail(210, 'ring-1')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "token"
    app.session_state["role"] = role
    return app


def test_ring_graph_points_from_payer_to_payee_and_explanation_footer_is_visible(monkeypatch, tmp_path):
    app = _detail_app(monkeypatch, "analyst", [], tmp_path).run()

    figure = json.loads(next(chart for chart in app.get("plotly_chart")
                             if "Account 1" in chart.proto.spec).proto.spec)
    nodes = {}
    for trace in figure["data"]:
        for x, y, text in zip(trace.get("x") or [], trace.get("y") or [], trace.get("hovertext") or []):
            if text.startswith("Account "):
                nodes[int(text.split("<br>")[0].split()[1])] = (x, y)
    arrow = figure["layout"]["annotations"][0]              # arrowhead at the payee (FR-D30)
    assert (arrow["ax"], arrow["ay"]) == nodes[1] and (arrow["x"], arrow["y"]) == nodes[2]
    assert any("Explainer l4-v7" in item.value and "revision 1" in item.value
               for item in app.caption)


def test_simulated_verdict_is_tagged_in_history(monkeypatch, tmp_path):
    app = _detail_app(monkeypatch, "analyst", [{
        "created_at": "2026-01-02T00:00:00Z", "user_name": "Simulator",
        "verdict": "confirm", "note": None, "is_simulated": True,
    }], tmp_path).run()

    history_table = app.dataframe[-1].value
    assert "Simulated" in history_table.columns
    assert bool(history_table.iloc[0]["Simulated"])


def test_admin_sees_read_only_verdict_warning_without_form(monkeypatch, tmp_path):
    app = _detail_app(monkeypatch, "admin", [], tmp_path).run()

    assert "Administrators cannot record verdicts." in [item.value for item in app.warning]
    assert "Record a verdict" not in [item.value for item in app.subheader]
    assert all(button.label not in {"Confirm ring", "Reject ring", "Partially correct"}
               for button in app.button)
    assert all(not box.label.startswith(("Keep account ", "Keep transaction "))
               for box in app.checkbox)


def test_ring_detail_disables_verdict_after_one_successful_request(monkeypatch, tmp_path):
    calls = []
    app = _detail_app(monkeypatch, "analyst", [], tmp_path, calls=calls).run()
    next(button for button in app.button if button.label == "Confirm ring").click().run(timeout=10)

    assert [call for call in calls if call[0] == "POST"] == [
        ("POST", "http://127.0.0.1:8000/tenants/210/rings/ring-1/verdicts")
    ]
    assert next(button for button in app.button if button.label == "Confirm ring").disabled
