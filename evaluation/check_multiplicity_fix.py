"""Check: the corrected metrics_from_evidence (repeats counted, no weights, no legacy flag) inside the
r14 / v36 builders reproduces the already-written _wci tables exactly. Writes only to --out-dir.

    .venv312/Scripts/python.exe evaluation/check_multiplicity_fix.py --out-dir <scratch> --exp-root ../RS-e2e/experiments
"""
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd

R = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(R))
import evaluation.component_scope as cs  # noqa: E402
import evaluation.scope_sensitivity as ss  # noqa: E402
from evaluation.ring_stats import metrics_from_evidence  # noqa: E402


def boot_corrected(evs, ids, metric, n, seed):
    """scope_sensitivity.boot, same draws, but the repeat list goes to the CORRECTED function."""
    ids = list(ids)
    if not ids:
        return float("nan"), float("nan"), float("nan")
    point = float(np.nanmean([metrics_from_evidence(e, truth_ids=ids)[metric] for e in evs]))
    rng = np.random.default_rng(seed); d = np.empty(n)
    for b in range(n):
        r = [ids[i] for i in rng.integers(0, len(ids), len(ids))]
        d[b] = np.nanmean([metrics_from_evidence(e, truth_ids=r)[metric] for e in evs])
    return point, float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))


ap = argparse.ArgumentParser(); ap.add_argument("--out-dir", type=Path, required=True)
ap.add_argument("--exp-root", type=Path, required=True); a = ap.parse_args()
a.out_dir.mkdir(parents=True, exist_ok=True)
old = R / "experiments"
ss.RUNS = {k: (a.exp_root / r.relative_to(old), a.exp_root / s.relative_to(old), m) for k, (r, s, m) in ss.RUNS.items()}
ss.boot = boot_corrected; cs.boot = boot_corrected
ss.main(["--n-boot", "1000", "--out", str(a.out_dir / "r14.csv")])
cs.main(["--exp-root", str(a.exp_root), "--n-boot", "1000", "--out", str(a.out_dir / "v36.csv")])
for mine, ref in (("r14.csv", "r14_scope_sensitivity_wci.csv"), ("v36.csv", "v36_component_scope_wci.csv")):
    x, y = pd.read_csv(a.out_dir / mine), pd.read_csv(R / "results/tables" / ref)
    num = [c for c in y.columns if pd.api.types.is_numeric_dtype(y[c])]
    dev = float(np.nanmax(np.abs(x[num].to_numpy(float) - y[num].to_numpy(float))))
    print(f"{ref}: {len(y)} rows x {len(num)} numeric cols, max abs dev {dev}")
