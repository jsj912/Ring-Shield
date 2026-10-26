"""Run-local provenance linking promoted versions to their training and ring artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class PromotionArtifactError(ValueError):
    """A retrain run's promotion artifacts are missing or inconsistent."""


MANIFEST_NAME = "promotion-manifest.json"


def manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / MANIFEST_NAME


def write_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    path = manifest_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)
    return path


def read_manifest(run_dir: Path, *, tenant_id: int, run_id: str) -> dict[str, Any]:
    path = manifest_path(run_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionArtifactError("R12 promotion manifest is missing or invalid") from exc
    if (payload.get("tenant_id") != int(tenant_id) or payload.get("run_id") != run_id
            or payload.get("status") != "succeeded"
            or not isinstance(payload.get("promotions"), list)):
        raise PromotionArtifactError("R12 promotion manifest does not match the successful tenant run")
    for item in payload["promotions"]:
        if (not isinstance(item, dict) or not item.get("component")
                or item.get("model_version_id") is None
                or not isinstance(item.get("training_ring_ids"), list)
                or not item.get("rings_path")):
            raise PromotionArtifactError("R12 promotion manifest has an incomplete promoted-version entry")
        rings_path = Path(item["rings_path"])
        if not rings_path.is_file():
            raise PromotionArtifactError(
                f"promoted model version {item['model_version_id']} refreshed rings are missing"
            )
    return payload
