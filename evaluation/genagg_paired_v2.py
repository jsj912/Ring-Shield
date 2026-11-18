"""GenAgg paired family, v2 (open item 21): GenAgg seed 1 rebuilt on the batch-2048 validation file.

    .venv312/Scripts/python.exe evaluation/genagg_paired_v2.py --out results/tables/r6_genagg_paired_v2.csv

evaluation/genagg_paired.py unchanged except that the GenAgg run directories are the *_v2 ones (seed 1 from
megagenagg_s1v2048, seeds 2-5 hard links of the shipped megagenagg runs). Same family, draws and rng seed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluation.genagg_paired as gp  # noqa: E402

E = gp.E
gp.RUNS.update(genagg_full=E / "R6_full_sb2048_k010" / "megagenagg_v2",
               genagg_b0=E / "R6_b0_sb2048_k010" / "megagenagg_v2",
               genagg_noembed_full=E / "R6_full_sb2048_k010" / "megagenagg_v2_noembed")

if __name__ == "__main__":
    gp.main()
