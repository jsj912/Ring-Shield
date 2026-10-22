"""Per-split account/time index for candidate generation and account-state features.

    idx = index_for(scored_edges)          # built once per split, cached (initializer-globals pattern
                                           # of graph/motif_features.py: build once, query many times)
    lo, hi = idx.window(acc, t_lo, t_hi)   # event range [t_lo, t_hi] at each account (vectorised)
    rows, ev = idx.expand(lo, hi)          # (query row, event index) pairs for every event in range

Every transaction is two events, one at each endpoint: (account, timestamp, edge position,
direction, counterparty, amount). Events are sorted by (account, timestamp, edge) and addressed
through a composite key `account_dense * 2**32 + timestamp`, so a window query at an account is
two np.searchsorted calls -- the same trick as models/density_detector.py. Prefix sums over the
sorted events give inflow / outflow counts, sums and the low-amount counts of any window in O(1)
per query; unique counterparties need the events themselves (features.py slices them).

Amounts: `amount_received` (the contract column; equal to amount_sent for 98.7 % of edges).
Transactions duplicated on (from, to, timestamp, amount) count once: the duplicates carry weight
0 in every prefix sum (Step 6.2 "amounts deduplicated"). `low` = amount below the split's 25th
percentile over all its edges.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

KEY_SHIFT = np.int64(1) << np.int64(32)      # timestamps (< 2**31) live in the low bits of the key
DIR_IN, DIR_OUT = 0, 1


@dataclass
class SplitIndex:
    # per edge, in position order (edge_id ascending)
    edge_id: np.ndarray
    from_id: np.ndarray
    to_id: np.ndarray
    ts: np.ndarray
    amount: np.ndarray
    dup: np.ndarray                   # duplicate on (from, to, ts, amount) -> weight 0
    # dense account ids
    acc_uniq: np.ndarray              # sorted unique account ids; dense id = position
    from_dense: np.ndarray
    to_dense: np.ndarray
    # events sorted by (account, ts, edge position)
    ev_acc: np.ndarray                # dense account
    ev_ts: np.ndarray
    ev_pos: np.ndarray                # edge position
    ev_dir: np.ndarray                # DIR_OUT at the sender, DIR_IN at the receiver
    ev_other: np.ndarray              # dense id of the counterparty
    ev_amt: np.ndarray
    ev_key: np.ndarray
    # prefix sums (len n_events + 1)
    cum_in_cnt: np.ndarray
    cum_out_cnt: np.ndarray
    cum_in_amt: np.ndarray
    cum_out_amt: np.ndarray
    cum_in_low: np.ndarray
    cum_out_low: np.ndarray
    amount_p25: float

    # ---------------------------------------------------------------- construction
    @classmethod
    def build(cls, df: pd.DataFrame) -> "SplitIndex":
        cols = {"edge_id", "from_id", "to_id", "timestamp"}
        missing = cols - set(df.columns)
        if missing:
            raise ValueError(f"index needs columns {sorted(missing)}")
        amt_col = "amount_received" if "amount_received" in df.columns else "amount"
        if amt_col not in df.columns:
            raise ValueError("index needs amount_received (contract) or amount")
        eid = df["edge_id"].to_numpy(np.int64)
        order = np.argsort(eid, kind="stable")
        eid = eid[order]
        assert np.all(np.diff(eid) > 0), "edge_id must be unique"
        frm = df["from_id"].to_numpy(np.int64)[order]
        to = df["to_id"].to_numpy(np.int64)[order]
        ts = df["timestamp"].to_numpy(np.int64)[order]
        amt = df[amt_col].to_numpy(np.float64)[order]
        assert ts.min() >= 0 and ts.max() < (1 << 31), "timestamps must fit the key's low 32 bits"
        dup = pd.DataFrame({"f": frm, "t": to, "ts": ts, "a": amt}).duplicated().to_numpy()
        n = len(eid)
        acc_uniq = np.unique(np.concatenate([frm, to]))
        fd = np.searchsorted(acc_uniq, frm)
        td = np.searchsorted(acc_uniq, to)
        ev_acc = np.concatenate([fd, td])
        ev_dir = np.concatenate([np.full(n, DIR_OUT, np.int8), np.full(n, DIR_IN, np.int8)])
        ev_pos = np.concatenate([np.arange(n), np.arange(n)])
        ev_other = np.concatenate([td, fd])
        ev_ts = np.concatenate([ts, ts])
        ev_amt = np.concatenate([amt, amt])
        w = np.concatenate([~dup, ~dup]).astype(np.float64)
        o = np.lexsort((ev_pos, ev_ts, ev_acc))
        ev_acc, ev_dir, ev_pos, ev_other, ev_ts, ev_amt, w = (a[o] for a in (ev_acc, ev_dir, ev_pos, ev_other, ev_ts, ev_amt, w))
        key = ev_acc.astype(np.int64) * KEY_SHIFT + ev_ts
        p25 = float(np.percentile(amt, 25))
        low = (ev_amt < p25).astype(np.float64)
        is_in = (ev_dir == DIR_IN).astype(np.float64)
        is_out = 1.0 - is_in

        def cum(x):
            c = np.zeros(len(x) + 1)
            np.cumsum(x, out=c[1:])
            return c
        return cls(edge_id=eid, from_id=frm, to_id=to, ts=ts, amount=amt, dup=dup, acc_uniq=acc_uniq,
                   from_dense=fd, to_dense=td, ev_acc=ev_acc, ev_ts=ev_ts, ev_pos=ev_pos, ev_dir=ev_dir,
                   ev_other=ev_other, ev_amt=ev_amt, ev_key=key,
                   cum_in_cnt=cum(is_in * w), cum_out_cnt=cum(is_out * w),
                   cum_in_amt=cum(is_in * w * ev_amt), cum_out_amt=cum(is_out * w * ev_amt),
                   cum_in_low=cum(is_in * w * low), cum_out_low=cum(is_out * w * low), amount_p25=p25)

    # ---------------------------------------------------------------- lookups
    @property
    def n_edges(self) -> int:
        return len(self.edge_id)

    def pos_of(self, edge_ids) -> np.ndarray:
        e = np.asarray(edge_ids, dtype=np.int64)
        p = np.searchsorted(self.edge_id, e)
        p = np.clip(p, 0, self.n_edges - 1)
        if not np.all(self.edge_id[p] == e):
            bad = e[self.edge_id[p] != e]
            raise KeyError(f"{len(bad)} edge ids not in this split, e.g. {bad[:5].tolist()}")
        return p

    def dense(self, account_ids) -> np.ndarray:
        a = np.asarray(account_ids, dtype=np.int64)
        d = np.searchsorted(self.acc_uniq, a)
        d = np.clip(d, 0, len(self.acc_uniq) - 1)
        assert np.all(self.acc_uniq[d] == a), "unknown account id"
        return d

    def window(self, acc_dense, t_lo, t_hi, *, hi_inclusive: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """Event index range at each account with timestamp in [t_lo, t_hi] (or [t_lo, t_hi) with
        hi_inclusive=False). Arrays broadcast; returns (lo, hi) with hi exclusive."""
        acc = np.asarray(acc_dense, dtype=np.int64)
        base = acc * KEY_SHIFT
        lo = np.searchsorted(self.ev_key, base + np.asarray(t_lo, dtype=np.int64), side="left")
        hi = np.searchsorted(self.ev_key, base + np.asarray(t_hi, dtype=np.int64), side="right" if hi_inclusive else "left")
        return lo, np.maximum(hi, lo)

    @staticmethod
    def expand(lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(query row index, event index) for every event of every [lo, hi) range."""
        n = hi - lo
        rows = np.repeat(np.arange(len(lo)), n)
        if len(rows) == 0:
            return rows, rows.copy()
        starts = np.cumsum(n) - n
        ev = np.arange(len(rows)) - np.repeat(starts, n) + np.repeat(lo, n)
        return rows, ev

    def window_sums(self, lo, hi) -> dict[str, np.ndarray]:
        """Counts / sums / low-amount counts of the events in each [lo, hi) range."""
        out = {}
        for name, c in (("in_cnt", self.cum_in_cnt), ("out_cnt", self.cum_out_cnt), ("in_amt", self.cum_in_amt),
                        ("out_amt", self.cum_out_amt), ("in_low", self.cum_in_low), ("out_low", self.cum_out_low)):
            out[name] = c[hi] - c[lo]
        return out


# ---------------------------------------------------------------------- module cache
_INDEX: SplitIndex | None = None
_INDEX_KEY = None


def _fingerprint(df: pd.DataFrame):
    e = df["edge_id"].to_numpy()
    t = df["timestamp"].to_numpy()
    return (id(df), len(df), int(e[0]) if len(e) else -1, int(e[-1]) if len(e) else -1,
            int(t.min()) if len(t) else -1, int(t.max()) if len(t) else -1)


def index_for(scored_edges: pd.DataFrame) -> SplitIndex:
    """The SplitIndex of this frame; rebuilt only when a different frame is given."""
    global _INDEX, _INDEX_KEY
    key = _fingerprint(scored_edges)
    if _INDEX is None or key != _INDEX_KEY:
        _INDEX, _INDEX_KEY = SplitIndex.build(scored_edges), key
    return _INDEX


def set_index(idx: SplitIndex | None, key=None):
    global _INDEX, _INDEX_KEY
    _INDEX, _INDEX_KEY = idx, key
