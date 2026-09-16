"""Step 3a: the seed-mask defect is fixed -- scored edges == seed edges exactly, zero NaN.

    python -m pytest tests/test_seed_mask.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from torch_geometric.nn import to_hetero

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.causal_loader import TO, make_loader, seed_mask  # noqa: E402
from models.tgn import AddEgoIds, GINe, _get_mask_and_clean, evaluate  # noqa: E402


@pytest.fixture(scope="module")
def setup(dry_data):
    tr, va, te, tr_inds, val_inds, te_inds, te_meta, args = dry_data
    torch.manual_seed(1)
    sample = next(iter(make_loader(va, val_inds[:64], args, causal=False, transform=AddEgoIds())))
    n_feats = sample["node"].x.shape[1]
    e_dim = sample[TO].edge_attr.shape[1]
    model = GINe(num_features=n_feats, num_gnn_layers=args.n_gnn_layers, n_classes=2, n_hidden=args.n_hidden,
                 edge_updates=args.emlps, edge_dim=e_dim, dropout=args.dropout, final_dropout=args.final_dropout)
    model = to_hetero(model, va.metadata(), aggr="mean").eval()
    return va, te, val_inds, te_inds, args, model


@pytest.mark.parametrize("causal", [False, True])
def test_every_seed_scored_exactly_once(setup, causal):
    va, te, val_inds, te_inds, args, _ = setup
    for data, inds in ((va, val_inds), (te, te_inds)):
        loader = make_loader(data, inds, args, causal=causal, batch_size=2048, transform=AddEgoIds())
        seen = []
        for batch in loader:
            mask, seed_global = _get_mask_and_clean(batch, loader, inds, True)
            assert int(mask.sum()) == seed_global.numel() == batch[TO].input_id.numel()
            assert torch.equal(batch[TO].e_id[mask], seed_global)
            seen.append(seed_global)
        seen = torch.cat(seen)
        assert seen.numel() == inds.numel(), "not every seed was scored"
        assert torch.equal(torch.sort(seen)[0], torch.sort(inds)[0]), "scored set != seed set"


@pytest.mark.parametrize("causal", [False, True])
def test_model_forward_scores_all_seeds_no_nan(setup, causal):
    va, te, val_inds, te_inds, args, model = setup
    loader = make_loader(va, val_inds, args, causal=causal, batch_size=2048, transform=AddEgoIds())
    n_scored = 0
    with torch.no_grad():
        for batch in loader:
            mask, seed_global = seed_mask(batch)
            out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)[TO]
            probs = torch.softmax(out[mask], dim=-1)[:, 1]
            assert probs.numel() == seed_global.numel()
            assert not torch.isnan(probs).any()
            n_scored += probs.numel()
    assert n_scored == val_inds.numel()


@pytest.mark.parametrize("causal", [False, True])
def test_evaluate_returns_one_row_per_seed_in_inds_order(setup, causal):
    """tgn.evaluate: len == len(inds), no NaN, labels aligned to inds order."""
    va, te, val_inds, te_inds, args, model = setup
    loader = make_loader(va, val_inds, args, causal=causal, batch_size=2048, transform=AddEgoIds())
    metrics, preds, gts, probs = evaluate(loader, val_inds, model, torch.device("cpu"), True, threshold=0.5)
    assert len(preds) == len(gts) == len(probs) == val_inds.numel()
    assert not np.isnan(probs).any()
    assert np.array_equal(gts, va[TO].y[val_inds].numpy()), "outputs are not in inds order"
    assert 0.0 <= metrics["average_precision"] <= 1.0


def test_score_test_set_mask_and_ids(setup):
    from score_test_set import mask_and_ids
    va, te, val_inds, te_inds, args, _ = setup
    loader = make_loader(te, te_inds, args, causal=False, batch_size=4096, transform=AddEgoIds())
    got = []
    for batch in loader:
        mask, ids = mask_and_ids(batch, loader, te_inds, True)
        assert int(mask.sum()) == ids.numel()
        got.append(ids)
    got = torch.cat(got)
    assert torch.equal(torch.sort(got)[0], torch.sort(te_inds)[0])
    assert got.numel() == torch.unique(got).numel()
