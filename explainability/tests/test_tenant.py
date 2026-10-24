"""Tenant-scoped explanations (Kashish's request): inputs verified, nothing hidden counted or mentioned, regenerate."""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from explainability.contract_io import load_config, repo_path
from explainability.tenant import GFP_COLS, adjacency, gfp_check, history, sha256, tenant_paths

CFG = load_config()
BANKS = CFG["tenants"]["banks"]
INPUTS = repo_path("results/xai/tenant/inputs")


def _visible(bank):
    se = pd.read_parquet(repo_path(CFG["inputs"]["scored_edges"].format(seed=CFG["tenants"]["seed"])),
                         columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank"])
    return se[(se.from_bank == bank) | (se.to_bank == bank)]


# ----------------------------------------------------------------------------- T-1: the research GFP, reproduced
def test_fast_history_index_equals_the_research_one():
    from graph.motif_features import build_adjacency
    h = pd.read_parquet(repo_path("data/processed/amlworld_test.parquet"), columns=["from_id", "to_id", "Timestamp"]).iloc[:30000]
    a, b = adjacency(h), build_adjacency(h)
    assert a[0] == b[0] and a[1] == b[1]
    for i in (2, 3):
        assert set(a[i]) == set(b[i]) and all(np.array_equal(a[i][k], b[i][k]) for k in b[i])


def test_research_gfp_is_reproduced_exactly_on_the_full_history():
    """Our index + the research per-edge functions = the shipped GFP file, on 300 random test edges + every tenant seed."""
    se = pd.read_parquet(repo_path(CFG["inputs"]["scored_edges"].format(seed=1))).set_index("edge_id")
    seeds = sorted({int(e) for b in BANKS for l in pd.read_parquet(repo_path(tenant_paths(CFG, b)["rings"]),
                                                                     columns=["seed_edges"]).seed_edges for e in l})
    rows = se.loc[seeds].reset_index()[["edge_id", "from_id", "to_id", "timestamp"]]
    res = gfp_check(CFG, rows, 300, 1)
    assert res["identical"] and res["n_edges_checked"] == 300 + len(seeds)


# ----------------------------------------------------------------------------- inputs = what Kashish sent
def test_inputs_match_the_platform_fingerprints_and_visibility_rule():
    listed = {}
    for name, enc in (("tenant_rings_sha256.txt", "utf-16"), ("edge_ids_sha256.txt", "utf-8")):
        for line in (INPUTS / name).read_text(encoding=enc).splitlines():
            m = re.match(r"\s*([0-9a-fA-F]{64})\s+(\S.*?)\s*$", line)
            if m:
                listed[m.group(2).split("\\")[-1].split("/")[-1]] = m.group(1).lower()
    for b in BANKS:
        p = tenant_paths(CFG, b)
        for key in ("rings", "edge_ids"):
            assert sha256(p[key]) == listed[repo_path(p[key]).name], (b, key)
        ids = set(pd.read_parquet(repo_path(p["edge_ids"]))["edge_id"].astype(int))
        assert ids == set(_visible(b)["edge_id"])                      # her edge set IS from_bank or to_bank = bank


# ----------------------------------------------------------------------------- T-3 / T-4: the outputs
@pytest.mark.parametrize("bank", BANKS)
def test_nothing_hidden_is_mentioned(bank):
    """Every edge in edge_weights, feature top edges and the narrative's evidence, and every account listed, is on the
    bank's visible edges; a foreign account appears only as a counterparty on them."""
    vis = _visible(bank)
    vis_ids = set(vis["edge_id"])
    vis_accounts = set(vis["from_id"]) | set(vis["to_id"])
    rows = pq.read_table(repo_path(tenant_paths(CFG, bank)["out"])).to_pylist()
    assert len(rows) == 5
    for r in rows:
        assert {e["edge_id"] for e in r["edge_weights"]} <= vis_ids, r["ring_id"]
        assert {f["top_edge_id"] for f in r["feature_weights"]} <= vis_ids
        assert {a["account_id"] for a in r["account_weights"]} <= vis_accounts
        v = json.loads(r["evidence_summary"])["values"]
        assert {e["edge_id"] for e in v["top_edges"]} <= vis_ids
        for key in ("sources", "sinks", "mules", "undetermined"):
            assert set(v[key]) <= vis_accounts
        hubs = {v["shape"][k] for k in ("out_hub", "in_hub", "gs_hub") if v["shape"][k] is not None}
        assert hubs <= vis_accounts                                      # accounts a shape sentence can name
        for a, b in re.findall(r"(\d+)→(\d+)", r["narrative"]):         # every transaction the sentence names
            assert int(a) in vis_accounts and int(b) in vis_accounts


@pytest.mark.parametrize("bank", BANKS)
def test_log_and_provenance_carry_scope_tenant_and_fingerprints(bank):
    p = tenant_paths(CFG, bank)
    log = json.loads(repo_path(p["out"] + ".log.json").read_text(encoding="utf-8"))
    fx = sha256(CFG["amounts"]["fx_rates"])
    assert log["scope"] == "tenant" and log["tenant_id"] == bank and log["fx_rates_sha256"] == fx
    assert log["n_explained"] == log["n_rings"] == 5 and log["n_reproduces_shipped_ring"] == 5 and log["not_reproduced"] == []
    for k, v in log["input_sha256"].items():
        assert sha256(v["path"]) == v["sha256"], k
    for r in pq.read_table(repo_path(p["out"]), columns=["provenance"]).to_pylist():
        prov = json.loads(r["provenance"])
        assert (prov["scope"], prov["tenant_id"], prov["feature_scope"], prov["fx_rates_sha256"]) == \
               ("tenant", bank, "tenant_view", fx)


@pytest.fixture(scope="module")
def explainer():
    from explainability.tenant import TenantExplainer
    return TenantExplainer(CFG, 20)


def test_tenant_counts_and_shap_inputs_use_the_visible_view_only(explainer):
    """w_account's denominator = activity on visible edges (Kashish 4a); SHAP graph features = the research functions
    on the visible history (4b), transaction fields untouched."""
    from explainability.account_weights import background_degree
    from explainability.contract_io import read_scored_edges
    from explainability.feature_weights import load_feature_model, load_feature_rows
    from explainability.tenant import gfp_for_edges, gfp_settings
    vis = read_scored_edges(tenant_paths(CFG, 20)["scored_edges"])
    assert explainer.ctx.deg_background.equals(background_degree(vis, exclude_conversions=True))
    rows = explainer.ctx.features.rows
    full = load_feature_rows(CFG, load_feature_model(CFG, 1), rows.index)
    other = [c for c in rows.columns if c not in GFP_COLS]
    assert rows[other].equals(full[other])
    se = vis.set_index("edge_id").loc[list(rows.index)].assign(edge_id=lambda d: d.index)
    view = gfp_for_edges(adjacency(history(CFG, 20)), se, gfp_settings(CFG))
    assert np.array_equal(rows[GFP_COLS].to_numpy(), view[GFP_COLS].to_numpy().astype(np.float32))


# ----------------------------------------------------------------------------- T-5: regenerate
def test_tenant_regenerate(explainer):
    from explainability.api import InvalidEdit, RingNotFound
    from explainability.explain import EXPLANATIONS_SCHEMA
    rid = max(explainer.rings.index, key=lambda r: explainer.rings.at[r, "n_members"])
    sink = sorted(int(a) for a in explainer.rings.at[rid, "sink_accounts"])[-1]
    a = explainer.regenerate(rid, 20, excluded_members=[sink])
    json.dumps(a, allow_nan=False)                                       # JSON-safe: NaN -> null
    assert list(a) == EXPLANATIONS_SCHEMA.names
    assert sink not in {x["account_id"] for x in a["account_weights"]}
    prov = json.loads(a["provenance"])
    assert prov["regenerated"] is True and prov["excluded_members"] == [sink] and prov["excluded_edges"] == []
    assert (prov["scope"], prov["tenant_id"], prov["fx_rates_sha256"]) == ("tenant", 20, sha256(CFG["amounts"]["fx_rates"]))
    b = explainer.regenerate(rid, 20, excluded_members=[sink])
    assert {k: v for k, v in a.items() if k != "latency_ms"} == {k: v for k, v in b.items() if k != "latency_ms"}
    with pytest.raises(RingNotFound):
        explainer.regenerate(rid, 12, excluded_members=[sink])
    with pytest.raises(InvalidEdit):
        explainer.regenerate(rid, 20)


def test_shipped_explanations_carry_no_tenant_fields():
    """The tenant extras ride on ctx.extra_provenance, empty for every shipped run (the reviewed narratives untouched)."""
    r = pq.read_table(repo_path("results/xai") / CFG["explanations_name_week3"].format(seed=1), columns=["provenance"]).to_pylist()[0]
    assert "scope" not in json.loads(r["provenance"])
