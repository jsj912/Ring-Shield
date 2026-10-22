"""Regression: typing_eval must type the ring that was MATCHED, not the ring at the same position
in the unfiltered list. restrict_rings drops rings with no member edge in the window, so the two
positions differ whenever an earlier ring falls outside it (found by Ruhani, L4 Week 5 check, 2026-10-22)."""
import pandas as pd

from evaluation.ring_metrics import match_rings
from evaluation.typing_eval import matched_rings
from ringshield.evaluate import restrict_rings
from ringshield.rings import Ring
from ringshield.windows import Window


def _ring(rid, members, edges, topology):
    r = Ring.baseline(ring_id=rid, tenant_id=1, aggregator_id="full", members=members, member_edges=edges,
                      seed_edges=edges, n_edges=len(edges), start_time=0, end_time=0, confidence=1.0,
                      max_edge_prob=1.0, density=1.0)
    r.topology_type = topology
    return r


def test_matched_ring_is_typed_when_an_earlier_ring_is_dropped():
    W = Window(name="w", split="test", day_lo=0, day_hi=0, day_zero=0, seconds_per_day=100)   # t in [0, 99]
    se = pd.DataFrame({"edge_id": [1, 2], "timestamp": [500, 5], "from_id": [10, 20], "to_id": [11, 21]})
    outside = _ring("outside", [10, 11], [1], "CYCLE")        # no edge in the window -> dropped
    inside = _ring("inside", [20, 21], [2], "FAN-OUT")
    rings, truth = [outside, inside], {7: {20, 21}}

    (m,), _, _ = match_rings(restrict_rings(rings, se, W), truth, 0.5)
    assert rings[m.pred_idx].ring_id == "outside", "fixture no longer exercises the old wrong lookup"

    pairs = matched_rings(rings, se, W, truth, 0.5)
    assert [(r.ring_id, mm.truth_id, r.topology_type) for r, mm in pairs] == [("inside", 7, "FAN-OUT")]
