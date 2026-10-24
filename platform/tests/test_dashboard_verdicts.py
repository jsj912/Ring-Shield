from __future__ import annotations

import csv
from datetime import date
import io
from pathlib import Path
import sys

import httpx
import streamlit as st
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


def _page(items=None, cursor="next-page"):
    rows = items if items is not None else [{
        "verdict_id": 42, "ring_id": "ring-42", "verdict": "confirm",
        "analyst_id": 17, "analyst_label": "Analyst 17", "is_simulated": True,
        "note_excerpt": "Reviewed safely", "created_at": "2026-01-02T00:00:00Z",
    }]
    return {
        "items": rows, "next_cursor": cursor, "total": 1,
        "counts": {"confirmed": 1, "rejected": 0, "partial": 0},
        "analysts": [{"analyst_id": 17, "analyst_label": "Analyst 17"}],
    }


def _app(monkeypatch, calls):
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        if url.endswith("/verdicts"):
            return Response(_page(cursor=None if dict(kwargs.get("params") or ()).get("cursor") else "next-page"))
        if url.endswith("/rings"):
            return Response({"items": [], "total": 0, "tenant_total": 0,
                             "next_cursor": None})
        return Response({})

    monkeypatch.setattr(httpx, "request", request)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "token"
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "North Bank"
    app.session_state["role"] = "analyst"
    return app


def test_verdict_page_filters_counts_and_cursor_pagination(monkeypatch):
    calls = []
    app = _app(monkeypatch, calls).run(timeout=10)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Verdict history").run(timeout=10)
    assert "1 verdicts match these filters" in [caption.value for caption in app.caption]
    assert app.dataframe[0].value.iloc[0]["Analyst"] == "Analyst 17"
    assert app.metric[0].value == "1"

    next(field for field in app.multiselect if field.label == "Verdict type").set_value(["reject"])
    next(field for field in app.selectbox if field.label == "Analyst").select("Analyst 17")
    next(field for field in app.selectbox if field.label == "Simulated or real").select("Simulated")
    next(field for field in app.date_input if field.label == "Verdict date range").set_value(
        (date(2026, 1, 1), date(2026, 1, 3))
    )
    next(button for button in app.button if button.label == "Apply verdict filters").click().run(timeout=10)
    filtered_params = dict(calls[-1][2])
    assert filtered_params["verdict"] == "reject"
    assert filtered_params["analyst_id"] == "17"
    assert filtered_params["simulated"] == "true"
    assert filtered_params["since"].startswith("2026-01-01T00:00:00")
    assert filtered_params["until"].startswith("2026-01-03T23:59:59")
    next(button for button in app.button if button.label == "Next verdict page").click().run(timeout=10)
    assert dict(calls[-1][2])["cursor"] == "next-page"


def test_verdict_csv_export_includes_filtered_rows(monkeypatch):
    calls = []
    exports = []
    original_download = st.download_button

    def capture_download(label, data, **kwargs):
        exports.append((label, data))
        return original_download(label, data, **kwargs)

    monkeypatch.setattr(st, "download_button", capture_download)
    app = _app(monkeypatch, calls).run(timeout=10)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Verdict history").run(timeout=10)
    next(button for button in app.button if button.label == "Prepare CSV export").click().run(timeout=10)

    assert any(button.label == "Download CSV" for button in app.get("download_button"))
    assert "ring-42" in exports[-1][1]
    assert "Reviewed safely" in exports[-1][1]
    assert any(dict(call[2]).get("cursor") == "next-page" for call in calls if call[2])


def test_verdict_csv_export_escapes_formula_text_without_changing_header_or_other_cells(monkeypatch):
    calls = []
    exports = []
    original_download = st.download_button
    formula_notes = ["=HYPERLINK(\"https://example.test\")", "+1", "-2+3",
                     "@SUM(A1)", "\tcell", "\rstart", "Ordinary note", ""]
    rows = [{
        "verdict_id": index, "ring_id": f"ring-{index}", "verdict": "confirm",
        "analyst_id": 17, "analyst_label": "Analyst 17", "is_simulated": False,
        "note_excerpt": note, "created_at": "2026-01-02T00:00:00Z",
    } for index, note in enumerate(formula_notes, 1)]

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        if url.endswith("/verdicts"):
            return Response(_page(rows, cursor=None))
        if url.endswith("/rings"):
            return Response({"items": [], "total": 0, "tenant_total": 0,
                             "next_cursor": None})
        return Response({})

    def capture_download(label, data, **kwargs):
        exports.append((label, data))
        return original_download(label, data, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setattr(st, "download_button", capture_download)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "token"
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "North Bank"
    app.session_state["role"] = "analyst"
    app.run(timeout=10)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Verdict history").run(timeout=10)
    next(button for button in app.button if button.label == "Prepare CSV export").click().run(timeout=10)

    header, *exported = list(csv.reader(io.StringIO(exports[-1][1])))
    assert header == ["created_at", "ring_id", "verdict", "analyst_label",
                      "is_simulated", "note_excerpt"]
    assert [row[-1] for row in exported] == ["'" + note if note and note[0] in "=+-@\t\r" else note
                                             for note in formula_notes]
    assert all(row[0] == "2026-01-02T00:00:00Z" and row[4] == "False" for row in exported)
    assert not any(any(term in column.lower() for term in ("email", "ground_truth", "path"))
                   for column in header)
    assert any(dict(call[2]).get("limit") == "100" for call in calls if call[2])


def test_verdict_csv_export_requests_only_session_tenant_and_all_filtered_pages(monkeypatch):
    calls = []
    exports = []
    original_download = st.download_button
    tenant_rows = {
        210: [
            ("tenant-210-ring-1", "Tenant 210 page one"),
            ("tenant-210-ring-2", "Tenant 210 page two"),
        ],
        220: [("tenant-220-ring-1", "Tenant 220 private row")],
    }

    def request(method, url, **kwargs):
        params = dict(kwargs.get("params") or ())
        calls.append((method, url, params))
        if url.endswith("/verdicts"):
            requested_tenant = int(url.split("/tenants/")[1].split("/")[0])
            assert "tenant_id" not in params
            if params.get("cursor") == "tenant-210-next":
                ring_id, note = tenant_rows[requested_tenant][1]
                return Response(_page([{
                    "verdict_id": 2, "ring_id": ring_id, "verdict": "reject",
                    "analyst_id": 17, "analyst_label": "Analyst 17", "is_simulated": False,
                    "note_excerpt": note, "created_at": "2026-01-03T00:00:00Z",
                }], cursor=None))
            ring_id, note = tenant_rows[requested_tenant][0]
            return Response(_page([{
                "verdict_id": 1, "ring_id": ring_id, "verdict": "reject",
                "analyst_id": 17, "analyst_label": "Analyst 17", "is_simulated": False,
                "note_excerpt": note, "created_at": "2026-01-02T00:00:00Z",
            }], cursor="tenant-210-next"))
        if url.endswith("/rings"):
            return Response({"items": [], "total": 0, "tenant_total": 0,
                             "next_cursor": None})
        return Response({})

    def capture_download(label, data, **kwargs):
        exports.append((label, data))
        return original_download(label, data, **kwargs)

    monkeypatch.setattr(httpx, "request", request)
    monkeypatch.setattr(st, "download_button", capture_download)
    app = AppTest.from_file(str(APP_FILE))
    app.session_state["token"] = "token"
    app.session_state["tenant_id"] = 210
    app.session_state["tenant_name"] = "North Bank"
    app.session_state["role"] = "analyst"
    app.run(timeout=10)
    next(radio for radio in app.radio if radio.label == "Workspace").set_value("Verdict history").run(timeout=10)
    next(field for field in app.multiselect if field.label == "Verdict type").set_value(["reject"])
    next(button for button in app.button if button.label == "Apply verdict filters").click().run(timeout=10)
    next(button for button in app.button if button.label == "Prepare CSV export").click().run(timeout=10)

    assert "CSV export includes all rows matching the active filters." in [
        caption.value for caption in app.caption
    ]
    export_csv = exports[-1][1]
    assert "Tenant 210 page one" in export_csv and "Tenant 210 page two" in export_csv
    assert "tenant-220" not in export_csv
    export_calls = [call for call in calls if call[0] == "GET" and call[1].endswith("/verdicts")]
    assert export_calls
    requested_tenants = [int(call[1].split("/tenants/")[1].split("/")[0])
                         for call in export_calls]
    assert requested_tenants and set(requested_tenants) == {210}
    assert all("tenant_id" not in call[2] for call in export_calls)
    export_query = [call[2] for call in export_calls if call[2].get("limit") == "100"]
    assert export_query and all(call.get("verdict") == "reject" for call in export_query)
    assert any(call.get("cursor") == "tenant-210-next" for call in export_query)
