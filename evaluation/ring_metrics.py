"""
Ring-level evaluation metrics for RingShield (E7).

Implements the matching rule fixed in docs/RING_GROUND_TRUTH_DEFINITION.md:
a predicted ring P matches a ground-truth ring T when Jaccard(P, T) >= 0.5,
under a greedy one-to-one pairing.

Jaccard is used deliberately. One-directional overlap (|P n T| / |T|) lets a
single over-merged component "match" every true ring it swallows, which scores
near-perfect recall on a useless result. Jaccard penalises that.

This module has no dependency on the model, the dataset, or any file on disk,
so it can be tested in isolation. Run it directly to execute the self-tests:

    python evaluation/ring_metrics.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Core set comparisons
# ---------------------------------------------------------------------------
def jaccard(a: Set, b: Set) -> float:
    """|a n b| / |a u b|. Empty-vs-empty is defined as 0.0, not 1.0 --
    two empty rings are not a meaningful match."""
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def coverage(pred: Set, truth: Set) -> float:
    """Fraction of the TRUE ring's members that the prediction recovered."""
    if not truth:
        return 0.0
    return len(pred & truth) / len(truth)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
@dataclass
class MatchResult:
    """One predicted ring paired with one ground-truth ring."""
    pred_idx: int
    truth_id: object
    jaccard: float
    coverage: float
    pred_size: int
    truth_size: int


def match_rings(
    predicted: Sequence[Set],
    truth: Dict[object, Set],
    threshold: float = 0.5,
) -> Tuple[List[MatchResult], List[int], List[object]]:
    """Greedy one-to-one pairing by descending Jaccard.

    Every candidate pair above `threshold` is scored, sorted, and consumed
    highest-first; each predicted ring and each ground-truth ring can be used
    at most once. Greedy is not guaranteed optimal (max-weight bipartite
    matching would be), but with a 0.5 threshold two different truth rings
    cannot both exceed it against the same prediction -- their Jaccards would
    have to sum above 1 -- so ties are rare and the difference is negligible.

    Returns (matches, unmatched_pred_indices, unmatched_truth_ids).
    """
    candidates = []
    for pi, p in enumerate(predicted):
        for tid, t in truth.items():
            j = jaccard(p, t)
            if j >= threshold:
                candidates.append((j, pi, tid))
    candidates.sort(key=lambda c: (-c[0], c[1], str(c[2])))

    used_pred: Set[int] = set()
    used_truth: Set = set()
    matches: List[MatchResult] = []

    for j, pi, tid in candidates:
        if pi in used_pred or tid in used_truth:
            continue
        used_pred.add(pi)
        used_truth.add(tid)
        matches.append(MatchResult(
            pred_idx=pi,
            truth_id=tid,
            jaccard=j,
            coverage=coverage(predicted[pi], truth[tid]),
            pred_size=len(predicted[pi]),
            truth_size=len(truth[tid]),
        ))

    unmatched_pred = [i for i in range(len(predicted)) if i not in used_pred]
    unmatched_truth = [t for t in truth if t not in used_truth]
    return matches, unmatched_pred, unmatched_truth


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass
class RingMetrics:
    ring_precision: float
    ring_recall: float
    ring_f1: float
    member_coverage: float
    n_predicted: int
    n_truth: int
    n_matched: int
    mean_jaccard: float
    per_pattern: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "ring_precision": round(self.ring_precision, 4),
            "ring_recall": round(self.ring_recall, 4),
            "ring_f1": round(self.ring_f1, 4),
            "member_coverage": round(self.member_coverage, 4),
            "mean_jaccard": round(self.mean_jaccard, 4),
            "n_predicted": self.n_predicted,
            "n_truth": self.n_truth,
            "n_matched": self.n_matched,
        }
        if self.per_pattern:
            d["per_pattern"] = self.per_pattern
        return d

    def __str__(self) -> str:
        lines = [
            f"Ring-Precision   {self.ring_precision:.4f}  "
            f"({self.n_matched}/{self.n_predicted} predicted rings matched)",
            f"Ring-Recall      {self.ring_recall:.4f}  "
            f"({self.n_matched}/{self.n_truth} true rings found)",
            f"Ring-F1          {self.ring_f1:.4f}",
            f"Member-Coverage  {self.member_coverage:.4f}  "
            f"(mean over matched pairs)",
            f"Mean Jaccard     {self.mean_jaccard:.4f}  (matched pairs only)",
        ]
        if self.per_pattern:
            lines.append("")
            lines.append(f"{'pattern':<16} {'recall':>8} {'found':>7} {'total':>7}")
            for pt, s in sorted(self.per_pattern.items()):
                lines.append(f"{pt:<16} {s['recall']:>8.4f} "
                             f"{int(s['n_matched']):>7} {int(s['n_truth']):>7}")
        return "\n".join(lines)


def evaluate_rings(
    predicted: Sequence[Set],
    truth: Dict[object, Set],
    threshold: float = 0.5,
    pattern_types: Dict[object, str] | None = None,
) -> RingMetrics:
    """Compute ring-level precision / recall / F1 / member coverage.

    predicted      -- list of account-id sets, one per candidate ring
    truth          -- {ring_id: set of account ids} for IN-SCOPE rings only
    threshold      -- Jaccard cutoff for a match (D1 fixes this at 0.5)
    pattern_types  -- optional {ring_id: pattern name} for the E13 breakdown
    """
    matches, _, _ = match_rings(predicted, truth, threshold)

    n_pred, n_truth, n_matched = len(predicted), len(truth), len(matches)
    precision = n_matched / n_pred if n_pred else 0.0
    recall = n_matched / n_truth if n_truth else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)

    # Member-Coverage averages over MATCHED pairs only. Unmatched true rings
    # are already penalised by recall; averaging their zero coverage in here
    # would double-count the same failure.
    mean_cov = sum(m.coverage for m in matches) / n_matched if n_matched else 0.0
    mean_jac = sum(m.jaccard for m in matches) / n_matched if n_matched else 0.0

    per_pattern: Dict[str, Dict[str, float]] = {}
    if pattern_types:
        matched_ids = {m.truth_id for m in matches}
        for tid in truth:
            pt = pattern_types.get(tid, "UNKNOWN")
            s = per_pattern.setdefault(pt, {"n_truth": 0.0, "n_matched": 0.0,
                                            "recall": 0.0})
            s["n_truth"] += 1
            if tid in matched_ids:
                s["n_matched"] += 1
        for s in per_pattern.values():
            s["recall"] = s["n_matched"] / s["n_truth"] if s["n_truth"] else 0.0

    return RingMetrics(
        ring_precision=precision,
        ring_recall=recall,
        ring_f1=f1,
        member_coverage=mean_cov,
        n_predicted=n_pred,
        n_truth=n_truth,
        n_matched=n_matched,
        mean_jaccard=mean_jac,
        per_pattern=per_pattern,
    )


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------
def _test_perfect():
    truth = {1: {"a", "b", "c"}, 2: {"x", "y", "z"}}
    pred = [{"a", "b", "c"}, {"x", "y", "z"}]
    m = evaluate_rings(pred, truth)
    assert m.ring_precision == 1.0 and m.ring_recall == 1.0
    assert m.member_coverage == 1.0
    print("  perfect recovery ......... OK")


def _test_nothing():
    truth = {1: {"a", "b", "c"}}
    m = evaluate_rings([], truth)
    assert m.ring_precision == 0.0 and m.ring_recall == 0.0 and m.ring_f1 == 0.0
    print("  no predictions ........... OK")


def _test_partial():
    # 4 of 5 members recovered: Jaccard 4/5 = 0.8 >= 0.5 -> match
    truth = {1: {"a", "b", "c", "d", "e"}}
    pred = [{"a", "b", "c", "d"}]
    m = evaluate_rings(pred, truth)
    assert m.n_matched == 1
    assert abs(m.member_coverage - 0.8) < 1e-9
    assert abs(m.mean_jaccard - 0.8) < 1e-9
    print("  partial recovery ......... OK")


def _test_below_threshold():
    # 2 of 5 recovered: Jaccard 2/5 = 0.4 < 0.5 -> no match
    truth = {1: {"a", "b", "c", "d", "e"}}
    pred = [{"a", "b"}]
    m = evaluate_rings(pred, truth)
    assert m.n_matched == 0
    assert m.ring_precision == 0.0
    print("  below threshold .......... OK")


def _test_giant_blob():
    """The reason D1 mandates Jaccard.

    One predicted component swallows three true rings. Under one-directional
    overlap it would "match" all three and score recall 1.0. Under Jaccard it
    matches none, and precision is 0.
    """
    truth = {1: {"a", "b", "c"}, 2: {"d", "e", "f"}, 3: {"g", "h", "i"}}
    blob = [set("abcdefghi")]
    m = evaluate_rings(blob, truth)
    assert m.n_matched == 0, "Jaccard must reject the over-merged component"
    assert m.ring_recall == 0.0
    # Sanity: one-directional overlap WOULD have accepted it.
    assert coverage(blob[0], truth[1]) == 1.0
    print("  giant blob rejected ...... OK")


def _test_one_to_one():
    """A prediction may not be credited against two truth rings."""
    truth = {1: {"a", "b", "c", "d"}, 2: {"a", "b", "c", "e"}}
    pred = [{"a", "b", "c", "d"}]
    m = evaluate_rings(pred, truth)
    assert m.n_matched == 1, "greedy pairing must consume both sides"
    assert m.ring_recall == 0.5
    print("  one-to-one pairing ....... OK")


def _test_boundary_inclusive():
    """Jaccard exactly 0.5 counts as a match -- D1 says >= 0.5, not > 0.5.

    A 6-member true ring split into two predicted halves of 3 gives each half
    Jaccard 3/6 = 0.5. One half is credited (one-to-one pairing), the other is
    a false positive, so precision is 0.5 and recall 1.0. Pinned here so the
    boundary cannot drift silently.
    """
    truth = {1: set("abcdef")}
    pred = [set("abc"), set("def")]
    m = evaluate_rings(pred, truth)
    assert m.n_matched == 1
    assert m.ring_precision == 0.5 and m.ring_recall == 1.0
    print("  boundary is inclusive .... OK")


def _test_fragmented_ring():
    """Fragments too small to clear the threshold match nothing."""
    truth = {1: set("abcdef")}
    pred = [set("ab"), set("cd")]          # Jaccard 2/6 = 0.33 each
    m = evaluate_rings(pred, truth)
    assert m.n_matched == 0
    assert m.ring_recall == 0.0 and m.ring_precision == 0.0
    print("  fragmented ring .......... OK")


def _test_per_pattern():
    truth = {1: {"a", "b", "c"}, 2: {"x", "y", "z"}, 3: {"p", "q", "r"}}
    pats = {1: "CYCLE", 2: "CYCLE", 3: "FAN-OUT"}
    pred = [{"a", "b", "c"}]
    m = evaluate_rings(pred, truth, pattern_types=pats)
    assert abs(m.per_pattern["CYCLE"]["recall"] - 0.5) < 1e-9
    assert m.per_pattern["FAN-OUT"]["recall"] == 0.0
    print("  per-pattern breakdown .... OK")


if __name__ == "__main__":
    print("ring_metrics self-tests")
    _test_perfect()
    _test_nothing()
    _test_partial()
    _test_below_threshold()
    _test_giant_blob()
    _test_one_to_one()
    _test_boundary_inclusive()
    _test_fragmented_ring()
    _test_per_pattern()
    print("all passed")
