"""Shared tenant explanation provenance and row validation."""

from __future__ import annotations

import math
from typing import Any


class ExplanationValidationError(ValueError):
    """A tenant explanation row failed its shared contract checks."""


def finite_json(value: Any, *, path: str = "value") -> Any:
    if value is None:
        return None
    if hasattr(value, "as_py"):
        value = value.as_py()
    if hasattr(value, "item") and not isinstance(value, (str, bytes, list, tuple, dict)):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ExplanationValidationError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, dict):
        return {str(key): finite_json(item, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def validate_tenant_provenance(
    provenance: dict[str, Any], *, tenant_id: int, explainer_version: str,
    fx_hash: str, rings_schema_version: int, regenerated: bool | None = None,
    excluded_members: list[int] | None = None, excluded_edges: list[int] | None = None,
) -> None:
    if provenance.get("scope") != "tenant":
        raise ExplanationValidationError("row provenance scope must be tenant")
    provenance_tenant_id = provenance.get("tenant_id")
    if (not isinstance(provenance_tenant_id, int)
            or isinstance(provenance_tenant_id, bool)
            or provenance_tenant_id != int(tenant_id)):
        raise ExplanationValidationError("row tenant_id does not match L4 log tenant")
    if provenance.get("feature_scope") != "tenant_view":
        raise ExplanationValidationError("row feature_scope must be tenant_view")
    if provenance.get("fx_rates_sha256") != fx_hash:
        raise ExplanationValidationError("row fx_rates_sha256 does not match platform config")
    actual_schema_version = provenance.get("rings_schema_version")
    if (not isinstance(actual_schema_version, int) or isinstance(actual_schema_version, bool)
            or actual_schema_version != rings_schema_version):
        raise ExplanationValidationError("row rings_schema_version does not match platform config")
    if provenance.get("explainer_version") != explainer_version:
        raise ExplanationValidationError("row explainer_version does not match result")
    if regenerated is not None:
        if provenance.get("regenerated") is not regenerated:
            raise ExplanationValidationError("row provenance regenerated flag is invalid")
        for field, expected in (("excluded_members", excluded_members),
                                ("excluded_edges", excluded_edges)):
            actual = provenance.get(field)
            matches = (
                isinstance(actual, list)
                and all(isinstance(value, int) and not isinstance(value, bool) for value in actual)
                and sorted(set(actual)) == sorted(set(expected or []))
            )
            if not matches:
                raise ExplanationValidationError(f"row provenance {field} does not match job")


def normalize_regenerated_row(raw: dict[str, Any], *, tenant_id: int, ring_id: str,
                              excluded_members: list[int], excluded_edges: list[int],
                              config: dict[str, Any]) -> dict[str, Any]:
    """Validate L4's JSON row and map JSON-string fields to database values."""
    import json

    if not isinstance(raw, dict):
        raise ExplanationValidationError("L4 result row must be an object")
    row_tenant = raw.get("tenant_id")
    if (not isinstance(row_tenant, int) or isinstance(row_tenant, bool)
            or row_tenant != tenant_id):
        raise ExplanationValidationError("row tenant_id does not match job tenant")
    if raw.get("ring_id") != ring_id:
        raise ExplanationValidationError("row ring_id does not match job")
    version = raw.get("explainer_version")
    if not isinstance(version, str) or not version.strip():
        raise ExplanationValidationError("row explainer_version is missing")
    provenance_raw = raw.get("provenance")
    evidence_raw = raw.get("evidence_summary")
    try:
        provenance = json.loads(provenance_raw) if isinstance(provenance_raw, str) else provenance_raw
        evidence = json.loads(evidence_raw) if isinstance(evidence_raw, str) else evidence_raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ExplanationValidationError("L4 JSON fields are malformed") from exc
    if not isinstance(provenance, dict) or not isinstance(evidence, dict):
        raise ExplanationValidationError("L4 provenance and evidence_summary must be JSON objects")
    fx_hash = config.get("fx_rates_sha256")
    l4 = config.get("l4") or {}
    rings_schema_version = l4.get("rings_schema_version")
    validate_tenant_provenance(
        provenance, tenant_id=tenant_id, explainer_version=version, fx_hash=fx_hash,
        rings_schema_version=rings_schema_version, regenerated=True,
        excluded_members=excluded_members, excluded_edges=excluded_edges,
    )
    narrative = raw.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        raise ExplanationValidationError("L4 narrative is missing")
    latency_value = raw.get("latency_ms")
    if (not isinstance(latency_value, int) or isinstance(latency_value, bool)
            or latency_value < 0):
        raise ExplanationValidationError("L4 latency is invalid")
    latency = latency_value
    normalized = {
        "tenant_id": tenant_id,
        "ring_id": ring_id,
        "explainer_version": version,
        "edge_weights": finite_json(raw.get("edge_weights"), path="edge_weights"),
        "account_weights": finite_json(raw.get("account_weights"), path="account_weights"),
        "feature_weights": finite_json(raw.get("feature_weights"), path="feature_weights"),
        "narrative": narrative,
        "evidence_summary": finite_json(evidence, path="evidence_summary"),
        "latency_ms": latency,
        "provenance": finite_json(provenance, path="provenance"),
        "fx_rates_sha256": fx_hash,
    }
    if not all(isinstance(normalized[name], list)
               for name in ("edge_weights", "account_weights", "feature_weights")):
        raise ExplanationValidationError("L4 weight columns must be arrays")
    for field, id_key in (("edge_weights", "edge_id"), ("account_weights", "account_id")):
        for item in normalized[field]:
            if (not isinstance(item, dict) or not isinstance(item.get(id_key), int)
                    or isinstance(item.get(id_key), bool)):
                raise ExplanationValidationError(f"L4 {field} contains an invalid identifier")
    for item in normalized["feature_weights"]:
        if not isinstance(item, dict):
            raise ExplanationValidationError("L4 feature_weights contains an invalid entry")
    return normalized
