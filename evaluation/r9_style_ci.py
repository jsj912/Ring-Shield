"""r9-style intervals (ring_stats.bootstrap_over_rings, the FINDINGS interval) for the post hoc rows
the paper adds: T-P3 baselines and the ring-folded pipeline. Runs evaluation/step9_tables.py
UNMODIFIED with its method table replaced; writes only under OUT_DIR.

    python evaluation/r9_style_ci.py OUT_DIR

Run roots: ../RS-e2e/experiments for the shipped methods and detector scores (git-ignored here),
experiments/R13_baselines for the baselines, experiments/R3_ringfold and
experiments/R4_partition_ringfold for the ring-folded arms."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
E2E = REPO.parent / "RS-e2e" / "experiments"
B = REPO / "experiments" / "R13_baselines"
sys.path.insert(0, str(REPO))
import evaluation.step9_tables as st  # noqa: E402

OUT = Path(sys.argv[1])
st.R1 = E2E / "R1_gine_causal"
st.METHODS = {
    "b0": (E2E / "R2_b0" / "gine_causal", "gine", "r2"),
    "b1b": (E2E / "R3_expansion" / "runs" / "b1b", "gine", "r3"),
    "proposed": (E2E / "R3_expansion" / "runs" / "proposed", "gine", "r3"),
    "average": (E2E / "R4_partition" / "runs" / "average", "gine", "r4"),
    "proposed_ringfold": (REPO / "experiments" / "R3_ringfold" / "runs" / "proposed", "gine", "r3"),
    "full_ringfold": (REPO / "experiments" / "R4_partition_ringfold" / "average", "gine", "r4"),
    **{m: (B / m, "gine", "r4") for m in ("louvain_r0.5", "louvain_r1", "louvain_r2", "lpa",
                                          "louvain_r1_on_expansion", "lpa_on_expansion", "csgm")},
}
st.FULL_ALIAS = "average"
st.COMPARISONS = [("full_ringfold_vs_full", "full_ringfold", "average"),
                  ("full_ringfold_vs_b0", "full_ringfold", "b0")]
st.main(["--windows", "primary", "--skip-appendix", "--out-dir", str(OUT)])
