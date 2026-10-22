"""Week 9: the regeneration service for the platform (python -m explainability.serve), on the real bank 12 inputs.

The platform's validator (platform/jobs/explanation_validation.py on origin/kashish) is not imported -- research code
never imports platform code -- so its rules are restated here and checked on a real response."""
from __future__ import annotations

import io
import json
import math
import secrets
import threading

import httpx
import pytest

from explainability.contract_io import load_config, repo_path

CFG = load_config()
BANK = 12
TOKEN = secrets.token_urlsafe(24)
EXAMPLE = repo_path("results/xai/tenant/regenerate_example_12.json")


@pytest.fixture(scope="module")
def service():
    from explainability.serve import make_server
    from explainability.tenant import TenantExplainer
    te = TenantExplainer(CFG, BANK)
    log = io.StringIO()
    server = make_server({BANK: te}, TOKEN, 0, CFG["explainer_version"], log=log)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}", timeout=120) as client:
        yield client, te, log
    server.shutdown()
    server.server_close()


def _post(client, body, token=TOKEN):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post("/regenerate", json=body, headers=headers)


def _ring(te):
    return te.rings.loc[json.loads(EXAMPLE.read_text(encoding="utf-8"))["request"]["ring_id"]]


def _finite(x) -> bool:
    if isinstance(x, float):
        return math.isfinite(x)
    if isinstance(x, dict):
        return all(_finite(v) for v in x.values())
    if isinstance(x, list):
        return all(_finite(v) for v in x)
    return True


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def platform_rules(row: dict, req: dict) -> None:
    """The checks the platform runs on every regenerated row (normalize_regenerated_row + validate_tenant_provenance)."""
    assert _is_int(row["tenant_id"]) and row["tenant_id"] == req["tenant_id"] and row["ring_id"] == req["ring_id"]
    version = row["explainer_version"]
    assert isinstance(version, str) and version.strip()
    prov, ev = json.loads(row["provenance"]), json.loads(row["evidence_summary"])     # JSON strings -> objects
    assert isinstance(prov, dict) and isinstance(ev, dict)
    assert prov["scope"] == "tenant" and _is_int(prov["tenant_id"]) and prov["tenant_id"] == req["tenant_id"]
    assert prov["feature_scope"] == "tenant_view"
    assert prov["fx_rates_sha256"] == "ee0e8a23b6037e4aeceb44b6874a70d7b46114559551fd2cf94a3842bb8d4ac6"
    assert _is_int(prov["rings_schema_version"]) and prov["rings_schema_version"] == 1
    assert prov["explainer_version"] == version == CFG["explainer_version"]
    assert prov["regenerated"] is True
    for k in ("excluded_members", "excluded_edges"):
        assert all(_is_int(v) for v in prov[k]) and sorted(set(prov[k])) == sorted(set(req[k]))
    assert isinstance(row["narrative"], str) and row["narrative"].strip()
    assert _is_int(row["latency_ms"]) and row["latency_ms"] >= 0
    for field, key in (("edge_weights", "edge_id"), ("account_weights", "account_id")):
        assert isinstance(row[field], list) and all(isinstance(i, dict) and _is_int(i[key]) for i in row[field])
    assert isinstance(row["feature_weights"], list) and all(isinstance(i, dict) for i in row["feature_weights"])
    assert _finite(row) and _finite(prov) and _finite(ev)


def test_health_needs_no_token_and_lists_the_ready_tenants(service):
    client, _, _ = service
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "tenants_ready": [BANK], "explainer_version": CFG["explainer_version"]}
    assert client.get("/other").status_code == 404


def test_regenerate_refuses_a_missing_or_wrong_token(service):
    client, te, _ = service
    body = {"tenant_id": BANK, "ring_id": te.rings.index[0], "excluded_members": [], "excluded_edges": [1]}
    for token in (None, "wrong", TOKEN + "x"):
        r = _post(client, body, token)
        assert r.status_code == 401 and r.json() == {"error": "Unauthorized"}
    r = client.post("/regenerate", json=body, headers={"Authorization": TOKEN})          # no "Bearer " prefix
    assert r.status_code == 401


def test_the_contract_errors(service):
    client, te, _ = service
    ring = _ring(te)
    rid, members = ring["ring_id"], sorted(int(a) for a in ring["members"])
    base = {"tenant_id": BANK, "ring_id": rid, "excluded_members": [], "excluded_edges": []}
    for body in ({**base, "ring_id": "no-such-ring", "excluded_members": members[:1]},
                 {**base, "tenant_id": 20, "excluded_members": members[:1]}):          # a tenant not served here
        r = _post(client, body)
        assert r.status_code == 404 and r.json() == {"error": "RingNotFound"}
    all_edges = sorted({int(e) for e in ring["member_edges"]})
    for body in (base,                                                                 # nothing excluded
                 {**base, "excluded_members": [999_999_999]},                          # not in the ring
                 {**base, "excluded_members": members[:-1]},                           # fewer than two accounts
                 {**base, "excluded_edges": all_edges}):                               # no seed / expanded edge
        r = _post(client, body)
        assert r.status_code == 422, body
        assert r.json()["error"] == "InvalidEdit" and r.json()["message"]
    for raw in (b"not json", b"[]", json.dumps({**base, "tenant_id": True}).encode(),
                json.dumps({**base, "excluded_members": "1"}).encode(),
                json.dumps({**base, "excluded_members": [1.5]}).encode()):
        r = client.post("/regenerate", content=raw, headers={"Authorization": f"Bearer {TOKEN}",
                                                             "Content-Type": "application/json"})
        assert r.status_code == 400 and r.json()["error"] == "BadRequest"


def test_a_real_regenerate_passes_the_platform_rules_and_matches_the_pinned_example(service):
    client, _, _ = service
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    r = _post(client, example["request"])
    assert r.status_code == 200
    row = r.json()
    platform_rules(row, example["request"])
    assert set(row) == set(example["response"])
    assert {k: v for k, v in row.items() if k != "latency_ms"} == \
           {k: v for k, v in example["response"].items() if k != "latency_ms"}
    assert json.loads(row["provenance"])["edges_removed_with_members"]                 # the member's edges went too


def test_the_log_holds_no_token_and_no_explanation_text(service):
    client, _, log = service
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    row = _post(client, example["request"]).json()
    _post(client, example["request"], "wrong")
    text = log.getvalue()
    assert TOKEN not in text and "wrong" not in text
    assert row["narrative"] not in text and example["request"]["ring_id"] not in text
    assert "POST /regenerate 200" in text and "POST /regenerate 401" in text


def test_the_command_refuses_to_start_without_a_token_or_from_another_folder(monkeypatch, tmp_path, capsys):
    from explainability import serve
    monkeypatch.delenv(serve.TOKEN_ENV, raising=False)
    assert serve.main(["--tenants", "12", "--data-root", str(repo_path("."))]) == 2
    assert "refusing to start" in capsys.readouterr().err
    monkeypatch.setenv(serve.TOKEN_ENV, TOKEN)
    with pytest.raises(SystemExit, match="must be the Ring-Shield checkout"):
        serve.main(["--tenants", "12", "--data-root", str(tmp_path)])
    assert serve.main(["--tenants", "999", "--data-root", str(repo_path("."))]) == 2
    with pytest.raises(RuntimeError):
        serve.make_server({}, "")
