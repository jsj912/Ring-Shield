"""XR-22 / XR-24 (Week 1): the fidelity metric, the score-only ranking, the random control, determinism."""
from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from explainability import evaluate
from explainability.contract_io import load_config, repo_path
from explainability.edge_weights import rank_by_score, w_score
from explainability.evaluate import evaluate_frames, fidelity_at_k, random_fidelity
from explainability.match import TruthEdges, match_in_window, window_from_config
from explainability.tests import fixtures as fx

CFG = load_config()


# ----------------------------------------------------------------------------- hand-computed case
def test_five_edge_ring_matches_the_hand_computation():
    case = fx.five_edge_case()
    ranked = rank_by_score(case["edges"])
    assert ranked == case["ranking"]
    for k, expected in case["fidelity"].items():
        assert abs(fidelity_at_k(ranked, case["truth"], k) - expected) < 1e-9


def test_w_score_is_the_calibrated_score():
    case = fx.five_edge_case()
    w = w_score(case["edges"])
    assert w.loc[11] == 0.90 and w.loc[15] == 0.10 and len(w) == 5


def test_ties_break_on_raw_score_then_edge_id_and_missing_scores_go_last():
    edges = pd.DataFrame({"edge_id": [5, 3, 9, 1, 7],
                          "score_calibrated": [0.5, 0.5, 0.5, float("nan"), 0.9],
                          "score_raw": [0.6, 0.6, 0.7, 0.99, 0.95]})
    # 7 (0.9) first; then the 0.5 tie: 9 (raw 0.7) before 3 and 5 (raw 0.6 tie -> lower edge_id first); NaN last
    assert rank_by_score(edges) == [7, 9, 3, 5, 1]


def test_fidelity_edge_cases():
    assert fidelity_at_k([1, 2], {1, 2, 3, 4}, 3) == 2 / 3      # fewer edges than k: denominator min(k, |T|)
    assert fidelity_at_k([1, 2, 3], {9}, 3) == 0.0
    assert fidelity_at_k([9, 1, 2], {9}, 3) == 1.0               # |T| = 1: denominator 1
    with pytest.raises(ValueError):
        fidelity_at_k([1], set(), 3)


# ----------------------------------------------------------------------------- the random control
def test_random_control_is_reproducible_under_its_seed():
    ids, T = list(range(40)), set(range(0, 40, 3))
    a = random_fidelity(ids, T, [3, 5, 10], 20, [20260921, 1, 0])
    b = random_fidelity(list(reversed(ids)), T, [3, 5, 10], 20, [20260921, 1, 0])   # input order must not matter
    assert a == b
    assert random_fidelity(ids, T, [3, 5, 10], 20, [20260921, 1, 1]) != a          # a different ring gets other shuffles


def test_random_control_converges_to_its_expected_value():
    """For a random order, E[|top-k & T|] = k * |T| / n, so E[fidelity@k] = (k * |T| / n) / min(k, |T|)."""
    n, T = 30, set(range(10))
    got = random_fidelity(list(range(n)), T, [3, 5, 10], 4000, [7])
    for k in (3, 5, 10):
        assert abs(got[k] - (k * len(T) / n) / min(k, len(T))) < 0.02


# ----------------------------------------------------------------------------- on the fixtures
def test_every_fixture_ring_scores_one_when_all_its_edges_are_true():
    """Sanity: match each fixture ring against itself; T = all its edges, so every ranking scores 1.0."""
    se, rings = fx.fixture_contract()
    W = window_from_config(CFG)
    truth = {i + 1: set(m) for i, m in enumerate(rings["members"])}
    res = match_in_window(rings, se, W, threshold=0.5, scope="test_visible", truth=truth)
    assert res.n_matched == len(rings)
    # truth rings never contain a currency conversion (checked on real data in
    # test_converted_policy_drops_exactly_the_conversions), so the fixture's "true" set excludes them too
    from explainability.edge_weights import conversion_mask
    conv = conversion_mask(se)
    edges_of = {i + 1: {e for e in m if not conv.loc[e]} for i, m in enumerate(rings["member_edges"])}
    T = TruthEdges(edges={int(t): edges_of[int(t)] for t in res.matches["truth_ring_id"]}, accounts={})
    per_ring, summary = evaluate_frames(se, rings, res, T, W, CFG, detector_seed=0)
    assert len(per_ring) == len(rings)
    for name in ("score_only", "random"):
        for k in ("3", "5", "10"):
            assert math.isclose(summary[name][k], 1.0)


# ----------------------------------------------------------------------------- determinism on real data
def test_two_runs_write_byte_identical_json(tmp_path):
    inp = CFG["inputs"]
    needed = [inp["scored_edges"].format(seed=1), inp["rings"].format(seed=1), inp["truth"], inp["split_parquet"]]
    if any(not repo_path(p).exists() for p in needed):
        pytest.skip("real contract files not on disk")
    for run in ("a", "b"):
        assert evaluate.main(["--seeds", "1", "--policy", "raw", "--out", str(tmp_path / run)]) == 0
    a = (tmp_path / "a" / "fidelity_week1_seed1.json").read_bytes()
    b = (tmp_path / "b" / "fidelity_week1_seed1.json").read_bytes()
    assert a == b and len(a) > 1000


# ----------------------------------------------------------------------------- migration: v2 rings, two policies
WEEK1 = {s: f"results/xai/fidelity_week1_seed{s}.json" for s in (1, 2, 3, 4, 5)}
WEEK1_KEYS = ["ring_id", "truth_ring_id", "pattern_type", "jaccard", "n_edges_ranked", "n_true_edges",
              "n_true_among_ranked"] + [f"{n}@{k}" for n in ("score_only", "random") for k in (3, 5, 10)]


def _run(seed, policy, rings=None):
    inp = CFG["inputs"]
    paths = [inp["scored_edges"].format(seed=seed), rings or inp["rings"].format(seed=seed), inp["truth"], inp["split_parquet"]]
    if any(not repo_path(p).exists() for p in paths):
        pytest.skip("real files not on disk")
    return evaluate.evaluate_seed(CFG, seed, scores=paths[0], rings_path=paths[1], truth=paths[2],
                                  split_parquet=paths[3], policy=policy)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_raw_policy_on_v2_rings_reproduces_week1(seed):
    """The schema change moved nothing: policy `raw` on the v2 rings gives Week 1's committed numbers exactly."""
    import json
    if not repo_path(WEEK1[seed]).exists():
        pytest.skip("Week 1 result file not on disk")
    old = json.loads(repo_path(WEEK1[seed]).read_text(encoding="utf-8"))
    new = _run(seed, "raw")
    assert new["provenance"]["rings_schema_version"] == 2
    assert new["fidelity"] == old["fidelity"] and new["counts"]["n_matched"] == old["counts"]["n_matched"]
    assert [{k: r[k] for k in WEEK1_KEYS} for r in new["per_ring"]] == [{k: r[k] for k in WEEK1_KEYS} for r in old["per_ring"]]


def test_raw_policy_on_v2_stub_reproduces_week1_stub():
    import json
    p = "results/xai/fidelity_week1_stub_cc_seed1.json"
    if not repo_path(p).exists():
        pytest.skip("Week 1 stub result not on disk")
    old = json.loads(repo_path(p).read_text(encoding="utf-8"))
    assert _run(1, "raw", rings="contract/out/rings_stub_cc.parquet")["fidelity"] == old["fidelity"]


def test_converted_policy_drops_exactly_the_conversions():
    """Under `converted`, a ranked edge is never a conversion; ranked + dropped = Week 1's ranked count;
    no true ring edge is a conversion (so dropping them can never remove evidence)."""
    from explainability.contract_io import read_scored_edges
    from explainability.edge_weights import conversion_mask
    raw, conv = _run(1, "raw"), _run(1, "converted")
    assert conv["policy"] == "converted" and conv["counts"]["n_conversions_dropped"] > 0
    for r, c in zip(raw["per_ring"], conv["per_ring"]):
        assert r["ring_id"] == c["ring_id"]
        assert c["n_edges_ranked"] + c["n_conversions_dropped"] == r["n_edges_ranked"]
        assert c["n_true_among_ranked"] == r["n_true_among_ranked"]          # no true edge was dropped
    se = read_scored_edges(CFG["inputs"]["scored_edges"].format(seed=1))
    is_conv = conversion_mask(se)
    from explainability.match import truth_edge_sets, window_from_config
    T = truth_edge_sets(CFG["inputs"]["split_parquet"], window_from_config(CFG))
    assert not any(is_conv.reindex(list(t)).fillna(False).any() for t in T.edges.values())


def test_evidence_filter_unit():
    from explainability.edge_weights import evidence_edge_ids
    flags = pd.Series([False, True, False], index=[10, 11, 12])
    assert evidence_edge_ids([12, 11, 10], flags, "converted") == ([12, 10], 1)
    assert evidence_edge_ids([12, 11, 10], flags, "raw") == ([12, 11, 10], 0)
    with pytest.raises(ValueError, match="unknown currency policy"):
        evidence_edge_ids([1], flags, "partitioned")


def test_policy_comparison_report_is_consistent():
    """Joan's item 8 report: transitions account for every ring-account once; 285 of 4,280 roles change and 3
    become undetermined (Joan's own figures, reproduced independently); saturation counts are well formed."""
    import json
    p = repo_path(f"{CFG['output_dir']}/{CFG['migration_report_name']}")
    if not p.exists():
        pytest.skip("migration report not generated")
    rep = json.loads(p.read_text(encoding="utf-8"))["pooled"]
    t = rep["role_transitions"]
    assert sum(t.values()) == rep["n_accounts"] == 4280 and rep["n_rings"] == 560
    assert rep["n_roles_changed"] == 285
    assert sum(v for k, v in t.items() if k.endswith("-> undetermined")) == 3
    for pol in ("raw", "converted"):
        s = rep["matched_rings_saturation"][pol]
        assert s["all_ranked_edges_true"] + s["can_discriminate_rankings"] <= s["n_matched"] == 401
    assert rep["topk_conversions_before_filter"]["3"] <= rep["topk_slots_total"]["3"]


# ----------------------------------------------------------------------------- migration M8: XR-05 on validation
def test_mixing_grid_has_66_triples_summing_to_one():
    from explainability.evaluate import mixing_grid
    g = mixing_grid(0.1)
    assert len(g) == 66 and all(abs(sum(t) - 1) < 1e-12 and min(t) >= 0 for t in g) and len(set(g)) == 66


def test_xr05_choice_was_made_on_validation_only_and_is_what_the_config_uses():
    """XR-05 acceptance: only validation inputs were read (no test-split file; every timestamp before the test
    window); the chosen triple is the grid argmax under the stated tie-break; the config's mixing_tuned is it."""
    import json
    import numpy as np
    from ringshield.windows import load_windows
    p = repo_path(f"{CFG['output_dir']}/{CFG['xr05_choice_name']}")
    if not p.exists():
        pytest.skip("XR-05 choice not generated")
    d = json.loads(p.read_text(encoding="utf-8"))
    test_files = {CFG["inputs"]["split_parquet"], CFG["research_inputs"]["gfp"]} | {
        CFG["inputs"][k].format(seed=s) for k in ("scored_edges", "rings", "rings_v1") for s in CFG["inputs"]["seeds"]} | {
        CFG["research_inputs"]["embeddings"].format(seed=s) for s in CFG["inputs"]["seeds"]}
    assert not (set(d["files_read"]) & test_files)
    assert d["window"]["split"] == "val" and d["max_timestamp_read"] < load_windows()["primary"].bounds[0]
    assert d["n_triples"] == 66 and d["objective"] == "fidelity@5"
    best = max(r["objective"] for r in d["grid"])
    tied = [r for r in d["grid"] if abs(r["objective"] - best) < 1e-12]
    default = np.array([0.4, 0.4, 0.2])
    expect = sorted(tied, key=lambda r: (round(float(np.linalg.norm(np.array([r["alpha"], r["beta"], r["gamma"]]) - default)), 12),
                                         -r["alpha"], -r["beta"]))[0]
    assert d["chosen"] == {k: expect[k] for k in ("alpha", "beta", "gamma")}
    assert {k: float(v) for k, v in CFG["edge_weights"]["mixing_tuned"].items()} == d["chosen"]


# ----------------------------------------------------------------------------- Week 4: fidelity.json
def test_expanded_edge_fidelity_by_hand():
    """XR-23 (Joan, Q3): (b) expanded recall@k, (c) the literal definition, (a) expanded precision."""
    from explainability.evaluate import expanded_rows
    case = fx.expanded_case()
    se, rings = case["scored_edges"], case["rings"]
    W = window_from_config(CFG)
    res = match_in_window(rings, se, W, threshold=0.5, scope="test_visible", truth=case["truth_accounts"])
    T = TruthEdges(edges=case["truth_edges"], accounts={})
    (row,) = expanded_rows(se, rings, res, T, W, CFG, 0, {rings.iloc[0]["ring_id"]: case["order"]})
    assert (row["n_expanded"], row["n_expanded_true"]) == (3, 2) and row["precision"] == pytest.approx(2 / 3)
    assert (row["b_w_total@3"], row["b_score_only@3"], row["b_score_only@5"]) == (1.0, 0.5, 1.0)
    assert row["c_defined"] and row["c_discriminates"]
    assert all(row[f"c_{n}@{k}"] == 1.0 for n in ("w_total", "score_only") for k in (3, 5, 10))
    assert 0 < row["b_random@3"] < 1


def test_week4_block_aggregates_per_truth_ring_and_tests_six_comparisons():
    """Unit = truth ring (mean over the seeds where matched); six paired comparisons, Holm over the six; the
    k=5 verdict follows the intervals."""
    import pandas as pd
    from explainability.evaluate import _block
    rows = []
    for seed in (1, 2):
        for t in range(40):
            if seed == 2 and t >= 30:                                   # rings 30-39 matched in one seed only
                continue
            r = {"seed": seed, "truth_ring_id": t}
            for k in (3, 5, 10):
                r.update({f"w_total@{k}": 1.0, f"score_only@{k}": 1.0 if t % 2 else 0.5, f"random@{k}": 0.25})
            rows.append(r)
    blk = _block(pd.DataFrame(rows), "", CFG, "unit test")
    assert blk["n_truth_rings"] == 40 and blk["truth_rings_by_n_seeds_matched"] == {1: 10, 2: 30}
    f = blk["fidelity"]
    assert f["score_only"]["5"]["point"] == pytest.approx(0.75) and f["w_total"]["5"]["point"] == 1.0
    assert len(blk["comparisons"]) == 6 and all("p_holm" in c for c in blk["comparisons"].values())
    c = blk["comparisons"]["w_total vs score_only @5"]
    assert c["n_nonzero"] == 20 and c["mean_delta"] == pytest.approx(0.25)
    assert blk["verdict_at_k5"]["random"] == "positive" and blk["overall"] in ("positive", "negative")


def _fidelity_json():
    p = repo_path(CFG["output_dir"]) / CFG["fidelity_week4_name"]
    if not p.exists():
        pytest.fail(f"{p} missing: run python -m explainability.evaluate --week4")
    return json.loads(p.read_text(encoding="utf-8"))


def test_fidelity_json_point_estimates_match_the_per_seed_files_and_the_findings_are_read_not_typed():
    """W4-2/W4-5: per-seed means equal the converted fidelity files; saturation and XR-05 strength agree with the
    stored per-ring rows and the XR-05 choice file; every interval contains its point."""
    rep = _fidelity_json()
    n_inst = 0
    for s, v in rep["per_seed"].items():
        old = json.loads((repo_path(CFG["output_dir"]) / CFG["output_name_converted"].format(seed=s)).read_text())
        for name in ("score_only", "random", "w_total"):
            assert v["fidelity"][name] == old["fidelity"][name], (s, name)
        n_inst += v["n_matched"]
    sat = rep["findings"]["saturation"]
    assert sat["n_matched_ring_instances"] == n_inst == 401
    assert (sat["n_with_a_true_ranked_edge"], sat["n_only_true_edges"], sat["n_non_saturated"]) == (395, 343, 52)
    h = rep["headline"]
    assert sum(int(k) * v for k, v in h["truth_rings_by_n_seeds_matched"].items()) == h["n_ring_instances"] == 401
    assert rep["secondary_non_saturated"]["n_ring_instances"] == 52
    x5 = rep["findings"]["xr05_strength"]
    choice = json.loads((repo_path(CFG["output_dir"]) / CFG["xr05_choice_name"]).read_text())
    assert x5["leave_one_out_weight"] == choice["chosen"]["beta"] == 0.0
    assert (x5["n_validation_ring_instances_that_can_discriminate"], x5["n_validation_ring_instances_matched"]) == (89, 431)
    assert rep["xr23"]["c_literal"]["n_ring_instances_that_discriminate"] == 11
    assert rep["evaluation"]["mixing_retuned_on_test"] is False
    for blk in (h, rep["secondary_non_saturated"], rep["xr23"]["headline_b_expanded_recall"]):
        for name, by_k in blk["fidelity"].items():
            for k, ci in by_k.items():
                assert ci["lo"] - 1e-12 <= ci["point"] <= ci["hi"] + 1e-12, (blk["label"], name, k)
        for c in blk["comparisons"].values():
            assert {"p_value", "p_holm", "n_nonzero", "delta_ci"} <= set(c)


def test_fidelity_json_is_reproducible():
    """Recomputing the report gives exactly the stored file (deterministic draws, current inputs)."""
    from explainability.evaluate import week4_report
    stored = _fidelity_json()
    stored.pop("role_accuracy", None)                    # added by `evaluate --roles` (Week 5), tested separately
    again = json.loads(json.dumps(week4_report(CFG, CFG["inputs"]["seeds"]), sort_keys=True))
    assert again == stored
