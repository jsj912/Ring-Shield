"""Week 5: no attention anywhere (XR-35), typology evaluation (XR-25), latency (XR-27)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from explainability.contract_io import load_config, repo_path

CFG = load_config()
LAYER = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- W5-1, XR-35
def test_no_attention_weights_and_no_torch_anywhere_in_the_layer():
    """XR-35: the spec forbids any attention-based explanation; spec 9: no torch import outside the optional XR-20
    module (which does not exist). Scans every .py file of explainability/ except this test."""
    me = Path(__file__).resolve()
    word = re.compile(r"attention|\battn|self_attn|att_weight", re.IGNORECASE)
    torch = re.compile(r"^\s*(import torch|from torch)", re.MULTILINE)
    files = [p for p in LAYER.rglob("*.py") if p.resolve() != me]
    assert len(files) >= 15
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert not word.search(text), f"{p.name} mentions attention"
        assert not torch.search(text), f"{p.name} imports torch"


# ----------------------------------------------------------------------------- W5-2, XR-25
@pytest.fixture(scope="module")
def typing_primary():
    from explainability.evaluate import typing_rows
    seeds = CFG["inputs"]["seeds"]
    return typing_rows(CFG, seeds, "primary", mapping="position"), typing_rows(CFG, seeds, "primary")


def test_corrected_r5_typing_equals_the_lookup_by_ring_id(typing_primary):
    """Research corrected its lookup (ca49ecd, "type the matched ring"), so r5_typing.json now equals our lookup by
    ring id: point estimates, macro-F1, per-class recall and both confusion matrices to the last digit. The 95 %
    bounds differ slightly (same 401 rings and 1,000 resamples, different row order, so different draws); each
    interval must hold the point. The old published 0.219 is what the position lookup gives -- the bug, kept on record."""
    from explainability.evaluate import typing_metrics
    legacy, prim = typing_primary
    r5 = json.loads(repo_path("results/tables/r5_typing.json").read_text(encoding="utf-8"))["by_window"]["primary"]
    got = typing_metrics(prim, 1000, 0)
    for k in ("head", "rule"):
        assert (got[k]["point"], got[k]["n"]) == (r5[k]["point"], r5[k]["n"]), k
        assert r5[k]["lo"] <= r5[k]["point"] <= r5[k]["hi"] and abs(got[k]["lo"] - r5[k]["lo"]) < 0.01, k
    for k in ("head_macro_f1", "rule_macro_f1", "per_class", "head_confusion", "rule_confusion"):
        assert got[k] == r5[k], k
    assert round(typing_metrics(legacy, 1000, 0)["head"]["point"], 3) == 0.219


def test_the_lookup_by_ring_id_types_the_matched_ring(typing_primary):
    """On the primary window research's lookup types a different ring than the matched one in 316 of 401 rows; the
    lookup by id types exactly the matched rings (the same ring ids research's lookup SHOULD have found)."""
    legacy, prim = typing_primary
    assert len(legacy) == len(prim) == 401
    assert int((legacy["ring_id"] != legacy["matched_ring_id"]).sum()) == 316
    key = ["seed", "ring_id", "truth_ring"]
    assert sorted(map(tuple, legacy[["seed", "matched_ring_id", "truth_ring"]].to_numpy().tolist())) == \
           sorted(map(tuple, prim[key].to_numpy().tolist()))


def test_typology_eval_json_is_consistent():
    p = repo_path(CFG["output_dir"]) / CFG["typology_name"]
    if not p.exists():
        pytest.fail(f"{p} missing: run python -m explainability.evaluate --typology")
    rep = json.loads(p.read_text(encoding="utf-8"))
    prim, whole = rep["primary"], rep["whole_test_period"]
    assert prim["n_matched_rings"] == 401 and whole["n_matched_rings"] == 433
    assert prim["head"]["lo"] <= prim["head"]["point"] <= prim["head"]["hi"]
    r5 = json.loads(repo_path("results/tables/r5_typing.json").read_text(encoding="utf-8"))
    # the whole test period drops no ring, so both lookups agree: same point and n as research (the interval ends
    # differ only because our rows are ordered by ring id and research's by match order, so the draws differ)
    for k in ("point", "n"):
        assert whole["head"][k] == r5["by_window"]["whole"]["head"][k]
    rr = rep["reproduction_of_r5_typing"]
    assert rr["position_lookup"]["head_accuracy"] == rr["r5_typing_json"]["head_accuracy"]
    assert rr["n_rows_typing_a_different_ring_than_matched"] == 316
    split = rep["shape_sentence_split"]
    assert split["stated"]["n"] + split["not_stated"]["n"] == 401
    assert sum(sum(row) for row in prim["head_confusion"]["data"]) == 401


# ----------------------------------------------------------------------------- W5-4, XR-27
def test_latency_json_covers_every_ring_and_its_stages_add_up():
    """latency.json (python -m explainability.explain --latency): every ring of every seed; the stage times add up to
    each ring's latency (to the 0.5 ms rounding of latency_ms); p95 under the 2 s target; machine recorded."""
    p = repo_path(CFG["output_dir"]) / CFG["latency_name"]
    if not p.exists():
        pytest.fail(f"{p} missing: run python -m explainability.explain --latency")
    rep = json.loads(p.read_text(encoding="utf-8"))
    assert rep["pooled"]["n_rings"] == sum(v["n_rings"] for v in rep["per_seed"].values()) == 560
    assert rep["stages_sum_vs_latency_max_gap_ms"] <= 0.5 + 1e-9
    assert abs(sum(s["share_of_time"] for s in rep["stages"].values()) - 1) < 0.01
    assert rep["pooled"]["p50_ms"] <= rep["pooled"]["p95_ms"] <= rep["pooled"]["max_ms"]
    assert (rep["pooled"]["p95_ms"] < rep["target_p95_ms"]) == (rep["verdict"] == "met")
    assert all(r["latency_ms"] > 5000 for r in rep["rings_over_5000_ms"])
    for k in ("processor", "logical_cpus", "ram_gb", "python", "packages"):
        assert rep["machine"].get(k), k


# ----------------------------------------------------------------------------- W5-3, XR-26
def test_role_counts_by_hand():
    """correct / predicted / true per role; an account in only one ring can only be wrong for that side."""
    from explainability.evaluate import _role_counts
    pred = {1: {"role": "source"}, 2: {"role": "mule"}, 3: {"role": "sink"}, 9: {"role": "sink"}}
    truth = {1: {"role": "source"}, 2: {"role": "sink"}, 3: {"role": "sink"}, 4: {"role": "mule"}}
    c = _role_counts(pred, truth)
    assert c["source"] == (1, 1, 1) and c["sink"] == (1, 2, 2) and c["mule"] == (0, 1, 1)
    assert c["undetermined"] == (0, 0, 0)


def test_role_accuracy_in_fidelity_json():
    """XR-26 (Joan, Q2): three variants, every role's precision and recall in [0, 1] with the point inside its interval;
    accounts-in-both agreement in [0, 1]; the shipped-vs-recomputed difference reported."""
    p = repo_path(CFG["output_dir"]) / CFG["fidelity_week4_name"]
    rep = json.loads(p.read_text(encoding="utf-8"))
    if "role_accuracy" not in rep:
        pytest.fail("run python -m explainability.evaluate --roles")
    ra = rep["role_accuracy"]
    assert ra["n_ring_instances"] == 401 and ra["n_truth_rings"] == 100
    assert set(ra["variants"]) == {"headline", "in_window", "accounts_in_both"}
    for v in ra["variants"].values():
        for role, x in v["per_role"].items():
            for k in ("precision", "recall"):
                if x[k]["point"] is not None:
                    lo, pt, hi = x[k]["lo"], x[k]["point"], x[k]["hi"]
                    assert 0 <= lo <= pt + 1e-12 and pt <= hi + 1e-12 and hi <= 1, (role, k)
    both = ra["variants"]["accounts_in_both"]
    assert 0 <= both["agreement"] <= 1 and both["n_accounts"] > 0
    assert ra["shipped_vs_recomputed"]["n_accounts_compared"] > 0


# ----------------------------------------------------------------------------- W5-8, XR-36
def test_detector_cfg_swaps_only_inputs_and_output_names():
    from explainability.contract_io import detector_cfg
    g = detector_cfg(CFG, "gine_causal")
    assert g["inputs"] == CFG["inputs"] and g["explanations_name_week3"] == CFG["explanations_name_week3"]
    x = detector_cfg(CFG, "gfpxgb")
    assert x["inputs"]["rings"] == "contract/out/rings_full_gfpxgb_{seed}.parquet" and x["research_inputs"]["embeddings"] is None
    assert x["explanations_name_week3"] == "explanations_gfpxgb_seed{seed}.parquet"
    assert x["edge_weights"] == CFG["edge_weights"] and x["narrative"] == CFG["narrative"]       # nothing else moves
    with pytest.raises(ValueError, match="unknown detector"):
        detector_cfg(CFG, "nope")


@pytest.mark.parametrize("det", ["gfpxgb", "mega"])
def test_leave_one_out_is_not_degraded_for_the_other_detectors(det):
    """Joan's detector-aware RingRerunner: gfpxgb's affinity uses no embeddings (none passed, not degraded); MEGA's
    gine-trained affinity uses cos_emb and gets MEGA's embeddings. Partition settings from the rings file's log."""
    import pandas as pd
    from explainability.contract_io import detector_cfg, read_rings, read_scored_edges
    from explainability.edge_weights import load_loo_inputs
    c = detector_cfg(CFG, det)
    se = read_scored_edges(c["inputs"]["scored_edges"].format(seed=1))
    rings = read_rings(c["inputs"]["rings"].format(seed=1), scored_edges=se)
    r = rings.iloc[0]
    inc = sorted(set(r["seed_edges"]) | set(r["expanded_edges"]))
    loo = load_loo_inputs(c, 1, "full", c["inputs"]["rings"].format(seed=1), inc)
    rr = loo.rerunner(se.set_index("edge_id").loc[inc].reset_index())
    assert rr.features_degraded is False and rr.missing_features == []
    assert (loo.emb is None) == (det == "gfpxgb")
    assert loo.params["partition_config"].endswith(".log.json")


def test_xr36_summary_covers_all_three_detectors_with_the_same_settings():
    p = repo_path(CFG["output_dir"]) / CFG["detectors_summary_name"]
    if not p.exists():
        pytest.fail(f"{p} missing: run python -m explainability.evaluate --detectors-summary")
    rep = json.loads(p.read_text(encoding="utf-8"))["detectors"]
    assert set(rep) == {"gine_causal", "gfpxgb", "mega"}
    expected_rings = {"gine_causal": 560, "gfpxgb": 177 + 168 + 169 + 185 + 174, "mega": 123 + 115 + 120 + 105 + 116}
    for d, v in rep.items():
        assert v["n_rings"] == v["n_explained"] == expected_rings[d], d
        assert v["n_degraded"] == 0
        assert v["mixing"] == {k: float(x) for k, x in CFG["edge_weights"]["mixing_tuned"].items()}, d
        assert v["verdict"] in ("positive", "negative") and 0 <= v["typing_accuracy_primary"] <= 1
    assert rep["gfpxgb"]["inputs"]["embeddings"] is None
