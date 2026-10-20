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
