"""T-P9 addendum 2 sections 2-5: threshold, convert TAML per-node predictions to rings, score, restricted recalls.

    .venv312/Scripts/python.exe evaluation/taml_convert.py --infer experiments/R15_taml/runs_seeded/<run>/infer \
        --build experiments/R15_taml/work_seeded/build_A --out experiments/R15_taml/scored_seed28

tau: score cut maximising class-1 F1 on validation steps 7-8 pooled (every observed score scanned).
joined: predicted on step 9 or 10; pieces of the name-joined undirected union graph restricted to predicted accounts.
per_step: pieces per step graph, predicted accounts of that step only.
Members: our account ids whose account_number equals a piece name (8 strings shared across banks map to all their ids).
Member edges: our test edges on days 8-9 with both endpoints in the piece and (sender, receiver, step) an edge of
TAML's graph for that step. Pieces with >= 3 names kept. Scored with evaluation/score_external.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
GDIR = "data/IBM/Graphs/Account_to_Account"
PY = str(R / ".venv312/Scripts/python.exe")


def step_edges(build: Path, t: int):
    g = torch.load(build / GDIR / f"acc_graph_{t}.pt", weights_only=False)
    names = json.loads((build / GDIR / f"names_{t}.json").read_text(encoding="utf-8"))
    ei = g.edge_index.numpy()
    return {(names[i], names[j]) for i, j in zip(ei[0], ei[1])}


def pieces(pred: set, pairs: set) -> list[set]:
    adj = defaultdict(set)
    for u, v in pairs:
        if u in pred and v in pred and u != v:
            adj[u].add(v); adj[v].add(u)
    seen, out = set(), []
    for s in sorted(pred):
        if s in seen:
            continue
        comp, stack = set(), [s]
        seen.add(s)
        while stack:
            u = stack.pop(); comp.add(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v); stack.append(v)
        if len(comp) >= 3:
            out.append(comp)
    return out


def best_tau(v: pd.DataFrame) -> tuple[float, float]:
    d = v.sort_values("score", ascending=False)
    y = d["label"].to_numpy()
    s = d["score"].to_numpy()
    tp = np.cumsum(y); k = np.arange(1, len(y) + 1)
    last = np.r_[s[1:] != s[:-1], True]  # cut only between distinct scores (ties stay together)
    f1 = np.where(last, 2 * tp / (k + y.sum()), -1)
    i = int(np.argmax(f1))
    return float(s[i]), float(f1[i])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--infer", type=Path, required=True)
    ap.add_argument("--build", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args()
    from preprocessing.account_bank import load_paths
    a.out.mkdir(parents=True, exist_ok=True)
    pdir = load_paths()["processed_dir"]

    st = {i: pd.read_parquet(a.infer / f"step{i}.parquet") for i in (7, 8, 9, 10)}
    tau, vf1 = best_tau(pd.concat([st[7], st[8]]))
    pred = {t: set(st[t].loc[st[t].score >= tau, "name"]) for t in (9, 10)}
    print(f"tau {tau:.6g} (val F1 {vf1:.4f}); predicted s9 {len(pred[9])} s10 {len(pred[10])}", flush=True)
    E = {t: step_edges(a.build, t) for t in (9, 10)}

    amap = pd.read_parquet(pdir / "account_bank.parquet")
    amap["account_number"] = amap["account_number"].astype(str)
    ids_of = amap.groupby("account_number")["account_id"].apply(list).to_dict()
    name_of = amap.set_index("account_id")["account_number"]
    te = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "from_id", "to_id", "Timestamp"])
    te["step"] = (te["Timestamp"].to_numpy() - 10) // 86400 + 1
    te = te[te.step.isin([9, 10])].copy()
    te["fa"] = name_of.reindex(te.from_id).to_numpy(); te["ta"] = name_of.reindex(te.to_id).to_numpy()
    te = te[[(f, t) in E[s] for f, t, s in zip(te.fa, te.ta, te.step)]]

    def rings(pcs: list[tuple[set, tuple]]):
        rows = []
        for k, (P, steps) in enumerate(pcs):
            mem = sorted({i for n in P for i in ids_of.get(n, [])})
            e = te[te.step.isin(steps) & te.fa.isin(P) & te.ta.isin(P)]["EdgeID"].astype(int).tolist()
            rows.append({"ring_id": k, "members": mem, "member_edges": sorted(e), "n_names": len(P)})
        return pd.DataFrame(rows)

    joined = rings([(P, (9, 10)) for P in pieces(pred[9] | pred[10], E[9] | E[10])])
    per = rings([(P, (t,)) for t in (9, 10) for P in pieces(pred[t], E[t])])
    info = {"tau": tau, "val_f1_class1": vf1, "n_pred_s9": len(pred[9]), "n_pred_s10": len(pred[10]),
            "n_rings_joined": len(joined), "n_rings_per_step": len(per),
            "rings_with_no_member_edge": {"joined": int((joined.member_edges.str.len() == 0).sum()) if len(joined) else 0,
                                          "per_step": int((per.member_edges.str.len() == 0).sum()) if len(per) else 0}}
    for nm, df in (("joined", joined), ("per_step", per)):
        f = a.out / f"rings_{nm}.parquet"
        df.drop(columns="n_names").to_parquet(f, index=False)
        subprocess.run([PY, str(R / "evaluation/score_external.py"), "--rings", str(f), "--split", "test", "--window",
                        "primary", "--thresholds", "0.3", "0.5", "0.7", "--n-boot", str(a.n_boot),
                        "--out", str(a.out / nm)], check=True)

    rep = pd.read_csv(R / "results/tables/p9_taml_representability_per_ring.csv")
    sets = {"rep63_joined": set(rep.loc[rep.matchable & (rep.conn_both >= 3), "ring_id"]),
            "rep25_s9": set(rep.loc[rep.matchable & (rep.conn_s9 >= 3), "ring_id"]),
            "rep39_s10": set(rep.loc[rep.matchable & (rep.conn_s10 >= 3), "ring_id"])}
    restricted = {}
    for nm in ("joined", "per_step"):
        ev = json.loads((a.out / nm / "evidence.json").read_text(encoding="utf-8"))["test_visible@0.5"]
        hit = dict(zip([int(str(t)) for t in ev["target_ids"]], ev["runs"][0]["matched"]))
        for sn, S in sets.items():
            restricted[f"{nm}:{sn}"] = {"n": len(S), "matched": int(sum(hit.get(r, 0) for r in S)),
                                        "recall": sum(hit.get(r, 0) for r in S) / len(S)}
    info["restricted_recall_test_visible_j05"] = restricted
    (a.out / "convert_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
