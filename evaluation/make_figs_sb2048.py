"""Batch-2048 versions of the paper figures that used batch-8192 MEGA values, with MEGA-GenAgg added.
New files beside the old ones (paper/figures/*_sb2048.png); paper/make_figs.py and the old PNGs are untouched.

    .venv312/Scripts/python.exe evaluation/make_figs_sb2048.py

Sources: results/tables/r6_detector_swap_sb2048.csv (GFP-XGBoost, Multi-GINe, MEGA-GNN at 2048);
results/tables/r6_genagg_5seed.csv (MEGA-GenAgg, five seeds, fixed 0.1 %);
results/tables/r6_ring_decomposition_sb2048.csv (Figure 3 classes).
fig_budget_sweep already used batch-2048 MEGA scores (v42_budget_sweep.json r1 = R6_mega_sb2048), so it is not redrawn.
"""
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

R = Path(__file__).resolve().parents[1]
T, OUT = R / "results" / "tables", R / "paper" / "figures"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, PURPLE = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#7a5cc7"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "legend.frameon": False, "savefig.dpi": 300,
    "savefig.bbox": "tight", "figure.facecolor": "white", "axes.facecolor": "white",
})

# ---- Figure 2 (sb2048): edge F1 vs ring F1 across detectors
d = pd.read_csv(T / "r6_detector_swap_sb2048.csv")
g = pd.read_csv(T / "r6_genagg_5seed.csv")
gs = g[(g.detector == "megagenagg") & (g.seed.astype(str) != "mean")]
gm = g[(g.detector == "megagenagg") & (g.seed.astype(str) == "mean")]
ga_std = gs.groupby("method").edge_f1.std(ddof=1).iloc[0]
pts = {}
for det, lab, col in (("gfpxgb", "GFP-XGBoost", AQUA), ("gine_causal", "Multi-GINe", BLUE), ("mega", "MEGA-GNN", ORANGE)):
    pts[det] = (lab, col, {m: d[(d.detector == det) & (d.method == m)].iloc[0] for m in ("b0", "full")}, None)
pts["megagenagg"] = ("MEGA-GenAgg", PURPLE, {m: gm[gm.method == m].iloc[0] for m in ("b0", "full")}, ga_std)
fig, ax = plt.subplots(figsize=(5.2, 3.2))
for det, (lab, col, rows, std) in pts.items():
    for meth, filled in (("b0", False), ("full", True)):
        r = rows[meth]
        ax.errorbar(r.edge_f1, r.ring_f1, yerr=[[r.ring_f1 - r.ring_f1_lo], [r.ring_f1_hi - r.ring_f1]],
                    xerr=r.edge_f1_std if std is None else std, fmt="o", ms=7, color=col, ecolor=col, elinewidth=1,
                    mfc=col if filled else "white", mew=1.6, capsize=2)
    r = rows["full"]
    ax.annotate(lab, (r.edge_f1, r.ring_f1_hi), textcoords="offset points", xytext={"mega": (-14, 5), "megagenagg": (16, 13)}.get(det, (0, 5)), ha="center", color=INK, fontsize=8.5)
ax.plot([], [], "o", color=INK2, mfc="white", mew=1.6, ms=7, label="seeds + components (B0)")
ax.plot([], [], "o", color=INK2, ms=7, label="full pipeline")
ax.set_xlabel("Edge F1, whole test split (mean ± s.d. over 5 seeds)")
ax.set_ylabel("Ring F1, primary window (95% CI)")
ax.set_xlim(0.45, 0.80)
ax.set_ylim(0.2, 0.78)
ax.legend(loc="lower right")
fig.savefig(OUT / "fig_edge_vs_ring_sb2048.png")
plt.close(fig)

# ---- Figure 3 (sb2048): what happens to the 174 truth rings, full pipeline
c = pd.read_csv(T / "r6_ring_decomposition_sb2048.csv")
c = c[c.seed.astype(str) == "mean"].set_index("detector")
order = [("gine_causal", "Multi-GINe"), ("mega_sb2048", "MEGA-GNN"), ("megagenagg_sb2048", "MEGA-GenAgg")]
keys = ["matched", "a_lt3_members", "b_untouched", "c_over_merged", "c_under_covered"]
classes = ["matched", "< 3 visible members, unmatched", "untouched", "over-merged", "under-covered"]
cols = [BLUE, "#b9b8b2", ORANGE, YELLOW, MAGENTA]
fig, ax = plt.subplots(figsize=(6.4, 2.3))
for i, (det, lab) in enumerate(order):
    left = 0
    for j, k in enumerate(keys):
        x = float(c.loc[det, k])
        ax.barh(i, x, left=left, color=cols[j], edgecolor="white", linewidth=1.5, height=0.6,
                label=classes[j] if i == 0 else None)
        if x >= 12:
            ax.text(left + x / 2, i, f"{x:.1f}", ha="center", va="center", color="white" if j in (0, 2) else INK, fontsize=8)
        left += x
ax.set_yticks(range(len(order)))
ax.set_yticklabels([o[1] for o in order])
ax.invert_yaxis()
ax.set_xlim(0, 174)
ax.set_xlabel("Truth rings per seed (of 174), full pipeline, primary window")
ax.grid(False)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=5, fontsize=7.5, handlelength=1.2, columnspacing=1.0)
fig.savefig(OUT / "fig_ring_decomposition_sb2048.png")
plt.close(fig)
print("-> paper/figures/fig_edge_vs_ring_sb2048.png, fig_ring_decomposition_sb2048.png")
