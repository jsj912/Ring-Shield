from __future__ import annotations

import json
from pathlib import Path
import sys

import httpx
from streamlit.testing.v1 import AppTest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(0, str(REPO_ROOT))


class FakeResponse:
    status_code = 200
    is_success = True
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_drift_chart_shows_daily_series_and_event_markers(monkeypatch, tmp_path):
    def request(_method, url, **_kwargs):
        if url.endswith("/series"):
            return FakeResponse({"items": [{
                "day": "2026-01-01T00:00:00Z", "mean": 0.25, "p99": 0.91,
            }]})
        return FakeResponse({"items": [{
            "event_id": 9, "monitor": "adwin_score_mean", "statistic": 0.42,
            "threshold": 0.002, "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-01T01:00:00Z", "detected_at": "2026-01-01T01:00:00Z",
            "acted_on": False,
        }], "next_before_id": None})

    monkeypatch.setattr(httpx, "request", request)
    script = tmp_path / "drift.py"
    script.write_text(
        "from dashboard.app import _drift_events\n"
        "_drift_events(210)\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(script))
    app.session_state["token"] = "token"
    app.session_state["role"] = "supervisor"
    app.run()

    figure_spec = app.get("plotly_chart")[0].proto.spec
    if isinstance(figure_spec, str):
        figure_spec = json.loads(figure_spec)
    traces = figure_spec["data"]
    names = {trace["name"] for trace in traces}
    assert {"Daily mean", "Daily 99th percentile", "Mean drift detected"} <= names
    assert any(trace.get("mode") == "markers" and trace.get("name") == "Mean drift detected"
               for trace in traces)
    assert "2026-01-01T00:00:00Z" in json.dumps(traces)
