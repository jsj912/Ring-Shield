"""Step 3b-z (3): legacy forward temporal_cycle vs trailing closes_cycle, per split.

    python preprocessing/gfp_cycle_flips.py            # -> docs/gfp_cycle_flips.json

Joins data/processed/amlworld_gfp_features_<split>.parquet (trailing, Step 3b-z) with
amlworld_gfp_features_<split>_legacy_forwardcycle.parquet (pre-3b-z) on EdgeID and the
split parquet's `Is Laundering`. Asserts the eight count features are bit-identical, then
reports for temporal_cycle: flips 1->0 and 0->1, both-1, the non-zero rate of each flag,
P(illicit | flag = 1) for both, the base rate, and recall of illicit edges by each flag.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA = REPO_ROOT / "data" / "processed"
OUT = REPO_ROOT / "docs" / "gfp_cycle_flips.json"
COUNTS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst", "scatter_gather",
          "gather_scatter"]


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def compare(split: str, data_dir: Path) -> dict:
    new_p = data_dir / f"amlworld_gfp_features_{split}.parquet"
    old_p = data_dir / f"amlworld_gfp_features_{split}_legacy_forwardcycle.parquet"
    new = pd.read_parquet(new_p).set_index("EdgeID")
    old = pd.read_parquet(old_p).set_index("EdgeID")
    lab = pd.read_parquet(data_dir / f"amlworld_{split}.parquet", columns=["EdgeID", "Is Laundering"]).set_index("EdgeID")
    assert new.index.equals(old.index), f"{split}: EdgeID sets differ between new and legacy parquets"
    assert lab.index.isin(new.index).all() and len(lab) == len(new)
    for c in COUNTS:
        assert (new[c].values == old.loc[new.index, c].values).all(), f"{split}: {c} changed"
    y = lab.loc[new.index, "Is Laundering"].to_numpy(np.int64)
    a = old.loc[new.index, "temporal_cycle"].to_numpy(np.int64)
    b = new["temporal_cycle"].to_numpy(np.int64)
    meta = pq.ParquetFile(new_p).schema_arrow.metadata or {}
    gfp_meta = json.loads(meta[b"gfp"]) if b"gfp" in meta else None

    def stats(flag):
        n1 = int(flag.sum())
        return {"n_flagged": n1, "rate": float(flag.mean()),
                "p_illicit_given_flag": float(y[flag == 1].mean()) if n1 else None,
                "recall_of_illicit": float(flag[y == 1].mean()),
                "lift_vs_base": float(y[flag == 1].mean() / y.mean()) if n1 else None,
                "mean_cycle_length_given_flag": None}
    s_old, s_new = stats(a), stats(b)
    s_old["mean_cycle_length_given_flag"] = float(old.loc[new.index, "cycle_length"].to_numpy()[a == 1].mean()) if a.sum() else None
    s_new["mean_cycle_length_given_flag"] = float(new["cycle_length"].to_numpy()[b == 1].mean()) if b.sum() else None
    res = {"n_edges": int(len(new)), "n_illicit": int(y.sum()), "base_rate": float(y.mean()),
           "flip_1_to_0": int(((a == 1) & (b == 0)).sum()), "flip_0_to_1": int(((a == 0) & (b == 1)).sum()),
           "both_1": int(((a == 1) & (b == 1)).sum()),
           "flip_1_to_0_illicit": int(((a == 1) & (b == 0) & (y == 1)).sum()),
           "flip_0_to_1_illicit": int(((a == 0) & (b == 1) & (y == 1)).sum()),
           "legacy_forward": s_old, "trailing_closes_cycle": s_new,
           "cycle_length_hist_new": {int(k): int(v) for k, v in
                                     zip(*np.unique(new["cycle_length"].to_numpy()[b == 1], return_counts=True))},
           "counts_identical": True, "gfp_metadata_new": gfp_meta}
    return res


def per_day(data_dir: Path) -> dict:
    """Fire rate and lift of both flags per dataset day, across all three splits.

    day = (Timestamp - 10) // 86400 in the loader basis (t = 10 is the first midnight), so
    day 0 is the first calendar day of the data. Because closes_cycle only looks back 14 d
    and the data start at day 0, the look-back is truncated for days < 14."""
    rows = []
    for split in ("train", "val", "test"):
        d = pd.read_parquet(data_dir / f"amlworld_{split}.parquet", columns=["EdgeID", "Timestamp", "Is Laundering"])
        new = pd.read_parquet(data_dir / f"amlworld_gfp_features_{split}.parquet", columns=["EdgeID", "temporal_cycle"])
        old = pd.read_parquet(data_dir / f"amlworld_gfp_features_{split}_legacy_forwardcycle.parquet",
                              columns=["EdgeID", "temporal_cycle"])
        m = d.merge(new, on="EdgeID").merge(old, on="EdgeID", suffixes=("_new", "_old"))
        m["day"] = (m["Timestamp"] - 10) // 86400
        m["split"] = split
        rows.append(m)
    m = pd.concat(rows, ignore_index=True)
    out = []
    for (day, split), g in m.groupby(["day", "split"], sort=True):
        y = g["Is Laundering"].to_numpy(np.int64)
        base = float(y.mean()) if len(y) else float("nan")
        rec = {"day": int(day), "split": split, "n_edges": int(len(g)), "n_illicit": int(y.sum()), "base_rate": base}
        for tag in ("new", "old"):
            f = g[f"temporal_cycle_{tag}"].to_numpy(np.int64)
            n1 = int(f.sum())
            p_ill = float(y[f == 1].mean()) if n1 else None
            rec[f"{tag}_rate"] = float(f.mean())
            rec[f"{tag}_n_flagged"] = n1
            rec[f"{tag}_p_illicit_given_flag"] = p_ill
            rec[f"{tag}_lift"] = (p_ill / base) if (p_ill is not None and base) else None
            rec[f"{tag}_recall_of_illicit"] = float(f[y == 1].mean()) if y.sum() else None
        out.append(rec)
    return {"definition": "per dataset day ((Timestamp - 10) // 86400); new = trailing closes_cycle, old = legacy "
                          "forward flag; lift = P(illicit | flag) / base rate of that day; look-back truncated "
                          "by the data start for days < 14",
            "rows": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    res = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "definition": "legacy = forward temporal_cycle (edges after t, unbounded); trailing = closes_cycle "
                         "(temporal path dst->...->src with edges < t, <= 5 hops, look-back 14 d). Flips on "
                         "temporal_cycle per split; the eight count columns are asserted identical.",
           "splits": {s: compare(s, args.data_dir) for s in ("train", "val", "test")},
           "per_day": per_day(args.data_dir)}
    args.out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"{'split':6s} {'edges':>10s} {'illicit':>7s} | {'old=1':>7s} {'new=1':>7s} {'both':>6s} {'1->0':>7s} {'0->1':>7s} | "
          f"{'P(ill|old)':>10s} {'P(ill|new)':>10s} {'base':>7s} | {'rec old':>7s} {'rec new':>7s} | {'len new':>7s}")
    for s, r in res["splits"].items():
        o, n = r["legacy_forward"], r["trailing_closes_cycle"]
        print(f"{s:6s} {r['n_edges']:10,d} {r['n_illicit']:7,d} | {o['n_flagged']:7,d} {n['n_flagged']:7,d} {r['both_1']:6,d} "
              f"{r['flip_1_to_0']:7,d} {r['flip_0_to_1']:7,d} | {100 * o['p_illicit_given_flag']:9.2f}% "
              f"{100 * n['p_illicit_given_flag']:9.2f}% {100 * r['base_rate']:6.3f}% | {100 * o['recall_of_illicit']:6.2f}% "
              f"{100 * n['recall_of_illicit']:6.2f}% | {n['mean_cycle_length_given_flag']:7.2f}")
    print(f"\n{'day':>3s} {'split':5s} {'edges':>8s} {'illicit':>7s} {'base':>7s} | {'new rate':>8s} {'P(ill|new)':>10s} "
          f"{'lift':>5s} {'recall':>6s} | {'old rate':>8s} {'lift':>5s} {'recall':>6s}")
    for r in res["per_day"]["rows"]:
        f = lambda v, w=6, nd=2: f"{100 * v:{w}.{nd}f}%" if v is not None else f"{'-':>{w + 1}s}"
        g = lambda v: f"{v:5.2f}" if v is not None else "    -"
        print(f"{r['day']:3d} {r['split']:5s} {r['n_edges']:8,d} {r['n_illicit']:7,d} {f(r['base_rate'], 6, 3)} | "
              f"{f(r['new_rate'])} {f(r['new_p_illicit_given_flag'], 9)} {g(r['new_lift'])} {f(r['new_recall_of_illicit'], 5, 1)} | "
              f"{f(r['old_rate'])} {g(r['old_lift'])} {f(r['old_recall_of_illicit'], 5, 1)}")
    print(f"-> {args.out}")
    return res


if __name__ == "__main__":
    main()
