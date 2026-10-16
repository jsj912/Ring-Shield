"""Load deployment settings shared by platform jobs and API handlers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.yaml"


@lru_cache(maxsize=4)
def load_platform_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.environ.get("RINGSHIELD_PLATFORM_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
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
    if "seed_score_cutoff" in config:
        cutoff = config["seed_score_cutoff"]
        if not isinstance(cutoff, (int, float)) or not 0 <= float(cutoff) <= 1:
            raise RuntimeError("seed_score_cutoff must be a score in [0, 1]")
        if not config.get("seed_score_cutoff_source"):
            raise RuntimeError("seed_score_cutoff_source is required with seed_score_cutoff")
    config["_path"] = config_path
    return config


def configured_path(config: dict[str, Any], key: str) -> Path:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"platform config requires {key}")
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path
