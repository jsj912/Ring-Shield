"""Week 4 statistics (XR-22 / XR-24): our mirror of Joan's ring_stats, checked against hers."""
from __future__ import annotations

import numpy as np
import pytest

from evaluation import ring_stats
from explainability.stats import bootstrap_mean, holm, non_overlap_verdict, paired_test, per_truth_ring


def _evidence(method: str, seed: int, matched: dict) -> ring_stats.RingEvidence:
    ids = list(matched)
    zero = {t: 0.0 for t in ids}
    return ring_stats.RingEvidence(method=method, seed=seed, window="primary", truth_ids=ids, matched=matched,
                                   jaccard=zero, coverage=zero, size={t: 3 for t in ids},
                                   pattern={t: "CYCLE" for t in ids}, quiet={t: set() for t in ids},
                                   quiet_found={t: set() for t in ids}, ttd={}, n_predicted=len(ids))


@pytest.fixture(scope="module")
def evidence():
    """Two methods x three seeds over 40 truth rings, random match indicators (fixed seed)."""
    rng = np.random.default_rng(11)
    ids = list(range(100, 140))
    evs = {m: [_evidence(m, s, {t: int(rng.random() < p) for t in ids}) for s in (1, 2, 3)]
           for m, p in (("a", 0.7), ("b", 0.5))}
    return ids, evs


def test_bootstrap_reproduces_joans_bootstrap_over_rings(evidence):
    """Joan, Q2: on RingEvidence, ring_recall per truth ring = its mean match rate over seeds; our bootstrap of
    those values gives the same point and interval as her bootstrap_over_rings (same draws)."""
    ids, evs = evidence
    hers = ring_stats.bootstrap_over_rings(evs["a"], n_resamples=1000, seed=7, metrics=("ring_recall",))["ring_recall"]
    values, seeds = per_truth_ring([ev.matched for ev in evs["a"]])
    ours = bootstrap_mean(values, n_resamples=1000, seed=7)
    assert list(values) == ids and seeds == {3: 40}
    for k in ("point", "lo", "hi"):
        assert ours[k] == pytest.approx(hers[k], abs=1e-12), k


def test_paired_test_reproduces_joans_paired_permutation(evidence):
    ids, evs = evidence
    hers = ring_stats.paired_permutation(evs["a"], evs["b"], metric="matched", n_permutations=2000, seed=3)
    a, _ = per_truth_ring([ev.matched for ev in evs["a"]])
    b, _ = per_truth_ring([ev.matched for ev in evs["b"]])
    ours = paired_test(a, b, n_permutations=2000, seed=3)
    assert ours["p_value"] == hers["p_value"]
    assert ours["mean_delta"] == pytest.approx(hers["mean_delta"], abs=1e-12)
    assert ours["delta_ci"] == pytest.approx(hers["delta_ci"], abs=1e-12)
    assert ours["n_nonzero"] == hers["n_differing_rings"]


def test_per_truth_ring_averages_only_the_seeds_where_a_ring_was_matched():
    values, seeds = per_truth_ring([{7: 1.0, 3: 0.5}, {7: 0.0}, {9: 0.25}])
    assert values == {3: 0.5, 7: 0.5, 9: 0.25} and list(values) == [3, 7, 9]
    assert seeds == {1: 2, 2: 1}


def test_bootstrap_basics():
    same = bootstrap_mean({i: 0.8 for i in range(30)}, n_resamples=200, seed=1)
    assert same["point"] == same["lo"] == same["hi"] == pytest.approx(0.8)
    vals = {i: float(i % 3 == 0) for i in range(60)}
    a, b = (bootstrap_mean(vals, n_resamples=500, seed=4) for _ in range(2))
    assert a == b and a["lo"] <= a["point"] <= a["hi"] and a["n_units"] == 60
    assert bootstrap_mean({}, n_resamples=10, seed=0)["point"] is None


def test_paired_test_counts_non_zero_differences_and_handles_ties():
    a = {i: 1.0 for i in range(10)}
    tie = paired_test(a, dict(a), n_permutations=100, seed=0)
    assert tie["p_value"] == 1.0 and tie["n_nonzero"] == 0 and tie["delta_ci"] == [0.0, 0.0]
    b = {i: (0.0 if i < 4 else 1.0) for i in range(10)}               # ours better on 4 rings, tied on 6
    t = paired_test(a, b, n_permutations=2000, seed=0)
    assert t["n_nonzero"] == 4 and t["mean_delta"] == pytest.approx(0.4) and 0 < t["p_value"] <= 1
    with pytest.raises(ValueError, match="same units"):
        paired_test(a, {0: 1.0}, n_permutations=10, seed=0)


def test_non_overlap_verdict_and_holm():
    ours = {"lo": 0.6, "hi": 0.7}
    assert non_overlap_verdict(ours, {"lo": 0.4, "hi": 0.55}) == "positive"
    assert non_overlap_verdict(ours, {"lo": 0.5, "hi": 0.65}) == "negative (intervals overlap)"
    assert non_overlap_verdict(ours, {"lo": 0.75, "hi": 0.8}) == "negative (below)"
    assert holm is ring_stats.holm                                     # Joan's, not a copy
    adj = holm([("x", 0.01), ("y", 0.04), ("z", 0.03)])
    assert [r["p_holm"] for r in adj] == pytest.approx([0.03, 0.06, 0.06])


def test_bootstrap_ratio_basics():
    """Ratio of sums over units (role precision / recall): point = sum(num) / sum(den); same answer twice; a unit set
    with no denominator has no ratio."""
    from explainability.stats import bootstrap_ratio
    num, den = {i: float(i % 2) for i in range(40)}, {i: 1.0 for i in range(40)}
    a = bootstrap_ratio(num, den, n_resamples=300, seed=2)
    assert a["point"] == 0.5 and a["lo"] <= 0.5 <= a["hi"] and a == bootstrap_ratio(num, den, n_resamples=300, seed=2)
    assert bootstrap_ratio({1: 0.0}, {1: 0.0}, n_resamples=10, seed=0)["point"] is None
    with pytest.raises(ValueError, match="same units"):
        bootstrap_ratio({1: 1.0}, {2: 1.0}, n_resamples=10, seed=0)
