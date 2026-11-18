"""Part C ring rows (PREREG_RECOVERY amendment, addendum 5): Amendment-15 close-out on transferred GenAgg scores.
Trained on HI-Small, zero-shot on HI-Medium.

    RINGSHIELD_PATHS=experiments/R18_hm_transfer/paths_hm_transfer.yaml \
    .venv312/Scripts/python.exe -u evaluation/hm_transfer_closeout.py --seed 1 [--only primary ...]

Builds experiments/R18_hm_transfer/closeout_input/R1_gine_causal_c1prime/ (hard links: scores_{val,test}_seed<S>,
model_best_seed<S>.pt from experiments/R18_hm_transfer/genagg_seed<S>/ and the GenAgg checkpoint), then runs
evaluation/hm_closeout.py unchanged with policy_no_detector and affinity_no_embedding. The only intervention:
the feature context is built without an embeddings file (the transferred model has none on HI-Medium).
Output: experiments/R18_hm_transfer/closeout/<window>/<rule>/<method>/seed<S>.parquet and log_seed<S>.json.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
D = R / "experiments" / "R18_hm_transfer"
CKPT = R / "experiments" / "R6_megagenagg"


def link(src: Path, dst: Path):
    assert src.exists(), src
    if not dst.exists():
        os.link(src, dst)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    assert os.environ.get("RINGSHIELD_PATHS", "").endswith("paths_hm_transfer.yaml")
    S = a.seed
    r1 = D / "closeout_input" / "R1_gine_causal_c1prime"
    r1.mkdir(parents=True, exist_ok=True)
    for sp in ("val", "test"):
        link(D / f"genagg_seed{S}" / f"scores_{sp}_seed{S}.parquet", r1 / f"scores_{sp}_seed{S}.parquet")
    link(CKPT / f"model_best_seed{S}.pt", r1 / f"model_best_seed{S}.pt")

    import evaluation.hm_closeout as hc
    orig = hc.build_context

    def no_emb(se, **kw):
        kw["embeddings_parquet"] = None
        return orig(se, **kw)
    hc.build_context = no_emb
    argv = ["--seed", str(S), "--exp-dir", str(D / "closeout_input"),
            "--policy-dir", str(R / "experiments_hi_medium/R3_expansion/policy_no_detector"),
            "--affinity-dir", str(R / "experiments_hi_medium/R4_partition/affinity_no_embedding"),
            "--out", str(D / "closeout")]
    if a.only:
        argv += ["--only", *a.only]
    hc.main(argv)


if __name__ == "__main__":
    main()
