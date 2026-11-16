"""Paper figures built only from files in the RS-react repository (read-only).
Usage: python make_figs.py <repo_root> <out_dir>
"""
import sys, os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

repo, out = sys.argv[1], sys.argv[2]
T = os.path.join(repo, "results", "tables")

BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "legend.frameon": False, "savefig.dpi": 300,
    "savefig.bbox": "tight", "figure.facecolor": "white", "axes.facecolor": "white",
})

# ---- Figure 1: per-day laundering base rate in the test period, HI-Small vs LI-Small
# source: docs/paper/evaluation_protocol.md §4 (per-day base-rate table)
days = list(range(8, 18))
hi = [0.079, 0.212, 58.6, 60.5, 57.6, 57.9, 60.9, 56.5, 65.2, 72.7]
li = [0.041, 0.106, 61.0, 56.3, 60.4, 58.1, 66.7, 71.4, 66.7, None]
fig, ax = plt.subplots(figsize=(5.2, 2.7))
ax.axvspan(7.5, 9.5, color="#f0efec", zorder=0)
ax.plot(days, hi, color=BLUE, lw=2, marker="o", ms=5, label="HI-Small")
ax.plot(days[:-1], li[:-1], color=ORANGE, lw=2, marker="s", ms=5, label="LI-Small")
ax.set_yscale("log")
ax.set_yticks([0.05, 0.1, 1, 10, 60])
ax.set_yticklabels(["0.05%", "0.1%", "1%", "10%", "60%"])
ax.set_xticks(days)
ax.set_xlabel("Test day")
ax.set_ylabel("Laundering base rate (log scale)")
ax.text(8.5, 3.0, "primary\nwindow", ha="center", va="center", color=INK2, fontsize=8)
ax.text(13.5, 20, "tail: ~60% base rate on\n0.13% of HI-Small test edges", ha="center",
        color=INK2, fontsize=8)
ax.legend(loc="lower right")
fig.savefig(os.path.join(out, "fig_tail_base_rate.png"))
plt.close(fig)

# ---- Figure 2: edge F1 vs ring F1 across detectors
# source: results/tables/r6_detector_swap.csv
d = pd.read_csv(os.path.join(T, "r6_detector_swap.csv"))
names = {"gfpxgb": ("GFP-XGBoost", AQUA), "gine_causal": ("Multi-GINe", BLUE), "mega": ("MEGA-GNN", ORANGE)}
fig, ax = plt.subplots(figsize=(5.2, 3.2))
for det, (lab, col) in names.items():
    for meth, filled in (("b0", False), ("full", True)):
        r = d[(d.detector == det) & (d.method == meth)].iloc[0]
        ax.errorbar(r.edge_f1, r.ring_f1,
                    yerr=[[r.ring_f1 - r.ring_f1_lo], [r.ring_f1_hi - r.ring_f1]],
                    xerr=r.edge_f1_std, fmt="o", ms=7, color=col, ecolor=col, elinewidth=1,
                    mfc=col if filled else "white", mew=1.6, capsize=2,
                    label=None)
    r = d[(d.detector == det) & (d.method == "full")].iloc[0]
    ax.annotate(lab, (r.edge_f1, r.ring_f1_hi), textcoords="offset points", xytext=(0, 5),
                ha="center", color=INK, fontsize=8.5)
ax.plot([], [], "o", color=INK2, mfc="white", mew=1.6, ms=7, label="seeds + components (B0)")
ax.plot([], [], "o", color=INK2, ms=7, label="full pipeline")
ax.set_xlabel("Edge F1, whole test split (mean ± s.d. over 5 seeds)")
ax.set_ylabel("Ring F1, primary window (95% CI)")
ax.set_xlim(0.45, 0.76)
ax.set_ylim(0.2, 0.78)
ax.legend(loc="lower right")
fig.savefig(os.path.join(out, "fig_edge_vs_ring.png"))
plt.close(fig)

# ---- Figure 3: what happens to the 174 truth rings
# source: docs/FINDINGS.md B11 (results/tables/r6_detector_swap.csv, evaluation/unmatched_rings.py)
classes = ["matched", "< 3 visible members,\nunmatched", "untouched", "over-merged", "under-covered"]
vals = {"Multi-GINe": [80.2, 48.6, 33.2, 5.2, 6.8], "MEGA-GNN": [83.6, 51.6, 24.0, 8.2, 6.6]}
cols = [BLUE, "#b9b8b2", ORANGE, YELLOW, MAGENTA]
fig, ax = plt.subplots(figsize=(6.4, 1.9))
for i, (det, v) in enumerate(vals.items()):
    left = 0
    for j, x in enumerate(v):
        ax.barh(i, x, left=left, color=cols[j], edgecolor="white", linewidth=1.5, height=0.6,
                label=classes[j].replace("\n", " ") if i == 0 else None)
        if x >= 12:
            ax.text(left + x / 2, i, f"{x:g}", ha="center", va="center",
                    color="white" if j in (0, 2) else INK, fontsize=8)
        left += x
ax.set_yticks([0, 1])
ax.set_yticklabels(list(vals.keys()))
ax.invert_yaxis()
ax.set_xlim(0, 174)
ax.set_xlabel("Truth rings per seed (of 174), full pipeline, primary window")
ax.grid(False)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.38), ncol=5, fontsize=7.5,
          handlelength=1.2, columnspacing=1.0)
fig.savefig(os.path.join(out, "fig_ring_decomposition.png"))
plt.close(fig)

# ---- Figure 4: ring F1 under four scope conventions (Multi-GINe)
# source: results/tables/v36_component_scope.csv and r14_scope_sensitivity.csv
c = pd.read_csv(os.path.join(T, "v36_component_scope.csv"))
s = pd.read_csv(os.path.join(T, "r14_scope_sensitivity.csv"))
c = c[c.detector == "gine_causal"]
s = s[(s.detector == "gine_causal") & (s.policy == "full_membership")]
methods = [("b0", "B0"), ("b1b", "rule (B1b)"), ("proposed", "policy"), ("full", "policy +\npartition")]
convs = [("full_membership", "all member accounts", MAGENTA, s),
         ("component", "every in-window piece", AQUA, c[c.policy == "component"]),
         ("test_visible", "in-window accounts (reported)", BLUE, c[c.policy == "test_visible"]),
         ("component_ge3", "pieces of >= 3 accounts", ORANGE, c[c.policy == "component_ge3"])]
fig, ax = plt.subplots(figsize=(6.2, 3.0))
w = 0.2
for k, (_, lab, col, df) in enumerate(convs):
    xs, ys, lo, hi_ = [], [], [], []
    for i, (m, _) in enumerate(methods):
        r = df[df.method == m].iloc[0]
        xs.append(i + (k - 1.5) * w); ys.append(r.ring_f1)
        lo.append(r.ring_f1 - r.ring_f1_lo); hi_.append(r.ring_f1_hi - r.ring_f1)
    ax.bar(xs, ys, width=w - 0.02, color=col, label=lab)
    ax.errorbar(xs, ys, yerr=[lo, hi_], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=1.5)
ax.set_xticks(range(len(methods)))
ax.set_xticklabels([m[1] for m in methods])
ax.set_ylabel("Ring F1 (95% CI)")
ax.set_ylim(0, 0.9)
ax.grid(axis="x", visible=False)
ax.legend(title="A truth ring's member set is...", loc="lower center",
          bbox_to_anchor=(0.5, 1.02), fontsize=7.5, title_fontsize=8, ncol=2)
fig.savefig(os.path.join(out, "fig_scope_conventions.png"))
plt.close(fig)
# ---- Figure 5: B0 ring F1 against seed budget, three detectors, global and in-window rules (T-P8)
# source: results/tables/v42_budget_sweep.csv (mean and SD over 5 seeds)
v = pd.read_csv(os.path.join(T, "v42_budget_sweep.csv"))
g = v.groupby(["detector", "rule", "k_pct"]).b0_ring_f1.agg(["mean", "std"]).reset_index()
dets = [("gine_causal", "Multi-GINe", BLUE, "o"), ("mega", "MEGA-GIN", ORANGE, "s"), ("gfpxgb", "GFP+XGB", AQUA, "^")]
fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.7), sharey=True)
for ax, (rule, title) in zip(axes, [("global", "global budget"), ("in_window", "in-window budget")]):
    for d, lab, col, mk in dets:
        r = g[(g.detector == d) & (g.rule == rule)].sort_values("k_pct")
        ax.errorbar(r.k_pct, r["mean"], yerr=r["std"], color=col, marker=mk, ms=4, lw=1.6, capsize=2, label=lab)
    ax.set_title(title, fontsize=9)
    ax.set_xlabel("Seed budget (% of test edges)")
    ax.set_xticks([0.05, 0.10, 0.15, 0.20, 0.30])
axes[0].set_ylabel("Seed-only ring F1 (mean, SD)")
axes[0].set_ylim(0, 0.7)
axes[1].legend(loc="lower right", fontsize=7.5)
fig.savefig(os.path.join(out, "fig_budget_sweep.png"))
plt.close(fig)
print("figures written")
