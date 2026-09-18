"""Mini-batch loader shared by training (models/tgn.py) and scoring (models/score.py).

    loader = make_loader(data, seed_inds, args, causal=True)

`data` is the Data / HeteroData object built by models.tgn.load_data (edge_attr column 0
is the global edge id, `timestamps` is per edge, `y` is per edge). `seed_inds` are the
global indices (into data's `to` edges) of the edges to score.

Every batch coming out of the loader satisfies:

* the seed edges of the batch are present in the message-passing edge set exactly once,
  as the LAST `n_seed` edges of the `to` store (and, for HeteroData, their reverses as the
  last `n_seed` edges of the `rev_to` store), in `input_id` order. `batch.seed_mask`
  (Data) / `batch['node','to','node'].seed_mask` (HeteroData) selects them and
  `seed_global` holds `seed_inds[input_id]`. This replaces the old
  `torch.isin(edge_attr[:, 0], ...)` mask, which missed seeds the sampler did not draw.
* the global-id column (`edge_attr[:, 0]`) is stripped from every store before the model
  sees features. Use `e_id` for identity.
* with `causal=True`, no edge in any store has a timestamp later than the latest seed of
  the batch. Route:
    native   PyG LinkNeighborLoader(time_attr="timestamps", edge_label_time=...) with
             edge-level time on both stores -- exact per-seed causality.
    fallback if the installed PyG rejects edge-level temporal sampling: seeds are sorted
             by time and batched in contiguous windows of `window_s` seconds (capped at
             batch_size); after sampling every edge with timestamp > max seed timestamp
             of the batch is dropped from both stores. Within-batch leak <= window_s.
             `window_s` comes from make_loader(window_s=...), else `args.window_s`, else
             WINDOW_S (1,800 s); the value used is stored on the loader (`loader.window_s`).
  The active route is logged once (`ROUTE`).
* with `causal=False`, sampling is exactly today's LinkNeighborLoader call (same
  arguments, same batching); only the seed guarantee and id stripping are added.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Iterator

import torch
from torch.utils.data import Sampler
from torch_geometric.data import Data, HeteroData
from torch_geometric.loader import LinkNeighborLoader

TO = ("node", "to", "node")
REV = ("node", "rev_to", "node")
WINDOW_S = 1800  # default fallback window width in seconds (override: --window-s)
EDGE_TENSORS = ("edge_attr", "timestamps", "y", "e_id")  # per-edge tensors we carry along

ROUTE: dict = {"route": None, "error": None, "window_s": WINDOW_S}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _store(obj, key):
    return obj[key] if isinstance(obj, HeteroData) else obj


def _edge_tensors(store, n_edges: int) -> list[str]:
    """Names of per-edge tensors present in an edge store (excluding edge_index)."""
    names = []
    for k in store.keys():
        if k in ("edge_index", "edge_label_index", "edge_label", "input_id", "seed_mask", "seed_global",
                 "seed_pos", "e_id_seed"):
            continue
        v = store[k]
        if torch.is_tensor(v) and v.dim() >= 1 and v.size(0) == n_edges:
            if k not in EDGE_TENSORS:
                raise RuntimeError(f"unexpected per-edge tensor '{k}' in batch store; extend EDGE_TENSORS")
            names.append(k)
    return names


def _filter_store(store, keep: torch.Tensor):
    n = store.edge_index.size(1)
    names = _edge_tensors(store, n)
    store.edge_index = store.edge_index[:, keep]
    for k in names:
        store[k] = store[k][keep]


def _append_store(store, edge_index_new, attrs: dict):
    store.edge_index = torch.cat([store.edge_index, edge_index_new.to(store.edge_index.device)], dim=1)
    for k, v in attrs.items():
        if k in store:
            store[k] = torch.cat([store[k], v.to(store[k].device)], dim=0)


class SeedFixTransform:
    """Guarantee seeds, (optionally) enforce causality, strip the id column."""

    def __init__(self, data, seed_inds: torch.Tensor, causal: bool, hetero: bool):
        self.hetero = hetero
        self.causal = causal
        self.seed_inds = seed_inds.detach().cpu()
        to = _store(data, TO)
        self.attr_to = to.edge_attr
        self.ts = to.timestamps
        self.y = to.y
        self.attr_rev = data[REV].edge_attr if hetero else None

    def __call__(self, batch):
        to = _store(batch, TO)
        seed_global = self.seed_inds[to.input_id.detach().cpu()]
        n_seed = seed_global.numel()
        seed_ts = self.ts[seed_global]
        stores = [(TO, to)] + ([(REV, batch[REV])] if self.hetero else [])

        for key, st in stores:
            keep = ~torch.isin(st.e_id.detach().cpu(), seed_global)          # drop sampled copies of seeds
            if self.causal and st.edge_index.size(1) > 0:
                keep &= st.timestamps.detach().cpu() <= seed_ts.max()        # drop anything after the last seed
            if not bool(keep.all()):
                _filter_store(st, keep.to(st.edge_index.device))

        eli = to.edge_label_index
        _append_store(to, eli, {"edge_attr": self.attr_to[seed_global], "timestamps": seed_ts,
                                "y": self.y[seed_global], "e_id": seed_global})
        if self.hetero:
            _append_store(batch[REV], eli.flipud(),
                          {"edge_attr": self.attr_rev[seed_global], "timestamps": seed_ts, "e_id": seed_global})

        n_edges = to.edge_index.size(1)
        mask = torch.zeros(n_edges, dtype=torch.bool, device=to.edge_index.device)
        mask[n_edges - n_seed:] = True
        to.seed_mask = mask
        to.seed_global = seed_global.to(to.edge_index.device)

        for _, st in stores:                                               # strip the global-id column
            st.edge_attr = st.edge_attr[:, 1:]
        return batch


def _chain(*fns: Callable | None) -> Callable | None:
    fns = [f for f in fns if f is not None]
    if not fns:
        return None

    def run(batch):
        for f in fns:
            batch = f(batch)
        return batch
    return run


class WindowBatchSampler(Sampler[list[int]]):
    """Contiguous time windows of seeds (<= window_s wide, <= batch_size long)."""

    def __init__(self, seed_ts: torch.Tensor, batch_size: int, window_s: int, shuffle: bool):
        order = torch.argsort(seed_ts, stable=True)
        ts = seed_ts[order].tolist()
        order = order.tolist()
        self.batches: list[list[int]] = []
        cur, t0 = [], None
        for pos, t in zip(order, ts):
            if cur and (t - t0 > window_s or len(cur) >= batch_size):
                self.batches.append(cur)
                cur, t0 = [], None
            if t0 is None:
                t0 = t
            cur.append(pos)
        if cur:
            self.batches.append(cur)
        self.shuffle = shuffle

    def __iter__(self) -> Iterator[list[int]]:
        idx = list(range(len(self.batches)))
        if self.shuffle:
            random.shuffle(idx)
        for i in idx:
            yield self.batches[i]

    def __len__(self) -> int:
        return len(self.batches)


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def make_loader(data, seed_inds: torch.Tensor, args, causal: bool, *, shuffle: bool = False,
                batch_size: int | None = None, transform: Callable | None = None,
                num_neighbors: list[int] | None = None, window_s: int | None = None) -> LinkNeighborLoader:
    """Build the loader. `args` needs num_neighs and batch_size (as in models/tgn.py);
    `transform` is applied after the seed/causal fix (e.g. AddEgoIds). `window_s` is the
    fallback window (default `args.window_s`, else WINDOW_S); the loader records the value
    it used as `loader.window_s` (None for the native and non-causal routes)."""
    hetero = isinstance(data, HeteroData)
    seed_inds = torch.as_tensor(seed_inds, dtype=torch.long).detach().cpu()
    batch_size = int(batch_size or args.batch_size)
    num_neighbors = list(num_neighbors or args.num_neighs)
    if window_s is None:
        window_s = getattr(args, "window_s", None)
    window_s = int(window_s if window_s is not None else WINDOW_S)
    assert window_s > 0, f"window_s must be positive, got {window_s}"
    to = _store(data, TO)
    if hetero and "timestamps" not in data[REV]:
        data[REV].timestamps = to.timestamps  # same edge order; needed for causal filtering / native route

    eli = to.edge_index[:, seed_inds]
    el = to.y[seed_inds]
    fix = SeedFixTransform(data, seed_inds, causal=causal, hetero=hetero)
    tf = _chain(fix, transform)
    common = dict(num_neighbors=num_neighbors, transform=tf)
    eli_arg = (TO, eli) if hetero else eli

    if not causal:
        loader = LinkNeighborLoader(data, edge_label_index=eli_arg, edge_label=el,
                                    batch_size=batch_size, shuffle=shuffle, **common)
        loader.window_s = None
        return loader

    seed_ts = to.timestamps[seed_inds]
    if ROUTE["route"] in (None, "native"):
        try:
            loader = LinkNeighborLoader(data, edge_label_index=eli_arg, edge_label=el, edge_label_time=seed_ts,
                                        time_attr="timestamps", batch_size=batch_size, shuffle=shuffle, **common)
            next(iter(loader))  # force the sampler to validate temporal support
            if ROUTE["route"] is None:
                ROUTE.update(route="native", error=None)
                print("[causal_loader] route=native (PyG edge-level temporal sampling on both stores)")
            loader.window_s = None
            return loader
        except (ImportError, NotImplementedError, ValueError, RuntimeError) as e:
            if ROUTE["route"] is None:
                ROUTE.update(route="fallback", error=f"{type(e).__name__}: {e}")
                print(f"[causal_loader] route=fallback window={window_s}s -- native rejected: {ROUTE['error']}")

    sampler = WindowBatchSampler(seed_ts, batch_size=batch_size, window_s=window_s, shuffle=shuffle)
    loader = LinkNeighborLoader(data, edge_label_index=eli_arg, edge_label=el, batch_sampler=sampler, **common)
    loader.window_s = window_s
    return loader


def seed_mask(batch):
    """(mask over `to` edges, global seed indices) for a batch from make_loader."""
    st = _store(batch, TO)
    return st.seed_mask, st.seed_global
