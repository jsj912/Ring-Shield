"""Tiny hand-built contract frames for the tests: one ring per AMLworld pattern type plus edge cases.

    se, rings = fixture_contract()        # scored_edges + rings DataFrames, contract columns and types

Every fixture is built in the exact contract layout (contract/schema.py) and must pass
`contract_io.validate_scored_edges` / `validate_rings`; test_contract_io.py asserts it. Amounts,
roles and closure here are simple illustrative values, NOT the research side's role algorithm --
they exist so the L4 code has one small, readable ring of every shape to run on.

Also here, for the matching and fidelity tests:
    five_edge_case()       a 5-edge ring with a known true-edge set (fidelity computed by hand)
    window_shift_case()    a ring with no edge in the window placed FIRST, then a ring that matches
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER, TOPOLOGY_TYPES, ring_record
from ringshield.windows import load_windows

MODEL_ID, SEED, AGGREGATOR = "fixture", 0, "full"
PREFIX = f"{AGGREGATOR}-{MODEL_ID}-{SEED}-"
PATTERN_TYPES = list(TOPOLOGY_TYPES)
EDGE_CASES = [PREFIX + n for n in ("nan_closure_cycle", "cross_bank", "mixed_currency", "with_expansion")]
T0 = load_windows()["primary"].bounds[0] + 3600          # one hour into the primary window (test day 8)


def _probs(topology: str) -> list[float]:
    """0.65 on the ring's own type, 0.05 on each of the other seven (sums to 1.0)."""
    return [0.65 if t == topology else 0.05 for t in TOPOLOGY_TYPES]


def _closure(edges: pd.DataFrame) -> float:
    """1 - |inflow at sinks - outflow at sources| / max; NaN when there is no source or no sink."""
    out_sum = edges.groupby("from_id")["amount_received"].sum()
    in_sum = edges.groupby("to_id")["amount_received"].sum()
    accounts = set(out_sum.index) | set(in_sum.index)
    sources = [a for a in accounts if a not in in_sum.index]
    sinks = [a for a in accounts if a not in out_sum.index]
    if not sources or not sinks:
        return math.nan
    a, b = float(in_sum[sinks].sum()), float(out_sum[sources].sum())
    return float(min(max(1 - abs(a - b) / max(a, b), 0.0), 1.0))


class _Builder:
    def __init__(self):
        self.edges, self.rings = [], []
        self.next_edge, self.next_account = 1000, 100

    def accounts(self, n):
        ids = list(range(self.next_account, self.next_account + n))
        self.next_account += n
        return ids

    def ring(self, name, topology, flows, *, seeds=None, expanded=None, banks=None, currencies=None,
             t0=T0, step_s=1800, times_h=None, scores=None):
        """flows: list of (from_account, to_account, amount). seeds / expanded: flow positions.
        times_h / scores: optional explicit hours after t0 and calibrated scores, one per flow."""
        seeds = list(range(len(flows))) if seeds is None else seeds
        expanded = expanded or {}
        rows = []
        for i, (f, t, amt) in enumerate(flows):
            fb, tb = (banks[i] if banks else (7, 7))
            cs, cr = (currencies[i] if currencies else (0, 0))
            is_seed = i in seeds
            score = 0.90 - 0.01 * i if is_seed else (0.05 if i in expanded else 0.01)
            if scores is not None:
                score = float(scores[i])
            ts = t0 + (int(round(times_h[i] * 3600)) if times_h is not None else i * step_s)
            rows.append({"edge_id": self.next_edge, "tenant_id": fb, "from_id": f, "to_id": t, "from_bank": fb,
                         "to_bank": tb, "timestamp": ts, "amount_sent": float(amt),
                         "amount_received": float(amt) * (1.1 if cs != cr else 1.0), "currency_sent": cs,
                         "currency_received": cr, "payment_format": 3, "score_raw": score + 0.001,
                         "score_calibrated": score, "is_seed": is_seed, "model_id": MODEL_ID, "seed": SEED})
            self.next_edge += 1
        self.edges.extend(rows)
        e = pd.DataFrame(rows)
        seed_ids = [int(e.edge_id[i]) for i in seeds]
        exp_ids = [int(e.edge_id[i]) for i in sorted(expanded)]
        members = sorted(set(e.from_id) | set(e.to_id))
        senders, receivers = set(e.from_id), set(e.to_id)
        closure = _closure(e)
        mean_seed = float(e.loc[e.is_seed, "score_calibrated"].mean())
        n_edges = len(seed_ids) + len(exp_ids)
        earliest_seed = e[e.is_seed].sort_values(["timestamp", "edge_id"]).iloc[0]
        # Through ring_record so every contract column is present and correctly typed: the fields
        # set below are the ones this fixture decides, the rest take the contract's defaults. Built
        # as a bare dict, any column added by a later schema version would materialise as all-NaN
        # float64 in `pd.DataFrame(self.rings, columns=RINGS_ORDER)` and fail the type check.
        self.rings.append(ring_record(**{
            "ring_id": PREFIX + name, "tenant_id": int(earliest_seed.from_bank), "aggregator_id": AGGREGATOR,
            "members": members, "n_members": len(members),
            "member_edges": [int(x) for x in e.edge_id], "seed_edges": seed_ids, "expanded_edges": exp_ids,
            "expanded_edge_probs": [float(expanded[i]) for i in sorted(expanded)], "n_edges": n_edges,
            "start_time": int(e.timestamp.min()), "end_time": int(e.timestamp.max()),
            "duration_hours": float((e.timestamp.max() - e.timestamp.min()) / 3600),
            "confidence": mean_seed if math.isnan(closure) else mean_seed * closure,
            "max_edge_prob": float(e.score_calibrated.max()), "density": n_edges / (len(members) * (len(members) - 1)),
            "conservation_closure": closure, "topology_type": topology, "topology_probs": _probs(topology),
            "source_accounts": sorted(senders - receivers), "sink_accounts": sorted(receivers - senders),
            "mule_accounts": sorted(senders & receivers)}))

    def frames(self):
        se = pd.DataFrame(self.edges, columns=SCORED_EDGES_ORDER)
        se["model_id"] = se["model_id"].astype(object)
        return se, pd.DataFrame(self.rings, columns=RINGS_ORDER)


def fixture_contract() -> tuple[pd.DataFrame, pd.DataFrame]:
    """scored_edges + rings with one ring per pattern type and the four edge cases."""
    b = _Builder()
    s, d = b.accounts(1), b.accounts(4)
    b.ring("fan_out", "FAN-OUT", [(s[0], x, 1000 + 10 * i) for i, x in enumerate(d)])
    s, d = b.accounts(4), b.accounts(1)
    b.ring("fan_in", "FAN-IN", [(x, d[0], 900 + 10 * i) for i, x in enumerate(s)])
    s, h, d = b.accounts(3), b.accounts(1)[0], b.accounts(3)
    b.ring("gather_scatter", "GATHER-SCATTER", [(x, h, 500) for x in s] + [(h, x, 495) for x in d])
    s, m, d = b.accounts(1)[0], b.accounts(3), b.accounts(1)[0]
    b.ring("scatter_gather", "SCATTER-GATHER", [(s, x, 700) for x in m] + [(x, d, 690) for x in m])
    s, a, bb, c, t = b.accounts(5)
    b.ring("cycle", "CYCLE", [(s, a, 800), (a, bb, 790), (bb, c, 780), (c, a, 770), (a, t, 760)])
    x = b.accounts(5)
    b.ring("random", "RANDOM", [(x[0], x[1], 300), (x[2], x[1], 250), (x[1], x[3], 520), (x[4], x[3], 100)])
    l, r = b.accounts(2), b.accounts(2)
    b.ring("bipartite", "BIPARTITE", [(l[0], r[0], 400), (l[0], r[1], 410), (l[1], r[0], 420), (l[1], r[1], 430)])
    c = b.accounts(5)
    b.ring("stack", "STACK", [(c[i], c[i + 1], 1000 - 5 * i) for i in range(4)])
    # edge cases
    a = b.accounts(3)
    b.ring("nan_closure_cycle", "CYCLE", [(a[0], a[1], 600), (a[1], a[2], 600), (a[2], a[0], 600)])
    s, m, d = b.accounts(3)
    b.ring("cross_bank", "STACK", [(s, m, 2000), (m, d, 1990)], banks=[(11, 22), (22, 33)])
    s, d = b.accounts(1)[0], b.accounts(3)
    b.ring("mixed_currency", "FAN-OUT", [(s, x, 300) for x in d], currencies=[(0, 0), (0, 4), (2, 5)])
    c = b.accounts(5)
    b.ring("with_expansion", "STACK", [(c[i], c[i + 1], 800 - 3 * i) for i in range(4)],
           seeds=[0, 1], expanded={2: 0.85, 3: 0.72})
    # background licit traffic between non-ring accounts
    bg = b.accounts(6)
    for i in range(5):
        b.edges.append({"edge_id": b.next_edge, "tenant_id": 9, "from_id": bg[i], "to_id": bg[i + 1], "from_bank": 9,
                        "to_bank": 9, "timestamp": T0 + 300 * i, "amount_sent": 50.0, "amount_received": 50.0,
                        "currency_sent": 0, "currency_received": 0, "payment_format": 1, "score_raw": 0.002,
                        "score_calibrated": 0.001, "is_seed": False, "model_id": MODEL_ID, "seed": SEED})
        b.next_edge += 1
    return b.frames()


def five_edge_case() -> dict:
    """A 5-edge ring whose fidelity can be computed by hand.

    Scores (calibrated) and truth:      edge  score  in T?
                                        11    0.90   yes
                                        12    0.80   no
                                        13    0.80   yes   (tie with 12 on score_calibrated;
                                                               12 has the higher score_raw, so 12 ranks first)
                                        14    0.30   yes
                                        15    0.10   no
    Score-only ranking: 11, 12, 13, 14, 15.  |T| = 3.
        fidelity@3  = |{11,12,13} & T| / min(3, 3) = 2/3
        fidelity@5  = |{11..15} & T|   / min(5, 3) = 3/3 = 1
        fidelity@10 = same as @5 (only 5 edges)    = 1
    """
    edges = pd.DataFrame({"edge_id": [15, 14, 13, 12, 11],
                          "score_calibrated": [0.10, 0.30, 0.80, 0.80, 0.90],
                          "score_raw": [0.11, 0.31, 0.79, 0.81, 0.91]})
    return {"edges": edges, "truth": {11, 13, 14}, "ranking": [11, 12, 13, 14, 15],
            "fidelity": {3: 2 / 3, 5: 1.0, 10: 1.0}}


def window_shift_case() -> dict:
    """Two rings: the FIRST has every edge before the primary window (so the windowed evaluation
    drops it), the SECOND sits inside the window and equals a truth ring exactly. A matcher that kept
    positions from the unfiltered list would credit the match to the first ring's id."""
    b = _Builder()
    early = b.accounts(3)
    b.ring("outside_window", "STACK", [(early[0], early[1], 100), (early[1], early[2], 99)], t0=T0 - 10 * 86400)
    inside = b.accounts(4)
    b.ring("inside_window", "FAN-OUT", [(inside[0], x, 200) for x in inside[1:]])
    se, rings = b.frames()
    return {"scored_edges": se, "rings": rings, "truth": {777: set(inside)},
            "expected_match": (PREFIX + "inside_window", 777)}


# ============================================================================= Week 2
def loo_case() -> dict:
    """A 5-edge ring whose leave-one-out, flow and total weights are computed by hand (XR-03 / 06 / 07).

    Accounts A, B, C, D. Edges, in flow order:
        e1  A -> B   100   seed      score 0.9   at 0.0 h
        e2  B -> C    90   seed      score 0.8   at 1.0 h
        e3  C -> D    80   seed      score 0.6   at 2.0 h
        e4  A -> C    30   expanded  score 0.2   at 0.5 h   (expansion probability 0.8)
        e5  B -> D    20   member only (neither seed nor expanded)  score 0.05  at 3.0 h
    Included edges U = {e1, e2, e3, e4}. The rerun uses the `cc` grouping (connected components, min 3
    accounts), whose confidence = mean seed score x conservation closure -- computable by hand:

      roles (tau 0.25, hold 72 h): source = no inflow; sink = no outflow; mule = in/out balanced within
      25 % and passed on within 72 h; peripheral = both flows, unbalanced.
      closure = 1 - |inflow at sinks - outflow at sources| / max(those two)

      all of U : A src out 130; B mule (in 100, out 90); C peripheral (in 120, out 80); D sink in 80
                 closure = 1 - |80 - 130| / 130 = 80/130;  seeds mean (0.9+0.8+0.6)/3   -> c0
      U - e1   : B src out 90, A src out 30; C peripheral; D sink 80
                 closure = 1 - |80 - 120| / 120 = 80/120;  seeds mean (0.8+0.6)/2 = 0.7
      U - e2   : A src 130; B sink 100; C peripheral (in 30, out 80); D sink 80
                 closure = 1 - |180 - 130| / 180 = 130/180;  seeds mean 0.75  -> higher than c0, drop 0
      U - e3   : A src 130; B mule; C sink 120 -> closure 120/130; seeds mean 0.85 -> higher, drop 0
      U - e4   : chain A->B->C->D, all mules in between; closure = 1 - |80-100|/100 = 0.8;
                 seeds mean 0.7667 -> 0.6133 > c0, drop 0
    split: removing e3 cuts D off (D's only link) -> split 1; every other edge sits on the cycle A-B-C-A
           or the chain, so removing it leaves A, B, C, D connected -> split 0.
    """
    b = _Builder()
    A, B, C, D = b.accounts(4)
    b.ring("loo", "STACK", [(A, B, 100), (B, C, 90), (C, D, 80), (A, C, 30), (B, D, 20)],
           seeds=[0, 1, 2], expanded={3: 0.8}, times_h=[0.0, 1.0, 2.0, 0.5, 3.0], scores=[0.9, 0.8, 0.6, 0.2, 0.05])
    se, rings = b.frames()
    ids = dict(zip(["e1", "e2", "e3", "e4", "e5"], se["edge_id"].tolist()))
    c0 = (2.3 / 3) * (80 / 130)
    c_minus = {"e1": 0.7 * (80 / 120), "e2": 0.75 * (130 / 180), "e3": 0.85 * (120 / 130), "e4": (2.3 / 3) * 0.8}
    drop = {k: max(0.0, c0 - v) for k, v in c_minus.items()}
    split = {"e1": 0, "e2": 0, "e3": 1, "e4": 0}
    raw = {k: drop[k] + 0.5 * split[k] for k in drop}
    w_loo = {k: raw[k] / max(raw.values()) for k in raw}
    w_loo["e5"] = 0.0
    amounts = {"e1": 100, "e2": 90, "e3": 80, "e4": 30, "e5": 20}
    w_flow = {k: v / 320 for k, v in amounts.items()}
    w_score = {"e1": 0.9, "e2": 0.8, "e3": 0.6, "e4": 0.2, "e5": 0.05}
    w_total = {k: 0.4 * w_score[k] + 0.4 * w_loo[k] + 0.2 * w_flow[k] for k in w_score}
    return {"scored_edges": se, "rings": rings, "ids": ids, "c0": c0, "c_minus": c_minus, "split": split,
            "w_loo": w_loo, "w_flow": w_flow, "w_score": w_score, "w_total": w_total,
            "order": sorted(w_total, key=lambda k: -w_total[k])}


def flow_case() -> dict:
    """Duplicate-payment rule for w_flow: edges 1 and 2 are the SAME payment listed twice (same from, to,
    timestamp and amount). The total counts it once: 100 + 50 + 50 = 200, so
    w_flow = 1: 100/200, 2: 100/200, 3: 50/200, 4: 50/200 (the two copies show the same share)."""
    edges = pd.DataFrame({"edge_id": [1, 2, 3, 4], "from_id": [10, 10, 11, 12], "to_id": [11, 11, 12, 13],
                          "timestamp": [100, 100, 200, 300], "amount_received": [100.0, 100.0, 50.0, 50.0]})
    return {"edges": edges, "w_flow": {1: 0.5, 2: 0.5, 3: 0.25, 4: 0.25}}


def roles_case() -> dict:
    """One ring that contains every one of the five roles (XR-10), plus one account (X) on which the
    research-side hold-time rule and the spec section 4.3 rule disagree (XR-12).

        S -> M 100 @0h,  M -> K  98 @1h      M: balanced, passed on after 1 h          -> mule
        S -> H 100 @0h,  H -> K 100 @100h    H: balanced, held 100 h (> 72 h)            -> holder
        S -> P 100 @0h,  P -> K  50 @2h      P: in 100 / out 50, neither side dominant   -> peripheral
        S -> X 100 @0h,  X -> K  50 @1h, X -> K 50 @200h
        S: only sends -> source;  K: only receives -> sink.
    X's hold time: research rule = for each inflow, wait to the first outflow after it = 1 h -> mule;
    spec rule = for each outflow, time since the latest inflow before it = 1 h and 200 h, median 100.5 h
    -> holder. So the two implementations disagree on X only."""
    b = _Builder()
    S, K, M, H, P, X = b.accounts(6)
    b.ring("roles", "GATHER-SCATTER",
           [(S, M, 100), (M, K, 98), (S, H, 100), (H, K, 100), (S, P, 100), (P, K, 50), (S, X, 100), (X, K, 50), (X, K, 50)],
           times_h=[0, 1, 0, 100, 0, 2, 0, 1, 200])
    se, rings = b.frames()
    return {"scored_edges": se, "rings": rings,
            "research_roles": {S: "source", K: "sink", M: "mule", H: "holder", P: "peripheral", X: "mule"},
            "spec_roles": {S: "source", K: "sink", M: "mule", H: "holder", P: "peripheral", X: "holder"},
            "disagree": {X}}


def account_weight_case() -> dict:
    """w_account by hand. Member edges A->B (w_total 0.8) and B->C (w_total 0.4); across the whole test
    period A touches 4 edges, B 2, C 1.
        sum of w_total on own edges: A 0.8, B 1.2, C 0.4  -> / max 1.2  = 0.6667, 1, 0.3333
        deg_in_ring / deg_background: A 1/4, B 2/2, C 1/1 = 0.25, 1, 1
        w_account = 0.5 * first + 0.5 * second  = A 0.458333, B 1.0, C 0.666667"""
    edges = pd.DataFrame({"edge_id": [1, 2], "from_id": [100, 101], "to_id": [101, 102]})
    w_total = {1: 0.8, 2: 0.4}
    deg_background = {100: 4, 101: 2, 102: 1}
    return {"edges": edges, "w_total": w_total, "deg_background": deg_background,
            "w_account": {100: 0.5 * (0.8 / 1.2) + 0.5 * 0.25, 101: 1.0, 102: 0.5 * (0.4 / 1.2) + 0.5 * 1.0}}
