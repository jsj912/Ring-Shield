"""Step 3a checks for models/causal_loader.py on the 1% dry-run graph.

    python -m pytest tests/test_causal_loader.py -q -s
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch
from torch_geometric.loader import LinkNeighborLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.causal_loader import REV, ROUTE, TO, WINDOW_S, make_loader, seed_mask  # noqa: E402
from models.tgn import AddEgoIds  # noqa: E402

N_SEEDS = 1000


@pytest.fixture(scope="module")
def val(dry_data):
    tr, va, te, tr_inds, val_inds, te_inds, te_meta, args = dry_data
    return va, val_inds, args


@pytest.fixture(scope="module")
def random_val_seeds(val):
    va, val_inds, _ = val
    g = torch.Generator().manual_seed(1)
    pick = torch.randperm(val_inds.numel(), generator=g)[:N_SEEDS]
    return val_inds[pick]


def test_route_is_logged(val):
    va, val_inds, args = val
    make_loader(va, val_inds[:10], args, causal=True)
    assert ROUTE["route"] in ("native", "fallback")
    assert ROUTE["window_s"] == WINDOW_S == 1800
    if ROUTE["route"] == "fallback":
        assert "pyg-lib" in ROUTE["error"]
    print(f"\n[route] {ROUTE}")


def test_per_seed_causality_and_id_stripping(val, random_val_seeds):
    """1,000 random validation seeds, one per batch: max sampled timestamp <= seed timestamp
    in both stores, and edge_attr[:, 0] (global id) is gone from both stores."""
    va, _, args = val
    full_width = va[TO].edge_attr.shape[1]
    ts_all = va[TO].timestamps
    loader = make_loader(va, random_val_seeds, args, causal=True, batch_size=1, transform=AddEgoIds())
    n, worst = 0, float("-inf")
    for batch in loader:
        mask, seed_global = seed_mask(batch)
        assert seed_global.numel() == 1
        seed_ts = float(ts_all[seed_global])
        for key in (TO, REV):
            st = batch[key]
            assert st.edge_attr.shape[1] == full_width - 1, f"{key}: id column not stripped"
            if st.edge_index.size(1):
                assert not torch.equal(st.edge_attr[:, 0].cpu(), st.e_id.float().cpu()), f"{key}: column 0 is the id"
                mx = float(st.timestamps.max())
                assert mx <= seed_ts, f"{key}: sampled edge at {mx} > seed {seed_ts}"
                worst = max(worst, mx - seed_ts)
        n += 1
    assert n == N_SEEDS
    print(f"\n[per-seed] {n} seeds checked; max(sampled - seed) = {worst:.0f}s (must be <= 0)")


def test_fallback_within_batch_leak(val):
    """Fallback route with full batches: every sampled edge <= max seed of its batch, and
    the within-batch leak (max sampled - min seed) <= 1,800 s. Prints five batches."""
    va, val_inds, args = val
    loader = make_loader(va, val_inds, args, causal=True, transform=AddEgoIds())
    if ROUTE["route"] != "fallback":
        pytest.skip("native route active; window bound not applicable")
    ts_all = va[TO].timestamps
    n_printed = 0
    print()
    for i, batch in enumerate(loader):
        _, seed_global = seed_mask(batch)
        seed_ts = ts_all[seed_global]
        assert float(seed_ts.max() - seed_ts.min()) <= WINDOW_S
        line = [f"batch {i:3d}: seeds {seed_global.numel():5d} window [{float(seed_ts.min()):.0f}, {float(seed_ts.max()):.0f}]"]
        for key in (TO, REV):
            st = batch[key]
            if st.edge_index.size(1) == 0:
                continue
            mx = float(st.timestamps.max())
            assert mx <= float(seed_ts.max()), f"{key}: {mx} > max seed {float(seed_ts.max())}"
            leak = mx - float(seed_ts.min())
            assert leak <= WINDOW_S, f"{key}: within-batch leak {leak}s > {WINDOW_S}s"
            line.append(f"{key[1]}: max ts {mx:.0f} leak {leak:.0f}s")
        if n_printed < 5:
            print("  " + " | ".join(line))
            n_printed += 1
    assert n_printed == 5, "fewer than five batches"


def test_non_causal_reproduces_todays_sampler(val):
    """causal=False == today's LinkNeighborLoader call plus the seed guarantee. With all
    neighbours (deterministic) the sampled edge set of the new loader must equal the old
    one plus the batch's seeds, and every seed attr must be the data's."""
    va, val_inds, args = val
    seeds = val_inds[:200]
    eli = va[TO].edge_index[:, seeds]
    el = va[TO].y[seeds]
    old = LinkNeighborLoader(va, num_neighbors=[-1, -1], edge_label_index=(TO, eli), edge_label=el,
                             batch_size=50, shuffle=False)
    new = make_loader(va, seeds, args, causal=False, batch_size=50, num_neighbors=[-1, -1])
    n = 0
    for ob, nb in zip(old, new):
        assert torch.equal(ob[TO].input_id, nb[TO].input_id)
        seed_global = seeds[nb[TO].input_id]
        for key in (TO, REV):
            want = set(ob[key].e_id.tolist()) | set(seed_global.tolist())
            got = nb[key].e_id.tolist()
            assert len(got) == len(set(got)), f"{key}: duplicate edge in batch"
            assert set(got) == want, f"{key}: sampled edge set differs from today's + seeds"
            assert nb[key].edge_attr.shape[1] == va[key].edge_attr.shape[1] - 1
            assert torch.allclose(nb[key].edge_attr, va[key].edge_attr[nb[key].e_id][:, 1:])
        mask, g = seed_mask(nb)
        assert torch.equal(g, seed_global)
        assert torch.equal(nb[TO].edge_index[:, mask], nb[TO].edge_label_index)
        n += 1
    assert n == 4
