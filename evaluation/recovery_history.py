"""Part B (paper/PREREG_RECOVERY_2026-11-16.md): do primary-window truth rings have labelled history?
A count; no method is run.

    .venv312/Scripts/python.exe evaluation/recovery_history.py

Assumption: labels of transactions before the window are known at test time (label-delay caveat: (d) limits
history to days 0-5). Days = Timestamp // 86400; days 0-7 = train + val splits. Loss buckets per ring and seed
are read from results/tables/q0_buckets_per_ring.csv (output of evaluation/q0_loss_decomposition.py, shipped full).
Writes results/tables/recovery_history_counts.csv, recovery_history_per_ring.csv, recovery_history_cost.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

BUCKET = {"d": "matched", "a": "unobservable", "b": "matchable_untouched", "c1": "too_thin", "c2": "merged_split",
          "c3": "merged_split"}
COLS = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering", "ring_id"]


def main():
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")
    hist = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=COLS) for s in ("train", "val")])
    hist["day"] = hist["Timestamp"] // 86400
    assert hist["day"].max() <= 7, hist["day"].max()
    ill = hist[hist["Is Laundering"] == 1]

    def endpoints(df):
        """account -> set of ring ids of the illicit edges it is an endpoint of (-1 = no ring id)."""
        out: dict = {}
        for a, b, r in zip(df.from_id, df.to_id, df.ring_id.fillna(-1).astype(int)):
            out.setdefault(a, set()).add(r); out.setdefault(b, set()).add(r)
        return out
    ep_all, ep_d05 = endpoints(ill), endpoints(ill[ill.day <= 5])
    ring_first_day = (gt.groupby("ring_id").timestamp_int.min() // 86400).to_dict()

    rows = []
    for t, V in truth.items():
        b = any(x in ep_all for x in V)
        c = any(any(r != t for r in ep_all.get(x, ())) for x in V)
        d = any(x in ep_d05 for x in V)
        rows.append({"ring_id": t, "n_visible": len(V), "a_ring_before_day8": bool(ring_first_day.get(t, 99) < 8),
                     "b_member_illicit_hist": b, "c_member_hist_other_ring": c, "d_member_illicit_hist_d0_5": d})
    hr = pd.DataFrame(rows)
    q0 = pd.read_csv(R / "results/tables/q0_buckets_per_ring.csv")[["seed", "ring_id", "bucket"]]
    q0["bucket5"] = q0.bucket.map(BUCKET)
    m = q0.merge(hr, on="ring_id", how="left")
    assert m["b_member_illicit_hist"].notna().all() and len(hr) == 174
    m.to_csv(R / "results/tables/recovery_history_per_ring.csv", index=False)

    flags = ["a_ring_before_day8", "b_member_illicit_hist", "c_member_hist_other_ring", "d_member_illicit_hist_d0_5"]
    g = m.groupby(["seed", "bucket5"])
    per = g.size().rename("n_rings").to_frame().join(g[flags].sum()).reset_index()
    # fill missing buckets with zeros so the means are over 5 seeds
    full = pd.MultiIndex.from_product([sorted(m.seed.unique()), sorted(set(BUCKET.values()))], names=["seed", "bucket5"])
    per = per.set_index(["seed", "bucket5"]).reindex(full, fill_value=0).reset_index()
    tgt = per[per.bucket5.isin(["matchable_untouched", "too_thin"])].groupby("seed")[["n_rings"] + flags].sum().reset_index()
    tgt["bucket5"] = "TARGET_untouched_plus_thin"
    per = pd.concat([per, tgt], ignore_index=True)
    mean = per.groupby("bucket5")[["n_rings"] + flags].mean().reset_index().assign(seed="mean")
    out = pd.concat([per, mean], ignore_index=True)
    out.to_csv(R / "results/tables/recovery_history_counts.csv", index=False)

    # cost side: accounts active in the primary window (test days 8-9)
    te = pd.read_parquet(pdir / "amlworld_test.parquet", columns=COLS)
    te = te[W.mask(te["Timestamp"].to_numpy())]
    acc = set(te.from_id) | set(te.to_id)
    cost = {"window": list(W.bounds), "in_window_edges": int(len(te)), "in_window_illicit_edges": int(te["Is Laundering"].sum()),
            "accounts_active_in_window": len(acc), "current_in_window_seeds": 463}
    for nm, ep in (("b_days0_7", ep_all), ("d_days0_5", ep_d05)):
        H = acc & set(ep)
        e = te[te.from_id.isin(H) | te.to_id.isin(H)]
        cost[nm] = {"accounts_with_history": len(H), "in_window_edges_touching": int(len(e)),
                    "illicit_share_of_those_edges": float(e["Is Laundering"].mean()) if len(e) else float("nan"),
                    "illicit_edges_among_them": int(e["Is Laundering"].sum()),
                    "edges_added_vs_463_seeds": round(len(e) / 463, 2)}
    bar = float(mean.loc[mean.bucket5 == "TARGET_untouched_plus_thin", "b_member_illicit_hist"].iloc[0])
    tgt_n = float(mean.loc[mean.bucket5 == "TARGET_untouched_plus_thin", "n_rings"].iloc[0])
    cost["bar"] = {"target_rings_per_seed_mean": tgt_n, "with_history_b_per_seed_mean": bar, "threshold": 8,
                   "verdict": "not worth building" if bar < 8 else "above bar: author decision"}
    (R / "results/tables/recovery_history_cost.json").write_text(json.dumps(cost, indent=2), encoding="utf-8")
    print(out[out.seed.astype(str) == "mean"].round(2).to_string(index=False))
    print(json.dumps(cost, indent=2))


if __name__ == "__main__":
    main()
