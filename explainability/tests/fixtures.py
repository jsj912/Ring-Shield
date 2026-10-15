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


# ============================================================================= currency migration
def converted_flow_case() -> pd.DataFrame:
    """Edges for the converted w_flow (XR-02). Currency 0 is the hub; currency 2 converts at the generator's
    fixed rate (contract/fx_rates.json, about 1.17178); currency 1 has NO usable rate.

        1  A -> B   100  in currency 0
        5  A -> B   100  in currency 0   (exact duplicate of 1: counted once in the total, same share)
        2  B -> C   100  in currency 2   -> 100 x rate(2) in currency 0
        3  C -> D    50  in currency 0
        4  B -> B   conversion: B changes 100 of currency 0 into currency 2 (a self-loop; never evidence)
        6  D -> E  1000  in currency 1   (only in the currency-1 variant: unconvertible -> ring is partial)
    """
    rows = [(1, 10, 11, 100, 0, 0, 100.0, 100.0, 0.9), (5, 10, 11, 100, 0, 0, 100.0, 100.0, 0.9),
            (2, 11, 12, 200, 2, 2, 100.0, 100.0, 0.8), (3, 12, 13, 300, 0, 0, 50.0, 50.0, 0.6),
            (4, 11, 11, 150, 0, 2, 100.0, 85.34, 0.01), (6, 13, 14, 400, 1, 1, 1000.0, 1000.0, 0.5)]
    return pd.DataFrame([{"edge_id": e, "from_id": f, "to_id": t, "timestamp": ts, "currency_sent": cs,
                          "currency_received": cr, "amount_sent": a_s, "amount_received": a_r,
                          "score_calibrated": s, "score_raw": s, "is_seed": s > 0.5}
                         for e, f, t, ts, cs, cr, a_s, a_r, s in rows])


def undetermined_case() -> dict:
    """A ring where one leg is in currency 1, the only currency with no recoverable rate.

        S -> M  100  currency 0  @0h      M -> K  100  currency 1  @1h
        S -> N   80  currency 0  @0h      N -> K   80  currency 0  @1h
    Under the converted policy, M (pays out in currency 1) and K (receives currency 1) touch a currency that
    cannot be converted, so their balance cannot be checked: role `undetermined` -- never `peripheral`.
    S is a source and N a mule either way. Under `raw` nobody is undetermined."""
    b = _Builder()
    S, M, N, K = b.accounts(4)
    b.ring("undetermined", "FAN-IN", [(S, M, 100), (M, K, 100), (S, N, 80), (N, K, 80)],
           currencies=[(0, 0), (1, 1), (0, 0), (0, 0)], times_h=[0, 1, 0, 1])
    se, rings = b.frames()
    return {"scored_edges": se, "rings": rings,
            "converted_roles": {S: "source", M: "undetermined", N: "mule", K: "undetermined"},
            "raw_roles": {S: "source", M: "mule", N: "mule", K: "sink"}}


# ============================================================================= Week 3 narrative
NARRATIVE_SHAPES = {
    # kind: (topology_type, edges as (from, to), roles {account: role}, closure)
    "FAN-OUT": ("FAN-OUT", [(1, 2), (1, 3), (1, 4)], {1: "source", 2: "sink", 3: "sink", 4: "sink"}, 0.96),
    "FAN-IN": ("FAN-IN", [(2, 1), (3, 1), (4, 1)], {1: "sink", 2: "source", 3: "source", 4: "source"}, 0.96),
    "GATHER-SCATTER": ("GATHER-SCATTER", [(2, 1), (3, 1), (1, 4), (1, 5)],
                       {1: "mule", 2: "source", 3: "source", 4: "sink", 5: "sink"}, 0.9),
    "SCATTER-GATHER": ("SCATTER-GATHER", [(1, 2), (1, 3), (2, 4), (3, 4)],
                       {1: "source", 2: "mule", 3: "mule", 4: "sink"}, 0.9),
    "CYCLE": ("CYCLE", [(1, 2), (2, 3), (3, 1)], {1: "mule", 2: "mule", 3: "mule"}, math.nan),
    "STACK": ("STACK", [(1, 2), (2, 3), (3, 4)], {1: "source", 2: "mule", 3: "holder", 4: "sink"}, 0.8),
    "BIPARTITE": ("BIPARTITE", [(1, 2), (3, 4)], {1: "source", 2: "sink", 3: "source", 4: "sink"}, 1.0),
    "RANDOM": ("RANDOM", [(1, 2), (2, 3), (1, 3), (3, 4)], {1: "source", 2: "peripheral", 3: "mule", 4: "sink"}, 0.5),
    "UNKNOWN": ("UNKNOWN", [(1, 2), (1, 3), (1, 4)], {1: "source", 2: "sink", 3: "sink", 4: "sink"}, 0.96),
}
NARRATIVE_FX = {"rate_to_ccy0": {0: 1.0, 1: None, 2: 1.17178}, "unconvertible": {1}, "hub": 0}
NARRATIVE_FEATURES = [{"feature_name": "Payment Format", "mean_shap": 2.5, "top_edge_id": 1},
                      {"feature_name": "scatter_gather", "mean_shap": 1.4, "top_edge_id": 1},
                      {"feature_name": "hour_of_day", "mean_shap": -1.1, "top_edge_id": 2}]


def narrative_case(kind: str, *, banks: dict | None = None, currencies: dict | None = None,
                   partial: bool = False, p: float | None = 0.65, features: bool = True, names: dict | None = None) -> dict:
    """Keyword arguments for `narrative.narrative_values` describing a tiny ring of one shape.

    Edge i (1-based, in the order listed) carries amount 1000 * i in currency 0 (or `currencies[i]`) and
    w_total 1 - i/10, so the strongest edge is the first one. Accounts weigh 1 / id (smaller id first).
    The ring spans 6 hours; every account is at bank 1 unless `banks` says otherwise; mules held 5 h. Every payment
    is ACH (payment format 3) and sent in the currency it is received in. `names`: the code -> name maps."""
    ttype, pairs, roles, closure = NARRATIVE_SHAPES[kind]
    currencies, banks = currencies or {}, banks or {}
    edges = pd.DataFrame([{"edge_id": i, "from_id": a, "to_id": b, "amount_received": 1000.0 * i,
                           "currency_received": currencies.get(i, 0), "currency_sent": currencies.get(i, 0),
                           "payment_format": 3,
                           "from_bank": banks.get(a, 1), "to_bank": banks.get(b, 1)}
                          for i, (a, b) in enumerate(pairs, start=1)])
    rate = NARRATIVE_FX["rate_to_ccy0"]
    convertible = edges[edges["currency_received"].map(rate).notna()]
    total = float((convertible["amount_received"] * convertible["currency_received"].map(rate)).sum())
    return {"topology_type": ttype, "topology_prob": p, "type_source": "rings", "duration_s": 6 * 3600.0,
            "evidence": edges, "member_edges": edges,
            "edge_weights": [{"edge_id": i, "w_total": 1 - i / 10} for i in edges["edge_id"]],
            "account_weights": [{"account_id": a, "role": r, "w_account": 1 / a,
                                 "hold_time_s": 5 * 3600.0 if r in ("mule", "holder") else math.nan}
                                for a, r in sorted(roles.items())],
            "flow": {"total_ccy0": total, "partial": partial},
            "conservation": {"closure": closure, "unconvertible": partial}, "closure_raw": closure,
            "feature_weights": NARRATIVE_FEATURES if features else [], "fx": NARRATIVE_FX,
            "n_top_edges": 3, "n_top_features": 3, "names": names}


# ============================================================================= Week 4
def expanded_case() -> dict:
    """XR-23 by hand. A chain A->B->C->D->E->F: flows 0, 1 are seeds; 2, 3, 4 were added by the expansion.
    The truth ring is flows 0-3 (flow 4 is a wrong addition).
        X (expanded, in window)      = {e2, e3, e4};  true expanded X & T = {e2, e3};  precision 2/3
        our order (given)            = e2, e0, e3, e1, e4      -> (b) recall@3 = 2 / min(3, 2) = 1
        score order (seeds first)    = e0, e1, e2, e3, e4      -> (b) recall@3 = 1 / 2 = 0.5;  @5 = 1
        (c) rank X alone vs T's non-seed edges {e2, e3}: both orders put e2, e3 first -> 1 at every k;
            it discriminates (2 of the 3 expanded edges are true)."""
    b = _Builder()
    a = b.accounts(6)
    b.ring("chain", "STACK", [(a[i], a[i + 1], 100 - i) for i in range(5)], seeds=[0, 1],
           expanded={2: 0.8, 3: 0.7, 4: 0.6})
    se, rings = b.frames()
    e = [int(x) for x in rings.iloc[0]["member_edges"]]
    return {"scored_edges": se, "rings": rings, "truth_accounts": {777: set(a)}, "truth_edges": {777: set(e[:4])},
            "order": [e[2], e[0], e[3], e[1], e[4]], "edges": e}
