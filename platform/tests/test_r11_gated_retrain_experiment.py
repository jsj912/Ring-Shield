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


def test_r11_cycles_tile_the_primary_window_in_four_hour_slices():
    intervals = r11.cycle_intervals()
    assert len(intervals) == 12
    assert all(end - start == 4 * 3_600 for start, end in intervals)
    assert all(left[1] == right[0] for left, right in zip(intervals, intervals[1:]))
    # Test day 8 starts at loader second 10 + 8 * 86,400; nothing before it is replayed.
    assert intervals[0][0] == 10 + 8 * 86_400
    assert intervals[-1][1] == 10 + 10 * 86_400


@pytest.mark.parametrize("accuracy", [0.90, 0.70])
def test_r11_runs_twelve_primary_window_cycles_and_one_retrain_after_cycle_six(
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
    retrained = {"done": False}

    def snapshot(_tenant):
        if not retrained["done"]:
            return {}
        return {1: SimpleNamespace(
            promoted=False, gate_reason="train CLI reported retrained=false; candidate identical",
            holdout_ring_f1=None, component="expansion",
        )}

    calls = []
    monkeypatch.setattr(r11, "_version_snapshot", snapshot)
    monkeypatch.setattr(r11, "_run_status", lambda *_args: "succeeded")

    def simulate(**kwargs):
        calls.append(("simulate", kwargs["interval"], kwargs["review_fraction"], kwargs["truth_window"]))
        return {"open_rings": 4, "simulated": 4}

    monkeypatch.setattr(r11, "simulate_cycle", simulate)

    def retrain(tenant, run_id, *, min_new_labels):
        calls.append(("retrain", tenant, run_id, min_new_labels))
        retrained["done"] = True

    monkeypatch.setattr(r11, "run_retrain_job", retrain)
    result = r11.run_experiment(tenant_id=210, accuracy=accuracy)
    assert result["retrained_false"] is True
    assert result["disclaimer"] == "Retraining was not real in this run; no improvement is claimed."
    simulated = [call for call in calls if call[0] == "simulate"]
    assert [call[1] for call in simulated] == r11.cycle_intervals()
    assert all(call[2] == 1.0 and call[3] == "primary" for call in simulated)
    # Exactly one retrain, between cycle 6 and cycle 7, with no minimum label count.
    order = [call[0] for call in calls]
    assert order.count("retrain") == 1
    assert order.index("retrain") == 6
    assert [call[3] for call in calls if call[0] == "retrain"] == [1]
    assert Path(result["markdown"]).read_text(encoding="utf-8").startswith(result["disclaimer"])
