"""11b: ensembled seed selection at an unchanged total budget (C7 follow-up).

    python evaluation/ensemble_seeds.py --dry-run
    python evaluation/ensemble_seeds.py

`FINDINGS.md` **C7**: two detectors each touch ~74 % of primary-window truth rings, their touched
sets overlap at only 71.5 %, and their **union reaches 150.8 of 174 (86.7 %)**. That was measured
post hoc as an upper bound. This turns it into a method and tests it honestly.

**The budget stays at 0.1 %.** An ensemble that simply unions two 0.1 % seed sets would spend up to
0.2 % and the comparison would be meaningless. Instead each detector's scores are converted to a
**within-split rank fraction** (rank / N, the same scale-free quantity the expansion policy uses as
its detector feature, Step 6 amendment a), and the ensemble score of an edge is its **best rank
across detectors**:

    ensemble_score(e) = 1 - min_d ( rank_d(e) / N )

The standard seed rule then applies unchanged — a strict quantile cut on `score_raw` at the
val-chosen k\\* — so the ensemble selects exactly as many seed edges as either detector alone. An
edge enters because *some* detector ranks it highly, and the budget is spent on the union of their
convictions rather than the intersection of their scores.

The output is written in the scores-parquet layout, so `run_rings.py` consumes it with no changes
and every downstream parameter is chosen on validation exactly as before.

Outputs: `experiments/R11b_ensemble/scores_{val,test}_seed<S>.parquet` (+ `config.yaml`).
"""
from __future__ import annotations

import argparse
import json
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

DETECTORS = {"gine_causal": REPO_ROOT / "experiments" / "R1_gine_causal",
             "mega": REPO_ROOT / "experiments" / "R6_mega"}


def rank_fraction(x: np.ndarray) -> np.ndarray:
    """rank / N in [0, 1], ties averaged -- the scale-free detector feature of Step 6 amendment (a)."""
    return pd.Series(x).rank(method="average").to_numpy() / len(x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detectors", nargs="*", default=list(DETECTORS))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--splits", nargs="*", default=["val", "test"])
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments" / "R11b_ensemble")
    ap.add_argument("--dry-run", action="store_true", help="one seed, prints the overlap, writes nothing")
    a = ap.parse_args(argv)
    if a.dry_run:
        a.seeds = a.seeds[:1]
    if not a.dry_run:
        a.out_dir.mkdir(parents=True, exist_ok=True)

    report = []
    for seed in a.seeds:
        for split in a.splits:
            frames = {}
            for det in a.detectors:
                f = pd.read_parquet(DETECTORS[det] / f"scores_{split}_seed{seed}.parquet",
                                    columns=["edge_id", "timestamp", "score_raw"])
                frames[det] = f.set_index("edge_id")
            ids = None
            for det, f in frames.items():
                ids = f.index if ids is None else ids.intersection(f.index)
            ids = ids.sort_values()
            assert len(ids), "detectors share no edge ids"

            ranks = {}
            for det, f in frames.items():
                g = f.loc[ids]
                ranks[det] = rank_fraction(g["score_raw"].to_numpy(float))
            best = np.minimum.reduce([1.0 - r for r in ranks.values()])   # 1 - rank => small is good
            ens = 1.0 - best                                              # best rank across detectors

            out = pd.DataFrame({"edge_id": ids.to_numpy(np.int64),
                                "timestamp": frames[a.detectors[0]].loc[ids, "timestamp"].to_numpy(np.int64),
                                "score_raw": ens})
            assert out["edge_id"].is_unique and not out["score_raw"].isna().any()

            # how much of the budget each detector supplies at k* = 0.1 %
            k = 0.001
            thr = np.quantile(ens, 1 - k)
            chosen = ens > thr
            contrib = {}
            for det, r in ranks.items():
                own_thr = np.quantile(r, 1 - k)
                contrib[det] = int((chosen & (r > own_thr)).sum())
            both = int((chosen & np.all([r > np.quantile(r, 1 - k) for r in ranks.values()], axis=0)).sum())
            row = {"seed": seed, "split": split, "n_edges": int(len(ids)), "n_seeds_at_k": int(chosen.sum()),
                   "from_each": contrib, "in_both_top_k": both}
            report.append(row)
            print(f"  seed {seed} {split}: {int(chosen.sum()):,} seeds at k*=0.1 % of {len(ids):,} edges | "
                  f"top-0.1 % of each: {contrib} | in both: {both}", flush=True)
            if not a.dry_run:
                out.to_parquet(a.out_dir / f"scores_{split}_seed{seed}.parquet", index=False)

    if a.dry_run:
        print("\n[11b] DRY RUN -- nothing written")
        return report
    cfg = {"experiment": a.out_dir.name, "step": "11b (ensembled seed selection)",
           "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "model_id": "ensemble", "detectors": {d: str(DETECTORS[d]) for d in a.detectors},
           "rule": "ensemble_score(e) = 1 - min_d(rank_d(e)/N); the standard strict quantile cut on "
                   "score_raw at the val-chosen k* then applies unchanged",
           "budget": "UNCHANGED at k* = 0.1 % -- the ensemble selects the same NUMBER of seed edges as "
                     "either detector alone, so the comparison against a single detector is like for like",
           "motivation": "FINDINGS C7: two detectors' touched-ring sets union to 150.8/174 (86.7 %) against "
                         "~74 % each, measured post hoc; this tests whether that union is reachable as a method",
           "caveat": "the ensemble score is a rank statistic, not a calibrated probability; score_calibrated "
                     "is absent and downstream confidence falls back to score_raw",
           "per_run": report}
    (a.out_dir / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"\n-> {a.out_dir}")
    return report


if __name__ == "__main__":
    main()
