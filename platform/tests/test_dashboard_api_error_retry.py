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
    def __init__(self, payload, headers=None):
        self.status_code = 500
        self.is_success = False
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        return self.payload


def _api_error_app(monkeypatch, tmp_path, request):
    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "api_error.py"
    script.write_text(
        "from dashboard.app import _api\n"
        "_api('GET', '/probe')\n",
        encoding="utf-8",
    )
    return AppTest.from_file(str(script)).run()


def test_server_error_shows_api_message_body_request_id_and_retry(monkeypatch, tmp_path):
    app = _api_error_app(monkeypatch, tmp_path, lambda *_args, **_kwargs: FakeResponse(
        {"message": "Service temporarily unavailable", "request_id": "body-req-7"},
        {"X-Request-ID": "header-req-8"},
    ))

    assert "Service temporarily unavailable (request id body-req-7)" in [
        item.value for item in app.error
    ]
    assert any(button.label == "Retry" for button in app.button)


def test_server_error_uses_request_id_response_header_when_body_omits_it(monkeypatch, tmp_path):
    app = _api_error_app(monkeypatch, tmp_path, lambda *_args, **_kwargs: FakeResponse(
        {"message": "Unexpected response"}, {"X-Request-ID": "header-req-9"},
    ))

    assert "Unexpected response (request id header-req-9)" in [
        item.value for item in app.error
    ]
    assert any(button.label == "Retry" for button in app.button)


def test_network_failure_keeps_unavailable_message_and_shows_retry(monkeypatch, tmp_path):
    def offline(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    app = _api_error_app(monkeypatch, tmp_path, offline)

    assert "RingShield API is unavailable: offline" in [item.value for item in app.error]
    assert any(button.label == "Retry" for button in app.button)


def test_ring_detail_can_render_two_api_failures_with_distinct_retry_controls(monkeypatch, tmp_path):
    class Response:
        def __init__(self, status_code, payload, headers=None):
            self.status_code = status_code
            self.is_success = 200 <= status_code < 300
            self.payload = payload
            self.headers = headers or {}

        def json(self):
            return self.payload

    def request(_method, url, **_kwargs):
        if url.endswith("/evidence"):
            return Response(500, {"message": "Evidence unavailable", "request_id": "evidence-req"})
        if url.endswith("/explanation"):
            return Response(500, {"message": "Explanation unavailable", "request_id": "explanation-req"})
        if url.endswith("/verdicts"):
            return Response(200, {"items": [], "next_before_id": None})
        return Response(200, {
            "ring_id": "ring-1", "topology_type": "CYCLE", "n_members": 2,
            "n_edges": 1, "status": "open", "total_amount": 10.0,
            "total_currency": "USD", "n_currencies": 1, "start_time": "t0",
            "end_time": "t1", "window_text": "over 1 h", "confidence": 0.9, "cross_bank": False,
            "counterparty_banks": [], "conservation_closure": 0.1,
            "model_id": "model", "aggregator_id": "aggregator",
            "member_accounts": [1, 2], "member_edges": [7],
        })

    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "ring_errors.py"
    script.write_text(
        "from dashboard.app import _ring_detail\n"
        "_ring_detail(210, 'ring-1')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "token"
    app.session_state["role"] = "analyst"
    app.run()

    messages = [item.value for item in app.error]
    assert "Evidence unavailable (request id evidence-req)" in messages
    assert "Explanation unavailable (request id explanation-req)" in messages
    assert sum(button.label == "Retry" for button in app.button) == 2
