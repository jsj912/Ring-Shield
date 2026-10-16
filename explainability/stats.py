"""Week 4: confidence intervals and paired tests over per-truth-ring values (XR-22, XR-24).

    vals, seeds_matched = per_truth_ring([{truth_id: value, ...} for each seed])
    ci = bootstrap_mean(vals, n_resamples=1000, seed=..., ci=0.95)        # {"point", "lo", "hi", ...}
    t = paired_test(ours, control, n_permutations=10000, seed=...)       # {"mean_delta", "p_value", "delta_ci", ...}
    adj = holm([(name, p), ...])                                          # imported from Joan's ring_stats

The algorithms are Joan's (`evaluation/ring_stats.py`), mirrored here because hers work on `RingEvidence`
(match indicators, Jaccard, ...) and we need them on arbitrary per-ring numbers (fidelity). A test runs both on
the same evidence and checks they give identical answers, so the two cannot drift apart.

The unit is the TRUTH RING (Joan, Q2). A truth ring's value is its mean over the detector seeds in which it was
matched; a truth ring never matched has no fidelity and is left out (how many rings were matched in how many
seeds is reported beside every table).

Bootstrap, in words: draw as many truth rings as there are, with replacement (some twice, some not at all), take
the mean of their values; repeat 1,000 times; the middle 95 % of those means is the interval.

Paired sign-flip test, in words: for each ring take d = ours - control. If the label "ours" meant nothing, each d
would be as likely to be +d as -d. Flip random signs 10,000 times and count how often the mean is at least as far
from 0 as the real mean: that share is the p-value. A ring where ours and the control score the same (d = 0, e.g.
every saturated ring) adds nothing either way, so the number of non-zero differences is reported beside each p.
"""
from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

import numpy as np

from evaluation.ring_stats import holm  # noqa: F401  (generic; re-exported so callers import one module)


def per_truth_ring(per_seed: Sequence[Mapping]) -> tuple[dict, dict]:
    """({truth_id: mean over the seeds where it has a value}, {n_seeds: n_truth_rings}). Ids sorted ascending."""
    acc: dict = {}
    for d in per_seed:
        for tid, v in d.items():
            acc.setdefault(tid, []).append(float(v))
    values = {tid: float(np.mean(acc[tid])) for tid in sorted(acc)}
    seeds = Counter(len(v) for v in acc.values())
    return values, {int(k): int(seeds[k]) for k in sorted(seeds)}


def _percentiles(ci: float) -> tuple[float, float]:
    tail = (1.0 - ci) / 2 * 100
    return tail, 100 - tail


def bootstrap_mean(values: Mapping, *, n_resamples: int, seed: int, ci: float = 0.95) -> dict:
    """Percentile bootstrap of the mean over units (Joan's bootstrap_over_rings draw order: one
    `rng.integers(0, n, n)` per resample)."""
    ids = list(values)
    x = np.array([values[i] for i in ids], dtype=float)
    n = len(x)
    if n == 0:
        return {"point": None, "lo": None, "hi": None, "n_units": 0, "n_resamples": n_resamples, "seed": seed}
    rng = np.random.default_rng(seed)
    draws = np.empty(n_resamples)
    for b in range(n_resamples):
        pick = rng.integers(0, n, n)
        draws[b] = x[pick].mean()
    lo_q, hi_q = _percentiles(ci)
    return {"point": float(x.mean()), "lo": float(np.percentile(draws, lo_q)), "hi": float(np.percentile(draws, hi_q)),
            "n_units": n, "n_resamples": n_resamples, "seed": seed, "ci": ci}


def paired_test(a: Mapping, b: Mapping, *, n_permutations: int, seed: int, ci: float = 0.95) -> dict:
    """Two-sided paired sign-flip test of mean(a - b) over the shared units, plus a bootstrap interval of the
    difference -- Joan's paired_permutation, same draw order, same p formula, on arbitrary values."""
    if set(a) != set(b):
        raise ValueError("paired_test: a and b must cover the same units")
    ids = list(a)
    d = np.array([a[i] - b[i] for i in ids], dtype=float)
    nz = d[d != 0]
    obs = float(d.mean()) if len(d) else 0.0
    base = {"mean_delta": obs, "n_units": len(ids), "n_nonzero": int(len(nz)), "n_permutations": n_permutations,
            "seed": seed}
    if len(nz) == 0:
        return {**base, "mean_delta": 0.0, "p_value": 1.0, "delta_ci": [0.0, 0.0]}
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_permutations, len(d)))
    perm = (signs * d).mean(axis=1)
    p = (1 + int(np.sum(np.abs(perm) >= abs(obs) - 1e-12))) / (1 + n_permutations)
    boot = rng.integers(0, len(d), (n_permutations, len(d)))
    bd = d[boot].mean(axis=1)
    lo_q, hi_q = _percentiles(ci)
    return {**base, "p_value": float(p), "delta_ci": [float(np.percentile(bd, lo_q)), float(np.percentile(bd, hi_q))]}


def non_overlap_verdict(ours: dict, control: dict) -> str:
    """Spec 6.2: ours must exceed the control with non-overlapping intervals.
    'positive' = our lower end above the control's upper end; 'negative' otherwise ('overlap' or 'below')."""
    if ours["lo"] > control["hi"]:
        return "positive"
    return "negative (below)" if ours["hi"] < control["lo"] else "negative (intervals overlap)"


def bootstrap_ratio(num: Mapping, den: Mapping, *, n_resamples: int, seed: int, ci: float = 0.95) -> dict:
    """Percentile bootstrap of sum(num) / sum(den) over units (e.g. precision = correct / predicted, summed over truth
    rings). Same draw order as bootstrap_mean (one rng.integers(0, n, n) per resample). A resample whose denominator
    is 0 has no ratio and is left out (reported as n_draws)."""
    ids = list(num)
    if set(ids) != set(den):
        raise ValueError("bootstrap_ratio: num and den must cover the same units")
    a = np.array([num[i] for i in ids], dtype=float)
    b = np.array([den[i] for i in ids], dtype=float)
    n = len(ids)
    if n == 0 or b.sum() == 0:
        return {"point": None, "lo": None, "hi": None, "n_units": n, "numerator": float(a.sum()),
                "denominator": float(b.sum()), "n_draws": 0}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_resamples):
        pick = rng.integers(0, n, n)
        d = b[pick].sum()
        if d > 0:
            draws.append(a[pick].sum() / d)
    lo_q, hi_q = _percentiles(ci)
    return {"point": float(a.sum() / b.sum()), "lo": float(np.percentile(draws, lo_q)),
            "hi": float(np.percentile(draws, hi_q)), "n_units": n, "numerator": float(a.sum()),
            "denominator": float(b.sum()), "n_draws": len(draws)}
