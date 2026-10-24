"""Typed subprocess boundary for the research CLI.

Research libraries remain out of the platform process; only JSON/parquet files
cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


class ResearchCLIError(RuntimeError):
    """The research CLI failed or produced an invalid result artifact."""


@dataclass(frozen=True)
class RingRunResult:
    rings_path: Path
    run_log: dict[str, Any]
    ring_count: int


@dataclass(frozen=True)
class TrainResult:
    model_dir: Path
    version: dict[str, Any]
    retrained: bool


@dataclass(frozen=True)
class EvalResult:
    metrics_path: Path
    metrics: dict[str, Any]
    ring_f1: float


def _run(command: list[str], *, operation: str) -> None:
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ResearchCLIError(f"could not start research CLI for {operation}: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise ResearchCLIError(f"research CLI {operation} failed (exit {result.returncode}): {detail}")


def _read_json(path: Path, *, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchCLIError(f"research CLI did not produce valid {description} JSON") from exc
    if not isinstance(value, dict):
        raise ResearchCLIError(f"research CLI {description} must be a JSON object")
    return value


def run_rings(*, scores: Path, model_dir: Path, aggregator: str = "full",
              gfp: Path | None = None, embeddings: Path | None = None,
              out: Path, edge_subset: Path | None = None, tenant_id: int | None = None) -> RingRunResult:
    if tenant_id is not None and edge_subset is None:
        raise ValueError("tenant-scoped run requires an edge_subset")
    out = Path(out)
    command = [sys.executable, "-m", "ringshield", "run", "--scores", str(scores),
               "--model-dir", str(model_dir), "--aggregator", aggregator, "--out", str(out)]
    if gfp is not None:
        command.extend(("--gfp", str(gfp)))
    if embeddings is not None:
        command.extend(("--embeddings", str(embeddings)))
    if edge_subset is not None:
        command.extend(("--edge-subset", str(edge_subset)))
    if tenant_id is not None:
        command.extend(("--tenant-id", str(tenant_id)))
    _run(command, operation="run")
    log = _read_json(Path(str(out) + ".log.json"), description="run log")
    if log.get("command") != "run" or not isinstance(log.get("n_rings"), int):
        raise ResearchCLIError("research CLI run log is missing command or n_rings")
    if not out.is_file():
        raise ResearchCLIError("research CLI reported success but the rings parquet is missing")
    return RingRunResult(rings_path=out, run_log=log, ring_count=log["n_rings"])


def train(*, component: str, labels: Path, base_dir: Path, out_dir: Path) -> TrainResult:
    if component not in {"expansion", "affinity", "typing"}:
        raise ValueError("component must be expansion, affinity, or typing")
    _run([sys.executable, "-m", "ringshield", "train", "--component", component,
          "--labels", str(labels), "--base-model-dir", str(base_dir), "--out-model-dir", str(out_dir)],
         operation="train")
    version = _read_json(Path(out_dir) / "version.json", description="train version")
    retrained = version.get("retrained")
    if not isinstance(retrained, bool):
        raise ResearchCLIError("research train version.json must contain boolean retrained")
    return TrainResult(model_dir=Path(out_dir), version=version, retrained=retrained)


def eval_rings(*, rings: Path, truth: Path, holdout: Path, window: str,
               scope: str, out: Path) -> EvalResult:
    out = Path(out)
    _run([sys.executable, "-m", "ringshield", "eval", "--rings", str(rings),
          "--truth", str(truth), "--holdout", str(holdout), "--window", window,
          "--scope", scope, "--out", str(out)], operation="eval")
    metrics = _read_json(out, description="evaluation metrics")
    score = metrics.get("ring_f1")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 1:
        raise ResearchCLIError("research evaluation metrics must contain ring_f1 in [0, 1]")
    return EvalResult(metrics_path=out, metrics=metrics, ring_f1=float(score))
