"""Addendum 5 primary comparison (paper/PREREG_RECOVERY_AMENDMENT_2026-11-16.md, sha256 39fd05b0...).

    RINGSHIELD_PATHS=experiments/R18_hm_transfer/paths_hm_transfer.yaml \
    .venv312/Scripts/python.exe -u evaluation/hm_transfer_paired.py

Transferred GenAgg (seeds 1-5, trained on HI-Small, zero-shot on HI-Medium) vs the existing HI-Medium detector
(closeout_a15, seeds 1-2): B0 arm, global seed rule, primary window (test days 6-14), ring-F1 (also precision, recall).
Paired unit bootstrap over the in-scope truth rings (evaluation.ring_stats.paired_unit_bootstrap), 10,000 draws,
seeds averaged inside each draw. Ring evidence from evaluation.ring_stats.ring_evidence on the stored rings.
New file only: results/tables/hm_transfer_paired_addendum5.csv.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--rng-seed", type=int, default=20261117)
    ap.add_argument("--rule", default="global")
    ap.add_argument("--vs", choices=["old", "b1b"], default="old",
                    help="old: addendum 5 (GenAgg B0 vs old detector B0); b1b: exploratory GenAgg B0 vs GenAgg B1b")
    a = ap.parse_args()
    from evaluation.ring_stats import paired_unit_bootstrap, ring_evidence
    from preprocessing.account_bank import load_paths
    from ringshield.rings import read_rings_parquet
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import Window, load_windows

    pdir = load_paths()["processed_dir"]
    P0 = load_windows()["primary"]
    W = Window("primary", "test", 6, 14, P0.day_zero, P0.seconds_per_day)
    truth, pats = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    arms = {"genagg_transfer": (R / "experiments/R18_hm_transfer/closeout_input/R1_gine_causal_c1prime",
                                R / "experiments/R18_hm_transfer/closeout", [1, 2, 3, 4, 5]),
            "old_hm_detector": (Path("E:/JSJ/Ring-Shield/experiments_hi_medium/R1_gine_causal_c1prime"),  # old scores live only there
                                R / "experiments_hi_medium/closeout_a15", [1, 2])}
    if a.vs == "b1b":
        g = arms["genagg_transfer"]
        arms = {"genagg_transfer": g, "genagg_b1b": g}
    ids = None
    M, NP = {}, {}
    for arm, (sdir, rdir, seeds) in arms.items():
        mats, nps = [], []
        for S in seeds:
            se = build_scored_edges(sdir / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S,
                                    processed_dir=pdir)
            meth = "b1b" if arm == "genagg_b1b" else "b0"
            rings = read_rings_parquet(rdir / "primary" / a.rule / meth / f"seed{S}.parquet")
            ev = ring_evidence(rings, se, truth, W, method=meth, seed=S, patterns=pats)
            if ids is None:
                ids = list(ev.truth_ids)
            assert list(ev.truth_ids) == ids
            mats.append(np.array([ev.matched[i] for i in ids], float)); nps.append(ev.n_predicted)
            print(arm, S, "rings", ev.n_predicted, "matched", int(mats[-1].sum()), flush=True)
        M[arm], NP[arm] = np.stack(mats), np.array(nps, float)
    n = len(ids)

    def stat(m, Wb):
        hit = Wb @ M[m].T                       # (B, seeds)
        tot = Wb.sum(1, keepdims=True)
        rec = hit / tot
        prec = np.minimum(hit / (NP[m][None, :] * tot / n), 1.0)
        f1 = np.where(prec + rec > 0, 2 * prec * rec / np.maximum(prec + rec, 1e-300), 0.0)
        return {"ring_f1": f1.mean(1), "ring_precision": prec.mean(1), "ring_recall": rec.mean(1)}

    other = "genagg_b1b" if a.vs == "b1b" else "old_hm_detector"
    res = paired_unit_bootstrap(stat, [(f"genagg_minus_{a.vs}", "genagg_transfer", other)], n,
                                n_boot=a.n_boot, seed=a.rng_seed)
    rows = []
    for (c, k), v in res.items():
        pt = {m: float(stat(m, np.ones((1, n)))[k][0]) for m in M}
        rows.append({"comparison": c, "rule": a.rule, "metric": k, "n_rings": n, "genagg": pt["genagg_transfer"],
                     "other": pt[other], **v})
    df = pd.DataFrame(rows)
    sfx = ("" if a.rule == "global" else f"_{a.rule}")
    name = "hm_transfer_paired_addendum5" if a.vs == "old" else "hm_transfer_paired_b0_vs_b1b_exploratory"
    df.to_csv(R / f"results/tables/{name}{sfx}.csv", index=False)
    print(df.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
