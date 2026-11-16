"""Run evaluation/step9_tables.py and evaluation/precision_paired.py UNMODIFIED with the ring-folded
policy added as a method. Run roots repointed to ../RS-e2e/experiments (git-ignored rings) and
R3_ringfold in this checkout. Usage: python evaluation/ringfold_followup.py OUT_DIR (writes only under OUT_DIR)."""
import sys
from pathlib import Path
REPO = Path(r"E:\JSJ\RS-react"); E2E = REPO.parent / "RS-e2e" / "experiments"
sys.path.insert(0, str(REPO))
OUT = Path(sys.argv[1])
RF = REPO / "experiments" / "R3_ringfold" / "runs" / "proposed"
import evaluation.step9_tables as st  # noqa
st.R1 = E2E / "R1_gine_causal"
st.METHODS = {"b0": (E2E / "R2_b0" / "gine_causal", "gine", "r2"),
              "b1b": (E2E / "R3_expansion" / "runs" / "b1b", "gine", "r3"),
              "proposed": (E2E / "R3_expansion" / "runs" / "proposed", "gine", "r3"),
              "proposed_ringfold": (RF, "gine", "r3")}
st.FULL_ALIAS = "proposed"
st.COMPARISONS = [("proposed_vs_b1b", "proposed", "b1b"), ("proposed_vs_b0", "proposed", "b0"),
                  ("proposed_ringfold_vs_b1b", "proposed_ringfold", "b1b"),
                  ("proposed_ringfold_vs_b0", "proposed_ringfold", "b0")]
st.main(["--windows", "primary", "--skip-appendix", "--out-dir", str(OUT / "step9")])
import evaluation.precision_paired as pp  # noqa
pp.RUNS = {"proposed": str(E2E / "R3_expansion/runs/proposed"), "b1b": str(E2E / "R3_expansion/runs/b1b"),
           "proposed_ringfold": str(RF)}
pp.FAMILY = [("proposed_vs_b1b", "proposed", "b1b"), ("proposed_ringfold_vs_b1b", "proposed_ringfold", "b1b")]
pp.main(["--exp-root", str(E2E), "--out", str(OUT / "precision_paired.csv")])
