"""Scope-sensitivity (r14) and component-scope (v36) rows for MEGA-GIN and MEGA-GenAgg at scoring batch 2048
(fixed 0.1 %), with corrected (weighted) intervals. Data only; new files; the frozen builders run unmodified with
their run tables repointed, exactly as evaluation/rescore_weighted_intervals.py does.

    .venv312/Scripts/python.exe evaluation/scope_rows_sb2048.py \
        --r14-out results/tables/r14_scope_sensitivity_sb2048.csv --v36-out results/tables/v36_component_scope_sb2048.csv
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

E, REF = REPO_ROOT / "experiments", REPO_ROOT.parent / "RS-e2e" / "experiments"
FROZEN = {"r14_scope_sensitivity.csv", "v36_component_scope.csv", "r14_scope_sensitivity_wci.csv",
          "v36_component_scope_wci.csv"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--r14-out", type=Path, required=True)
    ap.add_argument("--v36-out", type=Path, required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args(argv)
    for p in (a.r14_out, a.v36_out):
        if p.name in FROZEN:
            ap.error(f"{p} would overwrite an existing table")
    G, MG, GA = REF / "R1_gine_causal", E / "R6_mega_sb2048", E / "R6_megagenagg"
    B0, FU = E / "R6_b0_sb2048_k010", E / "R6_full_sb2048_k010"
    ss.RUNS = {
        ("gine_causal", "b0"): (REF / "R2_b0" / "gine_causal", G, "gine_causal"),
        ("gine_causal", "full"): (REF / "R4_partition" / "runs" / "average", G, "gine_causal"),
        ("mega_sb2048", "b0"): (B0 / "mega", MG, "mega"),
        ("mega_sb2048", "proposed"): (FU / "mega" / "expand", MG, "mega"),
        ("mega_sb2048", "full"): (FU / "mega", MG, "mega"),
        ("megagenagg_sb2048", "b0"): (B0 / "megagenagg", GA, "mega"),
        ("megagenagg_sb2048", "proposed"): (FU / "megagenagg" / "expand", GA, "mega"),
        ("megagenagg_sb2048", "full"): (FU / "megagenagg", GA, "mega"),
    }
    # component_scope paths are relative to --exp-root; absolute paths survive the join unchanged
    cs.RUNS = {k: (str(r), str(sd)) for k, (r, sd, _) in ss.RUNS.items()}
    cs.ORDER = {"gine_causal": ["b0", "full"], "mega_sb2048": ["b0", "proposed", "full"],
                "megagenagg_sb2048": ["b0", "proposed", "full"]}
    ss.boot = weighted_boot
    cs.boot = weighted_boot
    ss.main(["--n-boot", str(a.n_boot), "--out", str(a.r14_out)])
    cs.main(["--exp-root", str(E), "--n-boot", str(a.n_boot), "--out", str(a.v36_out)])


if __name__ == "__main__":
    main()
