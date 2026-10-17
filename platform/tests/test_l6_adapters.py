from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters import research_cli
from adapters.ground_truth import match_ring


def test_run_rings_returns_typed_result_from_run_log(monkeypatch, tmp_path):
    out = tmp_path / "rings.parquet"

    def fake_run(command, **kwargs):
        out.write_bytes(b"parquet fixture")
        Path(str(out) + ".log.json").write_text(json.dumps({"command": "run", "n_rings": 2}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(research_cli.subprocess, "run", fake_run)
    result = research_cli.run_rings(scores=tmp_path / "scores.parquet", model_dir=tmp_path / "model",
                                    out=out)

    assert isinstance(result, research_cli.RingRunResult)
    assert result.ring_count == 2
    assert result.rings_path == out


def test_train_result_never_infers_retraining_from_success_exit(monkeypatch, tmp_path):
    out_dir = tmp_path / "candidate"

    def fake_run(command, **kwargs):
        out_dir.mkdir()
        (out_dir / "version.json").write_text(json.dumps({"version": 2, "retrained": False}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(research_cli.subprocess, "run", fake_run)
    result = research_cli.train(component="expansion", labels=tmp_path / "labels.parquet",
                                base_dir=tmp_path / "base", out_dir=out_dir)

    assert isinstance(result, research_cli.TrainResult)
    assert result.retrained is False


def test_eval_result_requires_ring_f1_and_returns_typed_result(monkeypatch, tmp_path):
    out = tmp_path / "metrics.json"

    def fake_run(command, **kwargs):
        out.write_text(json.dumps({"ring_f1": 0.73}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(research_cli.subprocess, "run", fake_run)
    result = research_cli.eval_rings(rings=tmp_path / "rings.parquet", truth=tmp_path / "truth.parquet",
                                     holdout=tmp_path / "holdout.json", window="val",
                                     scope="test_visible", out=out)

    assert isinstance(result, research_cli.EvalResult)
    assert result.ring_f1 == pytest.approx(0.73)


def test_research_cli_nonzero_exit_has_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(research_cli.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="bad input"))

    with pytest.raises(research_cli.ResearchCLIError, match="run failed.*bad input"):
        research_cli.run_rings(scores=tmp_path / "scores.parquet", model_dir=tmp_path / "model",
                               out=tmp_path / "rings.parquet")


def test_ground_truth_match_uses_jaccard_and_corrected_members():
    truth = {"truth-a": {1, 2, 3}, "truth-b": {10, 11}}
    matched = match_ring({1, 2, 4}, truth, min_jaccard=0.5, full_confirm_jaccard=0.9)
    rejected = match_ring({100, 101}, truth, min_jaccard=0.5, full_confirm_jaccard=0.9)

    assert matched.verdict == "partial"
    assert matched.ring_id == "truth-a"
    assert matched.members == frozenset({1, 2, 3})
    assert matched.jaccard == pytest.approx(0.5)
    assert rejected.verdict == "reject"
    assert rejected.ring_id is None
