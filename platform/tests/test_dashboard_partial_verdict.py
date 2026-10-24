from __future__ import annotations

from pathlib import Path
import sys

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))


class Response:
    status_code = 200
    is_success = True
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _detail(monkeypatch, tmp_path, *, role="analyst", post_results=None):
    calls = []
    post_results = post_results if post_results is not None else []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "POST":
            if post_results:
                return Response(post_results.pop(0))
            return Response({"verdict_id": 50, "regeneration": None})
        if url.endswith("/evidence"):
            return Response({"missing_edge_ids": [], "next_before_edge_id": None,
                             "nodes": [], "edges": []})
        if url.endswith("/explanation"):
            return Response({
                "narrative": "Original explanation.", "explainer_version": "v1",
                "revision": 1, "regenerated": False, "regenerating": False,
                "latency_ms": 4, "evidence_summary": {}, "edge_weights": [],
                "account_weights": [], "feature_weights": [], "provenance": {},
            })
        if url.endswith("/verdicts"):
            return Response({"items": [], "next_before_id": None})
        return Response({
            "ring_id": "ring-1", "topology_type": "CYCLE", "n_members": 3,
            "n_edges": 2, "status": "open", "total_amount": 10.0,
            "total_currency": "USD", "n_currencies": 1, "start_time": "t0",
            "end_time": "t1", "window_text": "over 1 min", "confidence": 0.9,
            "cross_bank": False, "counterparty_banks": [], "conservation_closure": 0.1,
            "model_id": "model", "aggregator_id": "aggregator",
            "member_accounts": [1, 2, 3], "member_edges": [10, 11],
        "topology_prob": 0.8, "total_partial": False, "seed_edges": [10, 11], "expanded_edges": [],
        "source_accounts": [], "sink_accounts": [], "mule_accounts": [],
        })

    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "partial_verdict.py"
    script.write_text(
        "from dashboard.app import _ring_detail\n"
        "_ring_detail(210, 'ring-1')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "token"
    app.session_state["role"] = role
    return app, calls


def _open_partial(app):
    next(button for button in app.button if button.label == "Partially correct").click().run(timeout=10)


def _set_checkbox(app, key, value):
    box = next(item for item in app.checkbox if item.key == key)
    box.set_value(value)


def test_partial_checklists_start_checked_and_send_kept_accounts_and_transactions(
        monkeypatch, tmp_path):
    app, calls = _detail(monkeypatch, tmp_path, post_results=[{
        "verdict_id": 50, "regeneration": {"status": "unavailable", "job_id": None},
    }])
    app.run(timeout=10)
    _open_partial(app)

    assert all(box.value for box in app.checkbox)
    _set_checkbox(app, "partial_keep_account_210_ring-1_3", False)
    _set_checkbox(app, "partial_keep_transaction_210_ring-1_11", False)
    app.text_area[0].set_value("Remove the unrelated account and transaction")
    next(button for button in app.button if button.label == "Submit partial verdict").click().run(timeout=10)

    posts = [call for call in calls if call[0] == "POST"]
    assert posts == [(
        "POST", "http://127.0.0.1:8000/tenants/210/rings/ring-1/verdicts",
        {"verdict": "partial", "note": "Remove the unrelated account and transaction",
         "corrected_members": [1, 2],
         "corrected_edges": [10]},
    )]


def test_partial_verdict_blocks_fewer_than_two_kept_accounts(monkeypatch, tmp_path):
    app, calls = _detail(monkeypatch, tmp_path)
    app.run(timeout=10)
    _open_partial(app)
    _set_checkbox(app, "partial_keep_account_210_ring-1_2", False)
    _set_checkbox(app, "partial_keep_account_210_ring-1_3", False)
    app.text_area[0].set_value("Remove two accounts")
    next(button for button in app.button if button.label == "Submit partial verdict").click().run(timeout=10)

    assert "Keep at least two accounts for a partial correction." in [item.value for item in app.error]
    assert not [call for call in calls if call[0] == "POST"]


def test_partial_verdict_blocks_when_nothing_is_removed(monkeypatch, tmp_path):
    app, calls = _detail(monkeypatch, tmp_path)
    app.run(timeout=10)
    _open_partial(app)
    app.text_area[0].set_value("No change")
    next(button for button in app.button if button.label == "Submit partial verdict").click().run(timeout=10)

    assert "Remove at least one account or transaction; otherwise confirm the ring." in [
        item.value for item in app.error
    ]
    assert not [call for call in calls if call[0] == "POST"]


def test_partial_verdict_requires_a_note(monkeypatch, tmp_path):
    app, calls = _detail(monkeypatch, tmp_path)
    app.run(timeout=10)
    _open_partial(app)
    _set_checkbox(app, "partial_keep_transaction_210_ring-1_11", False)
    next(button for button in app.button if button.label == "Submit partial verdict").click().run(timeout=10)

    assert "A note is required for a partial verdict." in [item.value for item in app.error]
    assert not [call for call in calls if call[0] == "POST"]
