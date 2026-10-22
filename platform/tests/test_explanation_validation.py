from __future__ import annotations

import copy
import json

import pytest

from jobs.explanation_validation import (
    ExplanationValidationError,
    normalize_regenerated_row,
    validate_tenant_provenance,
)


FX_HASH = "a" * 64
CONFIG = {"fx_rates_sha256": FX_HASH, "l4": {"rings_schema_version": 1}}


def _row():
    provenance = {
        "scope": "tenant", "tenant_id": 20, "feature_scope": "tenant_view",
        "fx_rates_sha256": FX_HASH, "rings_schema_version": 1,
        "explainer_version": "0.5.0-review", "regenerated": True,
        "excluded_members": [3, 2], "excluded_edges": [9],
    }
    return {
        "tenant_id": 20, "ring_id": "repeat-ring", "explainer_version": "0.5.0-review",
        "edge_weights": [{"edge_id": 11, "weight": 0.5}],
        "account_weights": [{"account_id": 2, "weight": 1.0}],
        "feature_weights": [], "narrative": "Corrected ring explanation",
        "evidence_summary": json.dumps({"template": "cycle"}), "latency_ms": 10,
        "provenance": json.dumps(provenance),
    }


def _validate(row):
    return normalize_regenerated_row(
        row, tenant_id=20, ring_id="repeat-ring", excluded_members=[2, 3],
        excluded_edges=[9], config=CONFIG,
    )


def test_regenerated_row_parses_json_strings_and_matches_tenant_provenance():
    result = _validate(_row())
    assert result["evidence_summary"] == {"template": "cycle"}
    assert isinstance(result["provenance"], dict)
    assert result["tenant_id"] == 20
    assert result["ring_id"] == "repeat-ring"


@pytest.mark.parametrize(
    ("location", "updates", "message"),
    [
        ("row", {"tenant_id": 21}, "tenant_id"),
        ("provenance", {"scope": "pooled"}, "scope"),
        ("provenance", {"feature_scope": "global"}, "feature_scope"),
        ("provenance", {"fx_rates_sha256": "b" * 64}, "fx_rates_sha256"),
        ("provenance", {"regenerated": False}, "regenerated"),
        ("provenance", {"excluded_members": [8]}, "excluded_members"),
        ("provenance", {"excluded_members": [3.5, 2]}, "excluded_members"),
        ("provenance", {"excluded_edges": [True, 9]}, "excluded_edges"),
        ("provenance", {"excluded_edges": [10]}, "excluded_edges"),
        ("provenance", {"rings_schema_version": 2}, "rings_schema_version"),
        ("row", {"narrative": " "}, "narrative"),
        ("row", {"edge_weights": [{"weight": float("nan")}]}, "non-finite"),
    ],
)
def test_regenerated_row_refuses_invalid_provenance_and_values(location, updates, message):
    row = copy.deepcopy(_row())
    if location == "row":
        row.update(updates)
    else:
        provenance = json.loads(row["provenance"])
        provenance.update(updates)
        row["provenance"] = json.dumps(provenance)
    with pytest.raises(ExplanationValidationError, match=message):
        _validate(row)


def test_shared_tenant_check_keeps_loader_contract():
    validate_tenant_provenance(
        {"scope": "tenant", "tenant_id": 20, "feature_scope": "tenant_view",
         "fx_rates_sha256": FX_HASH, "rings_schema_version": 1,
         "explainer_version": "0.5.0-review"},
        tenant_id=20, explainer_version="0.5.0-review", fx_hash=FX_HASH,
        rings_schema_version=1,
    )
