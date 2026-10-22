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
    params = {"seed_frac_pct": float(chosen["seed_frac_pct"]), "min_size": int(chosen["min_size"]),
              "max_gap_hours": chosen.get("max_gap_hours")}
    extra = {"val_ring_f1_at_chosen": chosen.get("val_ring_f1"), "scope": cfg.get("scope"),
             "eval_window": cfg.get("eval_windows", {}).get("primary")}
    if cfg["aggregator"] == "expand":
        # Step 6.4: the expansion operating point plus the policy itself (policy/ next to model.json);
        # `python -m ringshield run --aggregator expand` needs --gfp and (for the cosine features) --embeddings
        import shutil
        params.update({"delta_t_h": float(chosen["delta_t_h"]), "p_min": float(chosen["p_min"]),
                       "max_hops": int(cfg["candidate_definition"]["max_hops"]),
                       "max_events_per_query": int(cfg["candidate_definition"]["max_events_per_query"]),
                       "policy_kind": cfg["policy_kind"],
                       "head_constants": cfg.get("context", {}).get("test", {}).get("head_constants")})
        if cfg["policy_kind"] == "model":
            src = Path(cfg["method"].split("policy:", 1)[1])
            dst = Path(model_dir) / "policy"
            dst.mkdir(parents=True, exist_ok=True)
            for f in ("policy.json", "policy.txt"):
                shutil.copy(src / f, dst / f)
        extra["expansion_inputs"] = ("run needs --gfp <split GFP parquet> and --embeddings <R1 embeddings parquet of the "
                                     "same detector seed>")
    if cfg["aggregator"] == "full":
        # Step 7: expansion operating point (fixed from R3) + partition method and its val-chosen cell;
        # policy/ and affinity/ copied next to model.json
        import shutil
        cell = {k: chosen[k] for k in ("gap_h", "resolution", "cut", "threshold") if k in chosen}
        params.update({"delta_t_h": float(chosen["delta_t_h"]), "p_min": float(chosen["p_min"]), "max_hops": 2,
                       "max_events_per_query": 500, "policy_kind": "model", "partition": chosen["method"], "partition_cell": cell,
                       "cluster_seed": int(cfg.get("cluster_seed", 0)),
                       "head_constants": cfg.get("context", {}).get("test", {}).get("head_constants")})
        src = Path(cfg["expansion_fixed"]["policy_dir"])
        dst = Path(model_dir) / "policy"
        dst.mkdir(parents=True, exist_ok=True)
        for f in ("policy.json", "policy.txt"):
            shutil.copy(src / f, dst / f)
        if cfg.get("affinity_dir"):
            src = Path(cfg["affinity_dir"])
            dst = Path(model_dir) / "affinity"
            dst.mkdir(parents=True, exist_ok=True)
            for f in ("affinity.json", "affinity.txt"):
                shutil.copy(src / f, dst / f)
        extra["expansion_inputs"] = "run needs --gfp <split GFP parquet> and --embeddings <R1 embeddings parquet of the same detector seed>"
    return write_model(model_dir, model_id=cfg.get("model_id", "unknown"), seed=int(cfg.get("seed", cfg.get("detector_seed", 0))),
                       aggregator=cfg["aggregator"], params=params, feature_set=cfg.get("feature_set", "trailing_closescycle"),
                       source=f"{run_dir.as_posix()} (ringshield/run_rings.py config.yaml, chosen on val)",
                       version=version, extra=extra)
