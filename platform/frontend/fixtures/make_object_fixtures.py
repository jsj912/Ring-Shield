"""Write fixtures/objects/: one JSON per object type of the requirements' Section 2 (NFR-D55).

    python platform/frontend/fixtures/make_object_fixtures.py

Each file is one example taken from the fixtures the fixture server serves (rings/, models.json,
drift.json, r10_result.json, users.json), so the examples and the served data never disagree.
Run it after make_fixtures.py or make_drift_fixtures.py.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "objects"


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main() -> None:
    ring = json.loads((ROOT / "rings" / "1001_full-gine_causal-1-1.json").read_text(encoding="utf-8"))
    user = next(item for item in _load("users.json") if item["role"] == "analyst")
    models = _load("models.json")["1001"]
    drift = _load("drift.json")
    hourly = drift["tenant_hourly"]["tenants"][0]
    objects = {
        "Session": {"user_id": user["user_id"], "tenant_id": user["tenant_id"], "tenant_name": user["tenant_name"],
                    "role": user["role"], "token": "fixture-token-1", "expires_at": "2026-10-25T20:00:00Z"},
        "RingSummary": ring["summary"],
        "Ring": ring["detail"],
        "Subgraph": ring["subgraph"],
        "Explanation": ring["explanation"],
        "Verdict": ring["verdicts"][0],
        "ModelVersion": models["versions"][0],
        "RetrainRun": models["runs"][0],
        "DriftEvent": drift["events"]["1001"][0],
        "DriftSeries": {**{k: hourly[k] for k in ("tenant_id", "active_model_id", "active_seed", "step_seconds",
                                                   "items", "adwin", "events")},
                        "statement": drift["tenant_hourly"]["statement"], "adwin_config": drift["tenant_hourly"]["adwin"]},
        "TenantComparison": {k: v for k, v in _load("r10_result.json").items() if not k.startswith("_")},
    }
    OUT.mkdir(exist_ok=True)
    for name, value in objects.items():
        (OUT / f"{name}.json").write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(objects)} object fixtures to {OUT}")


if __name__ == "__main__":
    main()
