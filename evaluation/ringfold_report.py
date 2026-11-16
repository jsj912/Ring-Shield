"""Ring-folded vs day-folded cross-scores: the quantities promised beside the B17 verdict
(docs/deep-analysis.md section 8; runbook T-P2).

    python evaluation/ringfold_report.py --shipped-root ../RS-e2e/experiments \
        --out results/tables/v39_ringfold_report.csv

Arms (primary window, detector seeds 1-5, Jaccard 0.5, scope test_visible):
    shipped      <shipped-root>/R3_expansion/runs/proposed/seed{S}   (policy on day-folded cross-scores)
    ringfold     <ringfold-root>/R3_ringfold/runs/proposed/seed{S}   (policy on ring-folded cross-scores)

Computed:
  (i)   paired ring-unit bootstrap (10,000 draws, seed 20261114) of ring-F1 and added-member
        precision, ringfold minus shipped; units = truth rings + off-ring account clusters, the
        same construction as evaluation/precision_paired.py;
  (ii)  ring precision and recall per arm, and their paired differences (same draws);
  (iii) per seed: share of shipped rings (in-window account sets) reproduced exactly by the
        ringfold run, and share matched one-to-one at Jaccard >= 0.5;
  (iv)  per fold: AP and ROC-AUC of each arm's fold models on the train edges they score, with
        ring edges (ring_id > 0) as positives; n ring edges per fold;
  (v)   from the ring-fold record: rings spanning day folds, edges moved.
  Assertion: every train ring's edges are scored by one fold model, the one that held the
  whole ring out (ring_folds.parquet against cross_scores_train.parquet).

Writes only --out (csv) and the json beside it.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.precision_paired import UF, predictions  # noqa: E402
from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.ring_stats import paired_unit_bootstrap  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

METRICS = ("ring_f1", "ring_precision", "ring_recall", "added_member_precision")


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def overlap_shares(shipped: list[set], other: list[set], tau: float = 0.5) -> dict:
    """Share of shipped account sets reproduced exactly by `other`, and matched one-to-one
    (greedy by descending Jaccard) at Jaccard >= tau."""
    n = len(shipped)
    if n == 0:
        return {"n_shipped": 0, "n_other": len(other), "exact_share": float("nan"), "jaccard_share": float("nan")}
    keys = {frozenset(s) for s in other}
    exact = sum(frozenset(s) in keys for s in shipped)
    pairs = sorted(((jaccard(a, b), i, j) for i, a in enumerate(shipped) for j, b in enumerate(other) if a & b),
                   key=lambda x: (-x[0], x[1], x[2]))
    used_i, used_j, m = set(), set(), 0
    for jv, i, j in pairs:
        if jv < tau:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        m += 1
    return {"n_shipped": n, "n_other": len(other), "n_exact": exact, "exact_share": exact / n,
            "n_jaccard": m, "jaccard_share": m / n}


def assert_ring_folds(ring_folds: pd.DataFrame, cross: pd.DataFrame) -> dict:
    """Every ring maps to one fold, and every one of its edges is scored by that fold's model."""
    per_ring = ring_folds.groupby("ring_id")["fold"].nunique()
    assert (per_ring == 1).all(), f"rings split across folds: {per_ring[per_ring > 1].index.tolist()[:5]}"
    m = ring_folds.merge(cross[["edge_id", "fold"]], on="edge_id", how="left", suffixes=("_ring", "_scored"))
    assert m["fold_scored"].notna().all(), "ring edge missing from cross_scores_train"
    bad = int((m["fold_ring"] != m["fold_scored"]).sum())
    assert bad == 0, f"{bad} ring edges scored by a fold model that trained on their ring"
    return {"n_rings": int(per_ring.size), "n_ring_edges": int(len(ring_folds)), "violations": 0, "passed": True}


def fold_ap(cross: pd.DataFrame, ring_of: pd.Series) -> list[dict]:
    y_all = (ring_of.reindex(cross["edge_id"]).fillna(0).to_numpy() > 0).astype(int)
    out = []
    for k, idx in cross.groupby("fold").indices.items():
        y, s = y_all[idx], cross["score_raw"].to_numpy()[idx]
        ok = 0 < y.sum() < len(y)
        out.append({"fold": int(k), "n_edges": int(len(y)), "n_ring_edges": int(y.sum()),
                    "ap": float(average_precision_score(y, s)) if ok else float("nan"),
                    "roc_auc": float(roc_auc_score(y, s)) if ok else float("nan")})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shipped-root", type=Path, default=REPO_ROOT / "experiments",
                    help="holds R3_expansion/runs/proposed, R3_cross_scores and R1_gine_causal")
    ap.add_argument("--ringfold-root", type=Path, default=REPO_ROOT / "experiments", help="holds R3_ringfold")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--rng-seed", type=int, default=20261114)
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v39_ringfold_report.csv")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    runs = {"shipped": a.shipped_root / "R3_expansion" / "runs" / "proposed",
            "ringfold": a.ringfold_root / "R3_ringfold" / "runs" / "proposed"}

    # per-seed ring-F1 as recorded by the runs themselves
    recorded = {arm: {s: json.loads((d / f"seed{s}" / "metrics.json").read_text())["test"]["ring_f1"] for s in a.seeds}
                for arm, d in runs.items()}

    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, a.scope, verbose=False)
    tids = sorted(truth)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    se = build_scored_edges(a.shipped_root / "R1_gine_causal" / "scores_test_seed1.parquet", "test",
                            model_id="gine_causal", seed=1, processed_dir=pdir)
    se_idx = se.set_index("edge_id")
    in_win_ids = set(se_idx.index[W.mask(se_idx["timestamp"].values)].tolist())
    acc2truth: dict = {}
    for t, accs in truth.items():
        for x in accs:
            acc2truth.setdefault(x, set()).add(t)

    preds, uf = {}, UF()
    for arm, d in runs.items():
        for s in a.seeds:
            P = predictions(read_rings_any(d / f"seed{s}" / "rings.parquet"), se_idx, in_win_ids, ring_id_of)
            matches, _, _ = match_rings([p["accs"] for p in P], truth, 0.5)
            for mt in matches:
                P[mt.pred_idx]["unit"], P[mt.pred_idx]["matched"] = ("T", mt.truth_id), 1
            for p in P:
                if "unit" in p:
                    continue
                p["matched"] = 0
                ov: dict = {}
                for x in p["accs"]:
                    for t in acc2truth.get(x, ()):
                        ov[t] = ov.get(t, 0) + 1
                if ov:
                    best = max(ov.values())
                    p["unit"] = ("T", min(t for t, c in ov.items() if c == best))
                else:
                    accs = sorted(p["accs"])
                    for x in accs[1:]:
                        uf.union(accs[0], x)
                    p["unit"] = ("O", accs[0])
            preds[(arm, s)] = P
    for P in preds.values():
        for p in P:
            if p["unit"][0] == "O":
                p["unit"] = ("O", uf.find(p["unit"][1]))
    units = [("T", t) for t in tids] + sorted({p["unit"] for P in preds.values() for p in P if p["unit"][0] == "O"})
    uix = {u: i for i, u in enumerate(units)}
    U = len(units)
    n_truth_u = np.array([1.0 if u[0] == "T" else 0.0 for u in units])

    def vec(P, key):
        v = np.zeros(U)
        for p in P:
            v[uix[p["unit"]]] += p[key] if key != "one" else 1
        return v
    arrays = {k: {"matched": vec(P, "matched"), "npred": vec(P, "one"), "tp": vec(P, "tp"), "nadd": vec(P, "n")}
              for k, P in preds.items()}

    def stats(arm, W_):
        tp = sum(W_ @ arrays[(arm, s)]["tp"] for s in a.seeds)
        na = sum(W_ @ arrays[(arm, s)]["nadd"] for s in a.seeds)
        nt = W_ @ n_truth_u
        f1s, ps, rs = [], [], []
        for s in a.seeds:
            mt, npd = W_ @ arrays[(arm, s)]["matched"], W_ @ arrays[(arm, s)]["npred"]
            with np.errstate(invalid="ignore", divide="ignore"):
                r, p = mt / nt, np.where(npd > 0, mt / npd, 0.0)
                f1s.append(np.where(p + r > 0, 2 * p * r / (p + r), 0.0))
            ps.append(p)
            rs.append(r)
        with np.errstate(invalid="ignore", divide="ignore"):
            return {"ring_f1": np.mean(f1s, axis=0), "ring_precision": np.mean(ps, axis=0),
                    "ring_recall": np.mean(rs, axis=0), "added_member_precision": np.where(na > 0, tp / na, np.nan)}

    points = {arm: {k: float(v[0]) for k, v in stats(arm, np.ones((1, U))).items()} for arm in runs}
    for arm in runs:   # the scorer must agree with the runs' own metrics.json
        mean_rec = float(np.mean(list(recorded[arm].values())))
        assert abs(points[arm]["ring_f1"] - mean_rec) < 5e-5, (arm, points[arm]["ring_f1"], mean_rec)
    comp = [("ringfold_vs_shipped", "ringfold", "shipped")]
    res = paired_unit_bootstrap(lambda m, W_: stats(m, W_), comp, U, n_boot=a.n_boot, seed=a.rng_seed)
    rows = []
    for metric in METRICS:
        r = res[("ringfold_vs_shipped", metric)]
        rows.append({"section": "paired", "metric": metric, "shipped": points["shipped"][metric],
                     "ringfold": points["ringfold"][metric], "delta": r["delta"], "ci_lo": r["lo"], "ci_hi": r["hi"],
                     "p": r["p"], "n_valid_draws": r["n_valid"]})

    # (iii) overlap with shipped rings, per seed, in-window account sets
    overlap = []
    for s in a.seeds:
        o = overlap_shares([p["accs"] for p in preds[("shipped", s)]], [p["accs"] for p in preds[("ringfold", s)]])
        overlap.append({"seed": s, **o, "shipped_ring_f1": recorded["shipped"][s], "ringfold_ring_f1": recorded["ringfold"][s],
                        "delta_ring_f1": recorded["ringfold"][s] - recorded["shipped"][s]})
    tot_s = sum(o["n_shipped"] for o in overlap)
    pooled = {"exact_share": sum(o["n_exact"] for o in overlap) / tot_s,
              "jaccard_share": sum(o["n_jaccard"] for o in overlap) / tot_s}
    for o in overlap:
        rows.append({"section": "overlap", "seed": o["seed"], "metric": "exact_share", "value": o["exact_share"],
                     "n": o["n_shipped"]})
        rows.append({"section": "overlap", "seed": o["seed"], "metric": "jaccard_share", "value": o["jaccard_share"],
                     "n": o["n_shipped"]})
    for k, v in pooled.items():
        rows.append({"section": "overlap", "seed": "pooled", "metric": k, "value": v, "n": tot_s})

    # (iv) fold models on ring edges; assertion; (v) fold record
    ring_of_train = pd.read_parquet(pdir / "amlworld_train.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rf_dir = a.ringfold_root / "R3_ringfold" / "cross_scores"
    cs = {"shipped": pd.read_parquet(a.shipped_root / "R3_cross_scores" / "cross_scores_train.parquet",
                                     columns=["edge_id", "score_raw", "fold"]),
          "ringfold": pd.read_parquet(rf_dir / "cross_scores_train.parquet", columns=["edge_id", "score_raw", "fold"])}
    leak = assert_ring_folds(pd.read_parquet(rf_dir / "ring_folds.parquet"), cs["ringfold"])
    folds = {arm: fold_ap(c, ring_of_train) for arm, c in cs.items()}
    for arm, fl in folds.items():
        for f in fl:
            rows.append({"section": "fold_models", "arm": arm, "fold": f["fold"], "metric": "ap_ring_edges",
                         "value": f["ap"], "n": f["n_ring_edges"]})
            rows.append({"section": "fold_models", "arm": arm, "fold": f["fold"], "metric": "roc_auc_ring_edges",
                         "value": f["roc_auc"], "n": f["n_ring_edges"]})
    rec = json.loads((rf_dir / "cross_scores.json").read_text())["folds"][0]["ring_folds"]
    for k in ("n_rings", "n_ring_edges", "n_rings_spanning_day_folds", "n_edges_moved_from_day_fold"):
        rows.append({"section": "fold_record", "metric": k, "value": rec[k]})

    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds,
            "n_boot": a.n_boot, "rng_seed": a.rng_seed, "scope": a.scope, "window": W.as_dict(),
            "runs": {k: str(v) for k, v in runs.items()}, "recorded_ring_f1": recorded, "points": points,
            "n_units": U, "n_truth_units": len(tids), "n_offring_units": U - len(tids),
            "overlap_per_seed": overlap, "overlap_pooled": pooled, "fold_models": folds,
            "fold_model_positives": "train edges with ring_id > 0, scored by the arm's owner fold model",
            "leak_assertion": leak, "fold_record": rec}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    r = res[("ringfold_vs_shipped", "ring_f1")]
    print(f"ring-F1 shipped {points['shipped']['ring_f1']:.4f}  ringfold {points['ringfold']['ring_f1']:.4f}  "
          f"delta {r['delta']:+.4f} [{r['lo']:+.4f}, {r['hi']:+.4f}] p={r['p']:.4f}")
    print(df.round(4).to_string(index=False))
    print(f"-> {a.out}")
    return df


if __name__ == "__main__":
    main()
