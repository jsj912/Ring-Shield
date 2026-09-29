"""Step 13: every reported figure, regenerated from the tables and run artefacts.

    python evaluation/make_figures.py
    python evaluation/make_figures.py --only quiet pattern

Each figure is built from a committed table or an `experiments/<run>/metrics.json`, never from a
number typed into this file, so `results/figures/` stays traceable in the same way
`results/tables/` is. Figures whose experiment was not run are skipped with a reason rather than
faked (R8 structuring, Step 12 — not run; its premise is weakened by B13 and B15).

    seedfrac      val ring-F1 and the precision/recall pair against the seed fraction, B0 vs full
                  -- the operating-point curve behind FINDINGS E and B3
    pattern       per-pattern ring recall, B0 vs full, primary window
    quiet         quiet-member recall by method with bootstrap CIs (the central claim)
    sensitivity   val-only sensitivity of ring-F1 to delta_t, p_min and the matching threshold tau
    reliability   reliability diagrams for every detector, val and test, before and after isotonic
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

TABLES = REPO_ROOT / "results" / "tables"
FIGS = REPO_ROOT / "results" / "figures"
SEEDS = [1, 2, 3, 4, 5]


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 160, "font.size": 9, "axes.grid": True,
                         "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})
    return plt


# --------------------------------------------------------------------------- 1. seed fraction
def fig_seedfrac(plt) -> Path:
    d = pd.read_csv(TABLES / "r4_sweep_val_curve.csv")
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for m, g in d.groupby("m"):
        s = g.groupby("seed_frac_pct")["ring_f1"].agg(["mean", "std", "count"])
        ax.errorbar(s.index, s["mean"], yerr=s["std"], marker="o", capsize=3, label=m, lw=1.6)
    ax.axvline(0.1, color="k", ls="--", lw=1, alpha=0.6)
    ax.annotate("k* = 0.1 %\n(chosen on val)", (0.1, ax.get_ylim()[0]), xytext=(6, 14),
                textcoords="offset points", fontsize=8)
    ax.set_xlabel("seed fraction k (%)")
    ax.set_ylabel("validation ring-F1")
    ax.set_title("Ring-F1 collapses as the seed budget grows\n"
                 "validation only; the operating point is the argmax, not a tuned curve", fontsize=9)
    ax.legend(title="aggregator", fontsize=8)
    fig.tight_layout()
    out = FIGS / "f1_val_ringf1_vs_seedfrac.png"
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- 2. per pattern
def _per_pattern(root: Path) -> pd.DataFrame:
    rows = []
    for s in SEEDS:
        p = root / f"seed{s}" / "metrics.json"
        if not p.exists():
            continue
        blk = json.loads(p.read_text(encoding="utf-8"))["blocks"]["primary"]["per_pattern"]
        for pat, v in blk.items():
            if isinstance(v, dict):
                n, tot = v.get("matched", v.get("n_matched")), v.get("n_truth", v.get("total"))
            else:
                n, tot = v, None
            rows.append({"seed": s, "pattern": pat, "matched": n, "n_truth": tot})
    return pd.DataFrame(rows)


def fig_pattern(plt) -> Path | None:
    b0 = _per_pattern(REPO_ROOT / "experiments" / "R2_b0" / "gine_causal")
    full = _per_pattern(REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average")
    if b0.empty or full.empty or b0["n_truth"].isna().all():
        print("  [skip] per-pattern: metrics.json has no per-pattern counts")
        return None
    def agg(d):
        g = d.groupby("pattern").agg(matched=("matched", "mean"), n=("n_truth", "mean"))
        return (g["matched"] / g["n"]).sort_values()
    a, b = agg(b0), agg(full)
    pats = list(a.index)
    x = np.arange(len(pats))
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.bar(x - 0.2, a.reindex(pats), 0.4, label="B0 (no expansion)", color="tab:gray")
    ax.bar(x + 0.2, b.reindex(pats), 0.4, label="full (expand + partition)", color="tab:blue")
    ax.set_xticks(x)
    ax.set_xticklabels(pats, rotation=30, ha="right")
    ax.set_ylabel("ring recall (primary window)")
    ax.set_title("Recall is pattern-bound: BIPARTITE and STACK stay near the floor\n"
                 "mean over 5 detector seeds", fontsize=9)
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = FIGS / "f2_per_pattern_recall.png"
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- 3. quiet members
def fig_quiet(plt) -> Path:
    d = pd.read_csv(TABLES / "r9_ring_ci.csv")
    d = d[d["window"] == "primary"]
    order = [m for m in ("b0", "b1", "b1b", "proposed", "average", "gfpxgb") if m in set(d["method"])]
    d = d.set_index("method").reindex(order)
    y = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    lo = d["quiet_member_recall"] - d["quiet_member_recall_lo"]
    hi = d["quiet_member_recall_hi"] - d["quiet_member_recall"]
    ax.barh(y, d["quiet_member_recall"], color="tab:blue", alpha=0.85)
    ax.errorbar(d["quiet_member_recall"], y, xerr=[lo, hi], fmt="none", ecolor="k", capsize=3, lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels(d.index)
    ax.set_xlabel("quiet-member recall (members with no seed edge, recovered)")
    ax.set_title("The central claim, with its interval\n"
                 "primary window, bootstrap over truth rings, seeds averaged inside each resample", fontsize=9)
    fig.tight_layout()
    out = FIGS / "f3_quiet_member_recall.png"
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- 4. val sensitivity
def fig_sensitivity(plt) -> Path:
    import yaml
    rows = []
    for s in SEEDS:
        p = REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed" / f"seed{s}" / "config.yaml"
        if not p.exists():
            continue
        for r in yaml.safe_load(p.read_text(encoding="utf-8"))["grid_results_val"]:
            rows.append({"seed": s, **r})
    g = pd.DataFrame(rows)
    tau = pd.read_csv(TABLES / "r4_appendix.csv")
    tau = tau[(tau["window"] == "primary") & (tau["method"].isin(["average", "b2"]))]

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    for dt, sub in g.groupby("delta_t_h"):
        m = sub.groupby("p_min")["ring_f1"].mean()
        axes[0].plot(m.index, m.values, marker="o", label=f"Δt = {int(dt)} h")
    axes[0].set_xlabel("p_min (policy floor)")
    axes[0].set_ylabel("validation ring-F1")
    axes[0].set_title("floor", fontsize=9)
    axes[0].legend(fontsize=7)

    for pm, sub in g.groupby("p_min"):
        m = sub.groupby("delta_t_h")["ring_f1"].mean()
        axes[1].plot(m.index, m.values, marker="o", label=f"p_min = {pm}")
    axes[1].set_xlabel("Δt (hours)")
    axes[1].set_title("time window", fontsize=9)
    axes[1].legend(fontsize=7)

    for meth, sub in tau.groupby("method"):
        m = sub.groupby("tau")["ring_f1"].mean()
        axes[2].plot(m.index, m.values, marker="o", label=meth)
    axes[2].set_xlabel("Jaccard τ (matching threshold)")
    axes[2].set_title("matching threshold (test)", fontsize=9)
    axes[2].legend(fontsize=7)
    fig.suptitle("Sensitivity: Δt and p_min are chosen on validation; τ is fixed and swept, never tuned",
                 fontsize=9)
    fig.tight_layout()
    out = FIGS / "f4_sensitivity.png"
    fig.savefig(out)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- 5. reliability
def fig_reliability(plt) -> Path:
    from preprocessing.account_bank import load_paths
    pdir = load_paths()["processed_dir"]
    lab = {s: pd.read_parquet(REPO_ROOT / "contract" / "out" / f"labels_{s}.parquet").set_index("edge_id")["true_label"]
           for s in ("val", "test")}
    dets = {"gine_causal": REPO_ROOT / "experiments" / "R1_gine_causal",
            "mega": REPO_ROOT / "experiments" / "R6_mega"}
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 4.0))
    for ax, split in zip(axes, ("val", "test")):
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="perfect")
        for name, root in dets.items():
            f = root / f"scores_{split}_seed1.parquet"
            if not f.exists():
                continue
            d = pd.read_parquet(f)
            y = lab[split].reindex(d["edge_id"]).to_numpy()
            for col, ls in (("score_raw", ":"), ("score_calibrated", "-")):
                if col not in d.columns:
                    continue
                p = d[col].to_numpy(float)
                q = pd.qcut(pd.Series(p).rank(method="first"), 15, labels=False)
                b = pd.DataFrame({"p": p, "y": y, "q": q}).groupby("q").mean()
                ax.plot(b["p"], b["y"], marker="o", ms=3, ls=ls, lw=1.3,
                        label=f"{name} {'calibrated' if col.endswith('calibrated') else 'raw'}")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("mean predicted probability")
        ax.set_ylabel("observed frequency")
        ax.set_title(f"{split} split (seed 1, 15 equal-mass bins)", fontsize=9)
        ax.legend(fontsize=7)
    fig.suptitle("Reliability: isotonic is fitted on val only and applied unchanged to test", fontsize=9)
    fig.tight_layout()
    out = FIGS / "f5_reliability.png"
    fig.savefig(out)
    plt.close(fig)
    return out


BUILDERS = {"seedfrac": fig_seedfrac, "pattern": fig_pattern, "quiet": fig_quiet,
            "sensitivity": fig_sensitivity, "reliability": fig_reliability}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=list(BUILDERS), choices=list(BUILDERS))
    a = ap.parse_args(argv)
    plt = _style()
    FIGS.mkdir(parents=True, exist_ok=True)
    made = []
    for name in a.only:
        try:
            out = BUILDERS[name](plt)
        except Exception as e:                                  # a missing artefact must not kill the run
            print(f"  [skip] {name}: {type(e).__name__}: {e}")
            continue
        if out:
            print(f"  {name:12s} -> {out.relative_to(REPO_ROOT)}")
            made.append(out)
    print("\n  [skip] r8 structuring curves: Step 12 was not run (premise weakened by FINDINGS B13/B15)")
    print(f"{len(made)} figures written to {FIGS.relative_to(REPO_ROOT)}")
    return made


if __name__ == "__main__":
    main()
