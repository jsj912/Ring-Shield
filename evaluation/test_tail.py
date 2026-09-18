"""Step 3b-w: quantify the test-period tail (days >= 10). Read-only.

    python evaluation/test_tail.py                    # parts 1-3 (seconds) -> docs/test_tail.json
    python evaluation/test_tail.py --neighbourhood    # + part 4 (loads the graph, ~20 min)

Day = (Timestamp - 10) // 86400 in the loader basis (day 0 = first calendar day; train = days
0-5, val = 6-7, test = 8-17). "Tail" = test edges on days >= --tail-from (default 10).

1. per day of test and val: edges, illicit, base rate, cumulative share of the split's positives
2. test-visible rings (models.ring_aggregator.load_ground_truth, policy test_visible): rings with
   >= 1 / all visible edges in the tail, distribution of the tail fraction, per pattern type
3. detectability on the legacy-feature R1 seed-1 test scores (--scores-dir, --seed): AP and
   P@R=0.5 for days 8-9 vs the tail, share of tail edges above the val-chosen threshold; and the
   trivial baseline score = 1[day >= tail_from] on the whole split (F1, AP, precision, recall)
4. neighbourhood sparsity: mean hop-1 sampled neighbours per seed edge in both stores of the
   causal loader (tests/measure_window_leak.measure) for days 8-9 vs the tail
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
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, precision_score, recall_score

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.edge_metrics import choose_threshold, load_scores_with_labels  # noqa: E402
from models.ring_aggregator import load_ground_truth  # noqa: E402

DATA = REPO_ROOT / "data" / "processed"
GT = DATA / "amlworld_ring_ground_truth.parquet"
OUT = REPO_ROOT / "docs" / "test_tail.json"
T0 = 10  # loader basis: first midnight


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def day_of(ts) -> np.ndarray:
    return ((np.asarray(ts, dtype=np.int64) - T0) // 86400).astype(np.int64)


def per_day(split: str) -> list[dict]:
    d = pd.read_parquet(DATA / f"amlworld_{split}.parquet", columns=["Timestamp", "Is Laundering"])
    d["day"] = day_of(d["Timestamp"])
    n_pos = int(d["Is Laundering"].sum())
    rows, cum = [], 0
    for day, g in d.groupby("day", sort=True):
        k = int(g["Is Laundering"].sum())
        cum += k
        rows.append({"day": int(day), "n_edges": int(len(g)), "n_illicit": k, "base_rate": float(g["Is Laundering"].mean()),
                     "cum_share_of_positives": cum / n_pos if n_pos else None})
    return rows


def rings(tail_from: int) -> dict:
    te = pd.read_parquet(DATA / "amlworld_test.parquet", columns=["Timestamp"])
    t_min, t_max = int(te["Timestamp"].min()), int(te["Timestamp"].max())
    truth, patterns = load_ground_truth(GT, t_min, t_max, "test_visible")
    gt = pd.read_parquet(GT)
    vis = gt[(gt["timestamp_int"] >= t_min) & (gt["timestamp_int"] <= t_max) & gt["ring_id"].isin(truth.keys())].copy()
    vis["day"] = day_of(vis["timestamp_int"])
    vis["tail"] = vis["day"] >= tail_from
    per_ring = vis.groupby("ring_id").agg(n_visible=("tail", "size"), n_tail=("tail", "sum"),
                                          pattern=("pattern_type", "first"))
    per_ring["tail_frac"] = per_ring["n_tail"] / per_ring["n_visible"]
    bins = [0, 1e-9, 0.25, 0.5, 0.75, 1 - 1e-9, 1.0001]
    labels = ["0", "(0,0.25]", "(0.25,0.5]", "(0.5,0.75]", "(0.75,1)", "1"]
    hist = pd.cut(per_ring["tail_frac"], bins=bins, labels=labels, right=True, include_lowest=True).value_counts().reindex(labels)
    by_pat = per_ring.groupby("pattern").agg(rings=("n_visible", "size"), any_tail=("n_tail", lambda s: int((s > 0).sum())),
                                              all_tail=("tail_frac", lambda s: int((s >= 1).sum())),
                                              mean_tail_frac=("tail_frac", "mean"),
                                              visible_edges=("n_visible", "sum"), tail_edges=("n_tail", "sum"))
    return {"n_rings_test_visible": int(len(per_ring)), "t_min": t_min, "t_max": t_max,
            "n_visible_edges": int(per_ring["n_visible"].sum()), "n_visible_edges_in_tail": int(per_ring["n_tail"].sum()),
            "rings_with_any_tail_edge": int((per_ring["n_tail"] > 0).sum()),
            "rings_with_all_edges_in_tail": int((per_ring["tail_frac"] >= 1).sum()),
            "tail_fraction_hist": {k: int(v) for k, v in hist.items()},
            "tail_fraction": {"mean": float(per_ring["tail_frac"].mean()), "median": float(per_ring["tail_frac"].median())},
            "per_pattern": {p: {"rings": int(r.rings), "any_tail": int(r.any_tail), "all_tail": int(r.all_tail),
                                "mean_tail_frac": float(r.mean_tail_frac), "visible_edges": int(r.visible_edges),
                                "tail_edges": int(r.tail_edges)} for p, r in by_pat.iterrows()}}


def p_at_r(y, s, r=0.5):
    if y.sum() == 0:
        return None
    p, rc, _ = precision_recall_curve(y, s)
    return float(p[rc >= r].max())


def detectability(scores_dir: Path, seed: int, tail_from: int) -> dict:
    val = load_scores_with_labels(scores_dir, seed, "val")
    thr, _ = choose_threshold(val["true_label"].values, val["score_raw"].values)
    te = load_scores_with_labels(scores_dir, seed, "test")
    te["day"] = day_of(te["timestamp"])
    y, s = te["true_label"].to_numpy(np.int64), te["score_raw"].to_numpy()
    tail = te["day"].to_numpy() >= tail_from
    out = {"scores_dir": str(scores_dir), "seed": seed, "val_threshold": thr, "by_window": {}}
    for name, m in (("days_8_9", ~tail), (f"days_ge_{tail_from}", tail), ("all", np.ones_like(tail))):
        yy, ss = y[m], s[m]
        pred = (ss >= thr).astype(int)
        out["by_window"][name] = {
            "n_edges": int(m.sum()), "n_illicit": int(yy.sum()), "base_rate": float(yy.mean()),
            "ap": float(average_precision_score(yy, ss)) if yy.sum() else None,
            "ap_over_prevalence": float(average_precision_score(yy, ss) / yy.mean()) if yy.sum() else None,
            "p_at_r50": p_at_r(yy, ss),
            "f1_at_val_thr": float(f1_score(yy, pred, zero_division=0)),
            "precision_at_val_thr": float(precision_score(yy, pred, zero_division=0)),
            "recall_at_val_thr": float(recall_score(yy, pred, zero_division=0)),
            "share_above_val_thr": float(pred.mean()),
            "share_illicit_above_val_thr": float(pred[yy == 1].mean()) if yy.sum() else None,
            "share_licit_above_val_thr": float(pred[yy == 0].mean()) if (yy == 0).sum() else None}
    # GNN positives: how many of them are in the tail
    pred_all = (s >= thr)
    out["gnn_predicted_positives"] = {"n": int(pred_all.sum()), "n_in_tail": int((pred_all & tail).sum()),
                                      "tp": int((pred_all & (y == 1)).sum()), "tp_in_tail": int((pred_all & (y == 1) & tail).sum())}
    # trivial baseline: 1 for the tail, 0 otherwise
    b = tail.astype(int)
    out["trivial_tail_baseline"] = {
        "definition": f"score = 1 if day >= {tail_from} else 0, whole test split",
        "f1": float(f1_score(y, b)), "precision": float(precision_score(y, b)), "recall": float(recall_score(y, b)),
        "ap": float(average_precision_score(y, b)), "n_predicted_positive": int(b.sum())}
    # oracle mix: GNN on days 8-9 + tail baseline (what a model that had learned 'the tail is illicit' could reach)
    mix = np.where(tail, 1.0, s)
    out["gnn_plus_tail_rule"] = {"definition": "score = 1 on the tail, GNN score elsewhere (upper bound of exploiting the tail)",
                                 "ap": float(average_precision_score(y, mix)),
                                 "f1_at_val_thr": float(f1_score(y, (mix >= thr).astype(int)))}
    return out


def neighbourhood(tail_from: int) -> dict:
    """Mean hop-1 sampled neighbours per seed edge (both stores) on the causal test loader."""
    from models.score import args_from_run_config
    from models.tgn import load_data
    from tests.measure_window_leak import measure
    run_dir = REPO_ROOT / "experiments" / "R1_gine_causal_legacyfeat"
    args, _ = args_from_run_config(run_dir, dry_run=False, dry_run_seed=1)
    tr, va, te, tr_inds, val_inds, te_inds, _ = load_data(args.raw_dir, args.data_dir, args)
    arr = measure(te, te_inds, args, 1800)
    day = day_of(arr["seed_t"])
    tail = day >= tail_from
    out = {"config": str(run_dir), "window_s": 1800, "n_seeds": int(len(day)), "by_window": {}}
    for name, m in (("days_8_9", ~tail), (f"days_ge_{tail_from}", tail)):
        h1 = arr["h1"][m]; h1_to = arr["to_h1"][m]; h1_rev = arr["rev_h1"][m]; h2 = arr["h2"][m]
        y = arr["seed_y"][m]
        out["by_window"][name] = {
            "n_seeds": int(m.sum()), "n_illicit": int(y.sum()),
            "hop1_both_stores": {"mean": float(h1.mean()), "median": float(np.median(h1)), "p10": float(np.percentile(h1, 10)),
                                 "share_zero": float((h1 == 0).mean())},
            "hop1_to": {"mean": float(h1_to.mean()), "median": float(np.median(h1_to))},
            "hop1_rev_to": {"mean": float(h1_rev.mean()), "median": float(np.median(h1_rev))},
            "hop2_both_stores": {"mean": float(h2.mean()), "median": float(np.median(h2))},
            "hop1_illicit_seeds_mean": float(h1[y == 1].mean()) if y.sum() else None,
            "hop1_licit_seeds_mean": float(h1[y == 0].mean()) if (y == 0).sum() else None,
            "seeds_per_batch_mean": float(arr["n_seed_batch"][m].mean())}
    per_day = {}
    for dd in np.unique(day):
        m = day == dd
        per_day[int(dd)] = {"n_seeds": int(m.sum()), "hop1_mean": float(arr["h1"][m].mean()),
                            "hop1_median": float(np.median(arr["h1"][m])), "hop2_mean": float(arr["h2"][m].mean())}
    out["per_day"] = per_day
    return out


def print_report(res: dict, tail_from: int):
    for split in ("test", "val"):
        print(f"\n[1] {split} per day")
        print(f"{'day':>3s} {'edges':>9s} {'illicit':>7s} {'base':>8s} {'cum pos':>8s}")
        for r in res["per_day"][split]:
            print(f"{r['day']:3d} {r['n_edges']:9,d} {r['n_illicit']:7,d} {100 * r['base_rate']:7.3f}% {100 * r['cum_share_of_positives']:7.1f}%")
    print(f"\ntest positives on days >= {tail_from}: {res['tail_positives']['n']} / {res['tail_positives']['n_total']} "
          f"= {100 * res['tail_positives']['share']:.1f}%; tail edges {res['tail_positives']['n_edges']:,} "
          f"({100 * res['tail_positives']['edge_share']:.2f}% of the split)")
    r = res["rings"]
    print(f"\n[2] test-visible rings: {r['n_rings_test_visible']} rings, {r['n_visible_edges']:,} visible edges, "
          f"{r['n_visible_edges_in_tail']:,} in the tail; rings with >= 1 tail edge {r['rings_with_any_tail_edge']}, "
          f"all edges in tail {r['rings_with_all_edges_in_tail']}; tail fraction mean {r['tail_fraction']['mean']:.2f} "
          f"median {r['tail_fraction']['median']:.2f}")
    print("   tail-fraction histogram: " + ", ".join(f"{k}: {v}" for k, v in r["tail_fraction_hist"].items()))
    print(f"   {'pattern':16s} {'rings':>5s} {'any':>4s} {'all':>4s} {'mean frac':>9s} {'vis edges':>9s} {'tail edges':>10s}")
    for p, d in sorted(r["per_pattern"].items()):
        print(f"   {p:16s} {d['rings']:5d} {d['any_tail']:4d} {d['all_tail']:4d} {d['mean_tail_frac']:9.2f} {d['visible_edges']:9d} {d['tail_edges']:10d}")
    d = res["detectability"]
    print(f"\n[3] detectability, {Path(d['scores_dir']).name} seed {d['seed']}, val threshold {d['val_threshold']:.2f}")
    print(f"   {'window':14s} {'edges':>8s} {'illicit':>7s} {'base':>8s} {'AP':>6s} {'AP/prev':>7s} {'P@R50':>6s} {'F1@thr':>6s} "
          f"{'P@thr':>6s} {'R@thr':>6s} {'>thr':>7s} {'ill>thr':>7s} {'lic>thr':>7s}")
    for k, w in d["by_window"].items():
        f = lambda v, nd=3: f"{v:.{nd}f}" if v is not None else "-"
        print(f"   {k:14s} {w['n_edges']:8,d} {w['n_illicit']:7,d} {100 * w['base_rate']:7.3f}% {f(w['ap'])} "
              f"{f(w['ap_over_prevalence'], 0):>7s} {f(w['p_at_r50'])} {f(w['f1_at_val_thr'])} {f(w['precision_at_val_thr'])} "
              f"{f(w['recall_at_val_thr'])} {100 * w['share_above_val_thr']:6.2f}% {f(w['share_illicit_above_val_thr'])} "
              f"{f(w['share_licit_above_val_thr'], 4)}")
    g = d["gnn_predicted_positives"]
    print(f"   GNN predicted positives {g['n']:,} of which {g['n_in_tail']:,} in the tail; TP {g['tp']:,} of which "
          f"{g['tp_in_tail']:,} in the tail")
    b = d["trivial_tail_baseline"]
    print(f"   trivial baseline (1 on the tail): F1 {b['f1']:.4f} P {b['precision']:.4f} R {b['recall']:.4f} AP {b['ap']:.4f} "
          f"(predicts {b['n_predicted_positive']:,} positives)")
    x = d["gnn_plus_tail_rule"]
    print(f"   GNN + tail rule: AP {x['ap']:.4f} F1@thr {x['f1_at_val_thr']:.4f}")
    if "neighbourhood" in res:
        n = res["neighbourhood"]
        print(f"\n[4] neighbourhood (causal test loader, W=1800, {n['n_seeds']:,} seeds)")
        for k, w in n["by_window"].items():
            print(f"   {k:14s} seeds {w['n_seeds']:8,d} | hop1 both stores mean {w['hop1_both_stores']['mean']:8.1f} "
                  f"median {w['hop1_both_stores']['median']:6.0f} p10 {w['hop1_both_stores']['p10']:5.0f} zero {100 * w['hop1_both_stores']['share_zero']:.2f}% | "
                  f"to {w['hop1_to']['mean']:7.1f} rev_to {w['hop1_rev_to']['mean']:7.1f} | hop2 mean {w['hop2_both_stores']['mean']:9.1f} | "
                  f"seeds/batch {w['seeds_per_batch_mean']:.0f}")
        print("   per day hop-1 mean: " + ", ".join(f"d{k}: {v['hop1_mean']:.0f} (n={v['n_seeds']:,})" for k, v in n["per_day"].items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tail-from", type=int, default=10, help="first day of the tail (default 10)")
    ap.add_argument("--scores-dir", type=Path, default=REPO_ROOT / "experiments" / "R1_gine_causal_legacyfeat")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--neighbourhood", action="store_true", help="part 4 (loads the graph)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    res = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "tail_from_day": args.tail_from, "day_definition": "(Timestamp - 10) // 86400, loader basis",
           "per_day": {s: per_day(s) for s in ("test", "val")}}
    test_days = res["per_day"]["test"]
    n_total = sum(r["n_illicit"] for r in test_days)
    n_tail = sum(r["n_illicit"] for r in test_days if r["day"] >= args.tail_from)
    e_total = sum(r["n_edges"] for r in test_days)
    e_tail = sum(r["n_edges"] for r in test_days if r["day"] >= args.tail_from)
    res["tail_positives"] = {"n": n_tail, "n_total": n_total, "share": n_tail / n_total,
                             "n_edges": e_tail, "edge_share": e_tail / e_total}
    res["rings"] = rings(args.tail_from)
    res["detectability"] = detectability(args.scores_dir, args.seed, args.tail_from)
    if args.neighbourhood:
        res["neighbourhood"] = neighbourhood(args.tail_from)
    elif args.out.exists():
        old = json.loads(args.out.read_text(encoding="utf-8"))
        if "neighbourhood" in old:
            res["neighbourhood"] = old["neighbourhood"]  # keep the expensive part from a previous run
    args.out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print_report(res, args.tail_from)
    print(f"\n-> {args.out}")
    return res


if __name__ == "__main__":
    main()
