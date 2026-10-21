from __future__ import annotations

from pathlib import Path
import sys

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
        "end_time": "2026-01-01T00:01:00Z", "confidence": 0.9,
        "cross_bank": False, "counterparty_banks": [], "conservation_closure": 0.2,
        "model_id": "gine_causal", "aggregator_id": "aggregator-v1",
        "member_accounts": [1, 2], "member_edges": [10],
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


def _detail_app(monkeypatch, role, history, tmp_path):
    def request(_method, url, **_kwargs):
        if url.endswith("/evidence"):
            return FakeResponse(_evidence_payload())
        if url.endswith("/explanation"):
            return FakeResponse({
                "narrative": "Two accounts exchange funds.",
                "explainer_version": "l4-v7", "latency_ms": 18.5,
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

    chart = app.get("graphviz_chart")[0]
    assert 'acct_p1 -> acct_p2 [label="edge 10"]' in chart.proto.spec
    assert "Explainer l4-v7 · 18.5 ms" in [item.value for item in app.caption]


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
