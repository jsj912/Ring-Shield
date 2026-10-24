"""Login screen in fixture mode: FR-D01-05, NFR-D10-12, D14 (docs/dashboard_checklist.md)."""

from __future__ import annotations

import ast
from pathlib import Path
import sys

import httpx
import pytest
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
APP_FILE = DASHBOARD / "app.py"
sys.path.insert(0, str(DASHBOARD))


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_DASHBOARD_FIXTURES", str(DASHBOARD / "fixtures"))
    import client
    client._fixture_api = None
    monkeypatch.setattr(httpx, "request", lambda *a, **k: pytest.fail("fixture mode called the network"))


def _sign_in(app: AppTest, email: str, password: str) -> AppTest:
    app.text_input[0].input(email)
    app.text_input[1].input(password)
    app.button[0].click()
    return app.run(timeout=10)


def test_login_shows_tenant_and_role_and_keeps_token_out_of_the_url(fixture_mode):
    app = AppTest.from_file(str(APP_FILE)).run(timeout=10)
    app = _sign_in(app, "analyst@bank-a.fixture", "fixture-only-a1")

    assert app.sidebar.title[0].value == "Fixture Bank A"
    assert "Role: analyst" in [item.value for item in app.sidebar.caption]
    assert app.session_state["token"].startswith("fixture-token-")
    assert all("token" not in str(value) for value in app.query_params.values())     # NFR-D10


def test_wrong_password_and_unknown_email_give_the_same_message(fixture_mode):
    messages = []
    for email, password in (("analyst@bank-a.fixture", "wrong-password"), ("nobody@nowhere.fixture", "x")):
        app = _sign_in(AppTest.from_file(str(APP_FILE)).run(timeout=10), email, password)
        messages.append([item.value for item in app.error])
    assert messages[0] == messages[1] == ["Incorrect email or password."]


def test_a_rejected_token_returns_to_login_with_session_expired(fixture_mode):
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "fixture-token-999"          # not a fixture user: every call is 401
    app.session_state["user"] = 999
    app.session_state["tenant_id"] = 1001
    app.session_state["tenant_name"] = "Fixture Bank A"
    app.session_state["role"] = "analyst"
    app = app.run(timeout=10)

    assert "token" not in app.session_state
    assert any("Session expired" in item.value for item in app.info)
    assert app.button[0].label == "Sign in"


def test_sign_out_clears_the_token_and_all_cached_data(fixture_mode):
    app = _sign_in(AppTest.from_file(str(APP_FILE)).run(timeout=10), "analyst@bank-a.fixture", "fixture-only-a1")
    app.session_state["ring_filter_values"] = {"cached": True}
    next(button for button in app.sidebar.button if button.label == "Sign out").click()
    app = app.run(timeout=10)

    assert "token" not in app.session_state
    assert "ring_filter_values" not in app.session_state
    assert app.button[0].label == "Sign in"


@pytest.mark.parametrize(("email", "password", "page", "allowed"), [
    ("analyst@bank-a.fixture", "fixture-only-a1", "drift", False),
    ("analyst@bank-a.fixture", "fixture-only-a1", "admin", False),
    ("supervisor@bank-a.fixture", "fixture-only-a2", "admin", False),
    ("supervisor@bank-a.fixture", "fixture-only-a2", "drift", True),
])
def test_pages_the_role_may_not_open_are_hidden_and_refused_by_url(fixture_mode, email, password, page, allowed):
    app = _sign_in(AppTest.from_file(str(APP_FILE)).run(timeout=10), email, password)
    navigation = next(radio for radio in app.sidebar.radio if radio.label == "Workspace")
    assert ({"drift": "Drift", "admin": "Admin"}[page] in navigation.options) is allowed

    app.query_params["page"] = page
    app = app.run(timeout=10)
    refused = "Not permitted" in [item.value for item in app.warning]
    assert refused is (not allowed)


def test_the_dashboard_package_has_no_database_driver():
    """NFR-D12: the dashboard never connects to the database or the file store directly."""
    forbidden = {"sqlalchemy", "psycopg", "psycopg2", "asyncpg", "pyarrow", "pandas.io.sql"}
    for path in DASHBOARD.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(name.split(".")[0] in forbidden for name in names), (path.name, names)
