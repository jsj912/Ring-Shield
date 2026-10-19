"""Load deployment settings shared by platform jobs and API handlers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"


def load_platform_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.environ.get("RINGSHIELD_PLATFORM_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    return _load_platform_config(str(config_path.resolve()))


@lru_cache(maxsize=4)
def _load_platform_config(resolved_path: str) -> dict[str, Any]:
    config_path = Path(resolved_path)
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"could not load platform config: {config_path}") from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"platform config must be a YAML mapping: {config_path}")
    if not isinstance(config.get("active_model_id"), str) or not config["active_model_id"].strip():
        raise RuntimeError("platform config requires active_model_id")
    if not isinstance(config.get("active_seed"), int):
        raise RuntimeError("platform config requires integer active_seed")
    l4 = config.get("l4")
    if not isinstance(l4, dict):
        raise RuntimeError("platform config requires l4.rings_schema_version in an l4 mapping")
    rings_schema_version = l4.get("rings_schema_version")
    if (not isinstance(rings_schema_version, int) or isinstance(rings_schema_version, bool)
            or rings_schema_version not in (1, 2)):
        raise RuntimeError("platform config requires integer l4.rings_schema_version 1 or 2")
    if "seed_score_cutoff" in config:
        cutoff = config["seed_score_cutoff"]
        if not isinstance(cutoff, (int, float)) or not 0 <= float(cutoff) <= 1:
            raise RuntimeError("seed_score_cutoff must be a score in [0, 1]")
        if not config.get("seed_score_cutoff_source"):
            raise RuntimeError("seed_score_cutoff_source is required with seed_score_cutoff")
    config["_path"] = config_path
    return config


# Preserve the public cache reset hook used by tests and runtime config reloads.
load_platform_config.cache_clear = _load_platform_config.cache_clear  # type: ignore[attr-defined]


def configured_path(config: dict[str, Any], key: str) -> Path:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"platform config requires {key}")
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_l6_config(config: dict[str, Any] | None = None, *, require_retrain_paths: bool = True) -> dict[str, Any]:
    """Validate L6 settings and resolve required artifact paths without guessing."""
    root = config if config is not None else load_platform_config()
    l6 = root.get("l6")
    if not isinstance(l6, dict):
        raise RuntimeError("platform config requires an l6 mapping")
    simulator = l6.get("simulator")
    retrain = l6.get("retrain")
    drift = l6.get("drift")
    if not isinstance(simulator, dict) or not isinstance(retrain, dict) or not isinstance(drift, dict):
        raise RuntimeError("platform config l6 requires simulator, retrain, and drift mappings")

    def fraction(section: dict[str, Any], key: str) -> float:
        value = section.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RuntimeError(f"platform config requires numeric l6.{key}")
        value = float(value)
        if not 0 <= value <= 1:
            raise RuntimeError(f"l6.{key} must be in [0, 1]")
        return value

    for key in ("review_fraction", "accuracy", "match_jaccard", "full_confirm_jaccard"):
        fraction(simulator, key)
    if int(simulator.get("cycle_days", 0)) < 1:
        raise RuntimeError("l6.simulator.cycle_days must be a positive integer")
    if int(simulator.get("seed", -1)) < 0:
        raise RuntimeError("l6.simulator.seed must be a non-negative integer")
    fraction(retrain, "epsilon")
    if int(retrain.get("min_new_labels", 0)) < 1:
        raise RuntimeError("l6.retrain.min_new_labels must be a positive integer")
    if retrain.get("components") != ["expansion", "affinity"]:
        raise RuntimeError("l6.retrain.components must be [expansion, affinity]; typing has no verdict label")
    if retrain.get("eval_window") != "val" or retrain.get("eval_scope") != "test_visible":
        raise RuntimeError("L6 retraining evaluation must use window=val and scope=test_visible")
    drift_delta = drift.get("delta")
    if not isinstance(drift_delta, (int, float)) or not 0 < float(drift_delta) < 1:
        raise RuntimeError("l6.drift.delta must be in (0, 1)")

    path_keys = (
        "holdout_manifest", "holdout_sha256_file", "val_scored_edges", "val_gfp",
        "val_embeddings", "truth_parquet", "base_model_dir",
    )
    paths: dict[str, Path] = {}
    for key in path_keys:
        value = retrain.get(key)
        if not isinstance(value, str) or not value.strip():
            if not require_retrain_paths:
                continue
            raise RuntimeError(f"platform config requires l6.retrain.{key}; path is unavailable")
        path = Path(value)
        if not path.is_absolute():
            path = REPO_ROOT / path
        paths[key] = path.resolve()
    return {"simulator": simulator, "retrain": retrain, "drift": drift, "paths": paths}
