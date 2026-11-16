"""precision_paired.py UNMODIFIED, ring-folded full added. Usage: python evaluation/ringfold_full_paired.py OUT_CSV (writes only OUT_CSV and its json)."""
import sys
from pathlib import Path
REPO = Path(r"E:\JSJ\RS-react"); E2E = REPO.parent / "RS-e2e" / "experiments"
sys.path.insert(0, str(REPO))
import evaluation.precision_paired as pp
pp.RUNS = {"gine_full": str(E2E / "R4_partition/runs/average"), "b1b": str(E2E / "R3_expansion/runs/b1b"),
           "full_ringfold": str(REPO / "experiments/R4_partition_ringfold/average")}
pp.FAMILY = [("full_vs_b1b", "gine_full", "b1b"), ("full_ringfold_vs_b1b", "full_ringfold", "b1b"),
             ("full_ringfold_vs_full", "full_ringfold", "gine_full")]
pp.main(["--exp-root", str(E2E), "--out", sys.argv[1]])
