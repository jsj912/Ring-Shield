"""B13: are the missing members of under-covered rings connected to the recovered fragment inside
the evaluation window?

    python evaluation/in_window_connectivity.py

For every under-covered ring (class c in `evaluation/unmatched_rings.py`) of the five shipped
`full` runs, the fragment is the prediction with the best Jaccard against the ring, restricted to
the window. A missing member edge is *disconnected* when no path through the ring's own in-window
edges joins it to the fragment: the walk of `historical_bridge.in_window_disconnected`, run here
per seed, per pattern and per window (primary, days 8-9, and whole, days 8-17). Graph walk only:
nothing is trained or re-scored.

Outputs `results/tables/r_in_window_connectivity.csv` (one row per ring) and `.json` (totals per
window, per seed and per pattern).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.historical_bridge import ROOT, SCORES, SEEDS, in_window_disconnected  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

WINDOWS = ("primary", "whole")


def window_rows(window, seeds, pdir, ring_edges) -> list[dict]:
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *window.bounds,
                                        "test_visible", verbose=False)
    rows = []
    for s in seeds:
        se = build_scored_edges(SCORES / f"scores_test_seed{s}.parquet", "test",
                                model_id="gine_causal", seed=s, processed_dir=pdir)
        rings = read_rings_any(ROOT / f"seed{s}" / "rings.parquet")
        kl = classify(rings, se, truth, patterns, window).set_index("ring_id")
        ts = se.set_index("edge_id")["timestamp"]
        in_win = set(ts.index[window.mask(ts.values)].tolist())
        pred = restrict_rings(rings, se, window)
        kept = [i for i, r in enumerate(rings) if any(e in in_win for e in r.member_edges)]
        for tid, accs in truth.items():
            if kl.loc[tid, "klass"] != "c_under_covered":
                continue
            g = ring_edges.get(int(tid))
            best_j, best_i = 0.0, None
            for j, P in enumerate(pred):
                inter = len(P & accs)
                if inter and inter / len(P | accs) > best_j:
                    best_j, best_i = inter / len(P | accs), j
            if g is None or best_i is None:
                continue
            frag = {e for e in rings[kept[best_i]].member_edges if e in in_win}
            n_missing, n_disconnected = in_window_disconnected(g, frag, in_win)
            rows.append({"window": window.name, "seed": s, "ring_id": int(tid),
                         "pattern": patterns.get(tid, "?"), "n_missing": n_missing,
                         "n_disconnected": n_disconnected})
        done = [r for r in rows if r["seed"] == s]
        print(f"  {window.name} seed {s}: {sum(r['n_disconnected'] for r in done)}/"
              f"{sum(r['n_missing'] for r in done)} disconnected", flush=True)
    return rows


def totals(d: pd.DataFrame) -> dict:
    n, k = int(d["n_missing"].sum()), int(d["n_disconnected"].sum())
    return {"n_missing": n, "n_disconnected": k, "share": k / n if n else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r_in_window_connectivity.csv")
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    cols = ["EdgeID", "from_id", "to_id", "Timestamp", "ring_id"]
    full = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=cols)
                      for s in ("train", "val", "test")], ignore_index=True)
    ring_edges = {int(r): g for r, g in full[full.ring_id > 0].groupby("ring_id")}
    windows = load_windows()

    d = pd.DataFrame([row for w in WINDOWS for row in window_rows(windows[w], a.seeds, pdir, ring_edges)])
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "seeds": a.seeds, "runs": "experiments/R4_partition/runs/average (full)", "windows": {}}
    for w, g in d.groupby("window"):
        summary["windows"][w] = {**totals(g),
                                 "by_seed": {int(s): totals(x) for s, x in g.groupby("seed")},
                                 "by_pattern": {p: totals(x) for p, x in g.groupby("pattern")}}
        t = summary["windows"][w]
        print(f"\n{w}: {t['n_disconnected']}/{t['n_missing']} disconnected = {t['share']*100:.1f} %")
        for p, x in t["by_pattern"].items():
            print(f"   {p:16s} {x['n_disconnected']:4d}/{x['n_missing']:4d}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    a.out.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n-> {a.out}")
    return summary


if __name__ == "__main__":
    main()
