"""A scored split must contain exactly the edges of the corresponding split parquet (Step V3.3).

`models/tgn.py::load_data` decides train/val/test by day boundaries. Until V3.3 it always
searched for the 60/20/20 day split, while `preprocessing/amlworld_loader.py` wrote the split
parquets from whatever boundaries *it* was given. On HI-Small the two agree because both run the
same search on the same data; on HI-Medium, whose split is chosen by ring observability rather
than edge proportion (`docs/V3_OBSERVABILITY.md`), the search picks train days 0-8 where the
parquets say 0-3.

That disagreement is silent in the worst way: the detector trains on one edge set and every
downstream stage joins its scores to a different one. The only reason it was caught at all is
that the GFP features are keyed by split, so the reindex found rows missing. Without GFP enabled
it would have produced plausible, wrong numbers.

So this asserts the contract directly, in both directions:

    the edge ids `load_data` assigns to a split  ==  the EdgeIDs of amlworld_<split>.parquet

and that `models/score.py::args_from_run_config` carries `split_days` out of a run config, which
is what makes the scoring and cross-scoring stages agree with training.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.score import args_from_run_config  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402

SPLITS = ("train", "val", "test")


def _write_cfg(tmp: Path, split_days) -> Path:
    cfg = {"experiment": "t", "model": "Multi-GINe v2", "arch": "gine",
           "adaptations": ["edge_MLPs", "ports", "time_deltas", "reverse_MP", "ego_IDs",
                           "GFP_features"],
           "seeds": [1], "epochs": 1, "patience": 20, "batch_size": 8192, "lr": 0.006,
           "n_hidden": 66, "n_gnn_layers": 2, "w_ce1": 1.0, "w_ce2": 9.0,
           "num_neighbors": [100, 100], "causal_sampling": True,
           "loader_route": "fallback", "loader_window_s": 1800, "dry_run": False,
           "split_days": split_days}
    (tmp / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
    return tmp


@pytest.mark.parametrize("split_days", [None, [4, 6]])
def test_args_from_run_config_carries_split_days(tmp_path, split_days):
    """Whatever the run recorded has to come back out, or scoring re-runs the day search."""
    run = _write_cfg(tmp_path, split_days)
    a, cfg = args_from_run_config(run, dry_run=False, dry_run_seed=1)
    assert getattr(a, "split_days", "MISSING") == split_days
    assert cfg["split_days"] == split_days


def test_absent_split_days_means_none(tmp_path):
    """A config written before V3.3 has no `split_days` key; that must mean 'search', not crash."""
    run = _write_cfg(tmp_path, None)
    raw = yaml.safe_load((run / "config.yaml").read_text(encoding="utf-8"))
    del raw["split_days"]
    (run / "config.yaml").write_text(yaml.dump(raw, sort_keys=False), encoding="utf-8")
    a, _ = args_from_run_config(run, dry_run=False, dry_run_seed=1)
    assert a.split_days is None


def _day_bounds_from_parquets(pdir: Path):
    """The split boundaries the parquets actually imply, as (i, j) day indices."""
    lo_hi = {}
    for s in SPLITS:
        ts = pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=["Timestamp"])["Timestamp"]
        lo_hi[s] = (int(ts.min()) // 86400, int(ts.max()) // 86400)
    return lo_hi[SPLITS[1]][0], lo_hi[SPLITS[2]][0]


@pytest.mark.parametrize("split", SPLITS)
def test_scored_split_edge_set_equals_parquet(split):
    """`load_data`'s split must be the parquet's split, edge for edge.

    Run against whichever dataset `RINGSHIELD_PATHS` selects, so the same test covers HI-Small
    (where the day search happens to agree) and HI-Medium (where it does not).
    """
    torch = pytest.importorskip("torch")
    pdir = load_paths()["processed_dir"]
    raw_dir = load_paths()["raw_dir"]
    for p in (pdir / f"amlworld_{split}.parquet", raw_dir / "formatted_transactions.csv"):
        if not p.exists():
            pytest.skip(f"{p} not present")

    from models.tgn import load_data

    i, j = _day_bounds_from_parquets(pdir)
    args = type("A", (), {})()
    for k, v in dict(gfp=False, ports=False, tds=False, reverse_mp=False, ego=False,
                     emlps=False, causal=False, dry_run=False, dry_run_seed=1,
                     split_days=[i, j], hold_out_pattern=None).items():
        setattr(args, k, v)
    _, _, _, tr_inds, val_inds, te_inds, edge_meta = load_data(raw_dir, pdir, args)

    got = {"train": tr_inds, "val": val_inds, "test": te_inds}
    ids = edge_meta["EdgeID"].to_numpy()
    want = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=["EdgeID"])["EdgeID"]
    got_ids = np.sort(ids[got[split].numpy()])
    assert len(got_ids) == len(want), (
        f"{split}: load_data gave {len(got_ids)} edges, parquet has {len(want)}")
    assert np.array_equal(got_ids, np.sort(want.to_numpy())), \
        f"{split}: load_data's edge set differs from amlworld_{split}.parquet"
