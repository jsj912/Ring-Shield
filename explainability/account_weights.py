"""Account weights and roles of a ring (spec sections 4.2 / 4.3, as amended by the Reality Check).

    roles = research_roles(ring, scored_edges)              # authoritative: ringshield.roles.account_roles
    deg   = background_degree(scored_edges)                 # edges per account over the whole test period
    A     = account_weight_table(ring.members, member_edges, edge_table, deg, roles, shares)
    spec  = spec_roles(included_edges, roles_cfg)           # spec 4.3 rule, comparison only (XR-12)
    log   = role_disagreements(ring_id, roles, spec)

Roles (source / sink / mule / holder / peripheral), inflow, outflow and hold time come from the research
side's `account_roles(edges="included")` -- the Reality Check makes that version authoritative, and it is
the one that produced the contract's source/sink/mule arrays. The spec's own rule is implemented here only
to log where the two disagree; it is never used in an explanation.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ringshield.roles import account_roles, dedup_edges

ACCOUNT_WEIGHT_COLUMNS = ["account_id", "role", "inflow", "outflow", "hold_time_s", "w_account"]
DISAGREEMENT_COLUMNS = ["ring_id", "account_id", "research_role", "spec_role", "research_hold_s", "spec_hold_s",
                        "inflow", "outflow", "cause"]


# ----------------------------------------------------------------------------- roles (research, authoritative)
def research_roles(ring, scored_edges: pd.DataFrame, currency: str = "raw") -> dict[int, dict]:
    """{account: {role, inflow, outflow, hold_time_s, closure, n_in, n_out, ...}} over the ring's included edges.

    currency "raw"        Weeks 1-2: amounts summed across currency codes (the shipped convention).
    currency "converted"  each leg booked on its own side (sender: amount_sent / currency_sent, receiver:
                          amount_received / currency_received), both converted to currency 0 with the
                          generator's fixed rates. Adds a sixth role, `undetermined`, ONLY for an account
                          touching a currency with no usable rate (currency 1); inflow / outflow are then in
                          currency 0."""
    return account_roles(ring, scored_edges, edges="included", currency=currency)


# ----------------------------------------------------------------------------- degrees
def _incident_counts(from_ids: np.ndarray, to_ids: np.ndarray) -> pd.Series:
    """How many edges touch each account (an edge from an account to itself counts once)."""
    f, t = np.asarray(from_ids, np.int64), np.asarray(to_ids, np.int64)
    s = pd.Series(np.concatenate([f, t[t != f]])).value_counts()
    s.index = s.index.astype(np.int64)
    return s


def background_degree(scored_edges: pd.DataFrame, exclude_conversions: bool = False) -> pd.Series:
    """Edges touching each account across the whole test period (the denominator of the degree ratio).
    With `exclude_conversions` (policy converted) an account changing its own money is not counted as
    activity, the same rule the in-ring count uses, so the ratio compares like with like."""
    se = scored_edges
    if exclude_conversions:
        se = se[se["currency_sent"] == se["currency_received"]]
    return _incident_counts(se["from_id"].to_numpy(), se["to_id"].to_numpy())


# ----------------------------------------------------------------------------- w_account
def account_weight_table(members, member_edges: pd.DataFrame, edge_table: pd.DataFrame, deg_background,
                         roles: dict | None, *, score_share: float = 0.5, degree_share: float = 0.5) -> pd.DataFrame:
    """One row per member account, sorted by w_account (high first), then account id.

        sum_w(a)        = sum of w_total over the member edges touching a
        deg_in_ring(a)  = number of member edges touching a
        deg_background  = number of test-period edges touching a
        w_account(a)    = score_share * sum_w(a) / max_a sum_w  +  degree_share * deg_in_ring(a) / deg_background(a)

    The second term is high for an account that is busy inside the ring and quiet outside it."""
    e = member_edges                    # the evidence edges of the ring (conversions already removed under `converted`)
    f, t = e["from_id"].to_numpy(np.int64), e["to_id"].to_numpy(np.int64)
    wt = pd.Series(edge_table.set_index("edge_id")["w_total"]).reindex(e["edge_id"].to_numpy(np.int64)).fillna(0.0).to_numpy(float)
    sum_w = pd.Series(np.concatenate([wt, wt[t != f]]), index=np.concatenate([f, t[t != f]])).groupby(level=0).sum()
    deg_ring = _incident_counts(f, t)
    deg_bg = pd.Series(deg_background)
    rows = []
    mx = float(sum_w.max()) if len(sum_w) else 0.0
    for a in sorted(int(x) for x in members):
        r = (roles or {}).get(a, {})
        dr, db = int(deg_ring.get(a, 0)), int(deg_bg.get(a, 0))
        sw = float(sum_w.get(a, 0.0))
        w = score_share * (sw / mx if mx > 0 else 0.0) + degree_share * (dr / db if db > 0 else 0.0)
        rows.append({"account_id": a, "role": r.get("role"), "inflow": float(r.get("inflow", math.nan)),
                     "outflow": float(r.get("outflow", math.nan)), "hold_time_s": float(r.get("hold_time_s", math.nan)),
                     "w_account": w, "sum_w_total": sw, "deg_in_ring": dr, "deg_background": db})
    out = pd.DataFrame(rows)
    return out.sort_values(["w_account", "account_id"], ascending=[False, True], kind="stable").reset_index(drop=True)


# ----------------------------------------------------------------------------- spec 4.3 rule (comparison only)
def _spec_hold_time(ts_in: np.ndarray, ts_out: np.ndarray) -> float:
    """Spec: median over OUTGOING edges of (t_out - time of the latest incoming edge at or before t_out).
    NaN when no outflow has an earlier inflow (e.g. a pure source)."""
    if len(ts_in) == 0 or len(ts_out) == 0:
        return math.nan
    ins = np.sort(ts_in)
    j = np.searchsorted(ins, ts_out, side="right") - 1
    ok = j >= 0
    if not ok.any():
        return math.nan
    return float(np.median(ts_out[ok] - ins[j[ok]]))


def spec_roles(edges: pd.DataFrame, roles_cfg: dict) -> dict[int, dict]:
    """Spec 4.3 roles over `edges` (deduplicated exactly as the research side does, so that any difference
    comes from the rule, not the data):
        source     outflow > 0 and inflow < tau * outflow
        sink       inflow > 0 and outflow < tau * inflow
        mule       |inflow - outflow| <= tau * max(inflow, outflow) and hold_time <= hold
        holder     same balance test, hold_time > hold
        peripheral anything else (including a balanced account whose hold time is undefined)"""
    tau, hold = float(roles_cfg["tau_role"]), float(roles_cfg["hold_seconds"])
    e = dedup_edges(edges, "amount_received")
    out = {}
    for a in sorted(set(e["from_id"].astype(int)) | set(e["to_id"].astype(int))):
        inc, outg = e[e["to_id"] == a], e[e["from_id"] == a]
        i, o = float(inc["amount_received"].sum()), float(outg["amount_received"].sum())
        h = _spec_hold_time(inc["timestamp"].to_numpy(np.int64), outg["timestamp"].to_numpy(np.int64))
        if o > 0 and i < tau * o:
            role = "source"
        elif i > 0 and o < tau * i:
            role = "sink"
        elif abs(i - o) <= tau * max(i, o) and not math.isnan(h):
            role = "mule" if h <= hold else "holder"
        else:
            role = "peripheral"
        out[a] = {"role": role, "inflow": i, "outflow": o, "hold_time_s": h}
    return out


def role_disagreements(ring_id: str, research: dict[int, dict], spec: dict[int, dict]) -> pd.DataFrame:
    """One row per account whose spec role differs from the research role, with the likely cause:
        hold_time_definition  both see a balanced account (mule/holder) but the two hold-time rules land on
                              opposite sides of 72 h
        undefined_hold_time   one rule has no hold time for the account (NaN) and therefore decides differently
        rule_order            anything else (the two rule lists test conditions in a different order)"""
    rows = []
    for a in sorted(set(research) | set(spec)):
        r, s = research.get(a, {}), spec.get(a, {})
        if r.get("role") == s.get("role"):
            continue
        rh, sh = float(r.get("hold_time_s", math.nan)), float(s.get("hold_time_s", math.nan))
        if {r.get("role"), s.get("role")} <= {"mule", "holder"}:
            cause = "hold_time_definition"
        elif math.isnan(rh) or math.isnan(sh):
            cause = "undefined_hold_time"
        else:
            cause = "rule_order"
        rows.append({"ring_id": ring_id, "account_id": a, "research_role": r.get("role"), "spec_role": s.get("role"),
                     "research_hold_s": rh, "spec_hold_s": sh, "inflow": float(r.get("inflow", s.get("inflow", math.nan))),
                     "outflow": float(r.get("outflow", s.get("outflow", math.nan))), "cause": cause})
    return pd.DataFrame(rows, columns=DISAGREEMENT_COLUMNS)
