"""The operating-point figure: quiet-member recall against added-member precision (Step 9 close).

    python evaluation/quiet_precision_figure.py

One point per method (B0, B1b, proposed, the hop-1 ablation, full) on the primary window over the
five detector seeds, with 95 % CIs on both axes:

    x  quiet-member recall          = quiet members inside a matched predicted ring / all quiet
                                      members (bootstrap over truth rings, results/tables/r9_ring_ci.csv)
    y  added-member precision       = expanded edges that are member edges of a truth ring / all
                                      expanded edges (bootstrap over the added edges, computed here)

B0 adds no edges, so its y is undefined; it is drawn on the x axis as the "adds nothing" anchor.
The figure is the recall / precision knob the ablations trace out, not a ranking.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.step9_tables import METHODS, read_rings_any  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

LABELS = {"b0": "B0 (no expansion)", "b1b": "B1b rule\n(adjacency + quantile)", "proposed": "proposed policy\n(expand + cc)",
          "hop1": "ablation: hop-1 only", "average": "full\n(expand + partition)"}
COLORS = {"b0": "tab:gray", "b1b": "tab:orange", "proposed": "tab:blue", "hop1": "tab:green", "average": "tab:purple"}


def added_edges_flags(method: str, seeds, window) -> np.ndarray:
    """Per expanded edge inside the window (pooled over seeds): 1 if it is a member edge of a truth ring."""
    paths = load_paths()
    pdir = paths["processed_dir"]
    ring_id = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id", "Timestamp"]).set_index("EdgeID")
    root = METHODS[method][0]
    flags = []
    for s in seeds:
        p = root / f"seed{s}" / "rings.parquet"
        if not p.exists():
            continue
        rings = read_rings_any(p)
        exp = sorted({e for r in rings for e in r.expanded_edges})
        if not exp:
            continue
        sub = ring_id.loc[exp]
        sub = sub[window.mask(sub["Timestamp"].to_numpy())]
        flags.append((sub["ring_id"].to_numpy() > 0).astype(float))
    return np.concatenate(flags) if flags else np.zeros(0)


def boot_mean(x: np.ndarray, n: int = 1000, seed: int = 0):
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    d = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main(argv=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--methods", nargs="*", default=["b0", "b1b", "proposed", "hop1", "average"])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "figures" / "r9_quiet_vs_precision.png")
    args = ap.parse_args(argv)
    W = load_windows()["primary"]
    ci = pd.read_csv(REPO_ROOT / "results" / "tables" / "r9_ring_ci.csv")
    ci = ci[ci["window"] == "primary"].set_index("method")
    rows = []
    for m in args.methods:
        q = ci.loc[m]
        flags = added_edges_flags(m, args.seeds, W)
        p, lo, hi = boot_mean(flags)
        rows.append({"method": m, "quiet": float(q["quiet_member_recall"]), "quiet_lo": float(q["quiet_member_recall_lo"]),
                     "quiet_hi": float(q["quiet_member_recall_hi"]), "prec": p, "prec_lo": lo, "prec_hi": hi,
                     "n_added_edges": int(len(flags)), "ring_f1": float(q["ring_f1"])})
        print(f"  {m:9s} quiet {rows[-1]['quiet']:.3f} [{rows[-1]['quiet_lo']:.3f}, {rows[-1]['quiet_hi']:.3f}] | "
              f"added-member precision {p:.3f} [{lo:.3f}, {hi:.3f}] over {len(flags)} added edges | ring-F1 {rows[-1]['ring_f1']:.3f}")
    d = pd.DataFrame(rows)
    d.to_csv(str(args.out).replace(".png", ".csv"), index=False)

    fig, ax = plt.subplots(figsize=(6.6, 4.6), dpi=160)
    for r in rows:
        c = COLORS.get(r["method"], "k")
        if np.isnan(r["prec"]):
            ax.errorbar(r["quiet"], 0.0, xerr=[[r["quiet"] - r["quiet_lo"]], [r["quiet_hi"] - r["quiet"]]],
                        fmt="v", color=c, capsize=3, ms=9)
            ax.annotate(LABELS.get(r["method"], r["method"]) + "\n(adds nothing)", (r["quiet"], 0.0),
                        textcoords="offset points", xytext=(8, 10), fontsize=8, color=c)
            continue
        ax.errorbar(r["quiet"], r["prec"], xerr=[[r["quiet"] - r["quiet_lo"]], [r["quiet_hi"] - r["quiet"]]],
                    yerr=[[r["prec"] - r["prec_lo"]], [r["prec_hi"] - r["prec"]]], fmt="o", color=c, capsize=3, ms=7)
        ax.annotate(LABELS.get(r["method"], r["method"]), (r["quiet"], r["prec"]), textcoords="offset points",
                    xytext=(9, -4), fontsize=8, color=c)
    ax.set_xlabel("quiet-member recall  (members with no seed edge, recovered)")
    ax.set_ylabel("added-member precision  (expanded edges that are true members)")
    ax.set_title("The operating point is a trade, not a ranking\nprimary window, 5 detector seeds, 95 % CIs on both axes", fontsize=10)
    ax.set_xlim(-0.01, 0.34)
    ax.set_ylim(-0.03, 1.03)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
