from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time

import httpx
import pytest

from adapters import xai


def _config(url="https://l4.example.test/api", timeout=2):
    return {"l4": {"regenerate_url": url, "regenerate_timeout_seconds": timeout}}


def _response(status, body, *, headers=None):
    return httpx.Response(status, json=body, headers=headers)


def test_regenerate_sends_contract_payload_and_bearer_token(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _response(200, {"ring_id": "r-1", "provenance": "{}"})

    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", "secret-token-value")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = xai.regenerate(20, "r-1", [8], [11], config=_config(), client=client)

    assert result["ring_id"] == "r-1"
    assert calls[0].url.path == "/api/regenerate"
    assert calls[0].headers["authorization"] == "Bearer secret-token-value"
    assert json.loads(calls[0].content) == {
        "tenant_id": 20, "ring_id": "r-1", "excluded_members": [8], "excluded_edges": [11],
    }


@pytest.mark.parametrize(
    ("status", "body", "error_type"),
    [
        (404, {"error": "RingNotFound"}, xai.XaiRingNotFoundError),
        (422, {"error": "InvalidEdit", "message": "At least two accounts must remain"},
         xai.XaiInvalidEditError),
        (400, {"message": "sensitive response text"}, xai.XaiBadRequestError),
        (500, {"message": "sensitive response text"}, xai.XaiInternalError),
        (503, {"sensitive": "response body must not leak"}, xai.XaiUnexpectedStatusError),
    ],
)
def test_adapter_maps_service_statuses(monkeypatch, status, body, error_type):
    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", "secret-token-value")
    with httpx.Client(transport=httpx.MockTransport(lambda _: _response(status, body))) as client:
        with pytest.raises(error_type) as raised:
            xai.regenerate(20, "r-1", [], [], config=_config(), client=client)
    assert "secret-token-value" not in str(raised.value)
    if status == 422:
        assert "At least two accounts" in str(raised.value)
    if status == 503:
        assert "sensitive" not in str(raised.value)
    if status in (400, 500):
        assert "sensitive" not in str(raised.value)


def test_adapter_maps_invalid_json_and_timeouts(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", "secret-token-value")
    invalid = httpx.Response(200, content=b"not json")
    with httpx.Client(transport=httpx.MockTransport(lambda _: invalid)) as client:
        with pytest.raises(xai.XaiInvalidResponseError):
            xai.regenerate(20, "r-1", [], [], config=_config(), client=client)
    with httpx.Client(transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("secret-token-value")))) as client:
        with pytest.raises(xai.XaiTimeoutError) as raised:
            xai.regenerate(20, "r-1", [], [], config=_config(), client=client)
    assert "secret-token-value" not in str(raised.value)


def test_adapter_fails_safely_when_unconfigured_or_token_missing(monkeypatch):
    monkeypatch.delenv("RINGSHIELD_XAI_TOKEN", raising=False)
    with pytest.raises(xai.XaiNotConfiguredError):
        xai.regenerate(20, "r-1", [], [], config=_config(url=None))
    with pytest.raises(xai.XaiNotConfiguredError):
        xai.regenerate(20, "r-1", [], [], config=_config())


def test_token_is_not_written_to_logs_or_exceptions(monkeypatch, caplog):
    secret = "never-log-this-token"
    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", secret)

    def handler(_):
        return httpx.Response(422, json={"message": f"bad edit {secret}"})

    caplog.set_level(logging.DEBUG)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(xai.XaiInvalidEditError) as raised:
            xai.regenerate(20, "r-1", [], [], config=_config(), client=client)
    assert secret not in str(raised.value)
    assert secret not in caplog.text


def test_real_http_server_checks_timeout_and_bearer_handling(monkeypatch):
    requests = []
    should_delay = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            requests.append((self.path, self.headers.get("Authorization")))
            if should_delay.is_set():
                time.sleep(1.5)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(b'{"ring_id":"r-1"}')
            except OSError:
                return

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", "local-test-token")
    config = _config(f"http://127.0.0.1:{server.server_port}", timeout=1)
    try:
        assert xai.regenerate(20, "r-1", [], [], config=config)["ring_id"] == "r-1"
        assert requests[0] == ("/regenerate", "Bearer local-test-token")
        should_delay.set()
        with pytest.raises(xai.XaiTimeoutError):
            xai.regenerate(20, "r-1", [], [], config=_config(
                f"http://127.0.0.1:{server.server_port}", timeout=1))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
