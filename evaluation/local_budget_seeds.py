"""11c: a per-account local seed budget at an unchanged total (C7 / 11b follow-up).

    python evaluation/local_budget_seeds.py --dry-run
    python evaluation/local_budget_seeds.py

11b showed that spending the same 0.1 % budget on the *union of two detectors' convictions* buys
+4.0 rings, about a fifth of the measured union headroom, because detectors agree at the top of
their rankings. This asks the other budget question: does spending the same budget **more evenly
across the graph** reach more rings than a global quantile does?

The rule. An edge is a **local maximum** if it is the highest-scoring edge of at least one of its
two accounts. Local maxima are ranked above every non-maximum, and the ordinary strict quantile cut
at k\* then applies unchanged — so the same NUMBER of seed edges is chosen, but they are spread
over distinct accounts instead of concentrating in whichever neighbourhoods the detector scores
highly.

`FINDINGS.md` **B13** bounds what this can achieve in advance: a local budget cannot help a ring
whose remaining members sit in a component disconnected from the seeded fragment inside the window,
which is 81.5 % of the under-covered mass. It is run because it is cheap and because the
budget-allocation question deserves a third answer, not because a large effect is expected.

Output: `experiments/R11c_local/scores_{val,test}_seed<S>.parquet` (+ config.yaml).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--splits", nargs="*", default=["val", "test"])
    ap.add_argument("--scores-dir", type=Path, default=R1)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments" / "R11c_local")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        a.seeds = a.seeds[:1]
    else:
        a.out_dir.mkdir(parents=True, exist_ok=True)
    pdir = load_paths()["processed_dir"]
    rep = []
    for seed in a.seeds:
        for split in a.splits:
            sc = pd.read_parquet(a.scores_dir / f"scores_{split}_seed{seed}.parquet",
                                 columns=["edge_id", "timestamp", "score_raw"])
            ends = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=["EdgeID", "from_id", "to_id"])
            d = sc.merge(ends, left_on="edge_id", right_on="EdgeID", how="inner", validate="one_to_one")
            long = pd.concat([d[["from_id", "score_raw"]].rename(columns={"from_id": "acc"}),
                              d[["to_id", "score_raw"]].rename(columns={"to_id": "acc"})])
            best = long.groupby("acc")["score_raw"].max()
            is_max = ((d["score_raw"].to_numpy() >= best.reindex(d["from_id"]).to_numpy() - 1e-15) |
                      (d["score_raw"].to_numpy() >= best.reindex(d["to_id"]).to_numpy() - 1e-15))
            # local maxima outrank everything else; within each tier the detector's own order is kept
            out = pd.DataFrame({"edge_id": d["edge_id"].to_numpy(np.int64),
                                "timestamp": d["timestamp"].to_numpy(np.int64),
                                "score_raw": np.where(is_max, 1.0, 0.0) + d["score_raw"].to_numpy() * 0.5})
            out = out.sort_values("edge_id").reset_index(drop=True)
            k = int(round(0.001 * len(out)))
            thr = np.quantile(out["score_raw"], 1 - 0.001)
            rep.append({"seed": seed, "split": split, "n_edges": int(len(out)),
                        "n_local_maxima": int(is_max.sum()), "n_seeds_at_k": int((out["score_raw"] > thr).sum())})
            print(f"  seed {seed} {split}: {int(is_max.sum()):,} local maxima of {len(out):,} edges "
                  f"({is_max.mean()*100:.1f} %); {int((out['score_raw'] > thr).sum()):,} seeds at k*=0.1 % (budget {k:,})",
                  flush=True)
            if not a.dry_run:
                out.to_parquet(a.out_dir / f"scores_{split}_seed{seed}.parquet", index=False)
    if a.dry_run:
        print("\n[11c] DRY RUN -- nothing written")
        return rep
    (a.out_dir / "config.yaml").write_text(yaml.dump(
        {"experiment": a.out_dir.name, "step": "11c (per-account local seed budget)",
         "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
         "model_id": "local", "base_scores": str(a.scores_dir),
         "rule": "an edge is a local maximum if it is the top-scoring edge of either endpoint account; "
                 "local maxima rank above all others, then the ordinary strict quantile cut at k* applies",
         "budget": "UNCHANGED at k* = 0.1 %",
         "expected_bound": "FINDINGS B13 -- a local budget cannot reach members in a component disconnected "
                           "from the seeded fragment inside the window (81.5 % of the under-covered mass)",
         "per_run": rep}, sort_keys=False), encoding="utf-8")
    print(f"\n-> {a.out_dir}")
    return rep


if __name__ == "__main__":
    main()
