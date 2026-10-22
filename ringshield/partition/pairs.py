"""Shared-account pairs of included edges inside expanded components, with their features (Step 7.1).

    comp = components_of(idx, inc_pos)                       # component id per included edge
    P = pair_features(idx, gfp, inc_pos, is_seed, comp, emb_of=...)

Included edges = seeds + expanded edges of one split. A pair is two included edges of the same
component that share an account; the earlier edge (by timestamp, then edge id) is `a`, the later
`b`. One row per (pair, shared account) -- two parallel edges between the same two accounts share
both endpoints and give two rows, one per account.

Features (PAIR_FEATURES):
    time_gap_s          t_b - t_a
    amount_ratio        min / max of the two amounts
    dir_in_out, dir_out_out, dir_in_in, dir_out_in     direction of a then b at the shared account
    cos_emb             cosine of the two head-input embeddings (NaN if unavailable)
    cos_gfp             cosine of the two log1p GFP vectors (0 when either is all zero)
    kind_seed_seed, kind_seed_exp, kind_exp_exp
    role_source, role_sink, role_mule, role_other      shared-account role over the component's included
                        edges at that account: mule if both flows, closure >= 1 - TAU_ROLE and an inflow is
                        followed by an outflow within HOLD_S; source if inflow / outflow < TAU_ROLE (or no
                        inflow); sink if outflow / inflow < TAU_ROLE (or no outflow); other = both flows,
                        unbalanced and/or not held (hub-like)
    acc_closure         min / max of the included inflow and outflow sums at the shared account (0 if one-sided)
    acc_n_included      number of included edges at the shared account (in this component)
    acc_n_counterparties  distinct counterparties among them
    acc_log_degree_window log1p of the account's stream events inside the component's time window
                        [min included time, max included time] -- the hub signal
    on_chain            a is an inflow to the account, b an outflow from it, 0 <= t_b - t_a <= HOLD_S and
                        amount_ratio >= 1 - TAU_ROLE

Label (train only): 1 if both edges carry the same ring_id > 0, else 0; grouped by component.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from ringshield.expand.index import SplitIndex

TAU_ROLE = 0.25
HOLD_S = 72 * 3600
PAIR_FEATURES = ["time_gap_s", "amount_ratio", "dir_in_out", "dir_out_out", "dir_in_in", "dir_out_in", "cos_emb", "cos_gfp",
                 "kind_seed_seed", "kind_seed_exp", "kind_exp_exp", "role_source", "role_sink", "role_mule", "role_other",
                 "acc_closure", "acc_n_included", "acc_n_counterparties", "acc_log_degree_window", "on_chain"]
KEY_COLUMNS = ["component", "edge_a", "edge_b", "shared_account"]
FEATURE_GROUPS = {"timing": ["time_gap_s"], "amount": ["amount_ratio", "on_chain"],
                  "direction": ["dir_in_out", "dir_out_out", "dir_in_in", "dir_out_in"],
                  "embedding": ["cos_emb"], "gfp": ["cos_gfp"], "kind": ["kind_seed_seed", "kind_seed_exp", "kind_exp_exp"],
                  "role": ["role_source", "role_sink", "role_mule", "role_other", "acc_closure", "acc_n_included",
                           "acc_n_counterparties", "acc_log_degree_window"]}


def components_of(idx: SplitIndex, inc_pos: np.ndarray) -> np.ndarray:
    """Connected-component id (0..k-1, by smallest member account) of each included edge in the
    account graph of the included edges. Pure numpy union-find, deterministic."""
    f, t = idx.from_dense[inc_pos], idx.to_dense[inc_pos]
    nodes, inv = np.unique(np.concatenate([f, t]), return_inverse=True)
    fi, ti = inv[:len(f)], inv[len(f):]
    parent = np.arange(len(nodes))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in zip(fi.tolist(), ti.tolist()):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(i) for i in range(len(nodes))])
    _, comp = np.unique(roots, return_inverse=True)
    return comp[fi]


def _cos_rows(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    na, nb = np.linalg.norm(A, axis=1), np.linalg.norm(B, axis=1)
    den = na * nb
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, (A * B).sum(axis=1) / np.where(den > 0, den, 1.0), 0.0)


def account_roles(idx: SplitIndex, inc_pos: np.ndarray, comp: np.ndarray) -> pd.DataFrame:
    """Per (component, dense account) with >= 1 included edge: in / out sums and counts, closure,
    counterparties, held flag, window degree and the role."""
    f, t, ts, amt = idx.from_dense[inc_pos], idx.to_dense[inc_pos], idx.ts[inc_pos], idx.amount[inc_pos]
    ev = pd.DataFrame({"comp": np.concatenate([comp, comp]), "acc": np.concatenate([f, t]),
                       "other": np.concatenate([t, f]), "ts": np.concatenate([ts, ts]), "amt": np.concatenate([amt, amt]),
                       "is_out": np.concatenate([np.ones(len(f), bool), np.zeros(len(f), bool)])})
    # numpy aggregation over the (component, account) groups: the equivalent groupby.agg on these
    # tiny frames cost more than everything else in rerun_ring's 50 ms budget
    from ringshield.roles import next_outflow_gaps
    comp_a = ev["comp"].to_numpy(np.int64)
    acc_a = ev["acc"].to_numpy(np.int64)
    other_a = ev["other"].to_numpy(np.int64)
    ts_all = ev["ts"].to_numpy(np.int64)
    amt_a = ev["amt"].to_numpy(float)
    is_out = ev["is_out"].to_numpy().astype(bool)
    span_acc = int(acc_a.max()) + 2 if len(acc_a) else 2
    grp = comp_a * span_acc + acc_a
    keys, gidx = np.unique(grp, return_inverse=True)
    n_groups = len(keys)
    in_sum = np.bincount(gidx, weights=np.where(is_out, 0.0, amt_a), minlength=n_groups)
    out_sum = np.bincount(gidx, weights=np.where(is_out, amt_a, 0.0), minlength=n_groups)
    n_included = np.bincount(gidx, minlength=n_groups)
    pair_keys = np.unique(gidx.astype(np.int64) * (int(other_a.max()) + 2 if len(other_a) else 2) + other_a)
    n_counterparties = np.bincount(pair_keys // (int(other_a.max()) + 2 if len(other_a) else 2), minlength=n_groups)
    # held: some inflow is followed by an outflow at the same (component, account) within HOLD_S
    gaps = next_outflow_gaps(grp[~is_out], ts_all[~is_out], grp[is_out], ts_all[is_out])
    held_groups = np.unique(grp[~is_out][(~np.isnan(gaps)) & (np.nan_to_num(gaps, nan=np.inf) <= HOLD_S)])
    out = pd.DataFrame({"in_sum": in_sum, "out_sum": out_sum, "n_included": n_included,
                        "n_counterparties": n_counterparties, "held": np.isin(keys, held_groups)},
                       index=pd.MultiIndex.from_arrays([keys // span_acc, keys % span_acc], names=["comp", "acc"]))
    hi = np.maximum(in_sum, out_sum)
    out["closure"] = np.where(hi > 0, np.minimum(in_sum, out_sum) / np.where(hi > 0, hi, 1), 0.0)
    i, o = in_sum, out_sum
    with np.errstate(divide="ignore", invalid="ignore"):
        in_over_out = np.where(o > 0, i / np.where(o > 0, o, 1), np.inf)
        out_over_in = np.where(i > 0, o / np.where(i > 0, i, 1), np.inf)
    mule = (i > 0) & (o > 0) & (out["closure"].to_numpy() >= 1 - TAU_ROLE) & out["held"].to_numpy()
    source = ~mule & (o > 0) & (in_over_out < TAU_ROLE)
    sink = ~mule & (i > 0) & (out_over_in < TAU_ROLE)
    role = np.where(mule, "mule", np.where(source, "source", np.where(sink, "sink", "other")))
    out["role"] = role
    # window degree: stream events at the account inside the component's included time span
    n_comp = int(comp.max()) + 1 if len(comp) else 0
    lo_ts = np.full(n_comp, np.iinfo(np.int64).max, dtype=np.int64)
    hi_ts = np.full(n_comp, np.iinfo(np.int64).min, dtype=np.int64)
    np.minimum.at(lo_ts, comp, ts)
    np.maximum.at(hi_ts, comp, ts)
    comps = out.index.get_level_values(0).to_numpy()
    accs = out.index.get_level_values(1).to_numpy()
    lo, hi_ = idx.window(accs, lo_ts[comps], hi_ts[comps])
    out["degree_window"] = (hi_ - lo)
    return out


def pair_features(idx: SplitIndex, gfp: np.ndarray, inc_pos: np.ndarray, is_seed: np.ndarray, comp: np.ndarray, *,
                  emb_of: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray] | None] | None = None,
                  ring_id: np.ndarray | None = None) -> pd.DataFrame:
    """Feature rows for every shared-account pair of included edges (KEY_COLUMNS + PAIR_FEATURES,
    plus `label` when `ring_id` per included edge is given). `emb_of(pos_a, pos_b)` returns the two
    embedding matrices (rows aligned) or None; `gfp` is the split's (n_edges, 10) raw-count array."""
    inc_pos = np.asarray(inc_pos, dtype=np.int64)
    n = len(inc_pos)
    empty = pd.DataFrame({c: pd.Series(dtype=float) for c in KEY_COLUMNS + PAIR_FEATURES + (["label"] if ring_id is not None else [])})
    if n < 2:
        return empty
    f, t, ts, amt = idx.from_dense[inc_pos], idx.to_dense[inc_pos], idx.ts[inc_pos], idx.amount[inc_pos]
    roles = account_roles(idx, inc_pos, comp)
    # events (component, account, local edge index, is_out) sorted by (component, account, ts, position)
    ev = pd.DataFrame({"comp": np.concatenate([comp, comp]), "acc": np.concatenate([f, t]),
                       "i": np.concatenate([np.arange(n), np.arange(n)]),
                       "is_out": np.concatenate([np.ones(n, np.int8), np.zeros(n, np.int8)])})
    ev["ts"], ev["pos"] = ts[ev["i"]], inc_pos[ev["i"]]
    ev = ev.sort_values(["comp", "acc", "ts", "pos"], kind="stable").reset_index(drop=True)
    grp_key = ev["comp"].to_numpy().astype(np.int64) * (len(idx.acc_uniq) + 1) + ev["acc"].to_numpy()
    starts = np.flatnonzero(np.r_[True, grp_key[1:] != grp_key[:-1]])
    ends = np.r_[starts[1:], len(ev)]
    ia, ib, acc_rows, out_a, out_b = [], [], [], [], []
    ev_i, ev_out, ev_acc, ev_comp = ev["i"].to_numpy(), ev["is_out"].to_numpy(), ev["acc"].to_numpy(), ev["comp"].to_numpy()
    for s, e in zip(starts, ends):
        m = e - s
        if m < 2:
            continue
        u, v = np.triu_indices(m, k=1)
        ia.append(ev_i[s + u]); ib.append(ev_i[s + v])
        out_a.append(ev_out[s + u]); out_b.append(ev_out[s + v])
        acc_rows.append(np.full(len(u), s))
    if not ia:
        return empty
    ia, ib = np.concatenate(ia), np.concatenate(ib)
    out_a, out_b, acc_rows = np.concatenate(out_a), np.concatenate(out_b), np.concatenate(acc_rows)
    acc = ev_acc[acc_rows]
    cmp = ev_comp[acc_rows]
    gap = ts[ib] - ts[ia]
    hi = np.maximum(amt[ia], amt[ib])
    ratio = np.where(hi > 0, np.minimum(amt[ia], amt[ib]) / np.where(hi > 0, hi, 1), 0.0)
    emb = emb_of(inc_pos[ia], inc_pos[ib]) if emb_of is not None else None
    g = np.log1p(gfp[inc_pos].astype(np.float64))
    sa, sb = is_seed[ia].astype(bool), is_seed[ib].astype(bool)
    r = roles.loc[list(zip(cmp.tolist(), acc.tolist()))]
    role_col = r["role"].to_numpy()
    cols = {"component": cmp, "edge_a": idx.edge_id[inc_pos[ia]], "edge_b": idx.edge_id[inc_pos[ib]],
            "shared_account": idx.acc_uniq[acc],
            "time_gap_s": gap, "amount_ratio": ratio,
            "dir_in_out": ((out_a == 0) & (out_b == 1)).astype(np.int64),
            "dir_out_out": ((out_a == 1) & (out_b == 1)).astype(np.int64),
            "dir_in_in": ((out_a == 0) & (out_b == 0)).astype(np.int64),
            "dir_out_in": ((out_a == 1) & (out_b == 0)).astype(np.int64),
            "cos_emb": _cos_rows(*emb) if emb is not None else np.full(len(ia), np.nan),
            "cos_gfp": _cos_rows(g[ia], g[ib]),
            "kind_seed_seed": (sa & sb).astype(np.int64), "kind_seed_exp": (sa ^ sb).astype(np.int64),
            "kind_exp_exp": (~sa & ~sb).astype(np.int64),
            **{f"role_{name}": (role_col == name).astype(np.int64) for name in ("source", "sink", "mule", "other")},
            "acc_closure": r["closure"].to_numpy(), "acc_n_included": r["n_included"].to_numpy(np.int64),
            "acc_n_counterparties": r["n_counterparties"].to_numpy(np.int64),
            "acc_log_degree_window": np.log1p(r["degree_window"].to_numpy(float)),
            "on_chain": ((out_a == 0) & (out_b == 1) & (gap >= 0) & (gap <= HOLD_S) & (ratio >= 1 - TAU_ROLE)).astype(np.int64)}
    if ring_id is not None:
        ra, rb = ring_id[ia], ring_id[ib]
        cols["label"] = ((ra > 0) & (ra == rb)).astype(np.int64)
    return pd.DataFrame(cols, columns=list(cols))
