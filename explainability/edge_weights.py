"""Edge weights of a ring (spec section 4.1, as amended by the Reality Check).

    w = w_score(edges)                                  # detector's calibrated score
    f = w_flow(member_edges, "amount_received")         # share of the ring's money
    L = w_loo(included_edges, make_rerunner, ...)       # leave-one-out: what happens to the ring without it
    T = edge_weight_table(member_edges, L, mixing)      # w_total = a*w_score + b*w_loo + g*w_flow, sorted

Every function is deterministic. A ranking is any `edges -> list of edge ids`; evaluate.py scores them.

Leave-one-out goes through the research side's `ringshield.roles.RingRerunner` only (XR-06): one
rerunner per ring, built over the ring's INCLUDED edges (seeds + expanded), with the same GFP features,
embeddings and affinity model the rings were built with, so `features_degraded` is False. That setup
reproduces every shipped seed-1 ring exactly (checked in the tests for all five seeds).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yaml

from explainability.contract_io import repo_path

EDGE_WEIGHT_COLUMNS = ["edge_id", "w_total", "w_score", "w_loo", "w_flow"]
POLICIES = ("converted", "raw")


# ----------------------------------------------------------------------------- currency conversions
def conversion_mask(scored_edges: pd.DataFrame) -> pd.Series:
    """True for a currency CONVERSION: an edge whose sent and received currencies differ. In AMLworld every
    such edge among ring members is an account changing its own money (a self-loop, from_id == to_id);
    0 of 72,170 is ever laundering and no truth ring contains one. Indexed by edge_id."""
    se = scored_edges.reset_index() if scored_edges.index.name == "edge_id" else scored_edges
    return pd.Series((se["currency_sent"] != se["currency_received"]).to_numpy(bool),
                     index=se["edge_id"].to_numpy(np.int64), name="is_conversion")


def evidence_edge_ids(edge_ids, conversions: pd.Series, policy: str) -> tuple[list[int], int]:
    """(edges that may serve as evidence, how many conversions were dropped).
    policy `converted`: conversions are dropped; `raw`: every edge kept (reproduces Weeks 1-2)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown currency policy {policy!r}; choose from {POLICIES}")
    ids = [int(e) for e in edge_ids]
    if policy == "raw":
        return ids, 0
    flags = conversions.reindex(ids).fillna(False).to_numpy(bool)
    return [e for e, f in zip(ids, flags) if not f], int(flags.sum())


# ----------------------------------------------------------------------------- w_score + Week 1 ranking
def w_score(edges: pd.DataFrame) -> pd.Series:
    """The detector's calibrated probability, as stored in scored_edges. Expanded (quiet) edges are
    usually low here by construction -- that is what w_loo and w_flow exist to compensate for."""
    return edges.set_index("edge_id")["score_calibrated"].astype(float)


def _score_order_keys(edges: pd.DataFrame):
    cal = edges["score_calibrated"].to_numpy(float)
    raw = edges["score_raw"].to_numpy(float)
    return np.where(np.isnan(cal), -np.inf, cal), np.where(np.isnan(raw), -np.inf, raw)


def rank_by_score(edges: pd.DataFrame) -> list[int]:
    """Edge ids sorted by score_calibrated (high first), then score_raw (high first), then edge_id
    (low first). Missing scores sort last.

    The two tie-breaks matter: isotonic calibration maps ~800k distinct raw scores onto ~100 levels,
    so many edges share a calibrated score. score_raw is the uncalibrated score those levels came
    from (same order, finer), and edge_id makes the order total, so two runs always agree."""
    cal, raw = _score_order_keys(edges)
    eid = edges["edge_id"].to_numpy(np.int64)
    order = np.lexsort((eid, -raw, -cal))         # last key is the primary one
    return [int(e) for e in eid[order]]


# ----------------------------------------------------------------------------- w_flow
def w_flow(member_edges: pd.DataFrame, amount_col: str = "amount_received") -> pd.Series:
    """Share of the ring's money carried by each edge: amount / total over the ring's member edges.

    Duplicate payments (same from, to, timestamp, amount) are counted ONCE in the total; every copy shows
    the same share. Amounts are summed raw across currencies (config amounts.currency_policy: raw,
    provisional -- the same convention as the shipped roles and conservation closure)."""
    e = member_edges
    amt = e[amount_col].astype(float)
    dup = e.duplicated(["from_id", "to_id", "timestamp", amount_col])
    total = float(amt[~dup].sum())
    share = amt / total if total > 0 else amt * 0.0
    return pd.Series(share.to_numpy(float), index=e["edge_id"].to_numpy(np.int64), name="w_flow")


def load_fx(cfg: dict) -> dict:
    """The research side's exchange-rate table (contract/fx_rates.json, read through ringshield.roles):
    {"rate_to_ccy0": {currency: rate or None}, "unconvertible": {1}, "hub": 0, "meta": {...}}."""
    from ringshield.roles import load_fx_rates
    return load_fx_rates(repo_path(cfg["amounts"]["fx_rates"]))


def w_flow_converted(edges: pd.DataFrame, fx: dict, amount_col: str = "amount_received") -> tuple[pd.Series, dict]:
    """Share of the ring's money in ONE unit (XR-02): each edge's amount converted to currency 0 with the
    generator's fixed rates, divided by the ring's converted total.

        value(e) = amount_received(e) x rate_to_ccy0[currency_received(e)]
        w_flow(e) = value(e) / sum of value over the ring's convertible edges   (duplicates counted once)

    `edges` must be evidence edges -- currency conversions already removed (refused otherwise). An edge in a
    currency with no usable rate (currency 1) is left out of the total and gets w_flow 0, and the ring is
    flagged `partial`: its shares sum to 1 over the convertible edges only. Returns (shares, info)."""
    e = edges
    if (e["currency_sent"] != e["currency_received"]).any():
        raise ValueError("w_flow_converted: currency conversions must be removed before computing flow shares")
    table = fx["rate_to_ccy0"]
    rate = e["currency_received"].map(lambda c: table.get(int(c))).astype(float)    # None -> NaN
    value = e[amount_col].astype(float) * rate
    ok = rate.notna()
    dup = e.duplicated(["from_id", "to_id", "timestamp", amount_col])
    total = float(value[ok & ~dup].sum())
    share = (value / total).where(ok, 0.0) if total > 0 else value * 0.0
    info = {"partial": bool((~ok).any()), "n_unconvertible_edges": int((~ok).sum()), "total_ccy0": total,
            "currency": int(fx["hub"])}
    return pd.Series(share.fillna(0.0).to_numpy(float), index=e["edge_id"].to_numpy(np.int64), name="w_flow"), info


# ----------------------------------------------------------------------------- research inputs for the rerun
@dataclass
class LooInputs:
    """Everything RingRerunner needs to group a ring exactly as the aggregator did."""
    aggregator_id: str
    min_size: int
    cut: float = 0.5
    method: str = "average"
    affinity: object = None
    gfp: pd.DataFrame | None = None
    emb: object = None
    params: dict = field(default_factory=dict)      # recorded in provenance

    def rerunner(self, included_edges: pd.DataFrame):
        from ringshield.roles import RingRerunner
        kw = {}
        if self.aggregator_id == "full":
            kw = dict(affinity=self.affinity, cut=self.cut, method=self.method, gfp=self.gfp, emb=self.emb)
        rr = RingRerunner(included_edges, self.aggregator_id, min_size=self.min_size, **kw)
        if rr.features_degraded:
            raise RuntimeError("RingRerunner reports features_degraded=True: GFP or embeddings missing; "
                               "leave-one-out weights would not be comparable with the shipped rings")
        return rr


def load_loo_inputs(cfg: dict, seed: int, aggregator_id: str, rings_path, edge_ids, split: str = "test") -> LooInputs:
    """Load the rerun inputs for one detector seed, restricted to `edge_ids` (the rings' included edges).
    `split` picks the GFP / embedding files of that split (test, or val for the XR-05 tuning)."""
    ri = dict(cfg["research_inputs"])
    if split == "val":
        ri["gfp"], ri["embeddings"] = ri["gfp_val"], ri["embeddings_val"]
    elif split != "test":
        raise ValueError(f"unknown split {split!r}")
    if aggregator_id == "cc":
        rp = repo_path(rings_path)
        log_path = rp.with_name(rp.name + ".log.json")
        ms = int(json.loads(log_path.read_text(encoding="utf-8"))["params"]["min_size"])
        return LooInputs("cc", ms, params={"aggregator_id": "cc", "min_size": ms, "source": log_path.name})
    if aggregator_id != "full":
        raise ValueError(f"no leave-one-out inputs defined for aggregator {aggregator_id!r}")
    from ringshield.expand.features import EmbeddingStore
    from ringshield.partition.affinity import Affinity
    part_cfg_path = ri["partition_config"].format(seed=seed)
    chosen = yaml.safe_load(repo_path(part_cfg_path).read_text(encoding="utf-8"))["chosen"]
    ids = sorted({int(e) for e in edge_ids})
    gfp = pd.read_parquet(repo_path(ri["gfp"]), filters=[("EdgeID", "in", ids)])
    emb_path = ri["embeddings"].format(seed=seed)
    embdf = pd.read_parquet(repo_path(emb_path), filters=[("edge_id", "in", ids)])
    emb = EmbeddingStore(embdf["edge_id"].to_numpy(np.int64),
                         embdf[[c for c in embdf.columns if c.startswith("emb_")]].to_numpy(np.float32))
    params = {"aggregator_id": "full", "min_size": int(chosen["min_size"]), "cut": float(chosen["cut"]),
              "method": str(chosen["method"]), "partition_config": part_cfg_path, "affinity_dir": ri["affinity_dir"],
              "gfp": ri["gfp"], "embeddings": emb_path}
    return LooInputs("full", int(chosen["min_size"]), float(chosen["cut"]), str(chosen["method"]),
                     Affinity.load(repo_path(ri["affinity_dir"])), gfp, emb, params)


# ----------------------------------------------------------------------------- w_loo + split
def _n_components(n_nodes: int, a: np.ndarray, b: np.ndarray) -> int:
    parent = list(range(n_nodes))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for x, y in zip(a.tolist(), b.tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)
    return len({find(i) for i in range(n_nodes)})


def split_flags(edges: pd.DataFrame) -> pd.Series:
    """split(e) = 1 when removing e breaks the ring's accounts into more pieces (payments read as
    undirected links between accounts; the set of accounts stays fixed). Graph-theory name: a bridge."""
    accounts, inv = np.unique(np.concatenate([edges["from_id"].to_numpy(np.int64), edges["to_id"].to_numpy(np.int64)]),
                              return_inverse=True)
    n = len(edges)
    a, b = inv[:n], inv[n:]
    base = _n_components(len(accounts), a, b)
    keep = np.ones(n, bool)
    out = []
    for i in range(n):
        keep[i] = False
        out.append(int(_n_components(len(accounts), a[keep], b[keep]) > base))
        keep[i] = True
    return pd.Series(out, index=edges["edge_id"].to_numpy(np.int64), name="split")


def w_loo(included_edges: pd.DataFrame, make_rerunner, *, lambda_split: float, nan_policy: str = "full_loss") -> pd.DataFrame:
    """Leave-one-out contribution of each INCLUDED edge (seed or expanded).

        c0      = confidence of the ring as the aggregator groups it        (1 rerunner call)
        c_minus = confidence of the largest ring left without edge e        (1 call per edge)
        drop    = max(0, c0 - c_minus);  NaN c_minus (no ring left) -> drop = c0  ("full_loss")
        raw     = drop + lambda_split * split(e)
        w_loo   = raw / max(raw over the ring's edges)   (all 0 if the max is 0)

    Returns one row per included edge: edge_id, c0, c_minus, drop, split, raw, w_loo, n_rings_without,
    plus two constant columns about the base run: base_n_rings and base_is_input (did the rerun group the
    ring's edges back into exactly one ring made of all of them -- i.e. reproduce the ring)."""
    if nan_policy != "full_loss":
        raise ValueError(f"unknown loo_nan_policy {nan_policy!r}")
    edges = included_edges.sort_values("edge_id").reset_index(drop=True)
    rr = make_rerunner(edges)
    base = rr.run()
    c0 = float(base["confidence"])
    base_is_input = int(base["n_rings"]) == 1 and list(base["largest_ring_edges"]) == edges["edge_id"].astype(int).tolist()
    splits = split_flags(edges)
    rows = []
    for e in edges["edge_id"].astype(int).tolist():
        out = rr.without(e)
        cm = float(out["confidence"])
        if math.isnan(c0):
            drop = 0.0
        elif math.isnan(cm):
            drop = c0
        else:
            drop = max(0.0, c0 - cm)
        rows.append({"edge_id": e, "c0": c0, "c_minus": cm, "drop": drop, "split": int(splits.loc[e]),
                     "raw": drop + lambda_split * int(splits.loc[e]), "n_rings_without": int(out["n_rings"]),
                     "base_n_rings": int(base["n_rings"]), "base_is_input": base_is_input})
    t = pd.DataFrame(rows)
    mx = float(t["raw"].max()) if len(t) else 0.0
    t["w_loo"] = t["raw"] / mx if mx > 0 else 0.0
    return t


# ----------------------------------------------------------------------------- w_total
def check_mixing(mixing: dict, tol: float) -> tuple[float, float, float]:
    a, b, g = float(mixing["alpha"]), float(mixing["beta"]), float(mixing["gamma"])
    if min(a, b, g) < 0 or abs(a + b + g - 1.0) > tol:
        raise ValueError(f"mixing weights must be >= 0 and sum to 1, got alpha={a} beta={b} gamma={g}")
    return a, b, g


def edge_weight_table(member_edges: pd.DataFrame, loo: pd.DataFrame, mixing: dict, *, amount_col: str = "amount_received",
                      tol: float = 1e-9, policy: str = "raw", fx: dict | None = None) -> pd.DataFrame:
    """One row per EVIDENCE edge: edge_id, w_total, w_score, w_loo, w_flow (plus split, included).
    Member edges that are not included (not seed, not expanded) get w_loo = 0 and split = 0: the grouping
    never used them, so removing one cannot change the ring. Sorted by w_total (high first), then by the
    Week 1 score tie-breaks, so the order is total and repeatable.

    policy `raw` (Weeks 1-2, reproduced exactly): every member edge; w_flow over raw cross-currency sums.
    policy `converted`: currency conversions are dropped (they are never laundering); w_flow is the converted
    share (w_flow_converted); w_loo is re-scaled so the top RANKED edge gets 1 (a conversion the aggregator used
    stays in the leave-one-out rerun but is never ranked). The table's `attrs` carry `n_conversions_dropped`
    and `flow` (partial flag, unconvertible edges, total in currency 0)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown currency policy {policy!r}; choose from {POLICIES}")
    a, b, g = check_mixing(mixing, tol)
    e = member_edges.sort_values("edge_id").reset_index(drop=True)
    L = loo.set_index("edge_id")
    n_conv, flow_info = 0, None
    if policy == "converted":
        is_conv = (e["currency_sent"] != e["currency_received"]).to_numpy(bool)
        n_conv = int(is_conv.sum())
        e = e[~is_conv].reset_index(drop=True)
        if fx is None:
            raise ValueError("policy 'converted' needs the exchange-rate table (fx)")
    ids = e["edge_id"].to_numpy(np.int64)
    ws = e["score_calibrated"].fillna(0.0).to_numpy(float)
    if policy == "raw":
        wf = w_flow(e, amount_col).reindex(ids).to_numpy(float)
        wl = L["w_loo"].reindex(ids).fillna(0.0).to_numpy(float)
    else:
        shares, flow_info = w_flow_converted(e, fx, amount_col)
        wf = shares.reindex(ids).to_numpy(float)
        loo_raw = L["raw"].reindex(ids).fillna(0.0).to_numpy(float) if len(L) else np.zeros(len(ids))
        mx = float(loo_raw.max()) if len(loo_raw) else 0.0
        wl = loo_raw / mx if mx > 0 else np.zeros(len(ids))
    sp = L["split"].reindex(ids).fillna(0).astype(int).to_numpy()
    inc = np.isin(ids, L.index.to_numpy(np.int64))
    wt = a * ws + b * wl + g * wf
    cal, raw = _score_order_keys(e)
    order = np.lexsort((ids, -raw, -cal, -wt))
    out = pd.DataFrame({"edge_id": ids, "w_total": wt, "w_score": ws, "w_loo": wl, "w_flow": wf,
                        "split": sp, "included": inc})
    out = out.iloc[order].reset_index(drop=True)
    out.attrs.update({"policy": policy, "n_conversions_dropped": n_conv, "flow": flow_info})
    return out


def rank_by_w_total(table: pd.DataFrame) -> list[int]:
    """The edge_weight_table order (already sorted)."""
    return [int(x) for x in table["edge_id"]]
