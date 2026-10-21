from __future__ import annotations

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

    def json(self):
        return {
            "token": "session-token",
            "user_id": 17,
            "tenant_id": 210,
            "tenant_name": "North Bank",
            "role": "supervisor",
        }


def test_successful_login_stores_token_and_shows_tenant_and_role(monkeypatch):
    monkeypatch.setattr(httpx, "request", lambda *_args, **_kwargs: FakeResponse())
    app = AppTest.from_file(str(APP_FILE)).run()
    app.text_input[0].set_value("analyst@example.test")
    app.text_input[1].set_value("correct-password")
    app.button[0].click().run()

    assert app.session_state["token"] == "session-token"
    assert app.session_state["tenant_name"] == "North Bank"
    assert "North Bank" in [item.value for item in app.title]
    assert "Role: supervisor" in [item.value for item in app.caption]


def test_sign_out_clears_session_and_returns_to_login(tmp_path):
    script = tmp_path / "sign_out.py"
    script.write_text(
        "import streamlit as st\n"
        "from dashboard.app import _clear_session_state\n"
        "if st.button('Sign out'):\n"
        "    _clear_session_state()\n"
        "if st.session_state.get('token'):\n"
        "    st.write('Signed in')\n"
        "else:\n"
        "    st.title('RingShield Investigator')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "session-token"
    app.session_state["user"] = 17
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "North Bank"
    app.session_state["role"] = "analyst"
    app.session_state["cached_ring_data"] = {"ring": "ring-1"}
    app.run()

    app.button[0].click().run()

    for key in ("token", "user", "tenant_id", "tenant_name", "role", "cached_ring_data"):
        assert key not in app.session_state
    assert "RingShield Investigator" in [item.value for item in app.title]
