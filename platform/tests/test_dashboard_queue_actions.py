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


class Response:
    status_code = 200
    is_success = True
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _ring(ring_id, status="open"):
    return {
        "ring_id": ring_id, "tenant_id": 210, "topology_type": "CYCLE",
        "topology_prob": 0.9, "n_members": 3, "n_edges": 3,
        "total_amount": None, "total_currency": None,
        "start_time": "2026-01-01T00:00:00Z", "end_time": "2026-01-01T01:00:00Z",
        "window_text": "over 1 h", "confidence": 0.8, "cross_bank": False,
        "status": status,
    }


def _app(monkeypatch, *, role="analyst", items=None, posts=None):
    rows = items if items is not None else [_ring("ring-a"), _ring("ring-b")]

    def request(method, url, **kwargs):
        if method == "POST":
            posts.append((url, kwargs.get("json")))
            return Response({"verdict_id": len(posts)})
        if url.endswith("/admin/tenants"):
            return Response([{"tenant_id": 210, "name": "North Bank", "bank_code": 210,
                              "is_loaded": True}])
        if url.endswith("/rings"):
            return Response({"items": rows, "total": len(rows), "tenant_total": len(rows),
                             "next_cursor": None})
        if url.endswith("/explanation"):
            response = Response({})
            response.status_code = 404
            response.is_success = False
            return response
        return Response({"items": [], "next_before_id": None})

    monkeypatch.setattr(httpx, "request", request)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "token"
    app.session_state["tenant_id"] = None if role == "admin" else 210
    app.session_state["tenant_name"] = "Admin" if role == "admin" else "North Bank"
    app.session_state["role"] = role
    return app


def test_multiple_queue_rows_render_distinct_action_widgets(monkeypatch):
    app = _app(monkeypatch, items=[_ring("ring-a"), _ring("ring-b"), _ring("ring-c")]).run(timeout=10)
    confirm_buttons = [button for button in app.button if button.label == "Confirm"]
    reject_buttons = [button for button in app.button if button.label == "Reject"]

    assert len(confirm_buttons) == 3
    assert len({button.key for button in confirm_buttons}) == 3
    assert len(reject_buttons) == 3
    assert len({button.key for button in reject_buttons}) == 3


def test_queue_verdict_requires_confirmation_and_only_submits_once(monkeypatch):
    posts = []
    app = _app(monkeypatch, posts=posts).run(timeout=10)

    next(button for button in app.button if button.key == "queue_confirm_210_ring-a").click().run(timeout=10)
    assert "Confirm ring ring-a?" in [item.value for item in app.warning]
    next(button for button in app.button
         if button.key == "queue_confirm_verdict_210_ring-a").click().run(timeout=10)

    assert posts == [("http://127.0.0.1:8000/tenants/210/rings/ring-a/verdicts",
                      {"verdict": "confirm", "note": None})]
    assert any(button.key == "queue_confirm_210_ring-a" and button.disabled for button in app.button)


def test_queue_hides_actions_for_closed_rings_and_disables_admin_actions(monkeypatch):
    analyst = _app(monkeypatch, items=[_ring("ring-closed", status="confirmed")]).run(timeout=10)
    assert not any(button.label in {"Confirm", "Reject"} for button in analyst.button)

    admin = _app(monkeypatch, role="admin").run(timeout=10)
    assert "Administrators cannot record verdicts." in [item.value for item in admin.warning]
    assert all(button.disabled for button in admin.button if button.label in {"Confirm", "Reject"})
