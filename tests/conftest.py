"""Shared fixtures: the 1% dry-run graph built exactly as models/tgn.py builds it
(edge MLP inputs, ports, time deltas, reverse MP, ego ids, GFP), on CPU."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import load_paths  # noqa: E402

PATHS = load_paths()


def make_args(**over):
    a = types.SimpleNamespace(
        raw_dir=PATHS["raw_dir"], data_dir=PATHS["processed_dir"],
        emlps=True, ports=True, tds=True, reverse_mp=True, ego=True, gfp=True,
        num_neighs=[100, 100], batch_size=8192, n_hidden=66, n_gnn_layers=2,
        dropout=0.01, final_dropout=0.1, causal=False, dry_run=True, dry_run_seed=1,
    )
    for k, v in over.items():
        setattr(a, k, v)
    return a


@pytest.fixture(scope="session")
def dry_data():
    """(tr_data, val_data, te_data, tr_inds, val_inds, te_inds, te_meta, args) on 1% of rows."""
    fmt = PATHS["raw_dir"] / "formatted_transactions.csv"
    gfp = PATHS["processed_dir"] / "amlworld_gfp_features_val.parquet"
    if not (fmt.exists() and gfp.exists()):
        pytest.skip("formatted_transactions.csv / GFP parquets not on disk")
    from models.tgn import load_data
    args = make_args()
    torch.manual_seed(1)
    out = load_data(args.raw_dir, args.data_dir, args)
    return (*out, args)
