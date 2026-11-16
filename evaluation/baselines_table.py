"""T-P3 table: community / external baselines and our four methods under every scope convention.

    python evaluation/baselines_table.py --baselines-root experiments/R13_baselines \
        --ours-root ../RS-e2e/experiments --out results/tables/v40_external_baselines.csv

1. Scores every method's runs with evaluation/score_external.py (primary window, four conventions,
   Jaccard 0.3 / 0.5 / 0.7) into <baselines-root>/scored/<method>/.
2. Bar (A): ordering of {CSGM, Louvain, label propagation, B0, B1b, proposed, full} by ring-F1 point
   estimate (Jaccard 0.5) under test_visible vs each other convention; success if any adjacent pair
   (in the test_visible order) swaps under another convention. Leiden was registered but not run
   (not installable here; see results/notes/p3_baselines.md).
3. Bar (B): the best community baseline -- chosen by mean VALIDATION ring-F1 at its chosen cell
   (config.yaml), not on test -- vs B0 and vs full: paired unit bootstrap over truth targets
   (score_external --compare, 10,000 draws, seed 20261114), Holm across these two comparisons,
   test_visible, Jaccard 0.5.
Gate: any baseline ring-F1 >= 0.5894 (test_visible, 0.5) -> METHOD_SUPERIORITY=OFF.

Writes only --out (csv), the json beside it, and <baselines-root>/scored/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import evaluation.score_external as sx  # noqa: E402
from evaluation.ring_stats import holm  # noqa: E402

COMMUNITY = ["louvain_r0.5", "louvain_r1", "louvain_r2", "lpa"]
PARTITION_ALT = ["louvain_r1_on_expansion", "lpa_on_expansion", "components_on_expansion"]
OURS = {"b0": "R2_b0/gine_causal", "b1b": "R3_expansion/runs/b1b", "proposed": "R3_expansion/runs/proposed",
        "full": "R4_partition/runs/average"}
FULL_REF = 0.5894
B0_REF = 0.5213


def val_f1(root: Path, method: str, seeds) -> float:
    vals = []
    for s in seeds:
        cfg = yaml.safe_load((root / method / f"seed{s}" / "config.yaml").read_text(encoding="utf-8"))
        vals.append(cfg["chosen"]["val_ring_f1"])
    return sum(vals) / len(vals)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baselines-root", type=Path, default=REPO_ROOT / "experiments" / "R13_baselines")
    ap.add_argument("--ours-root", type=Path, default=REPO_ROOT / "experiments")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v40_external_baselines.csv")
    ap.add_argument("--scored-dir", type=Path, default=None,
                    help="cache of per-method score_external outputs (default <baselines-root>/scored)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    runs = {m: [a.baselines_root / m / f"seed{s}" / "rings.parquet" for s in a.seeds] for m in COMMUNITY + PARTITION_ALT}
    runs["csgm"] = [a.baselines_root / "csgm" / f"seed{s}" / "rings.parquet" for s in a.seeds]
    for m, rel in OURS.items():
        runs[m] = [a.ours_root / rel / f"seed{s}" / "rings.parquet" for s in a.seeds]
    scored = a.scored_dir or a.baselines_root / "scored"
    rows = []
    for m, files in runs.items():
        d = scored / m
        if not (d / "summary.csv").exists():
            sx.main(["--rings", *map(str, files), "--split", "test", "--window", "primary",
                     "--n-boot", str(a.n_boot), "--out", str(d)])
        s = pd.read_csv(d / "summary.csv")
        s.insert(0, "method", m)
        rows.append(s)
    tab = pd.concat(rows, ignore_index=True)
    kind = {**{m: "community" for m in COMMUNITY}, **{m: "partition_alternative" for m in PARTITION_ALT},
            "csgm": "external", **{m: "ours" for m in OURS}}
    tab.insert(1, "kind", tab["method"].map(kind))

    # ---- bar (A)
    at = tab[tab.threshold == 0.5]
    ranked = ["csgm", *COMMUNITY, *OURS]
    piv = at[at.method.isin(ranked)].pivot(index="method", columns="convention", values="ring_f1")
    tv_order = piv["test_visible"].sort_values(ascending=False).index.tolist()
    swaps = {}
    for conv in [c for c in piv.columns if c != "test_visible"]:
        sw = [(x, y) for x, y in zip(tv_order, tv_order[1:]) if piv.loc[x, conv] < piv.loc[y, conv]]
        swaps[conv] = sw
    bar_a = {"test_visible_order": tv_order,
             "orders": {c: piv[c].sort_values(ascending=False).index.tolist() for c in piv.columns},
             "adjacent_swaps": swaps, "success": any(swaps.values())}

    # ---- bar (B)
    vf = {m: val_f1(a.baselines_root, m, a.seeds) for m in COMMUNITY}
    best = max(vf, key=vf.get)
    comps = {}
    for ref in ("b0", "full"):
        d = scored / f"compare_{best}_vs_{ref}"
        if not (d / "compare.csv").exists():
            sx.main(["--compare", str(scored / best), str(scored / ref), "--out", str(d)])
        c = pd.read_csv(d / "compare.csv")
        comps[ref] = c[(c.convention == "test_visible") & (c.threshold == 0.5) & (c.metric == "ring_f1")].iloc[0].to_dict()
    adj = {h["comparison"]: h for h in holm([(k, v["p"]) for k, v in comps.items()])}
    tv5 = at[at.convention == "test_visible"].set_index("method")["ring_f1"]
    bar_b = {"best_community_by_val": best, "val_ring_f1": vf, "test_ring_f1": float(tv5[best]),
             "competitive_vs_b0": bool(tv5[best] >= B0_REF),
             "comparisons": {k: {**v, "p_holm": adj[k]["p_holm"]} for k, v in comps.items()}}
    non_ours = tv5[[m for m in tv5.index if kind[m] != "ours" and m != "components_on_expansion"]]  # identity check, not a baseline
    gate = {"max_baseline": non_ours.idxmax(), "max_baseline_ring_f1": float(non_ours.max()),
            "METHOD_SUPERIORITY": "OFF" if (non_ours >= FULL_REF).any() else "ON"}

    a.out.parent.mkdir(parents=True, exist_ok=True)
    tab.drop(columns=[c for c in tab.columns if c == "per_pattern_recall"]).to_csv(a.out, index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "runs": {k: list(map(str, v)) for k, v in runs.items()},
            "bar_A": bar_a, "bar_B": bar_b, "gate": gate,
            "notes": ["Leiden registered, not run: leidenalg/igraph not installed (install not permitted in this session).",
                      "partition_alternative rows: community step on R3 proposed's expanded subgraph, nothing tuned; "
                      "components_on_expansion reproduces proposed (identity check).",
                      "CSGM uses no detector: its five runs are bank seeds 0-4 (random two-institution splits)."]}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(at[at.convention == "test_visible"][["method", "kind", "ring_precision", "ring_recall", "ring_f1", "ring_f1_lo", "ring_f1_hi"]]
          .round(4).to_string(index=False))
    print(json.dumps({"bar_A": bar_a, "bar_B": bar_b, "gate": gate}, indent=2, default=str))
    return meta


if __name__ == "__main__":
    main()
