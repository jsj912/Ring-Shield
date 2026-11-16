"""score_external intervals: default = weighted r9 bootstrap, --legacy-subsample-intervals = r14."""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from evaluation import score_external as se  # noqa: E402

RINGS = [REPO_ROOT / f"experiments/R4_partition/runs/average/seed{s}/rings.parquet" for s in range(1, 6)]
T = REPO_ROOT / "results" / "tables"


def _run(tmp_path, extra):
    if not all(p.exists() for p in RINGS):
        pytest.skip("R4_partition rings not present")
    try:
        rows = se.main(["--rings", *map(str, RINGS), "--conventions", "test_visible", "--thresholds", "0.5",
                        "--out", str(tmp_path), *extra])
    except (FileNotFoundError, KeyError) as e:  # data paths absent on this machine
        pytest.skip(f"AMLworld data not available: {e}")
    return rows[0]


def test_default_interval_equals_r9(tmp_path):
    r9 = pd.read_csv(T / "r9_ring_ci.csv").query("method == 'average' and window == 'primary'").iloc[0]
    row = _run(tmp_path, [])
    assert row["ring_f1"] == pytest.approx(r9["ring_f1"], abs=1e-12)
    assert (row["ring_f1_lo"], row["ring_f1_hi"]) == pytest.approx((r9["ring_f1_lo"], r9["ring_f1_hi"]), abs=1e-12)
    assert round(row["ring_f1_lo"], 4) == 0.5023 and round(row["ring_f1_hi"], 4) == 0.6747


def test_legacy_flag_equals_r14(tmp_path):
    r14 = pd.read_csv(T / "r14_scope_sensitivity.csv").query(
        "policy == 'test_visible' and detector == 'gine_causal' and method == 'full'").iloc[0]
    row = _run(tmp_path, ["--legacy-subsample-intervals"])
    assert row["ring_f1"] == pytest.approx(r14["ring_f1"], abs=1e-12)
    assert (row["ring_f1_lo"], row["ring_f1_hi"]) == pytest.approx((r14["ring_f1_lo"], r14["ring_f1_hi"]), abs=1e-12)
