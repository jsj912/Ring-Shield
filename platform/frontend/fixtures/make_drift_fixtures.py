"""Write fixtures/drift.json: drift fixtures in the shapes the API serves (NFR-D55).

    python platform/frontend/fixtures/make_drift_fixtures.py

- "tenant_hourly": the shape of R12 amendment A's results/platform/r12/amended/tenant_hourly.json
  (served by GET /tenants/{t}/drift/hourly), for Fixture Banks A and B.
- "events": drift events per tenant, in the DriftEventSummary field names.
- "panel": the shape of results/platform/r12/amended/panel.json (GET /admin/experiments/r12).

Every value is invented with a fixed seed: nothing here is a real score, a real R12 result or
tenant 900001's data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random

OUT = Path(__file__).resolve().parent / "drift.json"
DAY8 = datetime(2022, 9, 9, tzinfo=timezone.utc)
ADWIN = {"implementation": "river 0.22.0 ADWIN", "delta": 0.002, "clock": 1, "max_buckets": 5,
         "min_window_length": 5, "grace_period": 10, "units": "raw"}


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _hours():
    return [DAY8 + timedelta(hours=h) for h in range(48)]


def _tenant(tenant_id: int, rng: random.Random, drift_at: int | None) -> dict:
    items, adwin = [], []
    width = 0
    for h, hour in enumerate(_hours()):
        shift = 0.0006 if drift_at is not None and h >= drift_at else 0.0
        items.append({"day": _iso(hour), "mean": round(0.0009 + shift + rng.uniform(-1e-4, 1e-4), 9),
                      "p99": round(0.014 + 4 * shift + rng.uniform(-1e-3, 1e-3), 9)})
        width = 1 if drift_at is not None and h == drift_at + 3 else width + 1
        adwin.append({"hour": _iso(hour), "adwin_mean_width": width,
                      "adwin_mean_drift": drift_at is not None and h == drift_at + 3,
                      "adwin_p99_width": h + 1, "adwin_p99_drift": False})
    return {"tenant_id": tenant_id, "active_model_id": "gine_causal", "active_seed": 1, "step_seconds": 3600,
            "items": items, "adwin": adwin, "events": []}


def _stream(rng: random.Random, step_from: int | None, detect: bool) -> dict:
    rows = []
    for h, hour in enumerate(_hours()):
        step = 0.0012 if step_from is not None and h >= step_from else 0.0
        rows.append({"step": h + 1, "hour": _iso(hour), "mean": round(0.001 + step + rng.uniform(-1e-4, 1e-4), 9),
                     "p99": round(0.015 + rng.uniform(-1e-3, 1e-3), 9), "adwin_mean_width": h + 1,
                     "adwin_mean_drift": detect and h == 40, "adwin_p99_width": h + 1, "adwin_p99_drift": False})
    events = [{"monitor": "adwin_score_mean", "step": 41, "hour": rows[40]["hour"]}] if detect else []
    return {"rows": rows, "events": events, "detected": detect, "first_detection_step": 41 if detect else None,
            "delay_hours": 5.0 if detect else None}


def main() -> None:
    rng = random.Random(20261025)
    hourly = {"statement": "real scores, no synthetic step; ADWIN as in R12 amendment A (clock=1)",
              "adwin": ADWIN, "tenants": [_tenant(1001, rng, drift_at=34), _tenant(1002, rng, drift_at=None)]}
    events = {"1001": [{
        "event_id": 1, "monitor": "adwin_score_mean", "detected_at": _iso(DAY8 + timedelta(hours=37, minutes=5)),
        "window_start": _iso(DAY8), "window_end": _iso(DAY8 + timedelta(hours=37)),
        "statistic": 0.0015, "threshold": 0.002, "acted_on": False, "acted_on_note": None}], "1002": []}
    panel = {
        "statement": "drift was injected, not observed",
        "synthetic_control": "SYNTHETIC POSITIVE CONTROL: a step added to the monitor input, not data",
        "control_step": {"mean": 0.0012, "p99": 0.0},
        "control_onset": _iso(DAY8 + timedelta(hours=36)), "real_onset": _iso(DAY8 + timedelta(hours=24)),
        "removed_cycle_transactions": 31,
        "original_registered_run": {"adwin": {**ADWIN, "clock": 32}, "note": "fixture: as run, the control did not fire",
                                    "real": _stream(rng, None, False), "control": _stream(rng, 36, False)},
        "amendment_a_hourly": {"adwin": ADWIN, "real": _stream(rng, None, False), "control": _stream(rng, 36, True)},
    }
    OUT.write_text(json.dumps({"_note": "synthetic drift fixtures; see make_drift_fixtures.py",
                               "tenant_hourly": hourly, "events": events, "panel": panel}, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
