"""Why each unmatched ground-truth ring is unmatched (Step 7 close, item 2).

    python evaluation/unmatched_rings.py --out results/tables/r4_unmatched.csv

For every detector seed, every method (B0 = cc at k*, B2 = expand's plain components, full = the
val-chosen partition) and both evaluation windows (val = days 6-7, primary = test days 8-9), each
truth ring in scope that no predicted ring matches at Jaccard 0.5 is put in exactly one class:

    a_lt3_members       fewer than 3 visible members in the window (undetectable under min_size 3)
    b_untouched         >= 3 visible members, but no included edge (seed or expanded) of any
                        prediction touches one of its accounts
    c_over_merged       touched, Jaccard < 0.5, and the prediction that covers it best also covers
                        accounts of another truth ring (attempts merged)
    c_under_covered     touched, Jaccard < 0.5, and no such prediction holds a second truth ring
                        (the prediction is a proper subset / partial overlap)

`c_over_merged` wins over `c_under_covered` when both apply to different predictions of the same
ring. Matched rings are counted for completeness. The breakdown is written per (seed, method,
window, pattern_type) to the csv and summarised to <out>.json (headline counts per method and
window, summed over seeds, plus the per-pattern table of the primary window).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_metrics import match_rings  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, aggregate_cc, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.rings import Ring  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

CLASSES = ["a_lt3_members", "b_untouched", "c_over_merged", "c_under_covered"]
R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R3 = REPO_ROOT / "experiments" / "R3_expansion"
R4 = REPO_ROOT / "experiments" / "R4_partition"


def classify(rings: list[Ring], se: pd.DataFrame, truth: dict, patterns: dict, window) -> pd.DataFrame:
    """One row per truth ring in scope: class, pattern, size, best Jaccard."""
    pred = restrict_rings(rings, se, window)
    matches, _, _ = match_rings(pred, truth, 0.5)
    matched = {m.truth_id for m in matches}
    ts = se.set_index("edge_id")["timestamp"]
    in_win = set(ts.index[window.mask(ts.values)].tolist())
    touch = []                                   # accounts of each prediction's INCLUDED edges inside the window
    frm, to = se.set_index("edge_id")["from_id"], se.set_index("edge_id")["to_id"]
    for r in rings:
        inc = [e for e in (r.seed_edges + r.expanded_edges) if e in in_win]
        touch.append(set(frm.loc[inc].tolist()) | set(to.loc[inc].tolist()) if inc else set())
    tacc: dict[int, set] = {}
    for t, accs in truth.items():
        for a in accs:
            tacc.setdefault(a, set()).add(t)
    rows = []
    for tid, accs in truth.items():
        pat = patterns.get(tid, "?")
        if tid in matched:
            rows.append({"ring_id": tid, "pattern_type": pat, "n_members": len(accs), "klass": "matched", "best_jaccard": 1.0})
            continue
        if len(accs) < 3:
            rows.append({"ring_id": tid, "pattern_type": pat, "n_members": len(accs), "klass": "a_lt3_members", "best_jaccard": 0.0})
            continue
        hits = [i for i, t in enumerate(touch) if t & accs]
        if not hits:
            rows.append({"ring_id": tid, "pattern_type": pat, "n_members": len(accs), "klass": "b_untouched", "best_jaccard": 0.0})
            continue
        best_j = max((len(pred[i] & accs) / len(pred[i] | accs)) if i < len(pred) else 0.0 for i in hits)
        over = any(len({t for a in pred[i] for t in tacc.get(a, set())} - {tid}) > 0 for i in hits if i < len(pred))
        rows.append({"ring_id": tid, "pattern_type": pat, "n_members": len(accs),
                     "klass": "c_over_merged" if over else "c_under_covered", "best_jaccard": round(best_j, 4)})
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r4_unmatched.csv")
    ap.add_argument("--scope", default="test_visible")
    args = ap.parse_args(argv)
    paths = load_paths()
    pdir = paths["processed_dir"]
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()
    policy = Policy.load(R3 / "policy_proposed")
    affinity = Affinity.load(R4 / "affinity")
    import yaml
    rows = []
    for S in args.seeds:
        r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        r4 = yaml.safe_load((R4 / "runs" / "average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        k_pct, min_size = float(r3["seed_frac_pct"]), int(r3["min_size"])
        for split, window in (("val", W["val"]), ("test", W["primary"])):
            se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
            emb = R1 / f"embeddings_{split}_seed{S}.parquet"
            ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                                embeddings_parquet=emb if emb.exists() else None, checkpoint=R1 / f"model_best_seed{S}.pt")
            truth, patterns = load_ground_truth(ring_gt, *window.bounds, args.scope, verbose=False)
            mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct)
            trajs = expand_all(se, mask, policy, ctx, delta_t_h=float(r3["delta_t_h"]), p_floor=float(r3["p_min"]))
            inc_pos, is_seed = included_from_trajectories(se, mask, trajs, float(r3["p_min"]))
            comp = components_of(ctx.idx, inc_pos)
            P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
            lab_b2 = partition_labels(ctx, inc_pos, is_seed, comp, method="b2", pairs=P, min_members=min_size)
            lab_full = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=min_size,
                                        **{k: r4[k] for k in ("cut", "threshold", "gap_h", "resolution") if k in r4})
            methods = {"b0": aggregate_cc(se, k_pct, min_size),
                       "b2": rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab_b2, min_size),
                       "full": rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab_full, min_size)}
            for name, rings in methods.items():
                d = classify(rings, se, truth, patterns, window)
                d.insert(0, "window", "primary" if split == "test" else "val")
                d.insert(0, "method", name)
                d.insert(0, "seed", S)
                rows.append(d)
                c = Counter(d["klass"])
                print(f"seed {S} {split:4s} {name:5s}: {len(truth)} truth rings | matched {c['matched']} | "
                      + " ".join(f"{k} {c[k]}" for k in CLASSES), flush=True)
    df = pd.concat(rows, ignore_index=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    summ = {}
    for (w, m), g in df.groupby(["window", "method"]):
        c = Counter(g["klass"])
        n_seeds = g["seed"].nunique()
        summ[f"{w}/{m}"] = {"n_truth_per_seed": round(len(g) / n_seeds, 1), "n_seeds": n_seeds,
                            **{k: {"total": int(c[k]), "per_seed": round(c[k] / n_seeds, 1)} for k in ["matched"] + CLASSES}}
    per_pattern = (df[df["window"] == "primary"].groupby(["method", "pattern_type", "klass"]).size().unstack(fill_value=0)
                   .reindex(columns=["matched"] + CLASSES, fill_value=0))
    (Path(str(args.out).replace(".csv", ".json"))).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": args.seeds, "scope": args.scope,
         "classes": {"a_lt3_members": "< 3 visible members in the window", "b_untouched": ">= 3 members, no included edge touches it",
                     "c_over_merged": "touched, J < 0.5, best prediction also covers another truth ring",
                     "c_under_covered": "touched, J < 0.5, no prediction holds a second ring"},
         "summary": summ, "per_pattern_primary": json.loads(per_pattern.reset_index().to_json(orient="records"))}, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n== per seed (mean over seeds) ==")
    for k, v in summ.items():
        print(f"  {k:14s} truth {v['n_truth_per_seed']:.0f} | matched {v['matched']['per_seed']:.1f} | "
              + " ".join(f"{c} {v[c]['per_seed']:.1f}" for c in CLASSES))
    print("\n== primary window, per pattern (summed over 5 seeds) ==")
    print(per_pattern.to_string())
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
