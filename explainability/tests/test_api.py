"""Week 5 (XR-33 / XR-34): the endpoint shapes, the functions behind them, and the four endpoints on stub data."""
from __future__ import annotations

import json

import pytest

from explainability.api import ExplanationService, InvalidEdit, RingNotFound
from explainability.api_schemas import (MODELS, SCHEMA_DIR, ErrorBody, EvidenceAccount, EvidenceEdge, Explanation,
                                        RegenerateRequest, schema_text)
from explainability.contract_io import load_config, repo_path

CFG = load_config()
STUB = {"scores": CFG["inputs"]["scored_edges"].format(seed=1), "rings": "contract/out/rings_stub_cc.parquet",
        "explanations": "results/xai/explanations_week3_stub_cc_seed1.parquet"}
FILES = [(CFG["inputs"]["scored_edges"].format(seed=s), CFG["inputs"]["rings"].format(seed=s),
          f"results/xai/{CFG['explanations_name_week3'].format(seed=s)}") for s in CFG["inputs"]["seeds"]] + \
        [(STUB["scores"], STUB["rings"], STUB["explanations"])]
GROUND_TRUTH_KEYS = {"pattern_type", "is_laundering", "Is Laundering", "truth_ring_id", "truth_ring", "true_type",
                     "account_number", "Account Number"}           # and no real account numbers (only internal ids)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


# ----------------------------------------------------------------------------- W5-5 schemas
def test_exported_json_schemas_equal_the_models():
    """explainability/schemas/*.schema.json are what the models generate (run `python -m explainability.api_schemas`
    after changing a model): the platform engineer's copy can never silently drift."""
    for m in MODELS:
        p = SCHEMA_DIR / f"{m.__name__}.schema.json"
        assert p.exists(), p.name
        assert p.read_text(encoding="utf-8") == schema_text(m), p.name
    roles = json.loads((SCHEMA_DIR / "Explanation.schema.json").read_text())["$defs"]["AccountWeight"]["properties"]["role"]
    assert "undetermined" in roles["enum"]


@pytest.mark.parametrize("scores, rings, expl", FILES)
def test_every_real_explanation_fits_the_schemas(scores, rings, expl):
    """All three endpoint shapes are built and validated for every ring of all six Week 3 files; nothing in them is
    ground truth; the evidence edges are exactly the explanation's, in its order."""
    svc = ExplanationService(CFG, scores=scores, rings=rings, explanations=expl)
    for rid in svc.rows:
        tenant = int(svc.rings.at[rid, "tenant_id"])
        e = svc.get_explanation(tenant, rid)
        edges = svc.get_evidence_edges(tenant, rid)
        accounts = svc.get_evidence_accounts(tenant, rid)
        assert [x.edge_id for x in edges] == [w.edge_id for w in e.edge_weights]
        assert {a.account_id for a in accounts} == {a.account_id for a in e.account_weights}
        assert all(a.bank_name for a in accounts) and all(x.payment_format_name for x in edges)
        payload = [e.model_dump(mode="json"), [x.model_dump(mode="json") for x in edges],
                   [a.model_dump(mode="json") for a in accounts]]
        assert not GROUND_TRUTH_KEYS & set(_keys(payload)), rid


# ----------------------------------------------------------------------------- W5-6 the endpoints on stub data
@pytest.fixture(scope="module")
def client():
    """A minimal FastAPI app with the four routes of spec 3.3 over the stub data, as the platform will mount them."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    svc = ExplanationService(CFG, **STUB)
    app = FastAPI()

    @app.exception_handler(RingNotFound)
    def _nf(_, exc):
        return JSONResponse(status_code=404, content=ErrorBody(code="not_found", message="ring not found").model_dump())

    @app.exception_handler(InvalidEdit)
    def _ie(_, exc):
        return JSONResponse(status_code=422, content=ErrorBody(code="invalid_edit", message=str(exc)).model_dump())

    @app.get("/tenants/{t}/rings/{r}/explanation", response_model=Explanation)
    def explanation(t: int, r: str):
        return svc.get_explanation(t, r)

    @app.get("/tenants/{t}/rings/{r}/evidence/edges", response_model=list[EvidenceEdge])
    def edges(t: int, r: str):
        return svc.get_evidence_edges(t, r)

    @app.get("/tenants/{t}/rings/{r}/evidence/accounts", response_model=list[EvidenceAccount])
    def accounts(t: int, r: str):
        return svc.get_evidence_accounts(t, r)

    @app.post("/tenants/{t}/rings/{r}/explanation/regenerate", response_model=Explanation)
    def regenerate(t: int, r: str, req: RegenerateRequest):
        return svc.regenerate(t, r, req)

    big = max(svc.rows, key=lambda rid: len(svc.rows[rid]["account_weights"]))
    return TestClient(app), svc, big, int(svc.rings.at[big, "tenant_id"])


def test_the_three_get_endpoints_return_200_on_stub_data(client):
    c, svc, rid, t = client
    for path in ("explanation", "evidence/edges", "evidence/accounts"):
        r = c.get(f"/tenants/{t}/rings/{rid}/{path}")
        assert r.status_code == 200, path
    body = c.get(f"/tenants/{t}/rings/{rid}/explanation").json()
    assert body["ring_id"] == rid and body["narrative"] and body["explainer_version"] == CFG["explainer_version"]


def test_unknown_ring_and_other_tenants_ring_look_the_same(client):
    c, svc, rid, t = client
    a = c.get(f"/tenants/{t}/rings/no-such-ring/explanation")
    b = c.get(f"/tenants/{t + 1}/rings/{rid}/explanation")
    assert a.status_code == b.status_code == 404 and a.json() == b.json()


def test_regenerate_after_removing_a_member_changes_the_weights(client):
    """XR-34: remove one account; it and its transactions disappear, the weights change, the edit is recorded."""
    c, svc, rid, t = client
    before = svc.get_explanation(t, rid)
    gone = max(a.account_id for a in before.account_weights if a.role == "sink")
    r = c.post(f"/tenants/{t}/rings/{rid}/explanation/regenerate", json={"remove_accounts": [gone], "note": "not part of it"})
    assert r.status_code == 200
    after = r.json()
    assert gone not in {a["account_id"] for a in after["account_weights"]}
    touching = {int(e) for e in svc.se.index[(svc.se["from_id"] == gone) | (svc.se["to_id"] == gone)]}
    assert not touching & {w["edge_id"] for w in after["edge_weights"]}
    assert [w["w_total"] for w in after["edge_weights"]] != [w.w_total for w in before.edge_weights]
    reg = after["provenance"]["regenerated"]
    assert reg["removed_accounts"] == [gone] and reg["note"] == "not part of it"
    assert after["provenance"]["loo"]["reproduces_shipped_ring"] is False
    Explanation.model_validate(after)
    again = c.post(f"/tenants/{t}/rings/{rid}/explanation/regenerate", json={"remove_accounts": [gone], "note": "not part of it"}).json()
    for k in ("edge_weights", "account_weights", "feature_weights", "narrative"):
        assert again[k] == after[k], k                                  # deterministic apart from latency


def test_bad_regenerate_requests_are_refused(client):
    c, svc, rid, t = client
    assert c.post(f"/tenants/{t}/rings/{rid}/explanation/regenerate", json={}).status_code == 422
    r = c.post(f"/tenants/{t}/rings/{rid}/explanation/regenerate", json={"remove_accounts": [-5]})
    assert r.status_code == 422 and r.json()["code"] == "invalid_edit"
    everyone = [a.account_id for a in svc.get_explanation(t, rid).account_weights]
    assert c.post(f"/tenants/{t}/rings/{rid}/explanation/regenerate",
                  json={"remove_accounts": everyone[:-1]}).status_code == 422
    assert c.post(f"/tenants/{t + 1}/rings/{rid}/explanation/regenerate",
                  json={"remove_accounts": [everyone[0]]}).status_code == 404


def test_sample_fixtures_for_the_platform_validate():
    """explainability/schemas/examples/ (python -m explainability.api --examples): every example body is a valid
    instance of its model, from the stub data, with no ground truth and no account number."""
    from explainability.api_schemas import EvidenceAccount, EvidenceEdge
    d = SCHEMA_DIR / "examples"
    model = {"explanation.json": Explanation, "regenerate_response.json": Explanation,
             "regenerate_request.json": RegenerateRequest, "error_not_found.json": ErrorBody,
             "error_invalid_edit.json": ErrorBody}
    for name, m in model.items():
        body = json.loads((d / name).read_text(encoding="utf-8"))["body"]
        m.model_validate(body)
        assert not GROUND_TRUTH_KEYS & set(_keys(body)), name
    for name, m in (("evidence_edges.json", EvidenceEdge), ("evidence_accounts.json", EvidenceAccount)):
        body = json.loads((d / name).read_text(encoding="utf-8"))["body"]
        assert body and all(m.model_validate(x) for x in body)
    reg = json.loads((d / "regenerate_response.json").read_text(encoding="utf-8"))["body"]
    assert reg["provenance"]["regenerated"]["removed_accounts"]
