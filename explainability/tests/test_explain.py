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
from explainability.explain import active_mixing  # noqa: E402
MIX, MIX_SOURCE = active_mixing(CFG, CFG["amounts"]["currency_policy"])


def _fixture_ctx(case, cfg=CFG, policy=None):
    from explainability.edge_weights import load_fx
    se, rings = case["scored_edges"], case["rings"]
    policy = policy or cfg["amounts"]["currency_policy"]
    ctx = ExplainContext(se.set_index("edge_id"), background_degree(se, exclude_conversions=policy == "converted"),
                         LooInputs("cc", 3, params={"aggregator_id": "cc"}), cfg, load_research_config(cfg, "roles"),
                         provenance(se, rings), policy, load_fx(cfg) if policy == "converted" else None, "fixture")
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
        n = name_of[e["edge_id"]]                                  # components are the hand values; the mix is
        a, b, g = (MIX[x] for x in ("alpha", "beta", "gamma"))    # whichever one the active policy uses
        assert abs(e["w_total"] - (a * case["w_score"][n] + b * case["w_loo"][n] + g * case["w_flow"][n])) < 1e-6
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
    key = "mixing_tuned" if CFG["edge_weights"].get("mixing_tuned") else "mixing_default"   # the ACTIVE mix (converted)
    cfg2["edge_weights"][key] = {"alpha": 1.0, "beta": 0.0, "gamma": 0.0}
    ctx2, _ = _fixture_ctx(case, cfg2)
    t2, _, _ = explain_rings(rings, ctx2)
    p1, p2 = (json.loads(t.column("provenance")[0].as_py()) for t in (t1, t2))
    for key in ("model_id", "aggregator_id", "seed", "explainer_version", "mixing", "loo_edges", "currency_policy"):
        assert key in p1
    assert p1["mixing"] == MIX and p2["mixing"]["alpha"] == 1.0
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


# ----------------------------------------------------------------------------- migration M5: policies end to end
def test_undetermined_only_under_converted_and_never_peripheral():
    case = fx.undetermined_case()
    for policy, expect_key in (("converted", "converted_roles"), ("raw", "raw_roles")):
        ctx, rings = _fixture_ctx(case, policy=policy)
        table, _, diags = explain_rings(rings, ctx)
        roles = {a["account_id"]: a["role"] for a in table.to_pylist()[0]["account_weights"]}
        assert roles == case[expect_key], policy
        prov = json.loads(table.column("provenance")[0].as_py())
        assert prov["currency_policy"] == policy
        assert prov["n_undetermined_accounts"] == (2 if policy == "converted" else 0)
    assert "peripheral" not in case["converted_roles"].values()


def test_converted_provenance_records_the_currency_treatment():
    ctx, rings = _fixture_ctx(fx.loo_case(), policy="converted")
    t, _, _ = explain_rings(rings, ctx)
    p = json.loads(t.column("provenance")[0].as_py())
    assert p["currency_policy"] == "converted" and p["fx_rates"]["path"] == "contract/fx_rates.json"
    assert p["evidence_edges"] == "member edges minus currency conversions" and p["flow_partial"] is False
    assert p["mixing"] == MIX and p["mixing_source"] == MIX_SOURCE and p["rings_schema_version"] == 2


def _real_paths(seed, rings_key="rings"):
    scores, rings = CFG["inputs"]["scored_edges"].format(seed=seed), CFG["inputs"][rings_key].format(seed=seed)
    if any(not repo_path(p).exists() for p in (scores, rings, CFG["research_inputs"]["embeddings"].format(seed=seed))):
        pytest.skip("real files not on disk")
    return scores, rings


@pytest.mark.parametrize("rings_path, week2", [
    ("contract/out/v1/rings_full_gine_causal_1.parquet", "results/xai/explanations_week2_seed1.parquet"),
    ("contract/out/v1/rings_stub_cc.parquet", "results/xai/explanations_week2_stub_cc_seed1.parquet")])
def test_raw_policy_on_v1_rings_reproduces_week2(tmp_path, rings_path, week2):
    """Policy `raw` reproduces Week 2: edge weights, account weights and the role-disagreement file are
    identical (byte-for-byte as parquet / CSV). Provenance differs only by the fields added since."""
    if not repo_path(week2).exists():
        pytest.skip("Week 2 output not on disk")
    scores, _ = _real_paths(1)
    run_file(CFG, scores, rings_path, tmp_path / "x.parquet", tmp_path / "x.csv", policy="raw")
    new, old = pq.read_table(tmp_path / "x.parquet"), pq.read_table(repo_path(week2))
    for col in ("ring_id", "edge_weights", "account_weights", "topology_type", "topology_prob"):
        assert _bytes_of(new.select([col])) == _bytes_of(old.select([col])), col
    old_csv = repo_path(week2.replace("explanations_week2_", "roles_disagreement_").replace(".parquet", ".csv"))
    assert (tmp_path / "x.csv").read_bytes() == old_csv.read_bytes()


def _bytes_of(table) -> bytes:
    import pyarrow as pa
    buf = pa.BufferOutputStream()
    pq.write_table(table.replace_schema_metadata(None), buf)
    return buf.getvalue().to_pybytes()


def test_converted_explanations_hold_no_conversion_and_flow_sums_to_one(tmp_path):
    """On real seed 1 under `converted`: no conversion is ever an evidence edge; for every ring whose flow is not
    partial, w_flow sums to 1 over its edges with duplicate payments counted once."""
    from explainability.contract_io import read_scored_edges
    from explainability.edge_weights import conversion_mask
    scores, rings = _real_paths(1)
    log = run_file(CFG, scores, rings, tmp_path / "c.parquet", tmp_path / "c.csv", policy="converted")
    se = read_scored_edges(scores).set_index("edge_id")
    conv = conversion_mask(se)
    assert log["policy"] == "converted" and log["n_conversions_dropped"] > 0
    for row in pq.read_table(tmp_path / "c.parquet").to_pylist():
        ids = [e["edge_id"] for e in row["edge_weights"]]
        assert not conv.reindex(ids).any(), row["ring_id"]
        p = json.loads(row["provenance"])
        if not p["flow_partial"]:
            e = se.loc[ids].reset_index()
            keep = ~e.duplicated(["from_id", "to_id", "timestamp", "amount_received"]).to_numpy()
            total = sum(w["w_flow"] for w, k in zip(sorted(row["edge_weights"], key=lambda x: x["edge_id"]),
                                                    keep[e["edge_id"].argsort().to_numpy()]) if k)
            assert abs(total - 1.0) < 1e-9, row["ring_id"]


# ----------------------------------------------------------------------------- Week 3: SHAP + narrative, real rings
W3_FILES = [f"results/xai/{CFG['explanations_name_week3'].format(seed=s)}" for s in CFG["inputs"]["seeds"]] + \
           ["results/xai/explanations_week3_stub_cc_seed1.parquet"]


@pytest.fixture(scope="module")
def week3_seed1(tmp_path_factory):
    scores, rings = _real_paths(1)
    out = tmp_path_factory.mktemp("week3")
    log = run_file(CFG, scores, rings, out / "w3.parquet", out / "w3.csv", policy="converted", narrate=True)
    return log, pq.read_table(out / "w3.parquet")


def test_week3_leaves_the_weights_unchanged_and_fills_the_new_columns(week3_seed1):
    """W3-8: edge / account weights and topology byte-identical to the migrated Week 2 file; every ring has a
    narrative, an evidence_summary and 10 feature weights; latency p95 under 2,000 ms including SHAP."""
    log, t = week3_seed1
    old = pq.read_table(repo_path("results/xai/explanations_converted_seed1.parquet"))
    for col in ("ring_id", "edge_weights", "account_weights", "topology_type", "topology_prob"):
        assert _bytes_of(t.select([col])) == _bytes_of(old.select([col])), col
    assert t.schema.equals(EXPLANATIONS_SCHEMA)
    from explainability.narrative import load_phrasing
    feats = set(load_phrasing(repo_path(CFG["narrative"]["phrasing"]))["features"])
    for row in t.to_pylist():
        assert row["narrative"] and row["evidence_summary"], row["ring_id"]
        assert len(row["feature_weights"]) == CFG["feature_weights"]["top_n"]
        assert {f["feature_name"] for f in row["feature_weights"]} <= feats
    n = log["narrative"]
    assert n["n_narratives"] == 108 and n["topology_source"] == "rings" and n["words"]["max"] <= 90
    assert log["latency_ms"]["p95"] < 2000 and not log["latency_ms"]["rings_over_5000_ms"]


def test_feature_weights_come_from_seed_edges_that_are_not_conversions(week3_seed1):
    from explainability.contract_io import read_rings, read_scored_edges
    from explainability.edge_weights import conversion_mask
    _, t = week3_seed1
    scores, rings_path = _real_paths(1)
    se = read_scored_edges(scores)
    seeds = read_rings(rings_path, se).set_index("ring_id")["seed_edges"]
    conv = conversion_mask(se)
    for row in t.to_pylist():
        allowed = {int(e) for e in seeds[row["ring_id"]]} - set(conv[conv].index)
        assert {f["top_edge_id"] for f in row["feature_weights"]} <= allowed, row["ring_id"]
        p = json.loads(row["provenance"])
        assert p["n_shap_edges"] == len(allowed) and p["feature_model"].endswith("model_seed1.json")


def test_every_real_narrative_is_clean_and_regenerates(week3_seed1):
    """XR-31 on real rings: the sentence is rebuilt from evidence_summary, string-equal; every number in it is a
    stored value; no blanks, 'None', raw feature or type names; at most 90 words."""
    from explainability.narrative import NUMBER, load_phrasing, regenerate
    from explainability.tests.test_narrative import assert_clean
    phrasing = load_phrasing(repo_path(CFG["narrative"]["phrasing"]))
    for row in week3_seed1[1].to_pylist():
        text, summary = row["narrative"], json.loads(row["evidence_summary"])
        assert regenerate(row["evidence_summary"], phrasing, CFG["narrative"]) == text, row["ring_id"]
        assert set(NUMBER.findall(text)) <= {t for s in summary["slots"].values() for t in NUMBER.findall(s)}
        assert_clean(text)


def test_swapping_in_the_rule_scorer_changes_only_type_and_p_on_real_rings():
    """XR-19: where the rule scorer and the shipped typing head agree on the type, the sentence is identical
    apart from p; where they disagree, only the type wording and p change (same structure otherwise)."""
    import re
    from explainability.explain import build_context
    scores, rings_path = _real_paths(1)
    texts = {}
    for source in ("rings", "rule_scorer"):
        ctx, rings = build_context(CFG, scores, rings_path, "converted", narrate=True, topology_source=source)
        t, _, _ = explain_rings(rings.iloc[:40], ctx)
        texts[source] = {r["ring_id"]: (r["topology_type"], r["narrative"]) for r in t.to_pylist()}
    p = re.compile(r"p = \d\.\d\d")
    same = 0
    for rid, (type_a, a) in texts["rings"].items():
        type_b, b = texts["rule_scorer"][rid]
        if type_a == type_b:
            same += 1
            assert p.sub("p", a) == p.sub("p", b), rid
    assert same >= 5                                     # the comparison is not vacuous


@pytest.mark.parametrize("path", W3_FILES)
def test_every_shipped_week3_narrative_regenerates(path):
    """XR-31 on every file written by the Week 3 run (all five seeds and the stub)."""
    from explainability.narrative import load_phrasing, regenerate
    if not repo_path(path).exists():
        pytest.fail(f"{path} missing: run python -m explainability.explain (Week 3)")
    phrasing = load_phrasing(repo_path(CFG["narrative"]["phrasing"]))
    rows = pq.read_table(repo_path(path), columns=["ring_id", "narrative", "evidence_summary"]).to_pylist()
    assert rows
    for r in rows:
        assert regenerate(r["evidence_summary"], phrasing, CFG["narrative"]) == r["narrative"], r["ring_id"]


def test_review_sample_has_one_matched_ring_per_type_and_hides_the_truth_until_the_end():
    """W3-9: the review file shows, per predicted type, the narrative exactly as stored in the Week 3 file, the
    top-5 evidence edges and the roles; the truth appears only in the answer key after every entry."""
    import re
    path = repo_path("results/xai") / CFG["narrative_samples_name"]
    if not path.exists():
        pytest.fail(f"{path} missing: run python -m explainability.explain --samples")
    text = path.read_text(encoding="utf-8")
    body, key = text.split("## Answer key (read after reviewing)")
    entries = re.findall(r"^## (\S+) — `([^`]+)` \(detector seed (\d)", body, flags=re.M)
    assert entries and len({t for t, _, _ in entries}) == len(entries)
    for t, rid, seed in entries:
        row = [r for r in pq.read_table(repo_path("results/xai") / CFG["explanations_name_week3"].format(seed=seed))
               .to_pylist() if r["ring_id"] == rid][0]
        assert row["topology_type"] == t and f"> {row['narrative']}" in body
        assert f"`{rid}`" in key
    assert "true pattern" not in body.lower().replace("the true pattern types are at the very end", "")
