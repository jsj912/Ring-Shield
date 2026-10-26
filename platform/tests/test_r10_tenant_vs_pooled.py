from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters.experiment_metrics import bootstrap_ring_metrics, ring_level_summary
from experiments.r10_tenant_vs_pooled import tenant_truth_ids
from experiments.common import ExperimentInputError


def test_cross_bank_truth_ring_is_in_tenant_subset_and_pooled_finds_its_extra_recall():
    truth = {100: {11, 12}, 200: {21, 22}}
    bank_membership = {100: {210, 220}, 200: {220}}
    tenant_truth = {ring_id: truth[ring_id]
                    for ring_id in tenant_truth_ids(bank_membership, 210)}
    assert list(tenant_truth) == [100]

    tenant_metrics = ring_level_summary([], tenant_truth)
    pooled_metrics = ring_level_summary([{11, 12}], tenant_truth)
    assert tenant_metrics["ring_recall"] == 0.0
    assert pooled_metrics["ring_recall"] == 1.0
    assert pooled_metrics["ring_recall"] - tenant_metrics["ring_recall"] == 1.0


def test_r10_bootstrap_is_seeded_over_one_thousand_truth_ring_resamples():
    truth = {1: {1, 2}, 2: {3, 4}, 3: {5, 6}}
    predicted = [{1, 2}, {5}]
    first = bootstrap_ring_metrics(predicted, truth, seed=99)
    second = bootstrap_ring_metrics(predicted, truth, seed=99)
    assert first == second
    assert first["ring_recall"]["low"] <= 2 / 3 <= first["ring_recall"]["high"]


def test_r10_requires_explicit_score_source(repo_platform_config):
    from experiments.r10_tenant_vs_pooled import _candidate_seed_inputs
    from settings import load_platform_config

    config = copy.deepcopy(load_platform_config())
    config["r10"]["tenant_score_source"] = None
    with pytest.raises(ExperimentInputError, match="score source is unresolved"):
        _candidate_seed_inputs(config, [1])


def test_r10_tenant_visible_score_template_is_per_tenant(tmp_path, monkeypatch):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    monkeypatch.setattr(r10, "REPO_ROOT", tmp_path)
    gfp = tmp_path / "gfp.parquet"
    gfp.touch()
    monkeypatch.setattr(r10, "configured_path", lambda _config, _key: gfp)
    model_id, seed = "model", 3
    pooled = tmp_path / "scores" / f"pooled_{model_id}_{seed}.parquet"
    visible_template = tmp_path / "scores" / "tenant_{tenant_id}_{model_id}_{seed}.parquet"
    model_dir = tmp_path / "models" / "artifacts" / f"full_{model_id}_seed{seed}"
    embedding = tmp_path / "experiments" / f"R1_{model_id}" / f"embeddings_test_seed{seed}.parquet"
    for path in (pooled, model_dir / "model.json", embedding):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    log = {"split": "test", "model_id": model_id, "seed": seed,
           "seed_rule": {"q": 0.9}}
    Path(str(pooled) + ".log.json").write_text(json.dumps(log), encoding="utf-8")
    config = {
        "active_model_id": model_id,
        "r10": {"tenant_score_source": "tenant_visible",
                "tenant_visible_scores_template": str(visible_template),
                "pooled_scores_template": "scores/pooled_{model_id}_{seed}.parquet"},
    }

    candidate = r10._candidate_seed_inputs(config, [seed])[0]

    assert candidate["score_source"] == "tenant_visible"
    assert r10._tenant_score_path(candidate, 12) == tmp_path / "scores" / "tenant_12_model_3.parquet"
    assert candidate["pooled_scores"] == pooled


@pytest.mark.parametrize("template", [
    "scores/tenant_{tenant_id}_{seed}.parquet",
    "scores/tenant_{tenant_id}_{model_id}.parquet",
    "scores/tenant_{model_id}_{seed}.parquet",
])
def test_r10_rejects_tenant_template_missing_any_documented_placeholder(template):
    from experiments.r10_tenant_vs_pooled import _validate_visible_template

    with pytest.raises(ExperimentInputError, match="must include"):
        _validate_visible_template(template)


def test_r10_visible_test_log_must_match_requested_tenant(tmp_path):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "tenant-12.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": 3, "tenant_id": 20,
        "seed_rule": {"q": 0.9},
    }), encoding="utf-8")
    with pytest.raises(ExperimentInputError, match="tenant_id=12"):
        r10._score_log(scores, model_id="model", seed=3, tenant_id=12)


@pytest.mark.parametrize("tenant_value", ["not-a-number", None, [], {}])
def test_r10_malformed_tenant_log_id_uses_documented_input_error(tmp_path, tenant_value):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "tenant.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": 3,
        "tenant_id": tenant_value, "seed_rule": {"q": 0.9},
    }), encoding="utf-8")
    with pytest.raises(ExperimentInputError, match="integer tenant_id=12"):
        r10._score_log(scores, model_id="model", seed=3, tenant_id=12)


@pytest.mark.parametrize("tenant_value", [
    12.5, True, float("inf"), float("nan"), "12", "twelve", None,
])
def test_r10_tenant_log_id_rejects_non_integer_representations(tmp_path, tenant_value):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "tenant.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": 3,
        "tenant_id": tenant_value, "seed_rule": {"q": 0.9},
    }), encoding="utf-8")
    with pytest.raises(ExperimentInputError):
        r10._score_log(scores, model_id="model", seed=3, tenant_id=12)


@pytest.mark.parametrize("seed_value", [
    3.5, True, float("inf"), float("nan"), "3", "three", None, 0, 6,
])
def test_r10_score_log_seed_requires_documented_integer_seed(tmp_path, seed_value):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "scores.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": seed_value,
        "tenant_id": 12, "seed_rule": {"q": 0.9},
    }), encoding="utf-8")
    with pytest.raises(ExperimentInputError):
        r10._score_log(scores, model_id="model", seed=3, tenant_id=12)


@pytest.mark.parametrize("seed_value", [3.5, True, float("inf"), float("nan"), "3", 0, 6])
def test_r10_requested_seed_rejects_invalid_values_before_file_or_database_access(seed_value):
    from experiments.r10_tenant_vs_pooled import _candidate_seed_inputs

    config = {"active_model_id": "model", "r10": {"tenant_score_source": "pooled"}}
    with pytest.raises(ExperimentInputError, match="R10 seed"):
        _candidate_seed_inputs(config, [seed_value])


@pytest.mark.parametrize("cutoff", [
    float("nan"), float("inf"), float("-inf"), True, "0.9", None, -0.01, 1.01,
])
def test_r10_score_log_rejects_invalid_probability_cutoff(tmp_path, cutoff):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "scores.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": 3,
        "tenant_id": 12, "seed_rule": {"q": cutoff},
    }), encoding="utf-8")
    with pytest.raises(ExperimentInputError, match=r"finite number in \[0, 1\]"):
        r10._score_log(scores, model_id="model", seed=3, tenant_id=12)


@pytest.mark.parametrize("template", [
    "scores/{tenant_id}_{model_id}_{seed}_{bank}.parquet",
    "scores/{tenant_id}_{model_id}_{seed.parquet",
    "scores/{tenant_id}_{model_id}_{seed}}.parquet",
    "scores/{tenant_id!s}_{model_id}_{seed}.parquet",
    "scores/{tenant_id}_{model_id:>8}_{seed}.parquet",
    "scores/{tenant_id.name}_{model_id}_{seed}.parquet",
])
def test_r10_rejects_malformed_or_unsupported_template_fields(template):
    from experiments.r10_tenant_vs_pooled import _validate_visible_template

    with pytest.raises(ExperimentInputError):
        _validate_visible_template(template)


def test_r10_invalid_template_fails_before_truth_or_database_access(monkeypatch):
    import experiments.r10_tenant_vs_pooled as r10

    monkeypatch.setattr(r10, "load_platform_config", lambda: {
        "active_model_id": "model",
        "r10": {
            "tenant_score_source": "tenant_visible",
            "tenant_visible_scores_template": "scores/{tenant_id}_{model_id}_{seed}_{oops}.parquet",
        },
    })
    monkeypatch.setattr(
        r10, "_loaded_tenants",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be queried")),
    )
    with pytest.raises(ExperimentInputError, match="unsupported field"):
        r10.run_experiment(truth_path=Path("not-read.parquet"))


@pytest.mark.parametrize("cutoff", [0, 0.9, 1])
def test_r10_accepts_finite_probability_cutoff_endpoints(tmp_path, cutoff):
    import json
    import experiments.r10_tenant_vs_pooled as r10

    scores = tmp_path / "scores.parquet"
    scores.touch()
    Path(str(scores) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "model", "seed": 3,
        "tenant_id": 12, "seed_rule": {"q": cutoff},
    }), encoding="utf-8")

    log, _log_path, actual = r10._score_log(scores, model_id="model", seed=3, tenant_id=12)

    assert log["tenant_id"] == 12
    assert actual == cutoff


def test_r10_pooled_selection_uses_pooled_scores_for_every_tenant():
    from experiments.r10_tenant_vs_pooled import _tenant_score_path
    pooled = Path("pooled-test-scores.parquet")
    inputs = {"score_source": "pooled", "pooled_scores": pooled,
              "visible_scores_template": Path("tenant-{tenant_id}.parquet")}

    assert _tenant_score_path(inputs, 12) == pooled
    assert _tenant_score_path(inputs, 20) == pooled
