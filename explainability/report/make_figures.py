"""Figures for the XAI report chapter, drawn from the results files (no number is typed here).

    python -m explainability.report.make_figures        # -> explainability/report/figures/*.png

Palette: the reference categorical palette (slots 1-3 only, validated all-pairs), recessive grey axes, text in ink
colours, a legend for every multi-series chart and direct value labels where they help.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from explainability.contract_io import load_config, repo_path  # noqa: E402

S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"           # categorical slots 1-3 (reference palette, light mode)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#d9d8d3"
OUT = Path(__file__).resolve().parent / "figures"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK, "axes.titlesize": 11,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 100})


def _load(name):
    return json.loads((repo_path("results/xai") / name).read_text(encoding="utf-8"))


def _save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return OUT / name


def grouped_ci(blocks: dict, ks, title, ylabel, name, ylim=(0, 1.05)):
    """Grouped bars (one group per k, one bar per ranking) with 95 % CI whiskers and value labels."""
    import numpy as np
    names = [("w_total", "Ours (w_total)", S1), ("score_only", "Score-only", S2), ("random", "Random", S3)]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    x = np.arange(len(ks))
    w = 0.26
    for i, (key, label, col) in enumerate(names):
        pts = [blocks[key][str(k)]["point"] for k in ks]
        lo = [blocks[key][str(k)]["point"] - blocks[key][str(k)]["lo"] for k in ks]
        hi = [blocks[key][str(k)]["hi"] - blocks[key][str(k)]["point"] for k in ks]
        bars = ax.bar(x + (i - 1) * w, pts, w - 0.03, color=col, label=label, zorder=2)
        ax.errorbar(x + (i - 1) * w, pts, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=1, capsize=2, zorder=3)
        for b, v in zip(bars, pts):
            ax.text(b.get_x() + b.get_width() / 2, 0.03, f"{v:.2f}", ha="center", va="bottom", fontsize=7, color="white",
                    rotation=90)
    ax.set_xticks(x, [f"k = {k}" for k in ks])
    ax.set_ylim(*ylim)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    return _save(fig, name)


def fig_fidelity(cfg):
    f = _load("fidelity.json")
    ks = f["evaluation"]["k"]
    a = grouped_ci(f["headline"]["fidelity"], ks, "Fidelity@k on matched rings (100 truth rings, 95% CI)",
                   "fidelity@k", "fig_fidelity.png")
    b = grouped_ci(f["xr23"]["headline_b_expanded_recall"]["fidelity"], ks,
                   "Expanded recall@k: recovered quiet-member edges (56 truth rings)", "expanded recall@k",
                   "fig_expanded_recall.png")
    return [a, b]


def fig_detectors(cfg):
    import numpy as np
    d = _load(cfg["detectors_summary_name"])["detectors"]
    labels = {"gine_causal": "Multi-GINe", "gfpxgb": "GFP+XGBoost", "mega": "MEGA-GNN"}
    names = [("w_total", "Ours (w_total)", S1), ("score_only", "Score-only", S2), ("random", "Random", S3)]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    x = np.arange(len(d))
    w = 0.26
    for i, (key, label, col) in enumerate(names):
        pts = [d[k]["fidelity_at5"][key] for k in d]
        lo = [d[k]["fidelity_at5"][key] - d[k]["fidelity_at5_ci"][key][0] for k in d]
        hi = [d[k]["fidelity_at5_ci"][key][1] - d[k]["fidelity_at5"][key] for k in d]
        bars = ax.bar(x + (i - 1) * w, pts, w - 0.03, color=col, label=label, zorder=2)
        ax.errorbar(x + (i - 1) * w, pts, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=1, capsize=2, zorder=3)
        for b, v in zip(bars, pts):
            ax.text(b.get_x() + b.get_width() / 2, 0.03, f"{v:.3f}", ha="center", va="bottom", fontsize=7,
                    color="white", rotation=90)
    ax.set_xticks(x, [labels[k] for k in d])
    ax.set_ylim(0, 1.05)                                    # bars start at zero
    ax.set_ylabel("fidelity@5")
    ax.set_title("Fidelity@5 on three detectors, same code (95% CI)", loc="left")
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.legend(frameon=False, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    return [_save(fig, "fig_detectors.png")]


def fig_typology(cfg):
    import numpy as np
    t = _load(cfg["typology_name"])
    groups = [("Primary window\n(days 8-9)", t["primary"]), ("Whole test period\n(days 8-17)", t["whole_test_period"])]
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    x = np.arange(len(groups))
    w = 0.34
    for i, (key, label, col) in enumerate([("head", "Typing head (narrated)", S1), ("rule", "Rule scorer", S2)]):
        pts = [g[key]["point"] for _, g in groups]
        ax.bar(x + (i - 0.5) * w, pts, w - 0.04, color=col, label=label, zorder=2)
        for xi, v in zip(x + (i - 0.5) * w, pts):
            ax.text(xi, v + 0.015, f"{v:.3f}", ha="center", fontsize=8, color=INK)
    legacy = t["reproduction_of_r5_typing"]["position_lookup"]["head_accuracy"]
    ax.plot([-0.45, 0.05], [legacy, legacy], color=INK2, linestyle="--", linewidth=1.2, zorder=3)
    ax.text(-0.45, legacy + 0.035, f"earlier table (lookup bug): {legacy:.3f}", fontsize=8, color=INK2,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.set_xticks(x, [g for g, _ in groups])
    ax.set_ylim(0, 0.8)
    ax.set_ylabel("typology accuracy")
    ax.set_title("Accuracy of the narrated shape on matched rings", loc="left")
    ax.yaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    ax.legend(frameon=False, ncol=2, loc="upper left", bbox_to_anchor=(0, -0.18))
    return [_save(fig, "fig_typology.png")]


def fig_review(cfg):
    s = json.loads((repo_path(cfg["review"]["out_dir"]) / "review_summary.json").read_text(encoding="utf-8"))
    pq = s["per_question"]
    labels = {"q1_topology_plausible": "q1 shape plausible", "q2_named_accounts_matter": "q2 named accounts matter",
              "q3_evidence_enough": "q3 evidence enough", "q4_misleading": "q4 something misleading"}
    fig, ax = plt.subplots(figsize=(6.2, 2.8))
    keys = list(labels)[::-1]
    vals = [pq[k]["yes_rate"] for k in keys]
    ax.barh([labels[k] for k in keys], vals, color=S1, height=0.55, zorder=2)
    for i, k in enumerate(keys):
        kap = pq[k]["fleiss_kappa"]
        note = "κ n/a (unanimous)" if kap is None else f"κ = {kap:.2f} ({pq[k]['kappa_band']})"
        ax.text(vals[i] + 0.02, i, f"{vals[i]:.2f}   {note}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, 1.75)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xlabel("share of 'yes' answers (90 answers per question)")
    ax.set_title("Internal review of 30 explanations: answers and agreement", loc="left")
    ax.xaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    return [_save(fig, "fig_review.png")]


def fig_latency(cfg):
    lat = _load(cfg["latency_name"])
    st = sorted(lat["stages"].items(), key=lambda kv: kv[1]["mean_ms"])
    names = {"leave_one_out": "leave-one-out reruns", "shap": "SHAP", "roles_accounts_topology": "roles, accounts, shape",
             "narrative": "narrative", "edge_weights": "edge weights", "assemble": "assemble row", "read": "read ring"}
    fig, ax = plt.subplots(figsize=(6.2, 2.8))
    ax.barh([names.get(k, k) for k, _ in st], [v["mean_ms"] for _, v in st], color=S1, height=0.55, zorder=2)
    for i, (_, v) in enumerate(st):
        ax.text(v["mean_ms"] + 3, i, f"{v['mean_ms']:.0f} ms ({v['share_of_time']:.0%})", va="center", fontsize=8,
                color=INK)
    ax.set_xlabel("mean time per ring (ms)")
    p = lat["pooled"]
    ax.set_title(f"Where a ring's explanation time goes (p50 {p['p50_ms']:.0f} ms, p95 {p['p95_ms']:.0f} ms)", loc="left")
    ax.set_xlim(0, max(v["mean_ms"] for _, v in st) * 1.45)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6, zorder=0)
    return [_save(fig, "fig_latency.png")]


def _box(ax, x, y, w, h, text, fill="#eef3fb", edge=S1, size=8.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", facecolor=fill,
                                edgecolor=edge, linewidth=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK, wrap=True)


def _arrow(ax, x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=INK2, linewidth=1.2))


def fig_architecture(cfg):
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.axis("off")
    grey = "#f2f2f0"
    _box(ax, 0.1, 4.6, 2.3, 1.0, "Research layers L0-L3\nscored edges, rings\n(contract v2)", grey, INK2)
    _box(ax, 0.1, 3.1, 2.3, 1.0, "Shared inputs\nGFP, embeddings,\naffinity, fx, names", grey, INK2)
    _box(ax, 3.0, 4.6, 1.9, 1.0, "contract_io\nstrict reader\n(v1 / v2)")
    _box(ax, 3.0, 3.1, 1.9, 1.0, "edge_weights\nw_score, w_loo,\nw_flow, w_total")
    _box(ax, 3.0, 1.6, 1.9, 1.0, "account_weights\nroles, flows,\nw_account")
    _box(ax, 5.4, 4.6, 1.9, 1.0, "feature_weights\nSHAP on the\nreference model")
    _box(ax, 5.4, 3.1, 1.9, 1.0, "narrative\ntemplates +\nevidence_summary")
    _box(ax, 5.4, 1.6, 1.9, 1.0, "explain\none row per ring\n(provenance)")
    _box(ax, 7.8, 4.6, 2.1, 1.0, "evaluate / review\nfidelity, typology,\nroles, latency, κ")
    _box(ax, 7.8, 3.1, 2.1, 1.0, "api / tenant\nfour endpoint\nfunctions")
    _box(ax, 7.8, 1.6, 2.1, 1.0, "Platform L5-L6\nFastAPI service,\ndashboard", grey, INK2)
    _box(ax, 3.0, 0.15, 6.9, 0.9, "results/xai: explanations, fidelity, typology,\nlatency, review, tenant", "#fdf1ec", S2)
    _arrow(ax, 2.4, 5.1, 3.0, 5.1)
    _arrow(ax, 2.4, 3.6, 3.0, 3.6)
    _arrow(ax, 3.95, 4.6, 3.95, 4.1)
    _arrow(ax, 3.95, 3.1, 3.95, 2.6)
    _arrow(ax, 4.9, 3.6, 5.4, 3.6)
    _arrow(ax, 4.9, 2.1, 5.4, 2.1)
    _arrow(ax, 6.35, 4.6, 6.35, 4.1)
    _arrow(ax, 6.35, 3.1, 6.35, 2.6)
    _arrow(ax, 7.3, 2.1, 7.8, 3.4)
    _arrow(ax, 7.3, 2.1, 7.8, 4.9)
    _arrow(ax, 8.85, 3.1, 8.85, 2.6)
    _arrow(ax, 6.35, 1.6, 6.35, 1.05)
    ax.set_title("L4 explainability layer: modules and data flow", loc="left", fontsize=11, color=INK)
    return [_save(fig, "fig_architecture.png")]


def fig_sequence(cfg):
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")
    actors = [(1.0, "Analyst\n(dashboard)"), (3.4, "Platform\nFastAPI"), (5.8, "L4 api.regenerate"), (8.4, "explain_ring\n+ research code")]
    for x, name in actors:
        _box(ax, x - 0.9, 6.0, 1.8, 0.8, name)
        ax.plot([x, x], [0.3, 6.0], color=GRID, linewidth=1, linestyle="--")
    msgs = [(1.0, 3.4, 5.4, "partial verdict: remove accounts / edges"),
            (3.4, 5.8, 4.6, "regenerate(tenant, ring, request)"),
            (5.8, 5.8, 3.9, "edit_ring: check ids, drop edges, keep ≥ 2 accounts"),
            (5.8, 8.4, 3.2, "explain edited ring (LOO reruns, roles, SHAP)"),
            (8.4, 5.8, 2.4, "new row + provenance.regenerated"),
            (5.8, 3.4, 1.7, "Explanation (or 404 / 422 error)"),
            (3.4, 1.0, 1.0, "refreshed panels; original kept")]
    for x1, x2, y, text in msgs:
        if x1 == x2:
            ax.annotate("", xy=(x1 + 0.05, y - 0.25), xytext=(x1 + 0.05, y + 0.1),
                        arrowprops=dict(arrowstyle="->", color=INK2, connectionstyle="arc3,rad=-1.2"))
            ax.text(x1 + 0.35, y - 0.05, text, fontsize=7.5, color=INK, va="center")
        else:
            _arrow(ax, x1, y, x2, y)
            ax.text((x1 + x2) / 2, y + 0.12, text, fontsize=7.5, color=INK, ha="center")
    ax.set_title("Sequence: regenerating an explanation after a partial verdict", loc="left", fontsize=11, color=INK)
    return [_save(fig, "fig_sequence_regenerate.png")]


def main(argv=None) -> int:
    cfg = load_config()
    made = []
    for f in (fig_architecture, fig_sequence, fig_fidelity, fig_detectors, fig_typology, fig_review, fig_latency):
        made += f(cfg)
    for p in made:
        print(p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
