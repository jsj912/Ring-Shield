from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

import httpx

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from adapters import xai  # noqa: E402
from jobs.explanation_validation import normalize_regenerated_row  # noqa: E402
from settings import load_platform_config  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "regenerate_example_12.json"
FIXTURE_SHA256 = "1109adfc04c220923b66afe3750317676b007f9520b1b794cee94c6c5fee1d15"


def test_real_l4_example_round_trips_adapter_and_worker_validation(monkeypatch, repo_platform_config):
    example_bytes = FIXTURE.read_bytes()
    assert hashlib.sha256(example_bytes).hexdigest() == FIXTURE_SHA256
    example = json.loads(example_bytes)
    request = example["request"]
    response = example["response"]
    config = copy.deepcopy(load_platform_config())
    config["l4"]["regenerate_url"] = "https://l4.example.test"
    # The pinned example is a real L4 response made on v1 (22-column) rings; the repo config is now
    # v2, so the test uses the example's own schema version.
    config["l4"]["rings_schema_version"] = json.loads(response["provenance"])["rings_schema_version"] \
        if isinstance(response.get("provenance"), str) else response["provenance"]["rings_schema_version"]
    calls = []

    def handler(http_request):
        calls.append(http_request)
        return httpx.Response(200, json=response)

    monkeypatch.setenv("RINGSHIELD_XAI_TOKEN", "real-example-test-token")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter_response = xai.regenerate(
            request["tenant_id"], request["ring_id"],
            request["excluded_members"], request["excluded_edges"],
            config=config, client=client,
        )

    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].url.path == "/regenerate"
    assert json.loads(calls[0].content) == request
    normalized = normalize_regenerated_row(
        adapter_response,
        tenant_id=request["tenant_id"],
        ring_id=request["ring_id"],
        excluded_members=request["excluded_members"],
        excluded_edges=request["excluded_edges"],
        config=config,
    )

    provenance = normalized["provenance"]
    assert provenance["fx_rates_sha256"] == config["fx_rates_sha256"]
    assert provenance["rings_schema_version"] == config["l4"]["rings_schema_version"]
    assert normalized["explainer_version"] == provenance["explainer_version"]
    assert provenance["excluded_members"] == request["excluded_members"]
    assert provenance["excluded_edges"] == request["excluded_edges"]
    assert provenance["edges_removed_with_members"] == [4973391, 4973392]
    assert isinstance(normalized["evidence_summary"], dict)
    assert isinstance(provenance, dict)
    assert adapter_response["topology_prob"] is None
    assert all(item["hold_time_s"] is None for item in normalized["account_weights"])
