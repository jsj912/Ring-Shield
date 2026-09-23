"""Recovered train-period rings as extra typing-head training rows (Step 8.3).

    python ringshield/typing/recovered_rings.py --out experiments/R5_typing/recovered_train_rings.parquet

The head must type the rings the pipeline *builds*, not only ideal ground-truth fragments. This
takes the train split's included edges (seeds from the cross-scores + the expansion policy's
additions, `experiments/R4_partition/included_train.parquet`), partitions them exactly as the
`full` aggregator does (pair affinity + average linkage at the val-chosen cut, fragments
re-attached), and keeps every resulting ring that overlaps a train-visible ground-truth ring,
labelled with that ring's pattern. Features are `ringshield.typing.features.ring_features` on the
ring's own edges, so they are built the way inference will build them (including `seed_ratio`).

`ring_id` is the matched TRUTH ring's id, so the head's grouped CV keeps a truth ring and the
recovered version of it in the same fold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.aggregators.full import component_pairs, partition_labels, rings_from_edge_clusters  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.index import SplitIndex  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.roles import account_roles  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.typing.features import RING_FEATURES, ring_features  # noqa: E402

R3 = REPO_ROOT / "experiments" / "R3_cross_scores"
R4 = REPO_ROOT / "experiments" / "R4_partition"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--included", type=Path, default=R4 / "included_train.parquet")
    ap.add_argument("--affinity-dir", type=Path, default=R4 / "affinity")
    ap.add_argument("--r4-config", type=Path, default=R4 / "runs" / "average" / "seed1" / "config.yaml")
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--min-jaccard", type=float, default=0.0, help="keep a recovered ring when its best overlap exceeds this")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "experiments" / "R5_typing" / "recovered_train_rings.parquet")
    args = ap.parse_args(argv)
    paths = load_paths()
    pdir = paths["processed_dir"]
    chosen = yaml.safe_load(args.r4_config.read_text(encoding="utf-8"))["chosen"]
    cut = float(chosen.get("cut", 0.5))
    inc = pd.read_parquet(args.included)
    se = build_scored_edges(R3 / "cross_scores_train.parquet", "train", model_id="gine_causal_xfold", seed=1,
                            processed_dir=pdir, keep_unscored=False)
    se = se[se["edge_id"].isin(inc["edge_id"])].reset_index(drop=True)
    se["is_seed"] = se["edge_id"].isin(inc.loc[inc["is_seed"], "edge_id"]).to_numpy()
    gfp = pd.read_parquet(pdir / "amlworld_gfp_features_train.parquet")
    gfp = gfp[gfp["EdgeID"].isin(se["edge_id"])]
    ctx = build_context(se, gfp_parquet=None, embeddings_parquet=None)
    ctx.gfp = gfp.set_index("EdgeID").reindex(ctx.idx.edge_id).to_numpy(np.float32)
    idx: SplitIndex = ctx.idx
    inc_pos = np.arange(idx.n_edges)
    is_seed = se.sort_values("edge_id")["is_seed"].to_numpy(bool)
    comp = components_of(idx, inc_pos)
    aff = Affinity.load(args.affinity_dir)
    P = component_pairs(ctx, inc_pos, is_seed, comp, aff)
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method="average", pairs=P, cut=cut, min_members=args.min_size)
    rings = rings_from_edge_clusters(se.sort_values("edge_id").reset_index(drop=True), idx, inc_pos, is_seed, lab, args.min_size,
                                     aggregator_id="full")
    print(f"[recovered] {len(se):,} included train edges -> {int(comp.max()) + 1} components -> {len(rings)} rings (cut {cut})")

    tr = pd.read_parquet(pdir / "amlworld_train.parquet", columns=["EdgeID", "from_id", "to_id", "ring_id", "pattern_type"])
    rt = tr[tr["ring_id"] > 0]
    truth = {int(r): (set(g["from_id"]) | set(g["to_id"]), g["pattern_type"].iloc[0]) for r, g in rt.groupby("ring_id")}
    acc_to_rings: dict[int, set] = {}
    for rid, (accs, _) in truth.items():
        for a in accs:
            acc_to_rings.setdefault(a, set()).add(rid)
    rows, dropped = [], 0
    se_i = se.set_index("edge_id")
    for r in rings:
        cand = set().union(*[acc_to_rings.get(a, set()) for a in r.members]) if r.members else set()
        if not cand:
            dropped += 1
            continue
        best = max(cand, key=lambda t: len(set(r.members) & truth[t][0]) / len(set(r.members) | truth[t][0]))
        j = len(set(r.members) & truth[best][0]) / len(set(r.members) | truth[best][0])
        if j <= args.min_jaccard:
            dropped += 1
            continue
        edges = se_i.loc[sorted(set(r.seed_edges + r.expanded_edges))].reset_index()
        roles = account_roles(r, se)
        f = ring_features(edges, roles)
        rows.append({"ring_id": best, "pattern_type": truth[best][1], "n_visible_members": r.n_members,
                     "jaccard_to_truth": round(j, 4), **f})
    out = pd.DataFrame(rows, columns=["ring_id", "pattern_type", "n_visible_members", "jaccard_to_truth"] + RING_FEATURES)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    Path(str(args.out).replace(".parquet", ".json")).write_text(json.dumps(
        {"n_rings_built": len(rings), "n_kept": int(len(out)), "n_dropped_no_truth_overlap": dropped, "cut": cut,
         "min_size": args.min_size, "class_counts": out["pattern_type"].value_counts().to_dict(),
         "mean_jaccard_to_truth": float(out["jaccard_to_truth"].mean()) if len(out) else None,
         "included": str(args.included), "affinity": str(args.affinity_dir)}, indent=2), encoding="utf-8")
    print(f"[recovered] kept {len(out)} rings overlapping a truth ring (dropped {dropped}); classes "
          f"{out['pattern_type'].value_counts().to_dict()}; mean Jaccard to truth "
          f"{out['jaccard_to_truth'].mean():.2f} -> {args.out}")


if __name__ == "__main__":
    main()
