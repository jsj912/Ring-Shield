"""Implied FX rates from unlabelled pass-through accounts — SUPERSEDED, kept for the record.

    *** Use `contract/make_fx_rates.py` instead. ***

SUPERSEDED 2026-10-14. This script asked an ACCOUNT-level question — how many accounts receive in
one currency and pay out in another — and answered it correctly: 50 of 393,544. The conclusion
drawn from that answer, "no exchange rate is recoverable from the data", does NOT follow and is
withdrawn.

The rate is recorded on the EDGE. 13,627 test edges (1.58 %) carry
`Sent Currency != Received Currency` with a real amount on each side, so each one states a rate
directly, and 96.95 % of them are self-loops — one account converting. The generator's rates are
fixed: round trip and triangle close to 3e-5. `contract/make_fx_rates.py` recovers them into
`contract/fx_rates.json`; see `docs/FX_RATES.md` and `docs/PITFALLS.md` entry 3c. Found by the XAI
teammate's measurement.

Nothing below is wrong as a measurement of what it measures. It is kept so the error is traceable,
and because "a null that cannot discriminate is not a null" applies to a denominator too: the
population it searched was the wrong population.

Original header follows.


    python evaluation/fx_stability.py
    python evaluation/fx_stability.py --dataset-b data/processed_hi_medium

Why. Schema v2 withholds a role (`undetermined`) when an account's inflow and outflow currencies
do not overlap, because a balance cannot be checked without an exchange rate — 571 of 4,280
ring-accounts across 5 seeds. If a rate were known, some of those would resolve to `mule` and the
rest to something else. This estimates rates from the data itself and asks whether they are stable
enough to be trusted.

Method. Take accounts that are **single-currency in and single-currency out** with exactly one
currency on each side and at least `--min-edges` on both, pooled over the WHOLE dataset and
**excluding every ring member** (labels must play no part in estimating a rate). For each ordered
pair (cur_in -> cur_out) the implied rate is the **median** of outflow / inflow over those
accounts. Stability is then measured two ways: across days within the dataset, and between this
dataset and a second release.

Nothing here converts an amount or changes a role. The gate is explicit: unless a pair's rate is
stable, an `undetermined` account stays undetermined.

Outputs `results/tables/fx_stability.csv` and `.json`.
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

from contract.make_scored_edges import load_paths  # noqa: E402

COLS = ["EdgeID", "from_id", "to_id", "Timestamp", "Sent Currency", "Received Currency",
        "Amount Sent", "Amount Received", "ring_id"]


def load_all(pdir: Path) -> pd.DataFrame:
    frames = []
    for split in ("train", "val", "test"):
        f = pdir / f"amlworld_{split}.parquet"
        if f.exists():
            frames.append(pd.read_parquet(f, columns=COLS))
    assert frames, f"no split parquets under {pdir}"
    return pd.concat(frames, ignore_index=True)


def implied_rates(df: pd.DataFrame, *, min_edges: int, by_day: bool = False) -> pd.DataFrame:
    """Median outflow/inflow per (cur_in, cur_out) over single-currency pass-through accounts."""
    d = df[df["ring_id"] <= 0]                              # unlabelled only: no ring members
    inn = d[["to_id", "Received Currency", "Amount Received", "Timestamp"]].rename(
        columns={"to_id": "acc", "Received Currency": "cur_in", "Amount Received": "amt_in"})
    out = d[["from_id", "Sent Currency", "Amount Sent", "Timestamp"]].rename(
        columns={"from_id": "acc", "Sent Currency": "cur_out", "Amount Sent": "amt_out"})
    gi = inn.groupby("acc").agg(cur_in=("cur_in", "nunique"), one_in=("cur_in", "first"),
                                amt_in=("amt_in", "sum"), n_in=("amt_in", "size"),
                                day=("Timestamp", lambda x: int(x.min() // 86400)))
    go = out.groupby("acc").agg(cur_out=("cur_out", "nunique"), one_out=("cur_out", "first"),
                                amt_out=("amt_out", "sum"), n_out=("amt_out", "size"))
    j = gi.join(go, how="inner")
    j = j[(j["cur_in"] == 1) & (j["cur_out"] == 1) & (j["n_in"] >= min_edges) & (j["n_out"] >= min_edges)]
    j = j[(j["amt_in"] > 0) & (j["one_in"] != j["one_out"])]
    j["rate"] = j["amt_out"] / j["amt_in"]
    keys = ["one_in", "one_out"] + (["day"] if by_day else [])
    g = j.groupby(keys)["rate"].agg(n="size", median="median", q25=lambda x: x.quantile(0.25),
                                    q75=lambda x: x.quantile(0.75))
    return g.reset_index().rename(columns={"one_in": "cur_in", "one_out": "cur_out"})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-edges", type=int, default=3)
    ap.add_argument("--min-accounts", type=int, default=20, help="pairs with fewer estimates are not judged")
    ap.add_argument("--stable-iqr-ratio", type=float, default=0.10,
                    help="a pair is stable when its IQR is within this fraction of its median AND its "
                         "per-day medians vary by less than this fraction")
    ap.add_argument("--dataset-b", type=Path, default=REPO_ROOT / "data" / "processed_hi_medium",
                    help="a second release for cross-dataset stability (skipped when absent)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "fx_stability.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    pdir = load_paths()["processed_dir"]
    A = load_all(pdir)
    print(f"[fx] dataset A: {len(A):,} edges, {A['ring_id'].gt(0).sum():,} ring members excluded")
    pooled = implied_rates(A, min_edges=a.min_edges)
    daily = implied_rates(A, min_edges=a.min_edges, by_day=True)
    print(f"[fx] {len(pooled)} ordered currency pairs with any estimate; "
          f"{int((pooled['n'] >= a.min_accounts).sum())} with >= {a.min_accounts} accounts")

    rows = []
    for r in pooled.itertuples(index=False):
        sub = daily[(daily["cur_in"] == r.cur_in) & (daily["cur_out"] == r.cur_out)]
        sub = sub[sub["n"] >= max(3, a.min_edges)]
        iqr_rel = (r.q75 - r.q25) / r.median if r.median else np.nan
        day_rel = ((sub["median"].max() - sub["median"].min()) / r.median
                   if len(sub) >= 2 and r.median else np.nan)
        judged = r.n >= a.min_accounts and len(sub) >= 2
        stable = bool(judged and iqr_rel <= a.stable_iqr_ratio and day_rel <= a.stable_iqr_ratio)
        rows.append({"cur_in": int(r.cur_in), "cur_out": int(r.cur_out), "n_accounts": int(r.n),
                     "median_rate": float(r.median), "iqr_rel": float(iqr_rel) if np.isfinite(iqr_rel) else None,
                     "n_days": int(len(sub)),
                     "day_spread_rel": float(day_rel) if np.isfinite(day_rel) else None,
                     "judged": bool(judged), "stable": stable})
    d = pd.DataFrame(rows).sort_values("n_accounts", ascending=False)

    # cross-dataset
    cross = None
    if a.dataset_b.exists():
        B = load_all(a.dataset_b)
        pb = implied_rates(B, min_edges=a.min_edges)
        m = d.merge(pb.rename(columns={"median": "median_b", "n": "n_b"})[["cur_in", "cur_out", "median_b", "n_b"]],
                    on=["cur_in", "cur_out"], how="inner")
        m["rel_diff"] = (m["median_b"] - m["median_rate"]).abs() / m["median_rate"]
        cross = {"dataset_b": str(a.dataset_b), "n_pairs_shared": int(len(m)),
                 "median_rel_diff": float(m["rel_diff"].median()) if len(m) else None,
                 "pairs_within_10pct": int((m["rel_diff"] <= 0.10).sum()) if len(m) else 0}
        print(f"[fx] cross-dataset: {len(m)} shared pairs, median relative difference "
              f"{cross['median_rel_diff'] if cross['median_rel_diff'] is None else round(cross['median_rel_diff'],3)}")
    else:
        print(f"[fx] cross-dataset: SKIPPED, {a.dataset_b} not present "
              f"(HI-Medium lives on another branch; re-run there to fill this in)")

    judged = d[d["judged"]]
    verdict = ("NOT STABLE — nothing converts" if judged.empty or not judged["stable"].all()
               else "stable on every judged pair")
    print(f"\n[fx] judged pairs: {len(judged)} | stable: {int(judged['stable'].sum())} | verdict: {verdict}")
    if len(judged):
        print(judged.head(12).to_string(index=False))
    if a.dry_run:
        print("\n[fx] DRY RUN -- nothing written")
        return d
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "purpose": "REPORT ONLY -- implied FX rates are never applied; an `undetermined` account "
                    "stays undetermined until these are shown stable",
         "method": "median outflow/inflow over accounts with exactly one currency in and one out, "
                   "at least min_edges on each side, pooled over the whole dataset, RING MEMBERS "
                   "EXCLUDED so no label informs a rate",
         "thresholds": {"min_edges": a.min_edges, "min_accounts": a.min_accounts,
                        "stable_iqr_ratio": a.stable_iqr_ratio},
         "n_pairs": int(len(d)), "n_judged": int(len(judged)),
         "n_stable": int(judged["stable"].sum()) if len(judged) else 0,
         "verdict": verdict, "cross_dataset": cross,
         "if_stable_next_step": "report how many of the 571 `undetermined` ring-accounts resolve to "
                                "mule versus another role after conversion -- still report only",
         "pairs": json.loads(d.to_json(orient="records"))}, indent=2), encoding="utf-8")
    print(f"-> {a.out}")
    return d


if __name__ == "__main__":
    main()
