"""metrics_from_evidence counts repeated ring ids with their multiplicity (2026-11-16 fix);
the legacy flag reproduces the old collapse used by the frozen r14 / v36 / r7 tables."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.ring_stats import RingEvidence, metrics_from_evidence  # noqa: E402


def _ev():
    ids = [1, 2, 3, 4]
    matched = {1: 1, 2: 0, 3: 0, 4: 1}
    return RingEvidence(method="m", seed=1, window="primary", truth_ids=ids, matched=matched,
                        jaccard={t: 0.8 * m for t, m in matched.items()}, coverage={t: 0.9 * m for t, m in matched.items()},
                        size={t: 4 for t in ids}, pattern={t: "CYCLE" for t in ids},
                        quiet={t: set() for t in ids}, quiet_found={t: set() for t in ids}, ttd={}, n_predicted=3)


RES = [1, 1, 1, 2]          # ring 1 drawn three times, ring 2 once


def test_repeats_count_with_multiplicity():
    m = metrics_from_evidence(_ev(), truth_ids=RES)
    assert m["n_truth"] == 4 and m["n_matched"] == 3
    assert m["ring_recall"] == pytest.approx(0.75)


def test_repeats_equal_explicit_weights():
    a = metrics_from_evidence(_ev(), truth_ids=RES)
    b = metrics_from_evidence(_ev(), truth_ids=[1, 2], weights={1: 3, 2: 1})
    for k in ("ring_precision", "ring_recall", "ring_f1", "n_truth", "n_matched"):
        assert a[k] == pytest.approx(b[k])


def test_legacy_flag_collapses_repeats():
    m = metrics_from_evidence(_ev(), truth_ids=RES, legacy_collapse_repeats=True)
    assert m["n_truth"] == 2 and m["n_matched"] == 1
    assert m["ring_recall"] == pytest.approx(0.5)


def test_unique_ids_unchanged_by_flag():
    a = metrics_from_evidence(_ev())
    b = metrics_from_evidence(_ev(), legacy_collapse_repeats=True)
    assert {k: v for k, v in a.items() if v == v} == {k: v for k, v in b.items() if v == v}  # NaN-safe


def test_paired_unit_bootstrap_all_nan_metric_does_not_crash():
    import numpy as np
    from evaluation.ring_stats import paired_unit_bootstrap

    def stat(m, W):
        return {"f1": W.sum(axis=1) * (1.0 if m == "a" else 0.5), "undef": np.full(W.shape[0], np.nan)}
    r = paired_unit_bootstrap(stat, [("a_vs_b", "a", "b")], 5, n_boot=50, seed=0)
    assert r[("a_vs_b", "undef")]["n_valid"] == 0 and np.isnan(r[("a_vs_b", "undef")]["lo"])
    assert r[("a_vs_b", "f1")]["n_valid"] == 50 and r[("a_vs_b", "f1")]["lo"] > 0
