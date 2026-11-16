"""Rebuild r14_scope_sensitivity and v36_component_scope with corrected (weighted) intervals.

Runs evaluation/scope_sensitivity.py and evaluation/component_scope.py unmodified, with their
`boot` replaced by evaluation.score_external.weighted_boot (draw counts as weights, the
ring_stats.bootstrap_over_rings procedure). Same seed (0), same draws, same point estimates;
only the interval changes. Writes only to the --out paths given, never to the frozen tables.

    python evaluation/rescore_weighted_intervals.py \
        --r14-out results/tables/r14_scope_sensitivity_wci.csv \
        --v36-out results/tables/v36_component_scope_wci.csv --exp-root ../RS-e2e/experiments
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import evaluation.component_scope as cs  # noqa: E402
import evaluation.scope_sensitivity as ss  # noqa: E402
from evaluation.score_external import weighted_boot  # noqa: E402

FROZEN = {"r14_scope_sensitivity.csv", "v36_component_scope.csv"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--r14-out", type=Path, required=True)
    ap.add_argument("--v36-out", type=Path, required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--exp-root", type=Path, default=REPO_ROOT / "experiments",
                    help="experiments root holding the ring and score runs (both builders)")
    a = ap.parse_args(argv)
    for p in (a.r14_out, a.v36_out):
        if p.name in FROZEN:
            ap.error(f"{p} would overwrite a frozen table")
    old = REPO_ROOT / "experiments"
    ss.RUNS = {k: (a.exp_root / r.relative_to(old), a.exp_root / s.relative_to(old), m)
               for k, (r, s, m) in ss.RUNS.items()}
    ss.boot = weighted_boot
    cs.boot = weighted_boot
    ss.main(["--n-boot", str(a.n_boot), "--out", str(a.r14_out)])
    cs.main(["--exp-root", str(a.exp_root), "--n-boot", str(a.n_boot), "--out", str(a.v36_out)])


if __name__ == "__main__":
    main()
