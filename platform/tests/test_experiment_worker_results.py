from __future__ import annotations

import json
import subprocess

import pytest

from jobs import experiment_worker


def test_r10_results_are_the_registered_rows_with_only_aggregate_numbers():
    result = experiment_worker.r10_registered_results()

    assert set(result["rows"]) == {"primary", "pooled_scores", "budget_matched", "robustness"}
    primary = result["rows"]["primary"]
    assert primary["tenants"] == [1, 20, 11, 118, 12]
    assert primary["tenant"] == {"value": 0.0882, "low": 0.0314, "high": 0.1606}
    assert primary["pooled"] == {"value": 0.3588, "low": 0.2395, "high": 0.5}
    assert result["rows"]["robustness"]["tenants"] == [70, 12, 11, 1, 10]
    assert {item["row"] for item in result["per_tenant"]} == set(result["rows"])
    assert result["cross_bank_rings"] == 172 and result["n_in_scope_rings"] == 174
    text = json.dumps(result)
    for private in ("ring_id", "account", "pattern", "bounds"):
        assert private not in text


def test_r10_results_reject_a_non_finite_metric(tmp_path):
    payload = json.loads(experiment_worker.R10_RESULT.read_text(encoding="utf-8"))
    payload["rows"]["primary"]["tenant"]["value"] = float("nan")
    path = tmp_path / "r10_registered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        experiment_worker.r10_registered_results(path)


def test_run_starts_the_registered_script_and_stores_its_result(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append(args))
    job_id = "a" * 32
    state_path = tmp_path / f"{job_id}.json"
    state_path.write_text(json.dumps({"job_id": job_id, "status": "queued"}), encoding="utf-8")
    monkeypatch.setattr(experiment_worker, "_state_path", lambda _job: state_path)

    assert experiment_worker.main(["r10", job_id]) == 0

    assert calls[0][-1].endswith("r10_registered.py")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "succeeded"
    assert state["results"]["rows"]["primary"]["n_pairs"] == 68
