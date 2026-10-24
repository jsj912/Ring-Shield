from __future__ import annotations

from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
import json

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))
APP_FILE = PLATFORM_ROOT / "dashboard" / "app.py"


TENANTS = [{
    "tenant_id": 210, "bank_code": 12, "name": "North Bank", "is_loaded": True,
    "created_at": "2026-01-01T00:00:00Z", "ring_count": 4, "verdict_count": 2,
}]


def _signed_app(monkeypatch, handler, *, role="admin", page="Admin"):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return handler(method, url, kwargs)

    monkeypatch.setattr(httpx, "request", request)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "admin-token" if role == "admin" else f"{role}-token"
    app.session_state["user"] = 17
    app.session_state["tenant_id"] = None if role == "admin" else 210
    app.session_state["tenant_name"] = "Administrator" if role == "admin" else "North Bank"
    app.session_state["role"] = role
    app.session_state["workspace_page"] = page
    return app, calls


def _response(payload, status=200, request_id="admin-request"):
    return httpx.Response(status, json=payload, headers={"X-Request-ID": request_id})


R10 = {k: v for k, v in json.loads((PLATFORM_ROOT / "dashboard" / "fixtures" / "r10_result.json")
                                   .read_text(encoding="utf-8")).items() if not k.startswith("_")}


def test_admin_sees_registry_users_and_r10_sections(monkeypatch):
    def handler(_method, url, _kwargs):
        if url.endswith("/latest"):                       # no R10 result computed yet
            return _response({"error_code": "NOT_FOUND", "message": "none"}, 404)
        return _response(TENANTS)

    app, _calls = _signed_app(monkeypatch, handler)
    app.run()

    assert not app.exception
    assert "Admin" in [item.value for item in app.title]
    assert "Tenants" in [item.value for item in app.header]
    assert "Users" in [item.value for item in app.header]
    assert "R10 tenant vs pooled" in [item.value for item in app.header]
    assert "North Bank" in str([frame.value for frame in app.dataframe])
    assert "Rings" in str([frame.value for frame in app.dataframe])
    assert any("no user-list endpoint" in item.value for item in app.info)


def test_analyst_and_supervisor_cannot_navigate_to_admin(monkeypatch):
    for role in ("analyst", "supervisor"):
        app, calls = _signed_app(
            monkeypatch, lambda *_args: _response({}), role=role, page="Admin",
        )
        app.query_params["page"] = "admin"     # reached by URL (FR-D05)
        app.run()

        assert "Not permitted" in [item.value for item in app.warning]
        assert len(app.radio) == 0
        assert not calls


def test_r10_start_polls_running_then_renders_results_and_no_ground_truth(monkeypatch):
    status_payloads = [
        {"job_id": "job-one", "status": "running"},
        {
            "job_id": "job-one", "status": "succeeded", "message": "Available inputs: 2 seeds",
            "results": {**R10, "ground_truth_label": "must not render"},
        },
    ]

    def handler(method, url, _kwargs):
        if url.endswith("/admin/tenants"):
            return _response(TENANTS)
        if url.endswith("/latest"):
            return _response({"error_code": "NOT_FOUND", "message": "none"}, 404)
        if method == "POST":
            return _response({"job_id": "job-one", "status": "queued"}, 202)
        return _response(status_payloads.pop(0))

    app, calls = _signed_app(monkeypatch, handler)
    app.run()
    next(button for button in app.button if button.label == "Run").click().run()
    assert "Status: running" in [item.value for item in app.caption]
    app.run()

    assert "Status: succeeded" in [item.value for item in app.caption]
    assert "Available inputs: 2 seeds" in [item.value for item in app.caption]
    assert any("Budget-matched" in frame.value.columns for frame in app.dataframe)
    assert app.get("plotly_chart")
    visible = str({
        "dataframes": [frame.value for frame in app.dataframe],
        "markdown": [item.value for item in app.markdown],
        "captions": [item.value for item in app.caption],
        "info": [item.value for item in app.info],
    }).lower()
    assert "ground_truth" not in visible
    assert "must not render" not in visible
    assert len([call for call in calls if call[0] == "POST" and
                call[1].endswith("/admin/experiments/tenant-vs-pooled")]) == 1


def test_failed_r10_shows_safe_error_and_retry_starts_one_job(monkeypatch):
    posts = []

    def handler(method, url, _kwargs):
        if url.endswith("/admin/tenants"):
            return _response(TENANTS)
        if method == "POST":
            posts.append(url)
            return _response({"job_id": f"job-{len(posts)}", "status": "queued"}, 202)
        return _response({"job_id": "job-1", "status": "failed",
                          "message": "R10 inputs are unavailable"})

    app, _calls = _signed_app(monkeypatch, handler)
    app.session_state["admin_r10_job"] = {
        "job_id": "job-1", "status": "queued",
        "deadline": datetime.now(timezone.utc) + timedelta(minutes=1),
    }
    app.run()

    assert "R10 inputs are unavailable" in [item.value for item in app.error]
    next(button for button in app.button if button.label == "Retry").click().run()
    assert len(posts) == 1


def test_admin_page_two_api_failures_show_both_request_ids(monkeypatch, tmp_path):
    responses = [
        _response({"message": "Registry unavailable", "request_id": "req-admin-a"}, 500),
        _response({"message": "R10 status unavailable", "request_id": "req-admin-b"}, 500),
    ]
    monkeypatch.setattr(httpx, "request", lambda *_args, **_kwargs: responses.pop(0))
    script = tmp_path / "admin_two_failures.py"
    script.write_text(
        "from dashboard.app import _api\n"
        "_api('GET', '/admin/tenants')\n"
        "_api('GET', '/admin/experiments/tenant-vs-pooled/job-one')\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script)).run()

    assert not app.exception
    assert "Registry unavailable (request id req-admin-a)" in [item.value for item in app.error]
    assert "R10 status unavailable (request id req-admin-b)" in [item.value for item in app.error]
