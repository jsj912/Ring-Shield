"""B5 -- CSGM scatter-gather miner (Tian et al. 2025, github.com/zhihuat/Collaborative-AML) as a ring
baseline on the test edges (Step 7.3).

    python evaluation/csgm_baseline.py --out experiments/R4_partition/runs/b5/seed1

What the reference does (aml_sim.py): accounts are split into two institutions; for every
account a K = 2 breadth-first search inside its own institution collects the CROSS-institution
edges it can reach forward (as a sender) and backward (as a receiver); a source in one bank and a
sink in the other whose forward / backward edge sets are similar (MinHash-LSH banding + Bloom
filter membership, threshold on the band-match fraction) are flagged, and the intermediates are
the accounts their two node sets share. The reference evaluates account-level flags, not rings,
and its AMLworld preprocessing places every scatter-gather source and destination in opposite
banks using the pattern file (label-informed). Here:

* institutions: a deterministic random 2-way split of the accounts (seed 0), no label information;
* forward / backward sets exactly as `utils.AMLBFS` (imported from the cloned repo under
  external/), sets shorter than `len_threshold` ignored (their HI-Small value is 8; chosen on VAL
  from {2, 3, 4, 8} here because our rings are small);
* similarity: the exact Jaccard of the two edge sets (the quantity MinHash-LSH-Bloom estimates;
  with the data in one place the private estimate is not needed), threshold chosen on VAL from
  the reference's {0.1 ... 0.9};
* a ring = {source, sink} + the intermediates the two node sets share, for every matched
  (source, sink) pair with a non-empty intersection; rings sharing the same account set are
  merged; `min_size` 3 as everywhere.

metrics.json is written in the run_partition layout so evaluation/aggregate_partition.py picks
it up as method 'b5'. The method only ever proposes scatter-gather-shaped rings by construction.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "external" / "Collaborative-AML"))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from ringshield.evaluate import evaluate_blocks, ring_metrics_full  # noqa: E402
from ringshield.expand.index import SplitIndex  # noqa: E402
from ringshield.rings import Ring, write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit, write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth, split_window  # noqa: E402
from ringshield.windows import EVAL_WINDOW_YAML, load_windows  # noqa: E402

try:
    from utils import AMLBFS  # noqa: E402  (external/Collaborative-AML/utils.py)
except ImportError:  # pragma: no cover
    AMLBFS = None

LEN_GRID = [2, 3, 4, 8]
THR_GRID = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
K = 2


def csgm_sets(df: pd.DataFrame, seed: int = 0):
    """Forward / backward cross-institution edge sets and node sets per account (AMLBFS, K = 2)."""
    accounts = np.unique(np.concatenate([df["from_id"].to_numpy(), df["to_id"].to_numpy()]))
    rng = np.random.default_rng(seed)
    bank = dict(zip(accounts.tolist(), rng.integers(0, 2, len(accounts)).tolist()))
    src2dst, dst2src = {}, {}
    for s, d in zip(df["from_id"].tolist(), df["to_id"].tolist()):
        src2dst.setdefault(s, []).append(d)
        dst2src.setdefault(d, []).append(s)
    fwd, bwd = {}, {}
    for a in accounts.tolist():
        e, n = AMLBFS(src2dst, bank, a, K, reverse=False)
        if e:
            fwd[a] = (set(e), set(n))
        e, n = AMLBFS(dst2src, bank, a, K, reverse=True)
        if e:
            bwd[a] = (set(e), set(n))
    return bank, fwd, bwd


def csgm_rings(bank, fwd, bwd, len_threshold: int, threshold: float, min_size: int = 3) -> list[set]:
    """Matched (source, sink) pairs across institutions -> account sets (deduplicated)."""
    f = {a: v for a, v in fwd.items() if len(v[0]) >= len_threshold}
    b = {a: v for a, v in bwd.items() if len(v[0]) >= len_threshold}
    inv: dict[int, list] = {}
    for a, (edges, _) in b.items():
        for e in edges:
            inv.setdefault(e, []).append(a)
    out, seen = [], set()
    for s, (fe, fn) in f.items():
        cands = {d for e in fe for d in inv.get(e, []) if bank[d] != bank[s]}
        for d in cands:
            be, bn = b[d]
            sim = len(fe & be) / len(fe | be)
            if sim < threshold:
                continue
            inter = fn & bn
            if not inter:
                continue
            ring = frozenset(inter | {s, d})
            if len(ring) >= min_size and ring not in seen:
                seen.add(ring)
                out.append(set(ring))
    return out


def rings_from_sets(df: pd.DataFrame, idx: SplitIndex, sets: list[set]) -> list[Ring]:
    rings = []
    for k, members in enumerate(sets):
        md = idx.dense(sorted(members))
        both = np.isin(idx.from_dense, md) & np.isin(idx.to_dense, md)
        pos = np.flatnonzero(both)
        if len(pos) == 0:
            continue
        rings.append(Ring.baseline(ring_id=f"b5-{k}", tenant_id=int(df["from_bank"].iloc[0]), aggregator_id="b5",
                                   members=sorted(members), member_edges=idx.edge_id[pos].tolist(), seed_edges=idx.edge_id[pos].tolist(),
                                   n_edges=int(len(np.unique(np.minimum(idx.from_dense[pos], idx.to_dense[pos]) * (len(idx.acc_uniq) + 1)
                                                             + np.maximum(idx.from_dense[pos], idx.to_dense[pos])))),
                                   start_time=int(idx.ts[pos].min()), end_time=int(idx.ts[pos].max()), confidence=0.5, max_edge_prob=0.5,
                                   density=0.0))
    return rings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=1, help="detector seed slot the row is filed under (CSGM uses no detector)")
    ap.add_argument("--bank-seed", type=int, default=0)
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--eval-window", type=Path, default=EVAL_WINDOW_YAML)
    args = ap.parse_args(argv)
    assert AMLBFS is not None, "clone github.com/zhihuat/Collaborative-AML into external/"
    t_start = time.time()
    paths = load_paths()
    pdir = paths["processed_dir"]
    args.out.mkdir(parents=True, exist_ok=True)
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    eval_windows = load_windows(args.eval_window)
    test_windows = {k: w for k, w in eval_windows.items() if w.split == "test"}
    se, idx, sets = {}, {}, {}
    for split in ("val", "test"):
        df = build_scored_edges(REPO_ROOT / "experiments" / "R1_gine_causal" / f"scores_{split}_seed1.parquet", split, processed_dir=pdir)
        se[split] = df
        idx[split] = SplitIndex.build(df)
        t0 = time.time()
        sets[split] = csgm_sets(df, seed=args.bank_seed)
        bank, fwd, bwd = sets[split]
        print(f"[csgm] {split}: {len(bank):,} accounts, forward sets {len(fwd):,}, backward sets {len(bwd):,} ({time.time() - t0:.0f}s)")
    windows = {s: list(split_window(pdir / f"amlworld_{s}.parquet")) for s in ("val", "test")}
    truth_val, pat_val = load_ground_truth(ring_gt, *windows["val"], args.scope, verbose=False)
    grid = []
    for L in LEN_GRID:
        for thr in THR_GRID:
            rs = csgm_rings(*sets["val"], L, thr, args.min_size)
            m = evaluate_rings(rs, truth_val, 0.5, pat_val)
            grid.append({"len_threshold": L, "threshold": thr, "n_rings": len(rs), "ring_precision": round(m.ring_precision, 4),
                         "ring_recall": round(m.ring_recall, 4), "ring_f1": round(m.ring_f1, 4), "mean_jaccard": round(m.mean_jaccard, 4)})
    best = max(grid, key=lambda r: (r["ring_f1"], r["threshold"], r["len_threshold"]))
    chosen = {"method": "b5", "len_threshold": best["len_threshold"], "threshold": best["threshold"], "val_ring_f1": best["ring_f1"],
              "seed_frac_pct": None, "min_size": args.min_size}
    print(f"[csgm] chosen on val: {chosen}; best val grid rows: {sorted(grid, key=lambda r: -r['ring_f1'])[:3]}")
    cfg = {"experiment": args.out.name, "step": "7.3 B5 CSGM", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_commit": _git_commit(), "aggregator": "b5", "method": "b5", "bank_seed": args.bank_seed, "K": K, "grid": {"len_threshold": LEN_GRID, "threshold": THR_GRID},
           "grid_results_val": grid, "chosen": chosen, "reference": "github.com/zhihuat/Collaborative-AML aml_sim.py (exact Jaccard instead of LSH/Bloom estimate; random institutions)",
           "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()}, "primary_block": "primary"}
    (args.out / "config.yaml").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    rs = csgm_rings(*sets["test"], chosen["len_threshold"], chosen["threshold"], args.min_size)
    rings = rings_from_sets(se["test"], idx["test"], rs)
    write_rings_parquet(rings, args.out / "rings.parquet")
    blocks = evaluate_blocks(rings, se["test"], ring_gt, args.scope, test_windows, 0.5, [0.3, 0.7])
    for name in blocks:
        blocks[name]["n_rings_gt100_in_window"] = int(sum(1 for r in rings if r.n_members > 100))
    val_rings = csgm_rings(*sets["val"], chosen["len_threshold"], chosen["threshold"], args.min_size)
    metrics = {"experiment": args.out.name, "created_utc": cfg["created_utc"], "git_commit": cfg["git_commit"], "aggregator": "b5", "method": "b5",
               "detector_seed": args.seed, "scope": args.scope, "chosen": chosen, "reportable": True, "eval_windows": cfg["eval_windows"],
               "primary_block": "primary", "blocks": blocks, "test": blocks["primary"],
               "rings_total": {"n_rings": len(rings), "max_members": max((r.n_members for r in rings), default=0)},
               "test_partition": None, "val_at_chosen": ring_metrics_full(val_rings, truth_val, pat_val, 0.5, [0.3, 0.7]),
               "seconds": round(time.time() - t_start, 1)}
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    for name, t in blocks.items():
        print(f"[csgm] {name:7s}: {t['n_predicted']} rings | P {t['ring_precision']:.4f} R {t['ring_recall']:.4f} F1 {t['ring_f1']:.4f} | J {t['mean_jaccard']:.4f}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
