"""Feature rows for expansion candidates (Step 6.2) -- information at the candidate's timestamp only.

    ctx = FeatureContext.build(scored_edges, score_quantile=..., dead_region=..., gfp=..., emb=...)
    X = compute_features(ctx, cand, included_edge_ids, delta_t_h=72)

Two kinds of information go into a row for candidate c = (u -> v, t_c):

* the INCLUDED SET (the ring's seeds plus whatever expansion has added so far) -- given context:
  the anchor, the gap to it, the conservation balance of the included edges at the shared
  account, the mean included embedding. Included edges may lie after t_c (a quiet member is
  often paid before the seed that fires); their latest timestamp is reported as
  `max_included_ts`.
* the TRANSACTION STREAM -- read only at or before t_c: account state over the trailing 24 h and
  72 h windows [t_c - W, t_c), reach to other included accounts through edges in
  [t_c - delta_t, t_c], the candidate's own trailing GFP features and its detector score. The
  latest stream timestamp a row touched is `max_ts_used`; tests assert max_ts_used <= t_c on
  every row (the policy never sees a feature computed from a later transaction).

Feature groups (FEATURE_GROUPS; `--drop-feature-group` in the policy uses the names):
    timing        hop, gap to the anchor (signed / absolute / after-anchor flag), gap to the
                  nearest included edge, gap to the touching edge (hop 2), n_anchors, n_included,
                  the candidate's log amount and low-amount flag
    conservation  at the shared account: included inflow / outflow sums and counts, closure
                  before and after adding the candidate (min / max of the two sides; 0 with one
                  side empty), delta, hold-time estimate (outflow: t_c - latest included inflow
                  at or before t_c; inflow: earliest included outflow at or after t_c - t_c;
                  -1 if none), the candidate's direction at the shared account
    direction     one-hot of (touching edge's direction, candidate's direction) at the shared
                  account: in->out, out->out, in->in, out->in; far_is_member
    reach         reach_1hop / reach_2hop (0/1) and reach_count: included accounts other than the
                  shared one reachable from the far endpoint by <= 2 stream edges within
                  [t_c - delta_t, t_c] (the candidate's own edge excluded)
    account_state for the far endpoint and the shared account, trailing 24 h and 72 h: inflow
                  and outflow counts and sums, unique counterparties in / out (over at most
                  UNIQ_CAP most recent events), fraction of amounts below the split's p25
    embedding     cosine of the candidate's head-input embedding to the mean included embedding
                  and to the anchor's
    detector      score_quantile (rank / N of score_raw within the split, amendment a) and
                  dead_region (the head has no opinion on this edge, amendment d)
    gfp           the candidate's 10 trailing GFP counts (log1p)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ringshield.expand.index import DIR_IN, DIR_OUT, KEY_SHIFT, SplitIndex, index_for

H24, H72 = 24 * 3600, 72 * 3600
UNIQ_CAP = 2000          # unique-counterparty stats read at most this many most recent events
REACH_CAP = 200          # neighbours of the far endpoint considered for reach
GFP_COLS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
            "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]

FEATURE_GROUPS: dict[str, list[str]] = {
    "timing": ["hop", "gap_to_anchor_s", "abs_gap_to_anchor_s", "after_anchor", "abs_gap_via_s",
               "gap_to_nearest_seed_s", "nearest_seed_before", "n_anchors", "n_included", "log_amount", "amount_below_p25"],
    "conservation": ["inc_in_sum", "inc_out_sum", "inc_in_cnt", "inc_out_cnt", "closure_before", "closure_after",
                     "delta_closure", "hold_time_s", "cand_is_inflow"],
    "direction": ["pair_in_out", "pair_out_out", "pair_in_in", "pair_out_in", "far_is_member"],
    "reach": ["reach_1hop", "reach_2hop", "reach_count"],
    "account_state": [f"{who}_{w}h_{s}" for who in ("far", "shared") for w in (24, 72)
                      for s in ("in_cnt", "out_cnt", "in_sum", "out_sum", "uniq_in", "uniq_out", "low_frac")],
    "embedding": ["cos_mean_included", "cos_anchor"],
    "detector": ["score_quantile", "dead_region"],
    "gfp": [f"gfp_{c}" for c in GFP_COLS],
}
FEATURE_COLUMNS = [c for cols in FEATURE_GROUPS.values() for c in cols]
KEY_COLUMNS = ["candidate_edge_id", "anchor_edge_id", "candidate_ts", "max_ts_used", "max_included_ts"]   # + hop (a feature)


class EmbeddingStore:
    """Rows of a (possibly partial) embedding matrix keyed by edge_id."""

    def __init__(self, edge_ids: np.ndarray, matrix: np.ndarray):
        order = np.argsort(edge_ids, kind="stable")
        self.edge_ids = np.asarray(edge_ids, dtype=np.int64)[order]
        self.matrix = np.asarray(matrix, dtype=np.float32)[order]
        assert np.all(np.diff(self.edge_ids) > 0), "duplicate edge ids in the embedding store"

    @classmethod
    def from_parquet(cls, path, edge_ids=None) -> "EmbeddingStore":
        df = pd.read_parquet(path)
        if edge_ids is not None:
            df = df[df["edge_id"].isin(np.asarray(edge_ids))]
        cols = [c for c in df.columns if c.startswith("emb_")]
        return cls(df["edge_id"].to_numpy(np.int64), df[cols].to_numpy(np.float32))

    def get(self, edge_ids) -> np.ndarray:
        e = np.asarray(edge_ids, dtype=np.int64)
        p = np.clip(np.searchsorted(self.edge_ids, e), 0, len(self.edge_ids) - 1)
        if not np.all(self.edge_ids[p] == e):
            raise KeyError(f"{int((self.edge_ids[p] != e).sum())} edge ids without an embedding")
        return self.matrix[p]

    @property
    def dim(self) -> int:
        return self.matrix.shape[1]


@dataclass
class FeatureContext:
    idx: SplitIndex
    score_quantile: np.ndarray       # per index position
    dead_region: np.ndarray          # per index position (bool)
    gfp: np.ndarray                  # (n_edges, 10) float32, raw counts
    emb: EmbeddingStore | None = None
    meta: dict = field(default_factory=dict)

    @classmethod
    def build(cls, scored_edges: pd.DataFrame, *, score_quantile: pd.Series | None = None,
              dead_region: pd.Series | None = None, gfp: pd.DataFrame | None = None,
              emb: EmbeddingStore | None = None, index: SplitIndex | None = None) -> "FeatureContext":
        """`score_quantile` / `dead_region`: Series indexed by edge_id (default: rank / N of
        scored_edges.score_raw, all False). `gfp`: the split's GFP parquet frame (EdgeID + GFP_COLS)."""
        idx = index or index_for(scored_edges)
        se = scored_edges.set_index("edge_id")
        if score_quantile is None:
            score_quantile = se["score_raw"].rank(method="average") / len(se)
        q = score_quantile.reindex(idx.edge_id).to_numpy(np.float64)
        assert not np.isnan(q).any(), "score_quantile missing for some edges"
        d = (dead_region.reindex(idx.edge_id).fillna(False).to_numpy(bool) if dead_region is not None
             else np.zeros(idx.n_edges, dtype=bool))
        if gfp is None:
            g = np.zeros((idx.n_edges, len(GFP_COLS)), dtype=np.float32)
        else:
            g = gfp.set_index("EdgeID")[GFP_COLS].reindex(idx.edge_id).to_numpy(np.float32)
            assert not np.isnan(g).any(), "GFP rows missing for some edges"
        return cls(idx=idx, score_quantile=q, dead_region=d, gfp=g, emb=emb)


# ---------------------------------------------------------------------------- helpers
def _closure(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    hi = np.maximum(a, b)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(hi > 0, np.minimum(a, b) / np.where(hi > 0, hi, 1.0), 0.0)
    return c


def _uniq_counts(idx: SplitIndex, lo: np.ndarray, hi: np.ndarray):
    """Unique in-counterparties, unique out-counterparties and the latest timestamp of each
    [lo, hi) event range (the last UNIQ_CAP events when the range is longer)."""
    n = len(lo)
    u_in, u_out, tmax = np.zeros(n), np.zeros(n), np.full(n, -1, dtype=np.int64)
    other, dr, ts = idx.ev_other, idx.ev_dir, idx.ev_ts
    for i in range(n):
        a, b = int(lo[i]), int(hi[i])
        if b <= a:
            continue
        tmax[i] = ts[b - 1]
        a = max(a, b - UNIQ_CAP)
        o, d = other[a:b], dr[a:b]
        u_in[i] = len(np.unique(o[d == DIR_IN]))
        u_out[i] = len(np.unique(o[d == DIR_OUT]))
    return u_in, u_out, tmax


def _account_state(idx: SplitIndex, acc: np.ndarray, t_c: np.ndarray, w: int, prefix: str, out: dict) -> np.ndarray:
    """Trailing window [t_c - w, t_c) at `acc`; returns the latest timestamp read per row."""
    lo, hi = idx.window(acc, t_c - w, t_c, hi_inclusive=False)
    s = idx.window_sums(lo, hi)
    u_in, u_out, tmax = _uniq_counts(idx, lo, hi)
    cnt = s["in_cnt"] + s["out_cnt"]
    out[f"{prefix}_in_cnt"], out[f"{prefix}_out_cnt"] = s["in_cnt"], s["out_cnt"]
    out[f"{prefix}_in_sum"], out[f"{prefix}_out_sum"] = s["in_amt"], s["out_amt"]
    out[f"{prefix}_uniq_in"], out[f"{prefix}_uniq_out"] = u_in, u_out
    out[f"{prefix}_low_frac"] = np.where(cnt > 0, (s["in_low"] + s["out_low"]) / np.where(cnt > 0, cnt, 1), 0.0)
    return tmax


def _reach(idx: SplitIndex, far: np.ndarray, t_c: np.ndarray, c_pos: np.ndarray, shared: np.ndarray,
           inc_acc: np.ndarray, inc_pos: np.ndarray, delta: int):
    """reach_1hop, reach_2hop, reach_count and the latest stream timestamp read, per row.

    Stream edges in [t_c - delta, t_c], the candidate's own edge excluded. Targets: included
    accounts other than the row's shared account. 1 hop: an event at `far` whose counterparty
    is a target. 2 hops: an event at `far` to some x, and an event at x to a target inside the
    same window (contacts of the included accounts are indexed once per call)."""
    n = len(far)
    r1, r2 = np.zeros(n, dtype=np.int64), np.zeros(n, dtype=np.int64)
    count = np.zeros(n, dtype=np.int64)
    tmax = np.full(n, -1, dtype=np.int64)
    if n == 0 or len(inc_acc) == 0:
        return r1, r2, count, tmax
    is_inc = np.zeros(len(idx.acc_uniq), dtype=bool)
    is_inc[inc_acc] = True
    # events at `far` in the window (most recent REACH_CAP)
    lo, hi = idx.window(far, t_c - delta, t_c)
    lo = np.maximum(lo, hi - REACH_CAP)
    rows, ev = idx.expand(lo, hi)
    own = idx.ev_pos[ev] == c_pos[rows]
    rows, ev = rows[~own], ev[~own]
    if len(ev):
        np.maximum.at(tmax, rows, idx.ev_ts[ev])
    x = idx.ev_other[ev]
    hit1 = is_inc[x] & (x != shared[rows])
    if hit1.any():
        pairs = np.unique(rows[hit1].astype(np.int64) * (len(idx.acc_uniq) + 1) + x[hit1])
        pr = pairs // (len(idx.acc_uniq) + 1)
        np.add.at(count, pr, 1)
        r1[np.unique(pr)] = 1
    # 2 hops: contacts of included accounts -> (x, t, target), then a keyed range query per (row, x)
    lo_i, hi_i = idx.window(inc_acc, int(t_c.min()) - delta, int(t_c.max()))
    ri, evi = idx.expand(lo_i, hi_i)
    if len(evi):
        keep = ~np.isin(idx.ev_pos[evi], inc_pos)          # the included edges themselves are not contacts
        ri, evi = ri[keep], evi[keep]
    if len(evi) and (~hit1).any():
        cx, ct, ctarget = idx.ev_other[evi], idx.ev_ts[evi], inc_acc[ri]
        o = np.lexsort((ctarget, ct, cx))
        cx, ct, ctarget = cx[o], ct[o], ctarget[o]
        ckey = cx.astype(np.int64) * KEY_SHIFT + ct
        sel = ~hit1 & ~is_inc[x]                            # x not itself included
        rr, xx = rows[sel], x[sel]
        base = xx.astype(np.int64) * KEY_SHIFT
        a = np.searchsorted(ckey, base + (t_c[rr] - delta), side="left")
        b = np.searchsorted(ckey, base + t_c[rr], side="right")
        got = b > a
        if got.any():
            rr, a, b = rr[got], a[got], b[got]
            r2rows, cev = SplitIndex.expand(a, b)
            tgt = ctarget[cev]
            ok = (tgt != shared[rr[r2rows]]) & (tgt != far[rr[r2rows]])   # no degenerate far -> x -> far
            if ok.any():
                np.maximum.at(tmax, rr[r2rows[ok]], ct[cev[ok]])
                pairs = np.unique(rr[r2rows[ok]].astype(np.int64) * (len(idx.acc_uniq) + 1) + tgt[ok])
                pr = pairs // (len(idx.acc_uniq) + 1)
                r2[np.unique(pr)] = 1
                # count distinct targets over both hops
                p1 = (np.unique(rows[hit1].astype(np.int64) * (len(idx.acc_uniq) + 1) + x[hit1]) if hit1.any()
                      else np.zeros(0, np.int64))
                allp = np.unique(np.concatenate([p1, pairs]))
                count[:] = 0
                np.add.at(count, allp // (len(idx.acc_uniq) + 1), 1)
    return r1, r2, count, tmax


def _cos(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1) if b.ndim == 2 else np.linalg.norm(b)
    den = na * nb
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(den > 0, (a * b).sum(axis=1) / np.where(den > 0, den, 1.0), 0.0)
    return c


# ---------------------------------------------------------------------------- main entry
def compute_features(ctx: FeatureContext, cand: pd.DataFrame, included_edge_ids, delta_t_h: float) -> pd.DataFrame:
    """One feature row per candidate row (same order as `cand`), KEY_COLUMNS + FEATURE_COLUMNS."""
    idx = ctx.idx
    n = len(cand)
    inc = np.unique(np.asarray(list(included_edge_ids), dtype=np.int64))
    inc_pos = idx.pos_of(inc)
    delta = int(round(float(delta_t_h) * 3600))
    out: dict[str, np.ndarray] = {}
    if n == 0:
        df = pd.DataFrame({c: pd.Series(dtype=float) for c in KEY_COLUMNS + FEATURE_COLUMNS})
        return df

    c_pos = idx.pos_of(cand["candidate_edge_id"].to_numpy())
    a_pos = idx.pos_of(cand["anchor_edge_id"].to_numpy())
    hop = cand["hop"].to_numpy(np.int64)
    via_pos = np.where(hop == 2, idx.pos_of(np.where(hop == 2, cand["via_edge_id"].to_numpy(), idx.edge_id[0])), a_pos)
    shared = idx.dense(cand["shared_account"].to_numpy())
    t_c, t_a = idx.ts[c_pos], idx.ts[a_pos]
    inc_ts = idx.ts[inc_pos]
    fd, td = idx.from_dense, idx.to_dense
    far = np.where(fd[c_pos] == shared, td[c_pos], fd[c_pos])
    inc_acc = np.unique(np.concatenate([fd[inc_pos], td[inc_pos]]))
    is_inc_acc = np.zeros(len(idx.acc_uniq), dtype=bool)
    is_inc_acc[inc_acc] = True

    # timing --------------------------------------------------------------------------
    gap = t_c - t_a
    out["hop"] = hop
    out["gap_to_anchor_s"], out["abs_gap_to_anchor_s"] = gap, np.abs(gap)
    out["after_anchor"] = (gap > 0).astype(np.int64)
    out["abs_gap_via_s"] = np.abs(cand["gap_via_s"].to_numpy(np.int64))
    srt = np.sort(inc_ts)
    p = np.searchsorted(srt, t_c)
    before = np.where(p > 0, srt[np.maximum(p - 1, 0)], -10**12)
    after = np.where(p < len(srt), srt[np.minimum(p, len(srt) - 1)], 10**12)
    d_before, d_after = t_c - before, after - t_c
    out["gap_to_nearest_seed_s"] = np.minimum(d_before, d_after)
    out["nearest_seed_before"] = (d_before <= d_after).astype(np.int64)
    out["n_anchors"] = cand["n_anchors"].to_numpy(np.int64)
    out["n_included"] = np.full(n, len(inc_pos), dtype=np.int64)
    amt = idx.amount[c_pos]
    out["log_amount"] = np.log1p(np.maximum(amt, 0))
    out["amount_below_p25"] = (amt < idx.amount_p25).astype(np.int64)

    # conservation at the shared account ------------------------------------------------
    inc_df = pd.DataFrame({"f": fd[inc_pos], "t": td[inc_pos], "ts": inc_ts, "amt": idx.amount[inc_pos]})
    in_sum = inc_df.groupby("t")["amt"].sum()
    out_sum = inc_df.groupby("f")["amt"].sum()
    in_cnt = inc_df.groupby("t").size()
    out_cnt = inc_df.groupby("f").size()
    sh = pd.Index(shared)
    i_s = in_sum.reindex(sh).fillna(0).to_numpy()
    o_s = out_sum.reindex(sh).fillna(0).to_numpy()
    out["inc_in_sum"], out["inc_out_sum"] = i_s, o_s
    out["inc_in_cnt"] = in_cnt.reindex(sh).fillna(0).to_numpy(np.int64)
    out["inc_out_cnt"] = out_cnt.reindex(sh).fillna(0).to_numpy(np.int64)
    cand_in = (td[c_pos] == shared).astype(np.int64)
    out["cand_is_inflow"] = cand_in
    out["closure_before"] = _closure(i_s, o_s)
    out["closure_after"] = _closure(i_s + cand_in * amt, o_s + (1 - cand_in) * amt)
    out["delta_closure"] = out["closure_after"] - out["closure_before"]
    hold = np.full(n, -1.0)
    in_ts_of = {a: np.sort(g["ts"].to_numpy()) for a, g in inc_df.groupby("t")}
    out_ts_of = {a: np.sort(g["ts"].to_numpy()) for a, g in inc_df.groupby("f")}
    for a in np.unique(shared):
        rows = np.where(shared == a)[0]
        ins, outs = in_ts_of.get(a), out_ts_of.get(a)
        r_out = rows[cand_in[rows] == 0]
        if ins is not None and len(r_out):
            q = np.searchsorted(ins, t_c[r_out], side="right") - 1
            hold[r_out] = np.where(q >= 0, t_c[r_out] - ins[np.maximum(q, 0)], -1.0)
        r_in = rows[cand_in[rows] == 1]
        if outs is not None and len(r_in):
            q = np.searchsorted(outs, t_c[r_in], side="left")
            hold[r_in] = np.where(q < len(outs), outs[np.minimum(q, len(outs) - 1)] - t_c[r_in], -1.0)
    out["hold_time_s"] = hold

    # direction pair at the shared account: touching edge (anchor at hop 1, via at hop 2) -> candidate
    touch_in = (td[via_pos] == shared).astype(np.int64)
    out["pair_in_out"] = ((touch_in == 1) & (cand_in == 0)).astype(np.int64)
    out["pair_out_out"] = ((touch_in == 0) & (cand_in == 0)).astype(np.int64)
    out["pair_in_in"] = ((touch_in == 1) & (cand_in == 1)).astype(np.int64)
    out["pair_out_in"] = ((touch_in == 0) & (cand_in == 1)).astype(np.int64)
    out["far_is_member"] = is_inc_acc[far].astype(np.int64)

    # reach ---------------------------------------------------------------------------
    r1, r2, rc, t_reach = _reach(idx, far, t_c, c_pos, shared, inc_acc, inc_pos, delta)
    out["reach_1hop"], out["reach_2hop"], out["reach_count"] = r1, r2, rc

    # account state -------------------------------------------------------------------
    tmaxs = [t_reach]
    for who, acc in (("far", far), ("shared", shared)):
        for w, h in ((24, H24), (72, H72)):
            tmaxs.append(_account_state(idx, acc, t_c, h, f"{who}_{w}h", out))

    # embedding -----------------------------------------------------------------------
    if ctx.emb is not None:
        ec = ctx.emb.get(idx.edge_id[c_pos])
        ea = ctx.emb.get(idx.edge_id[a_pos])
        mean_inc = ctx.emb.get(inc).mean(axis=0)
        out["cos_mean_included"] = _cos(ec, mean_inc)
        out["cos_anchor"] = _cos(ec, ea)
    else:
        out["cos_mean_included"] = np.full(n, np.nan)
        out["cos_anchor"] = np.full(n, np.nan)

    # detector, gfp -------------------------------------------------------------------
    out["score_quantile"] = ctx.score_quantile[c_pos]
    out["dead_region"] = ctx.dead_region[c_pos].astype(np.int64)
    g = np.log1p(ctx.gfp[c_pos].astype(np.float64))
    for j, c in enumerate(GFP_COLS):
        out[f"gfp_{c}"] = g[:, j]

    max_ts_used = np.maximum.reduce([t_c] + tmaxs)      # the candidate's own row is read at t_c
    df = pd.DataFrame({"candidate_edge_id": idx.edge_id[c_pos], "anchor_edge_id": idx.edge_id[a_pos],
                       "candidate_ts": t_c, "max_ts_used": max_ts_used, "max_included_ts": np.full(n, int(inc_ts.max()))})
    for c in FEATURE_COLUMNS:
        df[c] = out[c]
    return df
