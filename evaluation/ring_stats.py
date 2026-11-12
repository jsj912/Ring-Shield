"""Step 9 -- metrics extensions and statistics over rings.

    ev  = ring_evidence(rings, scored_edges, truth, window, seed_mask=..., patterns=...)
    ci  = bootstrap_over_rings([ev_seed1, ev_seed2, ...], n_resamples=1000, seed=0)
    res = paired_permutation([ev_a...], [ev_b...], metric="matched", n=10000, seed=0)
    adj = holm([("a vs b", p1), ("c vs d", p2)])

Nothing here changes `evaluation/ring_metrics.py`: matching is still
`ring_metrics.match_rings` (greedy, Jaccard >= tau), and its self-tests are untouched. This
module only *re-uses* the matching to produce per-ring evidence and then resamples it.

**Evidence** (`RingEvidence`) is everything a resample needs, recorded once per (method, seed,
window): the in-scope truth ring ids, the matched indicator per truth ring, the Jaccard and
member coverage of each match, the quiet members of each ring and which of them a matched
prediction recovered, the time-to-detection per matched ring, and the predicted-ring count.
Because the indicators are per truth ring, a bootstrap over rings and a paired permutation test
between two methods are both exact re-tabulations -- no re-matching inside the loop.

**Quiet members** (amendment b): Q = accounts that are scored members of an in-scope truth ring
(the `test_visible` rule applied to the window) and none of whose incident edges *inside that
window* is a seed at k*. `quiet_member_recall` = |Q ∩ members of matched predicted rings| / |Q|,
also per pattern type. B0 cannot score above 0 on it except through a matched ring that happens
to contain a quiet account (its rings are built from seeds alone, so its member sets can still
reach a quiet account through the member-edge rule) -- the fixture test pins that it stays <= 0.05.

**Time to detection** (amendment e): first seed-edge timestamp of the matched prediction minus
the ring's start = the first in-window truth edge. Median and IQR over matched rings. It is only
meaningful for a causal detector, so `ring_evidence` refuses a non-causal run config
(`causal=False` in the caller's run config -> ValueError).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from evaluation.ring_metrics import match_rings

N_BOOTSTRAP = 1000
N_PERMUTATION = 10000
RATE_METRICS = ("ring_precision", "ring_recall", "ring_f1", "member_coverage", "mean_jaccard",
                "ring_recall_ge3", "quiet_member_recall")


# --------------------------------------------------------------------------------- evidence
@dataclass
class RingEvidence:
    """Per-truth-ring evidence for one (method, seed, window)."""
    method: str
    seed: int
    window: str
    truth_ids: list
    matched: dict            # truth_id -> 0/1
    jaccard: dict            # truth_id -> float (0 when unmatched)
    coverage: dict           # truth_id -> float
    size: dict               # truth_id -> number of scored members
    pattern: dict            # truth_id -> pattern type
    quiet: dict              # truth_id -> set of quiet accounts
    quiet_found: dict        # truth_id -> set of quiet accounts inside a matched prediction
    ttd: dict                # truth_id -> seconds from ring start to the first seed edge (matched only)
    n_predicted: int
    meta: dict = field(default_factory=dict)

    @property
    def n_truth(self) -> int:
        return len(self.truth_ids)


def quiet_accounts(truth: dict, scored_edges: pd.DataFrame, seed_mask: np.ndarray, window) -> dict:
    """{truth_id: set of quiet member accounts} -- members with no seed edge incident inside the window."""
    ts = scored_edges["timestamp"].to_numpy(np.int64)
    in_win = window.mask(ts)
    f = scored_edges["from_id"].to_numpy(np.int64)
    t = scored_edges["to_id"].to_numpy(np.int64)
    sel = in_win & np.asarray(seed_mask, dtype=bool)
    seeded = set(f[sel].tolist()) | set(t[sel].tolist())
    return {tid: {a for a in accs if a not in seeded} for tid, accs in truth.items()}


def ring_evidence(rings, scored_edges: pd.DataFrame, truth: dict, window, *, method: str, seed: int,
                  seed_mask: np.ndarray | None = None, patterns: dict | None = None, threshold: float = 0.5,
                  causal: bool | None = None, truth_edges: pd.DataFrame | None = None) -> RingEvidence:
    """Evidence for one run on one window. `rings` are `ringshield.rings.Ring` records.

    `seed_mask` (positional over `scored_edges`) enables the quiet-member columns; `truth_edges`
    (ring_id, from_id, to_id, timestamp_int) enables time-to-detection. `causal=False` raises:
    a time-to-detection on a non-causal run would be measured against edges the model could see
    from the future."""
    from ringshield.evaluate import restrict_rings
    if causal is False:
        raise ValueError("ring_evidence: time-to-detection and quiet-member recall are only meaningful for a "
                         "causal run (loader_route / causal_sampling); got causal=False")
    pred_sets = restrict_rings(rings, scored_edges, window)
    matches, _, _ = match_rings(pred_sets, truth, threshold)
    by_truth = {m.truth_id: m for m in matches}
    quiet = quiet_accounts(truth, scored_edges, seed_mask, window) if seed_mask is not None else {t: set() for t in truth}
    quiet_found, ttd = {}, {}
    ts_of = scored_edges.set_index("edge_id")["timestamp"]
    # a prediction's index in `pred_sets` is the index of the ring that survived the window filter;
    # rebuild that mapping the same way ringshield.evaluate.restrict_rings does
    keep_ids = set(scored_edges.loc[window.mask(scored_edges["timestamp"].to_numpy()), "edge_id"].tolist())
    ring_of_pred = [r for r in rings if [e for e in r.member_edges if e in keep_ids]]
    for tid, accs in truth.items():
        m = by_truth.get(tid)
        quiet_found[tid] = (quiet[tid] & pred_sets[m.pred_idx]) if m else set()
        if m is not None and truth_edges is not None:
            r = ring_of_pred[m.pred_idx]
            seeds_in = [e for e in r.seed_edges if e in keep_ids]
            te = truth_edges[(truth_edges["ring_id"] == tid) & window.mask(truth_edges["timestamp_int"].to_numpy())]
            if seeds_in and len(te):
                ttd[tid] = int(min(ts_of.loc[seeds_in])) - int(te["timestamp_int"].min())
    return RingEvidence(
        method=method, seed=seed, window=window.name, truth_ids=list(truth),
        matched={t: int(t in by_truth) for t in truth},
        jaccard={t: (by_truth[t].jaccard if t in by_truth else 0.0) for t in truth},
        coverage={t: (by_truth[t].coverage if t in by_truth else 0.0) for t in truth},
        size={t: len(a) for t, a in truth.items()},
        pattern={t: (patterns or {}).get(t, "UNKNOWN") for t in truth},
        quiet=quiet, quiet_found=quiet_found, ttd=ttd, n_predicted=len(pred_sets),
        meta={"threshold": threshold, "causal": causal})


# --------------------------------------------------------------------------------- metrics from evidence
def metrics_from_evidence(ev: RingEvidence, truth_ids: Sequence | None = None, weights: dict | None = None) -> dict:
    """Recompute the ring metrics from evidence over a (possibly resampled) set of truth rings.

    `truth_ids` may repeat entries (a bootstrap resample); `weights` counts them instead. Ring
    precision needs the predicted count, which a resample cannot change -- it is scaled by the
    resampled matched count over the observed matched count, the standard treatment when the
    resampling unit is the truth ring."""
    ids = list(ev.truth_ids if truth_ids is None else truth_ids)
    w = {i: 1 for i in ids} if weights is None else weights
    n_truth = sum(w[i] for i in set(ids))
    n_matched = sum(w[i] * ev.matched[i] for i in set(ids))
    recall = n_matched / n_truth if n_truth else 0.0
    obs_matched = sum(ev.matched.values())
    n_pred_eff = ev.n_predicted * (n_truth / len(ev.truth_ids)) if ev.truth_ids else 0
    precision = (n_matched / n_pred_eff) if n_pred_eff else 0.0
    precision = min(precision, 1.0)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    cov = (sum(w[i] * ev.coverage[i] * ev.matched[i] for i in set(ids)) / n_matched) if n_matched else 0.0
    jac = (sum(w[i] * ev.jaccard[i] * ev.matched[i] for i in set(ids)) / n_matched) if n_matched else 0.0
    big = [i for i in set(ids) if ev.size[i] >= 3]
    n_big = sum(w[i] for i in big)
    r_ge3 = (sum(w[i] * ev.matched[i] for i in big) / n_big) if n_big else float("nan")
    q_tot = sum(w[i] * len(ev.quiet[i]) for i in set(ids))
    q_found = sum(w[i] * len(ev.quiet_found[i]) for i in set(ids))
    return {"ring_precision": precision, "ring_recall": recall, "ring_f1": f1, "member_coverage": cov,
            "mean_jaccard": jac, "ring_recall_ge3": r_ge3,
            "quiet_member_recall": (q_found / q_tot) if q_tot else float("nan"),
            "n_truth": n_truth, "n_matched": n_matched, "n_quiet": q_tot, "n_quiet_found": q_found,
            "n_predicted": ev.n_predicted, "obs_matched": obs_matched}


def quiet_member_recall_per_pattern(evs: Sequence[RingEvidence]) -> dict:
    """{pattern: {n_quiet, n_found, recall}} pooled over the seeds given."""
    out: dict[str, dict] = {}
    for ev in evs:
        for tid in ev.truth_ids:
            d = out.setdefault(ev.pattern[tid], {"n_quiet": 0, "n_found": 0})
            d["n_quiet"] += len(ev.quiet[tid])
            d["n_found"] += len(ev.quiet_found[tid])
    for d in out.values():
        d["recall"] = d["n_found"] / d["n_quiet"] if d["n_quiet"] else float("nan")
    return out


def time_to_detection(evs: Sequence[RingEvidence]) -> dict:
    """Median and IQR (seconds and hours) of first-seed-edge minus ring start, over matched rings."""
    vals = np.array([v for ev in evs for v in ev.ttd.values()], dtype=float)
    if len(vals) == 0:
        return {"n": 0, "median_s": None, "q1_s": None, "q3_s": None, "median_h": None, "iqr_h": None,
                "frac_non_negative": None}
    q1, med, q3 = (float(np.percentile(vals, p)) for p in (25, 50, 75))
    return {"n": int(len(vals)), "median_s": med, "q1_s": q1, "q3_s": q3, "median_h": med / 3600,
            "iqr_h": (q3 - q1) / 3600, "frac_non_negative": float((vals >= 0).mean())}


# --------------------------------------------------------------------------------- bootstrap
def bootstrap_over_rings(evs: Sequence[RingEvidence], *, n_resamples: int = N_BOOTSTRAP, seed: int = 0,
                         metrics: Sequence[str] = RATE_METRICS) -> dict:
    """Percentile CIs over truth rings; the seeds are averaged INSIDE each resample.

    Every evidence in `evs` must cover the same truth rings (same window, same scope). One
    resample draws |T| ring ids with replacement, recomputes each seed's metrics on that multiset
    and averages them -- so the interval carries the ring-sampling variation with the seed
    variation folded in, which is what a reader of the table needs."""
    assert evs, "no evidence"
    ids = list(evs[0].truth_ids)
    for ev in evs[1:]:
        assert list(ev.truth_ids) == ids, f"{ev.method}: different truth rings"
    rng = np.random.default_rng(seed)
    point = {m: float(np.nanmean([metrics_from_evidence(ev)[m] for ev in evs])) for m in metrics}
    draws = {m: np.full(n_resamples, np.nan) for m in metrics}
    n = len(ids)
    for b in range(n_resamples):
        pick = rng.integers(0, n, n)
        uniq, counts = np.unique(pick, return_counts=True)
        sub = [ids[i] for i in uniq]
        w = {ids[i]: int(c) for i, c in zip(uniq, counts)}
        vals = [metrics_from_evidence(ev, sub, w) for ev in evs]
        for m in metrics:
            with np.errstate(invalid="ignore"):
                draws[m][b] = float(np.nanmean([v[m] for v in vals]))
    out = {}
    for m in metrics:
        d = draws[m][~np.isnan(draws[m])]
        out[m] = {"point": point[m], "lo": float(np.percentile(d, 2.5)) if len(d) else float("nan"),
                  "hi": float(np.percentile(d, 97.5)) if len(d) else float("nan"), "n_draws": int(len(d))}
    out["_meta"] = {"n_resamples": n_resamples, "seed": seed, "n_truth_rings": n, "n_seeds": len(evs),
                    "unit": "truth ring (with replacement); seeds averaged inside each resample"}
    return out


# --------------------------------------------------------------------------------- permutation
def paired_permutation(evs_a: Sequence[RingEvidence], evs_b: Sequence[RingEvidence], *, metric: str = "matched",
                       n_permutations: int = N_PERMUTATION, seed: int = 0) -> dict:
    """Two-sided paired sign-flip test on per-ring values, seeds averaged per ring.

    For every truth ring the per-seed values of A and B are averaged, giving one paired difference
    per ring; a permutation flips the sign of a random subset of those differences (the null: the
    label A/B carries no information about the ring). p = (1 + #|perm| >= |observed|) / (1 + n)."""
    ids = list(evs_a[0].truth_ids)
    for ev in list(evs_a) + list(evs_b):
        assert list(ev.truth_ids) == ids, f"{ev.method}: different truth rings"

    def per_ring(evs):
        if metric == "matched":
            return np.array([np.mean([ev.matched[t] for ev in evs]) for t in ids])
        if metric == "jaccard":
            return np.array([np.mean([ev.jaccard[t] for ev in evs]) for t in ids])
        if metric == "quiet_found":
            return np.array([np.mean([len(ev.quiet_found[t]) for ev in evs]) for t in ids])
        raise ValueError(f"unknown metric {metric!r}")
    a, b = per_ring(evs_a), per_ring(evs_b)
    d = a - b
    nz = d[d != 0]
    obs = float(d.mean())
    if len(nz) == 0:
        return {"metric": metric, "mean_delta": 0.0, "n_rings": len(ids), "n_differing_rings": 0,
                "p_value": 1.0, "n_permutations": n_permutations, "seed": seed,
                "delta_ci": [0.0, 0.0]}
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_permutations, len(d)))
    perm = (signs * d).mean(axis=1)
    p = (1 + int(np.sum(np.abs(perm) >= abs(obs) - 1e-12))) / (1 + n_permutations)
    boot = rng.integers(0, len(d), (n_permutations, len(d)))
    bd = d[boot].mean(axis=1)
    return {"metric": metric, "mean_delta": obs, "n_rings": len(ids), "n_differing_rings": int(len(nz)),
            "p_value": float(p), "n_permutations": n_permutations, "seed": seed,
            "delta_ci": [float(np.percentile(bd, 2.5)), float(np.percentile(bd, 97.5))]}


def paired_unit_bootstrap(stat: Callable, comparisons: Sequence[tuple], n_units: int, *, n_boot: int = N_PERMUTATION,
                          seed: int = 0, batch: int = 1000) -> dict:
    """Paired bootstrap on the difference of precision-bearing metrics (PITFALLS.md sections 7-8).

    `stat(method, W)` maps a (B, n_units) matrix of unit multiplicities to {metric: (B,) array}; the
    caller pools / averages seeds inside it. Both arms of every comparison are evaluated on the SAME
    draw, so the interval is on the paired difference. Returns {(comparison, metric): {delta, lo,
    hi, p, n_valid}} with a two-sided p = min(1, 2 * min(#(d <= 0) + 1, #(d >= 0) + 1) / (n + 1))."""
    rng = np.random.default_rng(seed)
    methods = sorted({m for _, x, y in comparisons for m in (x, y)})
    point = {m: stat(m, np.ones((1, n_units))) for m in methods}
    draws: dict = {m: {} for m in methods}
    done = 0
    while done < n_boot:
        b = min(batch, n_boot - done)
        Wb = np.stack([np.bincount(rng.integers(0, n_units, n_units), minlength=n_units) for _ in range(b)]).astype(float)
        for m in methods:
            for k, v in stat(m, Wb).items():
                draws[m].setdefault(k, []).append(v)
        done += b
    out = {}
    for c, x, y in comparisons:
        for k in draws[x]:
            d = np.concatenate(draws[x][k]) - np.concatenate(draws[y][k])
            d = d[~np.isnan(d)]
            n = len(d)
            p = min(1.0, 2 * min(int((d <= 0).sum()) + 1, int((d >= 0).sum()) + 1) / (n + 1))
            out[(c, k)] = {"delta": float(point[x][k][0] - point[y][k][0]), "lo": float(np.percentile(d, 2.5)),
                           "hi": float(np.percentile(d, 97.5)), "p": float(p), "n_valid": n}
    return out


def holm(pairs: Iterable[tuple]) -> list[dict]:
    """Holm-Bonferroni over (name, p) pairs -> [{name, p_raw, p_holm, rank, reject_at_05}]."""
    items = sorted(((n, float(p)) for n, p in pairs), key=lambda x: x[1])
    m = len(items)
    out, running = [], 0.0
    for i, (name, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)                       # Holm's step-down is monotone
        out.append({"comparison": name, "p_raw": p, "p_holm": running, "rank": i + 1,
                    "reject_at_05": bool(running < 0.05)})
    return out
