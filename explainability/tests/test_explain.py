"""XR-21 / 30 / 32 (+ XR-04's provenance half): the explanations file, its schema, determinism, provenance."""
from __future__ import annotations

import copy
import json

import pyarrow.parquet as pq
import pytest

from explainability.account_weights import background_degree
from explainability.contract_io import load_config, load_research_config, provenance, repo_path
from explainability.edge_weights import LooInputs
from explainability.explain import EXPLANATIONS_SCHEMA, ExplainContext, explain_rings, run_file
from explainability.tests import fixtures as fx

CFG = load_config()


def _fixture_ctx(case, cfg=CFG):
    se, rings = case["scored_edges"], case["rings"]
    ctx = ExplainContext(se.set_index("edge_id"), background_degree(se), LooInputs("cc", 3, params={"aggregator_id": "cc"}),
                         cfg, load_research_config(cfg, "roles"), provenance(se, rings))
    return ctx, rings


# ----------------------------------------------------------------------------- on the fixtures
def test_schema_and_coverage_on_the_fixture():
    """XR-21: the 3.1 layout; every member edge and every member account is explained, edges sorted by w_total."""
    case = fx.loo_case()
    ctx, rings = _fixture_ctx(case)
    table, dis, diags = explain_rings(rings, ctx)
    assert table.schema.equals(EXPLANATIONS_SCHEMA)
    row = table.to_pylist()[0]
    ring = rings.iloc[0]
    assert sorted(e["edge_id"] for e in row["edge_weights"]) == sorted(ring.member_edges)
    assert sorted(a["account_id"] for a in row["account_weights"]) == sorted(ring.members)
    totals = [e["w_total"] for e in row["edge_weights"]]
    assert totals == sorted(totals, reverse=True)
    name_of = {v: k for k, v in case["ids"].items()}
    for e in row["edge_weights"]:                                   # same numbers as the hand computation
        assert abs(e["w_total"] - case["w_total"][name_of[e["edge_id"]]]) < 1e-6
    assert row["feature_weights"] == [] and row["narrative"] is None and row["evidence_summary"] is None
    assert row["topology_type"] == "STACK" and abs(row["topology_prob"] - 0.65) < 1e-12
    assert row["latency_ms"] >= 0 and diags[0]["reproduces_shipped_ring"] in (True, False)


def test_provenance_records_every_setting_and_follows_the_config():
    """XR-32 / XR-04: provenance carries model, aggregator, seed, version and the mixing weights actually used;
    changing the mixing weights in the config changes both the weights and the provenance."""
    case = fx.loo_case()
    ctx, rings = _fixture_ctx(case)
    t1, _, _ = explain_rings(rings, ctx)
    cfg2 = copy.deepcopy(CFG)
    cfg2["edge_weights"]["mixing_default"] = {"alpha": 1.0, "beta": 0.0, "gamma": 0.0}
    ctx2, _ = _fixture_ctx(case, cfg2)
    t2, _, _ = explain_rings(rings, ctx2)
    p1, p2 = (json.loads(t.column("provenance")[0].as_py()) for t in (t1, t2))
    for key in ("model_id", "aggregator_id", "seed", "explainer_version", "mixing", "loo_edges", "currency_policy"):
        assert key in p1
    assert p1["mixing"] == {"alpha": 0.4, "beta": 0.4, "gamma": 0.2} and p2["mixing"]["alpha"] == 1.0
    assert t1.column("edge_weights").to_pylist() != t2.column("edge_weights").to_pylist()


def test_role_disagreements_reach_the_output():
    ctx, rings = _fixture_ctx(fx.roles_case())
    _, dis, _ = explain_rings(rings, ctx)
    assert len(dis) == 1 and dis.iloc[0]["cause"] == "hold_time_definition"


# ----------------------------------------------------------------------------- determinism on real data
def _bytes_without_latency(table) -> bytes:
    """The parquet bytes of the table with latency_ms set to 0 -- a byte comparison treats two NaNs in the
    same place as equal (Arrow's `equals` does not), so this is the strict, literal XR-30 check."""
    import pyarrow as pa
    i = table.schema.get_field_index("latency_ms")
    t = table.set_column(i, "latency_ms", pa.array([0] * table.num_rows, pa.int64()))
    buf = pa.BufferOutputStream()
    pq.write_table(t, buf)
    return buf.getvalue().to_pybytes()


def test_two_runs_are_identical_except_latency(tmp_path):
    """XR-30: every column except latency_ms is identical across runs; the disagreement CSV is byte-identical."""
    scores, rings = CFG["inputs"]["scored_edges"].format(seed=1), CFG["inputs"]["rings"].format(seed=1)
    if any(not repo_path(p).exists() for p in (scores, rings, CFG["research_inputs"]["embeddings"].format(seed=1))):
        pytest.skip("real files not on disk")
    logs = {}
    for run in ("a", "b"):
        logs[run] = run_file(CFG, scores, rings, tmp_path / run / "x.parquet", tmp_path / run / "x.csv")
    a, b = (pq.read_table(tmp_path / r / "x.parquet") for r in ("a", "b"))
    assert a.schema.equals(EXPLANATIONS_SCHEMA)
    assert _bytes_without_latency(a) == _bytes_without_latency(b)
    assert (tmp_path / "a" / "x.csv").read_bytes() == (tmp_path / "b" / "x.csv").read_bytes()
    assert logs["a"]["n_explained"] == logs["a"]["n_rings"] == 108
    assert logs["a"]["n_reproduces_shipped_ring"] == 108          # seed 1: every ring reproduces (see test_edge_weights)
