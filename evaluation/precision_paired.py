"""Precision-aware paired test (deep-analysis #2).

    python evaluation/precision_paired.py --exp-root ../RS-e2e/experiments \
        --out results/tables/v35_precision_paired.csv

The project's standard test (`ring_stats.paired_permutation` on per-ring matched indicators,
results/tables/r9_significance.csv) cannot see precision (PITFALLS.md section 7). This is a
paired bootstrap on the DIFFERENCE in two precision-bearing metrics, primary window:

    added_member_precision   in-window expanded edges that are truth member edges / all of them,
                             pooled over the 5 seeds (the A5 definition, r9_quiet_vs_precision.csv)
    ring_f1                  per seed at Jaccard 0.5, averaged over seeds

Resampling unit: the RING, not the edge (added edges cluster by ring). Every prediction of every
method and seed is assigned to one unit:
    matched prediction        -> the truth ring it matched
    unmatched, overlapping    -> the truth ring sharing the most accounts with it (ties: smallest id)
    overlapping no truth ring -> an off-ring cluster: union-find over shared accounts across ALL
                                 methods and seeds, so the same cluster is drawn for both arms
The 174 in-scope truth rings plus the off-ring clusters are resampled with replacement; each arm's
metric is recomputed on the same draw (seeds averaged / pooled inside), giving the paired
difference. Two-sided p = 2 * min(P(d <= 0), P(d >= 0)) with the +1 correction; Holm across the
four registered comparisons, separately per metric.

Family, fixed in advance (docs/deep-analysis.md #2):
    proposed_vs_b1b       R3 proposed        vs R3 b1b
    full_vs_b1b           R4 average         vs R3 b1b
    gine_full_vs_gfpxgb   R4 average         vs R6_full gfpxgb
    mega_full_vs_gine     R6_full mega       vs R4 average
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
from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.ring_stats import holm, paired_unit_bootstrap  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RUNS = {"proposed": "R3_expansion/runs/proposed", "b1b": "R3_expansion/runs/b1b",
        "gine_full": "R4_partition/runs/average", "gfpxgb_full": "R6_full/gfpxgb", "mega_full": "R6_full/mega"}
FAMILY = [("proposed_vs_b1b", "proposed", "b1b"), ("full_vs_b1b", "gine_full", "b1b"),
          ("gine_full_vs_gfpxgb_full", "gine_full", "gfpxgb_full"), ("mega_full_vs_gine_full", "mega_full", "gine_full")]


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def predictions(rings, se_idx, in_win_ids, ring_id_of):
    """Per prediction that survives the window: member account set, in-window added edges (tp, n)."""
    frm, to = se_idx["from_id"], se_idx["to_id"]
    out, seen = [], set()
    for r in rings:
        me = [e for e in r.member_edges if e in in_win_ids]
        if not me:
            continue
        accs = set(frm.loc[me].tolist()) | set(to.loc[me].tolist())
        exp = [e for e in r.expanded_edges if e in in_win_ids and e not in seen]
        seen.update(exp)
        tp = int((ring_id_of.reindex(exp).fillna(-1).to_numpy() > 0).sum()) if exp else 0
        out.append({"accs": accs, "tp": tp, "n": len(exp)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp-root", type=Path, default=REPO_ROOT / "experiments")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--rng-seed", type=int, default=20261111)
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v35_precision_paired.csv")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, a.scope, verbose=False)
    tids = sorted(truth)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    se = build_scored_edges(a.exp_root / "R1_gine_causal" / "scores_test_seed1.parquet", "test", model_id="gine_causal",
                            seed=1, processed_dir=pdir)
    se_idx = se.set_index("edge_id")
    in_win_ids = set(se_idx.index[W.mask(se_idx["timestamp"].values)].tolist())
    acc2truth: dict = {}
    for t, accs in truth.items():
        for x in accs:
            acc2truth.setdefault(x, set()).add(t)

    # ---- predictions and their units
    preds, uf = {}, UF()
    for m, rel in RUNS.items():
        for s in a.seeds:
            P = predictions(read_rings_any(a.exp_root / rel / f"seed{s}" / "rings.parquet"), se_idx, in_win_ids, ring_id_of)
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
            preds[(m, s)] = P
    for P in preds.values():
        for p in P:
            if p["unit"][0] == "O":
                p["unit"] = ("O", uf.find(p["unit"][1]))
    units = [("T", t) for t in tids] + sorted({p["unit"] for P in preds.values() for p in P if p["unit"][0] == "O"})
    uix = {u: i for i, u in enumerate(units)}
    U = len(units)
    n_truth_u = np.array([1.0 if u[0] == "T" else 0.0 for u in units])

    # per (method, seed): unit-level count vectors
    def vec(P, key):
        v = np.zeros(U)
        for p in P:
            v[uix[p["unit"]]] += p[key] if key != "one" else 1
        return v
    arrays = {k: {"matched": vec(P, "matched"), "npred": vec(P, "one"), "tp": vec(P, "tp"), "nadd": vec(P, "n")}
              for k, P in preds.items()}

    def stats(m, W_):
        """W_: (B, U) unit weights -> (added precision, mean ring-F1) per draw."""
        tp = sum(W_ @ arrays[(m, s)]["tp"] for s in a.seeds)
        na = sum(W_ @ arrays[(m, s)]["nadd"] for s in a.seeds)
        nt = W_ @ n_truth_u
        f1s = []
        for s in a.seeds:
            mt, npd = W_ @ arrays[(m, s)]["matched"], W_ @ arrays[(m, s)]["npred"]
            with np.errstate(invalid="ignore", divide="ignore"):
                r, p = mt / nt, np.where(npd > 0, mt / npd, 0.0)
                f1s.append(np.where(p + r > 0, 2 * p * r / (p + r), 0.0))
        with np.errstate(invalid="ignore", divide="ignore"):
            return {"added_member_precision": np.where(na > 0, tp / na, np.nan), "ring_f1": np.mean(f1s, axis=0)}

    point_w = np.ones((1, U))
    points = {m: {k: float(v[0]) for k, v in stats(m, point_w).items()} for m in RUNS}
    for m, d in points.items():
        n_add = int(sum(arrays[(m, s)]["nadd"].sum() for s in a.seeds))
        print(f"  {m:12s}: added-member precision {d['added_member_precision']:.4f} ({n_add} added edges, 5 seeds) "
              f"| ring-F1 {d['ring_f1']:.4f}")
    res = paired_unit_bootstrap(lambda m, W_: stats(m, W_), FAMILY, U, n_boot=a.n_boot, seed=a.rng_seed)
    rows = []
    for metric in ("added_member_precision", "ring_f1"):
        adj = {d["comparison"]: d for d in holm([(c, res[(c, metric)]["p"]) for c, _, _ in FAMILY])}
        for c, ma, mb in FAMILY:
            r = res[(c, metric)]
            rows.append({"comparison": c, "a": ma, "b": mb, "metric": metric, "a_point": points[ma][metric],
                         "b_point": points[mb][metric], "delta": r["delta"], "ci_lo": r["lo"], "ci_hi": r["hi"],
                         "p_raw": r["p"], "p_holm": adj[c]["p_holm"], "reject_at_05": adj[c]["reject_at_05"],
                         "n_valid_draws": r["n_valid"]})
    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    n_off = sum(1 for u in units if u[0] == "O")
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "n_boot": a.n_boot,
         "rng_seed": a.rng_seed, "scope": a.scope, "window": W.as_dict(), "exp_root": str(a.exp_root),
         "n_units": U, "n_truth_units": len(tids), "n_offring_units": n_off, "points": points,
         "unit": "truth ring or off-ring account cluster, with replacement; paired across arms; seeds pooled "
                 "(precision) / averaged (ring-F1) inside each draw"}, indent=2), encoding="utf-8")
    print(f"\nunits: {len(tids)} truth rings + {n_off} off-ring clusters; {a.n_boot} paired draws")
    print(df[["comparison", "metric", "a_point", "b_point", "delta", "ci_lo", "ci_hi", "p_raw", "p_holm", "reject_at_05"]]
          .round(4).to_string(index=False))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
