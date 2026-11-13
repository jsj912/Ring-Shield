"""HI-Medium pre-registration close-out: P1-P3 verdicts from the Amendment 15 rings (deep-analysis #7).

    set RINGSHIELD_PATHS=<paths yaml for HI-Medium>
    python evaluation/hm_closeout_report.py --seeds 1 2 --exp-dir E:/JSJ/Ring-Shield/experiments_hi_medium

Reads <rings-dir>/<window>/<rule>/<method>/seed<S>.parquet written by evaluation/hm_closeout.py and
writes results/tables/v3_closeout_{p1,p2,p3,blocks}.csv and v3_closeout_verdicts.json.

Definitions are those of docs/V3_HIMEDIUM_PREREG.md, unchanged:
  P1  primary window, `full`: ring recall > 0.4609 AND Ring-Recall>=3 > 0.6035 (point estimates are
      the bar; bootstrap CIs over truth rings are context). `proposed` is reported beside it, and a
      disagreement about a bar fails P1. Not interpreted as a containment test (Amendments 4/7).
  P2  primary window, `full`: class (b) untouched share < 19.08 % AND under-covered share < 3.91 %.
  P3  primary window, paired over truth rings (matched, seeds averaged per ring): full vs b2 and
      policy vs b1b; resolved = Holm p < 0.05 OR bootstrap CI excludes 0. Passes if either resolves.
The headline rule is `global` (Amendment 14); `per_day` is reported beside it on every row.
Amendment 15: primary = days 6-14. Seed 3 is excluded (saturated scores; see the dated note).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_stats import bootstrap_over_rings, holm, metrics_from_evidence, paired_permutation, ring_evidence  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.rings import read_rings_parquet  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import Window, load_windows  # noqa: E402

P1_BARS = {"ring_recall": 0.4609, "ring_recall_ge3": 0.6035}
P2_BARS = {"b_untouched": 0.1908, "c_under_covered": 0.0391}
BLOCKS = [(6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]
RULES = ("global", "per_day")
# P3 comparisons as registered; in hm_closeout `proposed` is the policy expansion with plain components (= b2)
P3 = [("full vs b2", "full", "proposed"), ("policy vs b1b", "proposed", "b1b"), ("full vs b1b", "full", "b1b")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--exp-dir", type=Path, required=True)
    ap.add_argument("--rings-dir", type=Path, default=REPO_ROOT / "experiments_hi_medium/closeout_a15")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results/tables")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    gt = pdir / "amlworld_ring_ground_truth.parquet"
    P0 = load_windows(REPO_ROOT / "configs/eval_window_hi_medium.yaml")["primary"]
    mk = lambda name, lo, hi: Window(name, "test", lo, hi, P0.day_zero, P0.seconds_per_day)  # noqa: E731
    primary = mk("primary", 6, 14)
    truth, pats = load_ground_truth(gt, *primary.bounds, "test_visible", verbose=False)
    print(f"primary days 6-14: {len(truth)} truth rings", flush=True)

    ev = {r: {m: [] for m in ("full", "proposed", "b1b", "b0")} for r in RULES}
    p2_rows, block_rows = [], []
    for S in a.seeds:
        se = build_scored_edges(a.exp_dir / "R1_gine_causal_c1prime" / f"scores_test_seed{S}.parquet", "test",
                                model_id="gine_causal", seed=S, processed_dir=pdir)
        for rule in RULES:
            for meth in ev[rule]:
                rings = read_rings_parquet(a.rings_dir / "primary" / rule / meth / f"seed{S}.parquet")
                ev[rule][meth].append(ring_evidence(rings, se, truth, primary, method=meth, seed=S, patterns=pats))
                if meth == "full":
                    c = classify(rings, se, truth, pats, primary)["klass"].value_counts()
                    p2_rows.append({"seed": S, "rule": rule, "n_truth": len(truth),
                                    **{k: int(c.get(k, 0)) for k in ("matched", "a_lt3_members", "b_untouched",
                                                                      "c_under_covered", "c_over_merged")}})
            print(f"  seed {S} {rule}: evidence + classes done", flush=True)
        for lo, hi in BLOCKS:
            W = mk(f"block{lo}-{hi}", lo, hi)
            tb, pb = load_ground_truth(gt, *W.bounds, "test_visible", verbose=False)
            for rule in RULES:
                for meth in ("full", "proposed"):
                    rings = read_rings_parquet(a.rings_dir / W.name / rule / meth / f"seed{S}.parquet")
                    m = metrics_from_evidence(ring_evidence(rings, se, tb, W, method=meth, seed=S, patterns=pb))
                    block_rows.append({"seed": S, "block": W.name, "rule": rule, "method": meth, "n_truth": len(tb),
                                       **{k: m[k] for k in ("ring_recall", "ring_recall_ge3", "ring_precision", "ring_f1")}})
        del se

    # ---- P1
    p1_rows, verdicts = [], {"seeds": a.seeds, "primary_days": [6, 14], "n_truth": len(truth)}
    for rule in RULES:
        for meth in ("full", "proposed"):
            bs = bootstrap_over_rings(ev[rule][meth], metrics=("ring_recall", "ring_recall_ge3", "ring_precision", "ring_f1"))
            for k in ("ring_recall", "ring_recall_ge3", "ring_precision", "ring_f1"):
                p1_rows.append({"rule": rule, "method": meth, "metric": k, "point": bs[k]["point"], "lo": bs[k]["lo"],
                                "hi": bs[k]["hi"], "bar": P1_BARS.get(k), "clears": (bs[k]["point"] > P1_BARS[k]) if k in P1_BARS else None})
    p1 = pd.DataFrame(p1_rows)
    blk = pd.DataFrame(block_rows)
    for rule in RULES:
        sub = p1[(p1.rule == rule) & p1.metric.isin(list(P1_BARS))]
        verdicts[f"P1_{rule}"] = {"pass": bool(sub.clears.all()),
                                  "values": {f"{r.method}/{r.metric}": round(r.point, 4) for r in sub.itertuples()}}
        # Amendment 13: mean over the five blocks with a t-CI over blocks (seeds averaged per block first)
        bm = blk[(blk.rule == rule) & (blk.method == "full")].groupby("block")[list(P1_BARS)].mean()
        verdicts[f"P1_blocks_{rule}"] = {}
        for k in P1_BARS:
            x = bm[k].to_numpy(float)
            h = sps.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))
            verdicts[f"P1_blocks_{rule}"][k] = {"mean": round(float(x.mean()), 4), "lo": round(float(x.mean() - h), 4),
                                                "hi": round(float(x.mean() + h), 4), "clears": bool(x.mean() > P1_BARS[k])}

    # ---- P2
    p2 = pd.DataFrame(p2_rows)
    for k in P2_BARS:
        p2[f"{k}_share"] = p2[k] / p2["n_truth"]
    for rule in RULES:
        sh = p2[p2.rule == rule][[f"{k}_share" for k in P2_BARS]].mean()
        verdicts[f"P2_{rule}"] = {"pass": bool(all(sh[f"{k}_share"] < b for k, b in P2_BARS.items())),
                                  "shares": {k: round(float(sh[f"{k}_share"]), 4) for k in P2_BARS}}

    # ---- P3
    p3_rows = []
    for rule in RULES:
        tests = {name: paired_permutation(ev[rule][x], ev[rule][y], metric="matched") for name, x, y in P3}
        adj = {h["comparison"]: h for h in holm((n, t["p_value"]) for n, t in tests.items())}
        for name, t in tests.items():
            lo, hi = t["delta_ci"]
            res = bool(adj[name]["reject_at_05"] or lo > 0 or hi < 0)
            p3_rows.append({"rule": rule, "comparison": name, "mean_delta": t["mean_delta"], "lo": lo, "hi": hi,
                            "p_raw": t["p_value"], "p_holm": adj[name]["p_holm"], "n_differing": t["n_differing_rings"],
                            "resolved": res})
        r = {x["comparison"]: x["resolved"] for x in p3_rows if x["rule"] == rule}
        verdicts[f"P3_{rule}"] = {"pass": bool(r["full vs b2"] or r["policy vs b1b"]), "resolved": r}
    p3 = pd.DataFrame(p3_rows)

    a.out.mkdir(parents=True, exist_ok=True)
    p1.to_csv(a.out / "v3_closeout_p1.csv", index=False)
    p2.to_csv(a.out / "v3_closeout_p2.csv", index=False)
    p3.to_csv(a.out / "v3_closeout_p3.csv", index=False)
    blk.to_csv(a.out / "v3_closeout_blocks.csv", index=False)
    (a.out / "v3_closeout_verdicts.json").write_text(json.dumps(verdicts, indent=1), encoding="utf-8")
    print(json.dumps(verdicts, indent=1))


if __name__ == "__main__":
    main()
