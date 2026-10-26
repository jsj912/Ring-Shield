from __future__ import annotations

from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))

APP_FILE = PLATFORM_ROOT / "dashboard" / "app.py"


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self.payload = payload
        self.is_success = 200 <= status_code < 400

    def json(self):
        if self.payload is None:
            raise ValueError("no JSON body")
        return self.payload


def _login_app(monkeypatch, payload):
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FakeResponse(401, payload))
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["unrelated_state"] = "keep me"
    app.run()
    app.text_input[0].set_value("user@example.test")
    app.text_input[1].set_value("not-the-password")
    app.button[0].click().run()
    return app


@pytest.mark.parametrize("payload", [
    {"message": "Invalid email or password", "request_id": "request-a"},
    {"message": "account exists; password incorrect", "request_id": "request-b"},
])
def test_login_401_shows_generic_error_and_preserves_unrelated_session_state(monkeypatch, payload):
    app = _login_app(monkeypatch, payload)

    assert "Incorrect email or password." in [element.value for element in app.error]
    assert "Session expired. Please sign in again." not in [element.value for element in app.info]
    assert "token" not in app.session_state
    assert app.session_state["unrelated_state"] == "keep me"


def test_authenticated_401_is_shown_as_notice_after_login_rerun(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FakeResponse(
        401, {"message": "Session expired or invalid"},
    ))
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "expired-token"
    app.session_state["user"] = 31
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "Example Bank"
    app.session_state["role"] = "analyst"

    app.run()

    assert "token" not in app.session_state
    assert "tenant_id" not in app.session_state
    assert "Session expired. Please sign in again." in [element.value for element in app.info]


@pytest.mark.parametrize(("payload", "expected"), [
    ({"error_code": "NOT_PERMITTED", "message": "Not permitted", "request_id": "req-123"},
     "Not permitted: your role cannot do this. (request id req-123)"),
    ({"error_code": "NOT_PERMITTED", "message": "Not permitted"},
     "Not permitted: your role cannot do this."),
])
def test_403_warns_and_keeps_authenticated_session(monkeypatch, payload, expected):
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FakeResponse(403, payload))
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "valid-token"
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "Example Bank"
    app.session_state["role"] = "analyst"

    app.run()

    assert expected in [element.value for element in app.warning]
    assert app.session_state["token"] == "valid-token"
    assert app.session_state["tenant_id"] == 210


@pytest.mark.parametrize(("status", "quiet", "marker"), [(404, True, "RESULT_NONE"), (204, False, "RESULT_VALUE")])
def test_quiet_404_and_204_handling_remain_unchanged(tmp_path, monkeypatch, status, quiet, marker):
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: FakeResponse(status))
    script = tmp_path / "exercise_api.py"
    script.write_text(
        "import streamlit as st\n"
        "from dashboard.app import _api\n"
        f"result = _api('GET', '/probe', quiet_not_found={quiet!r})\n"
        "st.write('RESULT_NONE' if result is None else 'RESULT_VALUE')\n",
        encoding="utf-8",
    )

    app = AppTest.from_file(str(script)).run()

    assert any(marker in str(element.value) for element in app.markdown)
    assert not app.error


def test_api_unavailable_error_remains_unchanged(tmp_path, monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "request", raise_connection_error)
    script = tmp_path / "exercise_unavailable.py"
    script.write_text(
        "from dashboard.app import _api\n"
        "_api('GET', '/probe')\n",
        encoding="utf-8",
    )

    app = AppTest.from_file(str(script)).run()

    assert any("RingShield API is unavailable: offline" in element.value for element in app.error)


def test_login_error_does_not_depend_on_response_message(monkeypatch):
    app = _login_app(monkeypatch, {"message": "Internal authentication wording", "request_id": "secret"})
    assert [element.value for element in app.error] == ["Incorrect email or password."]
