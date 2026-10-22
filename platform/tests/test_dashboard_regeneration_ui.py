from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.headers = {}

    def json(self):
        return self.payload


def _app(monkeypatch, tmp_path, *, job_statuses=(), regeneration=None,
         explanation_regenerating=False):
    calls = []
    status_responses = list(job_statuses)
    post_responses = [regeneration or {
        "verdict_id": 50,
        "regeneration": {"status": "queued", "job_id": "210.job-1"},
    }]
    explanation_reads = []
    partial_recorded = [False]

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "POST" and url.endswith("/verdicts"):
            partial_recorded[0] = True
            return Response(post_responses.pop(0))
        if method == "POST" and url.endswith("/explanation/regenerate"):
            return Response({"job_id": "210.job-2", "status": "queued",
                             "result_revision": None, "error": None})
        if method == "GET" and "/explanation/jobs/" in url:
            payload = status_responses.pop(0) if status_responses else {
                "job_id": "210.job-1", "status": "queued",
                "result_revision": None, "error": None,
            }
            return Response(payload)
        if url.endswith("/evidence"):
            return Response({
                "missing_edge_ids": [], "next_before_edge_id": None,
                "nodes": [{"account_id": 1, "is_source": True, "is_sink": False,
                           "is_mule": False, "bank_label": "Bank A"},
                          {"account_id": 2, "is_source": False, "is_sink": True,
                           "is_mule": False, "bank_label": "Bank A"}],
                "edges": ([{"source_account": 1, "target_account": 2, "edge_id": 10,
                            "timestamp": "t0", "amount_sent": 1.0, "currency_sent": "USD",
                            "amount_received": 1.0, "currency_received": "USD",
                            "payment_format": "wire", "calibrated_score": 0.9,
                            "is_seed": True}] if partial_recorded[0] else []),
            })
        if url.endswith("/explanation"):
            explanation_reads.append(True)
            is_new = bool(status_responses == [] and len(explanation_reads) > 1)
            return Response({
                "narrative": "Regenerated explanation." if is_new else "Original explanation.",
                "explainer_version": "v1", "revision": 2 if is_new else 1,
                "regenerated": is_new,
                "regenerating": explanation_regenerating,
                "latency_ms": 4, "evidence_summary": {}, "edge_weights": [],
                "account_weights": [], "feature_weights": [], "provenance": {},
            })
        if url.endswith("/verdicts"):
            items = ([{"created_at": "2026-01-01T00:00:00Z", "user_name": "Analyst",
                       "verdict": "partial", "note": "Corrected", "is_simulated": False}]
                     if partial_recorded[0] else [])
            return Response({"items": items, "next_before_id": None})
        return Response({
            "ring_id": "ring-1", "topology_type": "CYCLE", "n_members": 3,
            "n_edges": 2, "status": "partial" if partial_recorded[0] else "open",
            "total_amount": 10.0,
            "total_currency": "USD", "n_currencies": 1, "start_time": "t0",
            "end_time": "t1", "window_text": "over 1 min", "confidence": 0.9,
            "cross_bank": False, "counterparty_banks": [], "conservation_closure": 0.1,
            "model_id": "model", "aggregator_id": "aggregator",
            "member_accounts": [1, 2, 3], "member_edges": [10, 11],
        })

    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "regeneration_detail.py"
    script.write_text(
        "from dashboard.app import _ring_detail\n"
        "_ring_detail(210, 'ring-1')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "token"
    app.session_state["role"] = "analyst"
    return app, calls


def _submit_partial(app):
    next(button for button in app.button if button.label == "Partially correct").click().run(timeout=10)
    next(box for box in app.checkbox if box.key.endswith("partial_keep_account_210_ring-1_3")).set_value(False)
    app.text_area[0].set_value("Remove account three")
    next(button for button in app.button if button.label == "Submit partial verdict").click().run(timeout=10)


def test_queued_partial_verdict_shows_progress_and_polls_job(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, tmp_path, job_statuses=[{
        "job_id": "210.job-1", "status": "queued", "result_revision": None, "error": None,
    }])
    app.run(timeout=10)
    _submit_partial(app)

    assert "Regenerating explanation..." in [item.value for item in app.info]
    assert any(call[0] == "GET" and call[1].endswith(
        "/explanation/jobs/210.job-1") for call in calls)


def test_succeeded_regeneration_refreshes_explanation_and_revision(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, tmp_path, job_statuses=[{
        "job_id": "210.job-1", "status": "succeeded", "result_revision": 2, "error": None,
    }])
    app.run(timeout=10)
    _submit_partial(app)

    assert "Regenerated explanation." in [item.value for item in app.markdown]
    assert any("Regenerated" in item.value and "revision 2" in item.value
               for item in app.caption)
    assert any("partial" in item.value for item in app.caption)
    assert any("Verdict" in item.value.columns and item.value.iloc[0]["Verdict"] == "partial"
               for item in app.dataframe)
    assert len([call for call in calls if call[0] == "GET" and call[1].endswith("/explanation")]) >= 2
    assert any(call[1].endswith("/evidence") for call in calls)
    assert any(call[1].endswith("/rings/ring-1") for call in calls)
    assert any(call[1].endswith("/verdicts") for call in calls)


def test_regeneration_stops_polling_after_120_seconds(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, tmp_path)
    app.session_state["ring_regeneration"] = {
        "tenant_id": 210, "ring_id": "ring-1", "verdict_id": 50,
        "job_id": "210.job-1", "status": "queued",
        "deadline": datetime(2000, 1, 1, tzinfo=timezone.utc),
    }
    app.run(timeout=10)

    assert "Still working, refresh later." in [item.value for item in app.info]
    assert not any("/explanation/jobs/" in call[1] for call in calls)


def test_failed_regeneration_shows_safe_error_and_retry_calls_regenerate_once(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, tmp_path, job_statuses=[{
        "job_id": "210.job-1", "status": "failed", "result_revision": None,
        "error": "L4 explanation service request failed",
    }])
    app.run(timeout=10)
    _submit_partial(app)

    assert "L4 explanation service request failed" in [item.value for item in app.error]
    next(button for button in app.button if button.label == "Retry").click().run(timeout=10)
    retry_posts = [call for call in calls if call[0] == "POST" and call[1].endswith(
        "/explanation/regenerate")]
    assert retry_posts == [(
        "POST", "http://127.0.0.1:8000/tenants/210/rings/ring-1/explanation/regenerate",
        {"verdict_id": 50},
    )]


def test_unavailable_partial_verdict_explains_that_verdict_was_recorded(monkeypatch, tmp_path):
    app, _calls = _app(monkeypatch, tmp_path, regeneration={
        "verdict_id": 50, "regeneration": {"status": "unavailable", "job_id": None},
    })
    app.run(timeout=10)
    _submit_partial(app)

    assert "The verdict was recorded, but the explanation could not be regenerated." in [
        item.value for item in app.info
    ]


def test_ring_with_regenerating_explanation_shows_progress_state(monkeypatch, tmp_path):
    app, _calls = _app(monkeypatch, tmp_path, explanation_regenerating=True)
    app.run(timeout=10)

    assert "Regenerating explanation..." in [item.value for item in app.info]


def test_ring_detail_two_api_failures_render_with_distinct_retry_buttons(monkeypatch, tmp_path):
    app, _calls = _app(monkeypatch, tmp_path)
    original_request = httpx.request

    def failing_request(method, url, **kwargs):
        if url.endswith("/evidence"):
            return Response({"message": "Evidence unavailable", "request_id": "evidence-req"}, 500)
        if url.endswith("/explanation"):
            return Response({"message": "Explanation unavailable", "request_id": "explanation-req"}, 500)
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", failing_request)
    app.run(timeout=10)

    messages = [item.value for item in app.error]
    assert "Evidence unavailable (request id evidence-req)" in messages
    assert "Explanation unavailable (request id explanation-req)" in messages
    retry_buttons = [button for button in app.button if button.label == "Retry"]
    assert len(retry_buttons) == 2
    assert len({button.key for button in retry_buttons}) == 2
