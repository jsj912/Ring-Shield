"""Step 9 -- bootstrap CIs, paired permutation tests, quiet-member recall, time-to-detection.

    python -m pytest tests/test_ring_stats.py -q

`evaluation/ring_metrics.py` is untouched; its own self-tests run here too (check 1).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_stats import (RingEvidence, bootstrap_over_rings, holm, metrics_from_evidence,  # noqa: E402
                                   paired_permutation, quiet_accounts, quiet_member_recall_per_pattern,
                                   ring_evidence, time_to_detection)
from ringshield.windows import load_windows  # noqa: E402

H = 3600


# --------------------------------------------------------------------------- check 1
def test_ring_metrics_self_tests_still_pass():
    r = subprocess.run([sys.executable, str(REPO_ROOT / "evaluation" / "ring_metrics.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "all passed" in r.stdout


def _evidence(method: str, matched: dict, *, seed: int = 1, n_pred: int = 100, quiet=None, quiet_found=None) -> RingEvidence:
    ids = list(matched)
    return RingEvidence(method=method, seed=seed, window="primary", truth_ids=ids, matched=dict(matched),
                        jaccard={t: (0.8 if m else 0.0) for t, m in matched.items()},
                        coverage={t: (0.9 if m else 0.0) for t, m in matched.items()},
                        size={t: 4 for t in ids}, pattern={t: "CYCLE" for t in ids},
                        quiet=quiet or {t: set() for t in ids}, quiet_found=quiet_found or {t: set() for t in ids},
                        ttd={}, n_predicted=n_pred)


# --------------------------------------------------------------------------- permutation fixtures
def test_identical_methods_give_p_one():
    m = {i: int(i % 3 == 0) for i in range(85)}
    a, b = _evidence("A", m), _evidence("B", dict(m))
    out = paired_permutation([a], [b])
    assert out["mean_delta"] == 0.0 and out["n_differing_rings"] == 0 and out["p_value"] == 1.0


def test_twenty_of_eightyfive_rings_one_way_is_significant():
    base = {i: 0 for i in range(85)}
    a = dict(base)
    for i in range(20):
        a[i] = 1                                        # A matches 20 rings B does not; B matches none extra
    out = paired_permutation([_evidence("A", a)], [_evidence("B", base)])
    assert out["n_differing_rings"] == 20
    assert out["mean_delta"] == pytest.approx(20 / 85)
    assert out["p_value"] < 0.01, out
    # and the reverse direction is symmetric
    rev = paired_permutation([_evidence("B", base)], [_evidence("A", a)])
    assert rev["p_value"] == out["p_value"] and rev["mean_delta"] == -out["mean_delta"]


def test_a_wash_is_not_significant():
    """10 rings each way: the methods differ on 20 rings but neither is better."""
    a = {i: int(i < 10) for i in range(85)}
    b = {i: int(10 <= i < 20) for i in range(85)}
    out = paired_permutation([_evidence("A", a)], [_evidence("B", b)])
    assert out["n_differing_rings"] == 20 and out["mean_delta"] == 0.0 and out["p_value"] > 0.5


def test_permutation_is_deterministic_and_seeds_are_averaged_per_ring():
    a1 = _evidence("A", {i: int(i < 10) for i in range(30)}, seed=1)
    a2 = _evidence("A", {i: int(i < 6) for i in range(30)}, seed=2)
    b = [_evidence("B", {i: 0 for i in range(30)}, seed=s) for s in (1, 2)]
    out1 = paired_permutation([a1, a2], b)
    out2 = paired_permutation([a1, a2], b)
    assert out1 == out2
    assert out1["mean_delta"] == pytest.approx(((10 + 6) / 2) / 30)


# --------------------------------------------------------------------------- holm
def test_holm_correction():
    adj = holm([("a", 0.001), ("b", 0.02), ("c", 0.04), ("d", 0.9)])
    by = {d["comparison"]: d for d in adj}
    assert by["a"]["p_holm"] == pytest.approx(0.004) and by["a"]["reject_at_05"]
    assert by["b"]["p_holm"] == pytest.approx(0.06) and not by["b"]["reject_at_05"]
    assert by["c"]["p_holm"] >= by["b"]["p_holm"]            # monotone step-down
    assert by["d"]["p_holm"] == pytest.approx(0.9)
    assert holm([("only", 0.03)])[0]["p_holm"] == pytest.approx(0.03)


# --------------------------------------------------------------------------- bootstrap
def test_bootstrap_ci_brackets_the_point_estimate():
    m = {i: int(i % 2 == 0) for i in range(100)}
    ev = _evidence("A", m, n_pred=100)
    ci = bootstrap_over_rings([ev], n_resamples=400, seed=0)
    r = ci["ring_recall"]
    assert r["point"] == pytest.approx(0.5)
    assert r["lo"] < r["point"] < r["hi"] and (r["hi"] - r["lo"]) < 0.3
    assert ci["_meta"]["n_truth_rings"] == 100 and ci["_meta"]["n_seeds"] == 1
    again = bootstrap_over_rings([ev], n_resamples=400, seed=0)
    assert again["ring_recall"] == r                                     # deterministic
    wider = bootstrap_over_rings([_evidence("A", {i: int(i % 2 == 0) for i in range(10)})], n_resamples=400, seed=0)
    assert (wider["ring_recall"]["hi"] - wider["ring_recall"]["lo"]) > (r["hi"] - r["lo"])   # fewer rings -> wider


def test_bootstrap_averages_seeds_inside_each_resample():
    evs = [_evidence("A", {i: int(i < 40) for i in range(100)}, seed=1),
           _evidence("A", {i: int(i < 60) for i in range(100)}, seed=2)]
    ci = bootstrap_over_rings(evs, n_resamples=300, seed=1)
    assert ci["ring_recall"]["point"] == pytest.approx(0.5)              # (0.4 + 0.6) / 2
    assert ci["_meta"]["n_seeds"] == 2


# --------------------------------------------------------------------------- quiet members
def test_quiet_accounts_and_recall_from_evidence():
    ids = [1, 2]
    quiet = {1: {10, 11}, 2: {20}}
    found = {1: {10}, 2: set()}
    ev = _evidence("A", {1: 1, 2: 1}, quiet=quiet, quiet_found=found)
    m = metrics_from_evidence(ev)
    assert m["n_quiet"] == 3 and m["n_quiet_found"] == 1
    assert m["quiet_member_recall"] == pytest.approx(1 / 3)
    per = quiet_member_recall_per_pattern([ev])
    assert per["CYCLE"]["n_quiet"] == 3 and per["CYCLE"]["recall"] == pytest.approx(1 / 3)


def test_quiet_accounts_uses_only_in_window_seed_edges():
    W = load_windows()["primary"]
    lo, hi = W.bounds
    se = pd.DataFrame({"edge_id": [1, 2, 3], "from_id": [1, 2, 5], "to_id": [2, 3, 6],
                       "timestamp": [lo + H, lo + 2 * H, lo - 10 * H]})      # edge 3 is outside the window
    seed_mask = np.array([True, False, True])
    q = quiet_accounts({7: {1, 2, 3, 5, 6}}, se, seed_mask, W)
    assert q[7] == {3, 5, 6}          # 1 and 2 touch an in-window seed edge; 5 / 6 only an out-of-window one


def test_ring_evidence_refuses_a_non_causal_run():
    W = load_windows()["primary"]
    se = pd.DataFrame({"edge_id": [1], "from_id": [1], "to_id": [2], "timestamp": [W.bounds[0]]})
    with pytest.raises(ValueError, match="causal"):
        ring_evidence([], se, {}, W, method="x", seed=1, causal=False)


def test_time_to_detection_median_and_iqr():
    ev = _evidence("A", {1: 1, 2: 1, 3: 1})
    ev.ttd = {1: 0, 2: 2 * H, 3: 6 * H}
    t = time_to_detection([ev])
    assert t["n"] == 3 and t["median_h"] == pytest.approx(2.0) and t["frac_non_negative"] == 1.0
    assert t["iqr_h"] == pytest.approx(3.0)
    assert time_to_detection([_evidence("A", {1: 0})])["n"] == 0


# --------------------------------------------------------------------------- check 2 (real data)
def test_quiet_member_recall_of_b0_is_at_most_five_percent():
    """B0 builds rings from seed edges only, so it can reach a quiet account only through the
    member-edge rule -- by construction the recall must stay near zero."""
    path = REPO_ROOT / "results" / "tables" / "r9_quiet_members.csv"
    if not path.exists():
        pytest.skip("run evaluation/step9_tables.py first")
    d = pd.read_csv(path)
    b0 = d[(d["method"] == "b0") & (d["window"] == "primary") & (d["pattern"] == "ALL")]
    assert len(b0) == 1, b0
    assert float(b0["quiet_member_recall"].iloc[0]) <= 0.05, b0.to_dict("records")
