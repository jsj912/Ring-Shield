from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from experiments import r11_gated_retrain as r11


def test_retrained_false_report_starts_with_required_no_claim_disclaimer():
    rows = [{"retrained_false_count": 0}, {"retrained_false_count": 1}]
    assert r11.retrained_false_disclaimer(rows) == (
        "Retraining was not real in this run; no improvement is claimed."
    )
    assert r11.retrained_false_disclaimer([{"retrained_false_count": 0}]) == ""


@pytest.mark.parametrize("accuracy", [0.90, 0.70])
def test_r11_runs_ten_test_window_simulator_and_retrain_cycles_with_static_control(
        monkeypatch, tmp_path, accuracy):
    paths = {}
    for key in ("holdout_manifest", "holdout_sha256_file", "val_scored_edges",
                "val_gfp", "val_embeddings", "truth_parquet"):
        path = tmp_path / key
        path.write_text(key, encoding="utf-8")
        paths[key] = path
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.json").write_text("{}", encoding="utf-8")
    paths["base_model_dir"] = model_dir
    config_path = tmp_path / "config.yaml"
    config_path.write_text("config: test\n", encoding="utf-8")
    config = {"_path": config_path, "active_model_id": "fixture", "active_seed": 1}
    l6 = {"paths": paths, "simulator": {"seed": 3, "review_fraction": 0.05,
          "match_jaccard": 0.5, "full_confirm_jaccard": 0.9},
          "retrain": {"components": ["expansion", "affinity"]}}
    monkeypatch.setattr(r11, "load_platform_config", lambda: config)
    monkeypatch.setattr(r11, "load_l6_config", lambda _config: l6)
    monkeypatch.setattr(r11, "_validate_inputs", lambda _l6, _config: paths)
    monkeypatch.setattr(r11, "load_window_truth", lambda *args, **kwargs: {1: frozenset({1, 2})})
    monkeypatch.setattr(r11, "_tenant_actor", lambda tenant: SimpleNamespace(tenant_id=tenant))
    monkeypatch.setattr(r11, "_baseline_f1", lambda *_args: 0.74)
    monkeypatch.setattr(r11, "REPO_ROOT", tmp_path)

    class FakeDB:
        def add(self, _row): pass

    @contextmanager
    def fake_db_session(*, tenant_id=None, role=None):
        assert tenant_id == 210
        assert role == "supervisor"
        yield FakeDB()

    monkeypatch.setattr(r11, "db_session", fake_db_session)
    snapshot_counter = {"count": 0}

    def snapshot(_tenant):
        snapshot_counter["count"] += 1
        if snapshot_counter["count"] % 2:
            return {}
        return {snapshot_counter["count"]: SimpleNamespace(
            promoted=False, gate_reason="train CLI reported retrained=false; candidate identical",
            holdout_ring_f1=None, component="expansion",
        )}

    calls = []
    monkeypatch.setattr(r11, "_version_snapshot", snapshot)
    monkeypatch.setattr(r11, "_run_status", lambda *_args: "succeeded")

    def simulate(**kwargs):
        calls.append(("simulate", kwargs["cycle_day"], kwargs["accuracy"], kwargs["truth_window"]))
        return {"open_rings": 4, "simulated": 1}

    monkeypatch.setattr(r11, "simulate_cycle", simulate)

    def retrain(tenant, run_id):
        calls.append(("retrain", tenant, run_id))

    monkeypatch.setattr(r11, "run_retrain_job", retrain)
    result = r11.run_experiment(tenant_id=210, accuracy=accuracy)
    assert result["retrained_false"] is True
    assert result["disclaimer"] == "Retraining was not real in this run; no improvement is claimed."
    assert sum(call[0] == "simulate" for call in calls) == 10
    assert sum(call[0] == "retrain" for call in calls) == 10
    assert [call[1] for call in calls if call[0] == "simulate"] == list(range(8, 18))
    assert all(call[3] == "whole" for call in calls if call[0] == "simulate")
    assert Path(result["markdown"]).read_text(encoding="utf-8").startswith(result["disclaimer"])
