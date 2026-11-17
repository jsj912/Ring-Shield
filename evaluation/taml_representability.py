"""T-P9 addendum (2026-11-17) steps 1-2: repeatability check of the seeded TAML rebuild and the representability count.

    .venv312/Scripts/python.exe evaluation/taml_representability.py \
        --build-a experiments/R15_taml/work_seeded/build_A --build-b experiments/R15_taml/work_seeded/build_B

Primary window = our days 8-9 = TAML steps 9-10. Truth: the 174 test_visible rings; matchable: the 97 with an in-window
connected piece of >= 3 accounts. Accounts are compared as account strings (TAML's key).
Writes results/tables/p9_taml_representability_per_ring.csv and results/tables/p9_taml_representability.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
STEPS = (9, 10)
GDIR = "data/IBM/Graphs/Account_to_Account"


def load_step(build: Path, t: int):
    g = torch.load(build / GDIR / f"acc_graph_{t}.pt", weights_only=False)
    names = json.loads((build / GDIR / f"names_{t}.json").read_text(encoding="utf-8"))
    return g, names


def repeatable(a: Path, b: Path) -> dict:
    out = {}
    for t in range(1, 11):
        ga, na = load_step(a, t)
        gb, nb = load_step(b, t)
        same = {k: bool(torch.equal(getattr(ga, k), getattr(gb, k))) for k in ("x", "y", "edge_index", "edge_attr", "n_id")}
        same["names"] = na == nb
        out[t] = {"identical": all(same.values()), **same, "nodes": int(ga.num_nodes), "edges": int(ga.edge_index.shape[1])}
    return out


def big_component(members: set, adj: dict) -> int:
    seen, best = set(), 0
    for m in members:
        if m in seen:
            continue
        stack, size = [m], 0
        seen.add(m)
        while stack:
            u = stack.pop()
            size += 1
            for v in adj.get(u, ()):
                if v in members and v not in seen:
                    seen.add(v)
                    stack.append(v)
        best = max(best, size)
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-a", type=Path, required=True)
    ap.add_argument("--build-b", type=Path, required=True)
    a = ap.parse_args()
    from evaluation.component_scope import component_truth
    from preprocessing.account_bank import load_paths
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows

    rep = repeatable(a.build_a, a.build_b)
    print(json.dumps(rep, indent=1))
    if not all(v["identical"] for v in rep.values()):
        sys.exit("STOP: the two seeded builds differ")

    pdir = load_paths()["processed_dir"]
    gt_path = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(gt_path, *W.bounds, "test_visible", verbose=False)
    gt = pd.read_parquet(gt_path)
    comp3, _, _ = component_truth(truth, patterns, gt, W, min_members=3)
    matchable = {k[0] for k in comp3}
    assert len(truth) == 174 and len(matchable) == 97, (len(truth), len(matchable))
    name = pd.read_parquet(pdir / "account_bank.parquet").set_index("account_id")["account_number"].astype(str)

    nodes, adj, pairs = {}, {}, {}
    adj_u = defaultdict(set)
    for t in STEPS:
        g, names = load_step(a.build_a, t)
        nodes[t] = set(names)
        ei = g.edge_index.numpy()
        s = [names[i] for i in ei[0]]
        d = [names[i] for i in ei[1]]
        pairs[t] = set(zip(s, d))
        adj[t] = defaultdict(set)
        for u, v in zip(s, d):
            adj[t][u].add(v); adj[t][v].add(u)
            adj_u[u].add(v); adj_u[v].add(u)
    union_nodes = nodes[9] | nodes[10]

    g_in = gt[gt["ring_id"].isin(truth) & W.mask(gt["timestamp_int"].to_numpy())].copy()
    g_in["step"] = (g_in["timestamp_int"].to_numpy() - 10) // 86400 + 1
    assert set(g_in["step"]) <= set(STEPS)
    g_in["fa"] = name.reindex(g_in["from_id"]).to_numpy()
    g_in["ta"] = name.reindex(g_in["to_id"]).to_numpy()
    g_in["survives"] = [(f, to) in pairs[st] for f, to, st in zip(g_in["fa"], g_in["ta"], g_in["step"])]
    surv = g_in.groupby("ring_id")["survives"].agg(["sum", "size"])

    rows = []
    for rid, V in truth.items():
        M = {name[m] for m in V}
        r = {"ring_id": rid, "pattern_type": patterns.get(rid, "?"), "matchable": rid in matchable, "n_members": len(M)}
        for t, key in ((9, "s9"), (10, "s10")):
            P = M & nodes[t]
            r[f"present_{key}"] = len(P)
            r[f"conn_{key}"] = big_component(P, adj[t])
        P = M & union_nodes
        r["present_either"] = len(P)
        r["share_present_either"] = len(P) / len(M)
        r["conn_both"] = big_component(P, adj_u)
        r["tx_in_window"] = int(surv.loc[rid, "size"]) if rid in surv.index else 0
        r["tx_survive"] = int(surv.loc[rid, "sum"]) if rid in surv.index else 0
        rows.append(r)
    df = pd.DataFrame(rows)

    def summ(d):
        return {"n_rings": len(d),
                "members_total": int(d.n_members.sum()), "members_present_either": int(d.present_either.sum()),
                "share_present_median": float(d.share_present_either.median()),
                "share_present_mean": float(d.share_present_either.mean()),
                "rings_ge3_present_s9": int((d.present_s9 >= 3).sum()), "rings_ge3_present_s10": int((d.present_s10 >= 3).sum()),
                "rings_ge3_present_either": int((d.present_either >= 3).sum()),
                "rings_ge3_connected_s9": int((d.conn_s9 >= 3).sum()), "rings_ge3_connected_s10": int((d.conn_s10 >= 3).sum()),
                "rings_ge3_connected_both": int((d.conn_both >= 3).sum()),
                "rings_zero_present": int((d.present_either == 0).sum()),
                "tx_in_window": int(d.tx_in_window.sum()), "tx_survive": int(d.tx_survive.sum()),
                "tx_survive_share": float(d.tx_survive.sum() / max(d.tx_in_window.sum(), 1))}
    res = {"addendum": "paper/PREREG_TP9_ADDENDUM_2026-11-17.md", "seed": 20261117, "repeatability": rep,
           "graph_sizes": {t: {"nodes": len(nodes[t]), "edges": len(pairs[t])} for t in STEPS},
           "all_174": summ(df), "matchable_97": summ(df[df.matchable])}
    m = res["matchable_97"]["rings_ge3_connected_both"]
    res["gate"] = {"statistic": m, "of": 97, "share": m / 97, "bar_share": 0.60,
                   "outcome": "NO-GO" if m / 97 < 0.60 else "GO-to-author (stop and report)"}
    df.to_csv(R / "results/tables/p9_taml_representability_per_ring.csv", index=False)
    (R / "results/tables/p9_taml_representability.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "repeatability"}, indent=1, default=str))


if __name__ == "__main__":
    main()
