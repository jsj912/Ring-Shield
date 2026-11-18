"""Part B2 (paper/PREREG_RECOVERY_AMENDMENT_2026-11-16.md): history-reserved seeds for shipped Multi-GINe.

    .venv312/Scripts/python.exe evaluation/history_seeds.py counts            # step 0, descriptive
    .venv312/Scripts/python.exe evaluation/history_seeds.py build [--test-history-days 0-7|0-5]

`build` writes experiments/R17_history_seeds/<cell>[_testhist05]/ with scores_{val,test}_seed<S>.parquet in which
the round(r*K) reserved edges (highest-scored edges meeting the endpoint rule against H) have score_raw lifted above
the split maximum (order kept); every other column and edge is unchanged. Embeddings/checkpoint are hard-linked.
History H is strictly earlier than the scored split: val (days 6-7) <- labels days 0-5; test (8-9) <- days 0-7
(or 0-5 for the label-delay sensitivity). See history_set().
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

GINE = R.parent / "RS-e2e" / "experiments" / "R1_gine_causal"
OUT = R / "experiments" / "R17_history_seeds"
DAY = 86400
CELLS = [(r, e) for r in (0.10, 0.25, 0.50) for e in ("one", "both")]
LINKED = ["embeddings_val_seed{S}.parquet", "embeddings_test_seed{S}.parquet", "model_best_seed{S}.pt"]


def cell_name(r: float, e: str) -> str:
    return f"r{int(round(r * 100)):02d}_{e}"


def load_history_edges(pdir: Path) -> pd.DataFrame:
    cols = ["from_id", "to_id", "Timestamp", "Is Laundering"]
    h = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=cols) for s in ("train", "val")])
    return h[h["Is Laundering"] == 1]


def history_set(illicit: pd.DataFrame, last_day: int, scored_split_start_ts: int) -> set:
    """Endpoints of labelled-illicit edges on days 0..last_day. Raises if any such edge is at or after the scored
    split's first second (no label from inside or after the scored window may enter)."""
    h = illicit[illicit["Timestamp"] // DAY <= last_day]
    if len(h) and int(h["Timestamp"].max()) >= scored_split_start_ts:
        raise ValueError(f"history leaks into the scored window: max ts {int(h['Timestamp'].max())} >= {scored_split_start_ts}")
    return set(h["from_id"]) | set(h["to_id"])


def reserved_mask(se: pd.DataFrame, H: set, r: float, endpoint: str, k_pct: float = 0.1) -> tuple[np.ndarray, int]:
    """Boolean mask of the reserved edges: the round(r*K) highest-scored edges meeting the endpoint rule."""
    K = int(seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct).sum())
    n_res = int(round(r * K))
    f, t = se["from_id"].isin(H).to_numpy(), se["to_id"].isin(H).to_numpy()
    elig = (f | t) if endpoint == "one" else (f & t)
    idx = np.flatnonzero(elig)
    top = idx[np.argsort(-se[SELECT_COL].to_numpy(float)[idx], kind="stable")[:n_res]]
    m = np.zeros(len(se), bool)
    m[top] = True
    return m, K


def lifted_scores(sc: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    """Lift masked edges' score_raw above the split max, keeping their relative order; all else unchanged."""
    out = sc.copy()
    s = out["score_raw"].to_numpy(float).copy()
    hi = float(s.max())
    s[mask] = hi + 1.0 + (s[mask] - s[mask].min()) if mask.any() else s[mask]
    out["score_raw"] = s
    return out


def _endpoints(pdir: Path, split: str) -> pd.DataFrame:
    return pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=["EdgeID", "from_id", "to_id"]).rename(columns={"EdgeID": "edge_id"})


def cmd_build(a):
    pdir = load_paths()["processed_dir"]
    ill = load_history_edges(pdir)
    start = {s: int(pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=["Timestamp"])["Timestamp"].min()) for s in ("val", "test")}
    test_last = {"0-7": 7, "0-5": 5}[a.test_history_days]
    H = {"val": history_set(ill, 5, start["val"]), "test": history_set(ill, test_last, start["test"])}
    ends = {s: _endpoints(pdir, s) for s in ("val", "test")}
    suffix = "" if a.test_history_days == "0-7" else "_testhist05"
    meta = {"H_size": {k: len(v) for k, v in H.items()}, "test_history_days": a.test_history_days, "cells": {}}
    for r, e in CELLS:
        name = cell_name(r, e) + suffix
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        for S in a.seeds:
            for split in ("val", "test"):
                sc = pd.read_parquet(GINE / f"scores_{split}_seed{S}.parquet")
                se = sc[["edge_id", "score_raw"]].merge(ends[split], on="edge_id", how="left")
                assert se["from_id"].notna().all()
                m, K = reserved_mask(se, H[split], r, e)
                lifted_scores(sc, m).to_parquet(d / f"scores_{split}_seed{S}.parquet", index=False)
                meta["cells"].setdefault(name, {})[f"{split}_seed{S}"] = {"K": K, "reserved": int(m.sum())}
            for pat in LINKED:
                src, dst = GINE / pat.format(S=S), d / pat.format(S=S)
                if src.exists() and not dst.exists():
                    os.link(src, dst)
        print(name, meta["cells"][name], flush=True)
    (OUT / f"build{suffix}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def cmd_counts(a):
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    ill = load_history_edges(pdir)
    te_start = int(pd.read_parquet(pdir / "amlworld_test.parquet", columns=["Timestamp"])["Timestamp"].min())
    te = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering"])
    rows = []
    for hname, last in (("b_days0_7", 7), ("d_days0_5", 5)):
        H = history_set(ill, last, te_start)
        for S in a.seeds:
            sc = pd.read_parquet(GINE / f"scores_test_seed{S}.parquet", columns=["edge_id", "score_raw"])
            d = te.merge(sc, left_on="EdgeID", right_on="edge_id")
            q = d["score_raw"].rank(pct=True, method="average")
            win = W.mask(d["Timestamp"].to_numpy())
            touch = (d.from_id.isin(H) | d.to_id.isin(H)).to_numpy() & win
            for lab, sel in (("all", touch), ("top1pct", touch & (q > 0.99).to_numpy()), ("top0.5pct", touch & (q > 0.995).to_numpy())):
                n, k = int(sel.sum()), int(d["Is Laundering"].to_numpy()[sel].sum())
                rows.append({"history": hname, "seed": S, "subset": lab, "edges": n, "illicit": k, "illicit_share": k / n if n else np.nan})
    df = pd.DataFrame(rows)
    mean = df.groupby(["history", "subset"])[["edges", "illicit", "illicit_share"]].mean().reset_index().assign(seed="mean")
    df = pd.concat([df, mean], ignore_index=True)
    df.to_csv(R / "results/tables/recovery_history_topk.csv", index=False)
    print(mean.round(4).to_string(index=False))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["counts", "build"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--test-history-days", choices=["0-7", "0-5"], default="0-7")
    a = ap.parse_args(argv)
    {"counts": cmd_counts, "build": cmd_build}[a.cmd](a)


if __name__ == "__main__":
    main()
