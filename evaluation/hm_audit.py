"""Replicate the HI-Small benchmark audit on HI-Medium, with no new training (runbook T-P4).

    set RINGSHIELD_PATHS=<HI-Medium paths yaml>
    python evaluation/hm_audit.py --exp-dir E:/JSJ/Ring-Shield/experiments_hi_medium --out results/tables
    # HI-Small cross-check through the same code path (default paths file):
    python evaluation/hm_audit.py --hi-small-check --rings ../RS-e2e/experiments/R4_partition/runs/average/seed{1..5}/rings.parquet --out <dir>

Inputs: the Amendment-15 close-out rings `<rings-dir>/primary/<rule>/<method>/seed<S>.parquet`
(rules global and per_day; methods b0, b1b, proposed = expansion-only, full), HI-Medium seeds 1-2,
primary window = test days 6-14 (Amendment 15, as evaluation/hm_closeout_report.py builds it).
Scoring uses evaluation/score_external.py (build_targets, score), the T-P1 protocol scorer; rings are
scored as written (no extra min-size filter), so `test_visible` rows equal the close-out report.

Writes only under --out:
  v41_hm_audit_scope.csv      P/R/F1 + CI per rule x method under test_visible and full_membership, the
                              gap, and the median target size under each convention
  v41_hm_audit_component.csv  observability counts; ring-F1 under component / component_ge3; orderings
  v41_hm_audit_threshold.csv  full - expansion-only ring recall and ring-F1 at Jaccard 0.3 / 0.5 / 0.7
  v41_hm_audit_tail.csv       per test day: edges, laundering base rate, share of global-quantile seeds
  v41_hm_audit.json           everything above plus provenance and the three bar verdicts
Every table carries the invariant-11 note (seed 3 excluded; adequacy bar) in a `note` column.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.score_external import build_targets, load_predictions, load_split_edges, score, sha256  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import seed_mask_for_pct  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.windows import Window, load_windows  # noqa: E402

RULES = ("global", "per_day")
METHODS = ("b0", "b1b", "proposed", "full")
THRESHOLDS = (0.3, 0.5, 0.7)
CONVENTIONS = ("test_visible", "full_membership", "component", "component_ge3")
NOTE = ("HI-Medium seeds 1-2 only: seed 3 is excluded (saturated scores, docs/V3_HIMEDIUM_PREREG.md dated note); "
        "the detector did not meet the pre-registered adequacy bar on HI-Medium, so these rows are an audit "
        "replication, not a method comparison (invariant 11).")
HS_OBS = {"n_in_scope_rings": 174, "rings_no_in_window_piece_ge3": 77}
HS_GAP_FULL = -0.347


def hm_primary() -> Window:
    P0 = load_windows(REPO_ROOT / "configs" / "eval_window_hi_medium.yaml")["primary"]
    return Window("primary", "test", 6, 14, P0.day_zero, P0.seconds_per_day)


def median_size(targets: dict) -> float:
    return float(np.median([len(v) for v in targets.values()])) if targets else float("nan")


def score_runs(paths, edges, targets, W, n_boot, conventions=CONVENTIONS):
    runs = [load_predictions(p, edges, 0)[0] for p in paths]
    rows, _ = score(runs, edges, targets, W, list(THRESHOLDS), n_boot, 0, conventions=list(conventions))
    return {(r["convention"], r["threshold"]): r for r in rows}


def hi_small_check(a) -> dict:
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    edges = load_split_edges("test", pdir)
    targets, obs = build_targets(pdir / "amlworld_ring_ground_truth.parquet", W)
    res = score_runs(a.rings, edges, targets, W, a.n_boot, conventions=("test_visible", "full_membership"))
    gap = res[("full_membership", 0.5)]["ring_f1"] - res[("test_visible", 0.5)]["ring_f1"]
    out = {"observability": obs, "gap_full_membership_minus_test_visible": gap,
           "matches_77_of_174": obs["n_in_scope_rings"] == 174 and obs["rings_no_in_window_piece_ge3"] == 77,
           "matches_r14_gap": abs(gap - HS_GAP_FULL) < 5e-4}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "hi_small_check.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp-dir", type=Path, help="holds R1_gine_causal_c1prime/scores_test_seed<S>.parquet")
    ap.add_argument("--rings-dir", type=Path, default=REPO_ROOT / "experiments_hi_medium" / "closeout_a15")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--seed-frac-pct", type=float, default=0.1, help="global seed budget (close-out k*)")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--hi-small-check", action="store_true")
    ap.add_argument("--rings", type=Path, nargs="+", help="--hi-small-check: HI-Small full rings, one per seed")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.hi_small_check:
        return hi_small_check(a)

    paths = load_paths()
    assert paths.get("dataset") == "HI-Medium", f"RINGSHIELD_PATHS must select HI-Medium, got {paths.get('dataset')}"
    pdir = paths["processed_dir"]
    gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = hm_primary()
    edges = load_split_edges("test", pdir)
    targets, obs = build_targets(gt, W)
    sizes = {c: median_size(targets[c][0]) for c in CONVENTIONS}
    print(f"[hm_audit] primary days 6-14: {obs}", flush=True)

    res = {}
    for rule in RULES:
        for m in METHODS:
            files = [a.rings_dir / "primary" / rule / m / f"seed{s}.parquet" for s in a.seeds]
            res[(rule, m)] = score_runs(files, edges, targets, W, a.n_boot)
            r = res[(rule, m)]
            print(f"  {rule:7s} {m:8s} tv F1 {r[('test_visible', 0.5)]['ring_f1']:.4f}  fm F1 "
                  f"{r[('full_membership', 0.5)]['ring_f1']:.4f}  comp>=3 F1 {r[('component_ge3', 0.5)]['ring_f1']:.4f}",
                  flush=True)

    # ---- scope
    scope_rows = []
    for (rule, m), r in res.items():
        tv, fm = r[("test_visible", 0.5)], r[("full_membership", 0.5)]
        row = {"rule": rule, "method": m}
        for tag, x in (("tv", tv), ("fm", fm)):
            for k in ("ring_precision", "ring_recall", "ring_f1"):
                row[f"{tag}_{k}"], row[f"{tag}_{k}_lo"], row[f"{tag}_{k}_hi"] = x[k], x[f"{k}_lo"], x[f"{k}_hi"]
        row.update({"gap_f1_fm_minus_tv": fm["ring_f1"] - tv["ring_f1"], "n_targets": tv["n_targets"],
                    "median_target_size_tv": sizes["test_visible"], "median_target_size_fm": sizes["full_membership"],
                    "note": NOTE})
        scope_rows.append(row)
    scope = pd.DataFrame(scope_rows)
    verdict_scope = {}
    for rule in RULES:
        s = scope[scope.rule == rule].set_index("method")
        effect = abs(s.loc["full", "tv_ring_f1"] - s.loc["b0", "tv_ring_f1"])
        gaps = s["gap_f1_fm_minus_tv"]
        verdict_scope[rule] = {"all_gaps_negative": bool((gaps < 0).all()), "min_abs_gap": float(gaps.abs().min()),
                               "largest_method_effect_full_minus_b0": float(effect),
                               "reproduced": bool((gaps < 0).all() and gaps.abs().min() > effect)}

    # ---- component
    comp_rows = []
    for (rule, m), r in res.items():
        comp_rows.append({"rule": rule, "method": m,
                          "ring_f1_component": r[("component", 0.5)]["ring_f1"],
                          "ring_f1_component_ge3": r[("component_ge3", 0.5)]["ring_f1"],
                          "recall_component_ge3": r[("component_ge3", 0.5)]["ring_recall"],
                          "ring_f1_test_visible": r[("test_visible", 0.5)]["ring_f1"],
                          **{f"obs_{k}": v for k, v in obs.items()}, "note": NOTE})
    comp = pd.DataFrame(comp_rows)
    order = {}
    for rule in RULES:
        c = comp[comp.rule == rule].set_index("method")
        for conv in ("test_visible", "component", "component_ge3"):
            v = c[f"ring_f1_{conv}"]
            order[f"{rule}/{conv}"] = {"ascending_b0_b1b_proposed_full": bool(v["b0"] < v["b1b"] < v["proposed"] < v["full"]),
                                       "proposed_gt_full": bool(v["proposed"] > v["full"]),
                                       "order_low_to_high": v.sort_values().index.tolist()}
    share_no_piece = obs["rings_no_in_window_piece_ge3"] / obs["n_in_scope_rings"]
    hs_share = HS_OBS["rings_no_in_window_piece_ge3"] / HS_OBS["n_in_scope_rings"]
    verdict_obs = {"hm_share": share_no_piece, "hs_share": hs_share, "diff_pp": 100 * (share_no_piece - hs_share),
                   "within_15pp": bool(abs(share_no_piece - hs_share) <= 0.15)}

    # ---- threshold
    th_rows, verdict_thr = [], {}
    for rule in RULES:
        f, p = res[(rule, "full")], res[(rule, "proposed")]
        g = {}
        for tau in THRESHOLDS:
            d_r = f[("test_visible", tau)]["ring_recall"] - p[("test_visible", tau)]["ring_recall"]
            d_f = f[("test_visible", tau)]["ring_f1"] - p[("test_visible", tau)]["ring_f1"]
            g[tau] = d_r
            th_rows.append({"rule": rule, "threshold": tau, "full_ring_recall": f[("test_visible", tau)]["ring_recall"],
                            "expansion_only_ring_recall": p[("test_visible", tau)]["ring_recall"],
                            "gain_ring_recall": d_r, "gain_ring_f1": d_f, "note": NOTE})
        verdict_thr[rule] = {"gain_0.3": g[0.3], "gain_0.7": g[0.7],
                             "reproduced": bool(g[0.7] < 0.5 * g[0.3]) if g[0.3] > 0 else False}
    thr = pd.DataFrame(th_rows)

    # ---- tail and budget (whole test split, global quantile)
    test = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "Timestamp", "Is Laundering"])
    day = ((test["Timestamp"].to_numpy() - W.day_zero) // W.seconds_per_day).astype(int)
    tail = pd.DataFrame({"day": day, "y": test["Is Laundering"].to_numpy()}).groupby("day").agg(edges=("y", "size"), base_rate=("y", "mean"))
    for s in a.seeds:
        se = build_scored_edges(a.exp_dir / "R1_gine_causal_c1prime" / f"scores_test_seed{s}.parquet", "test",
                                model_id="gine_causal", seed=s, processed_dir=pdir)
        mask = seed_mask_for_pct(se["score_raw"].to_numpy(float), a.seed_frac_pct)
        d = ((se["timestamp"].to_numpy() - W.day_zero) // W.seconds_per_day).astype(int)
        cnt = pd.Series(d[mask]).value_counts()
        tail[f"global_seeds_seed{s}"] = cnt.reindex(tail.index).fillna(0).astype(int)
        tail[f"global_seed_share_seed{s}"] = tail[f"global_seeds_seed{s}"] / max(int(mask.sum()), 1)
    tail = tail.reset_index()
    tail["note"] = NOTE

    a.out.mkdir(parents=True, exist_ok=True)
    scope.to_csv(a.out / "v41_hm_audit_scope.csv", index=False)
    comp.to_csv(a.out / "v41_hm_audit_component.csv", index=False)
    thr.to_csv(a.out / "v41_hm_audit_threshold.csv", index=False)
    tail.to_csv(a.out / "v41_hm_audit_tail.csv", index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
            "dataset": paths.get("dataset"), "processed_dir": str(pdir), "ground_truth_sha256": sha256(gt),
            "rings_dir": str(a.rings_dir), "exp_dir": str(a.exp_dir), "seeds": a.seeds, "window": "test days 6-14 (Amendment 15)",
            "n_boot": a.n_boot, "observability": obs, "median_target_size": sizes, "orderings": order,
            "verdicts": {"scope": verdict_scope, "observability": verdict_obs, "threshold": verdict_thr},
            "HM_AUDIT": "REPRODUCED" if verdict_scope["global"]["reproduced"] else "NOT_REPRODUCED", "note": NOTE}
    (a.out / "v41_hm_audit.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(json.dumps(meta["verdicts"], indent=2, default=str))
    print(f"HM_AUDIT={meta['HM_AUDIT']}  -> {a.out}")
    return meta


if __name__ == "__main__":
    main()
