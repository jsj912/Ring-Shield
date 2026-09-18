"""Model directories for the research CLI (Step 5).

A "model" for the ring side is the aggregator plus its validation-chosen parameters, the id
and training seed of the edge scorer whose scores it expects, and a version. It lives in a
directory with `model.json` (this file's schema); Steps 6-8 add learned components (expansion
policy, affinity, typing head) as further files next to it, behind the same layout.

    model.json
    {
      "model_id": "gfpxgb",            # edge scorer id -> ring_id prefix and scored_edges.model_id
      "seed": 1,                        # edge scorer training seed
      "aggregator": "cc",               # cc | expand | full
      "params": {"seed_frac_pct": 0.1, "min_size": 3, "max_gap_hours": null},
      "feature_set": "trailing_closescycle",
      "threshold_rule": "configs/threshold_rule.yaml (strict quantile on score_raw)",
      "source": "experiments/R2_b0/gfpxgb/seed1 (ringshield/run_rings.py config.yaml)",
      "version": 1, "created_utc": "...", "git_commit": "..."
    }

`from_run_dir` builds one from a ringshield/run_rings.py output directory (chosen cell).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = "model.json"
AGGREGATORS = ("cc", "expand", "full")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def write_model(model_dir: Path, *, model_id: str, seed: int, aggregator: str, params: dict, feature_set: str,
                source: str, version: int = 1, extra: dict | None = None) -> Path:
    assert aggregator in AGGREGATORS, aggregator
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    doc = {"model_id": str(model_id), "seed": int(seed), "aggregator": aggregator, "params": dict(params),
           "feature_set": feature_set, "threshold_rule": "configs/threshold_rule.yaml (strict quantile on score_raw)",
           "source": source, "version": int(version),
           "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           **(extra or {})}
    (model_dir / MODEL_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return model_dir / MODEL_FILE


def read_model(model_dir: Path) -> dict:
    p = Path(model_dir) / MODEL_FILE
    if not p.exists():
        raise FileNotFoundError(f"{p} not found: not a ringshield model directory (see ringshield/model_dir.py)")
    doc = json.loads(p.read_text(encoding="utf-8"))
    for k in ("model_id", "seed", "aggregator", "params"):
        if k not in doc:
            raise ValueError(f"{p}: missing '{k}'")
    if doc["aggregator"] not in AGGREGATORS:
        raise ValueError(f"{p}: unknown aggregator {doc['aggregator']!r}")
    for k in ("seed_frac_pct", "min_size"):
        if k not in doc["params"]:
            raise ValueError(f"{p}: params.{k} missing")
    return doc


def from_run_dir(run_dir: Path, model_dir: Path, version: int = 1) -> Path:
    """Model dir from a ringshield/run_rings.py output (its config.yaml holds the chosen cell)."""
    run_dir = Path(run_dir)
    cfg = yaml.safe_load((run_dir / "config.yaml").read_text(encoding="utf-8"))
    chosen = cfg["chosen"]
    return write_model(model_dir, model_id=cfg.get("model_id", "unknown"), seed=int(cfg.get("seed", 0)),
                       aggregator=cfg["aggregator"],
                       params={"seed_frac_pct": float(chosen["seed_frac_pct"]), "min_size": int(chosen["min_size"]),
                               "max_gap_hours": chosen.get("max_gap_hours")},
                       feature_set=cfg.get("feature_set", "unknown"),
                       source=f"{run_dir.as_posix()} (ringshield/run_rings.py config.yaml, chosen on val)",
                       version=version,
                       extra={"val_ring_f1_at_chosen": chosen.get("val_ring_f1"), "scope": cfg.get("scope"),
                              "eval_window": cfg.get("eval_windows", {}).get("primary")})
