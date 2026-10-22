"""Collect the tenant-visible score logs into experiments/R10_tenant_visible/summary.csv.

One row per tenant x seed, test split. Labels were read for REPORTING only (edge-level AP); nothing
was tuned or selected on them. Which set a tenant belongs to (primary / robustness) is recorded
from the registration in docs/TENANT_SIZES.md (2026-10-22).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from contract.make_scored_edges import load_paths  # noqa: E402

PRIMARY = (1, 20, 11, 118, 12)
ROBUSTNESS = (70, 12, 11, 1, 10)


def ring_visibility(tenants) -> dict[int, tuple[int, int]]:
    """DESCRIPTIVE ONLY, no rule depends on it. Per tenant: (in-scope truth rings, how many of them
    have >= 1 laundering edge visible to the tenant). In scope = the 174 primary-window rings under
    test_visible; a ring's laundering edges are its ground-truth pattern edges inside the window; an
    edge is visible to T when either endpoint's home bank is T (from_bank == T or to_bank == T)."""
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    paths = load_paths()
    lo, hi = load_windows()["primary"].bounds
    gt_path = paths["processed_dir"] / "amlworld_ring_ground_truth.parquet"
    truth, _ = load_ground_truth(gt_path, lo, hi, "test_visible", verbose=False)
    gt = pd.read_parquet(gt_path, columns=["ring_id", "from_id", "to_id", "timestamp_int"])
    gt = gt[gt["timestamp_int"].between(lo, hi) & gt["ring_id"].isin(set(int(r) for r in truth))]
    amap = pd.read_parquet(paths["processed_dir"] / "account_bank.parquet").set_index("account_id")["bank_code"]
    gt = gt.assign(fb=amap.reindex(gt["from_id"]).to_numpy(), tb=amap.reindex(gt["to_id"]).to_numpy())
    out = {}
    for t in tenants:
        vis = gt[(gt["fb"] == t) | (gt["tb"] == t)]
        out[int(t)] = (len(truth), int(vis["ring_id"].nunique()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores-root", type=Path, required=True)
    ap.add_argument("--model-id", default="gine_causal")
    a = ap.parse_args(argv)
    rows = []
    for f in sorted(a.scores_root.glob(f"scored_edges_visible_*_{a.model_id}_[1-5].parquet.log.json")):
        lg = json.loads(f.read_text(encoding="utf-8"))
        v = lg["vs_pooled"]
        t = int(lg["tenant_id"])
        rows.append({"tenant_id": t, "seed": int(lg["seed"]),
                     "set": "+".join(n for n, s in (("primary", PRIMARY), ("robustness", ROBUSTNESS)) if t in s),
                     "n_visible_test_edges": v["n_edges"], "n_positive_edges": v["n_positive_edges"],
                     "n_seeds_fixed_cutoff": v["n_seeds_fixed_cutoff"], "n_seeds_pooled_visible": v["n_seeds_pooled_visible"],
                     "spearman_vs_pooled": v["spearman_vs_pooled"], "seed_jaccard_vs_pooled": v["seed_jaccard_vs_pooled"],
                     "ap_pooled": v["ap_pooled"], "ap_tenant_visible": v["ap_tenant_visible"],
                     "cutoff_q": lg["seed_rule"]["q"], "log": f.name})
    df = pd.DataFrame(rows).sort_values(["tenant_id", "seed"])
    rv = ring_visibility(sorted(df["tenant_id"].unique()))
    df["n_in_scope_truth_rings"] = df["tenant_id"].map(lambda t: rv[int(t)][0])
    df["n_in_scope_rings_with_visible_laundering_edge"] = df["tenant_id"].map(lambda t: rv[int(t)][1])
    out = load_paths()["experiments_dir"] / "R10_tenant_visible" / "summary.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{len(df)} rows -> {out}")
    print(df.groupby("tenant_id").agg(set=("set", "first"), seeds_b=("n_seeds_fixed_cutoff", "mean"),
                                      seeds_pooled=("n_seeds_pooled_visible", "mean"), rho=("spearman_vs_pooled", "mean"),
                                      jac=("seed_jaccard_vs_pooled", "mean"), ap_pooled=("ap_pooled", "mean"),
                                      ap_b=("ap_tenant_visible", "mean"), pos=("n_positive_edges", "first"),
                                      rings_in_scope=("n_in_scope_truth_rings", "first"),
                                      rings_visible=("n_in_scope_rings_with_visible_laundering_edge", "first")).round(4).to_string())


if __name__ == "__main__":
    main()
