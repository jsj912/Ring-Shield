"""`--train-label-days` removes training supervision without removing graph history (V3.3 C').

The C' arm trains the detector on HI-Medium days 1-3 instead of 0-3, because day 0 is 48.8 % of
C1's training edges at ~0.27x the laundering base rate (`FINDINGS` C8) and C1's seed-1 detector
failed the Amendment 4 adequacy gate. The point of the flag is a *narrow* one: day 0 must stop
being a supervised example while remaining in the message-passing graph as causal history, so
the sampler can still walk it and the ports / time-delta / GFP features still see it.

Those are two different things and it is easy to implement one and believe you have both. This
asserts them separately:

    1. day-0 edges are ABSENT from the training seed edges (`tr_inds`), and
    2. day-0 edges are PRESENT in the graph the loader samples (`tr_data.edge_index`),

plus that val and test are untouched, that the excluded labels are not silently zeroed, and that
the default (flag absent) reproduces the unrestricted behaviour exactly.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import load_paths  # noqa: E402

SECONDS_PER_DAY = 86400


def _args(**kw):
    base = dict(gfp=False, ports=False, tds=False, reverse_mp=False, ego=False, emlps=False,
                causal=False, dry_run=False, dry_run_seed=1, split_days=None,
                hold_out_pattern=None, feature_cache=None, train_label_days=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _day(ts) -> np.ndarray:
    return (np.asarray(ts, dtype=np.int64) - 10) // SECONDS_PER_DAY


@pytest.fixture(scope="module")
def paths():
    p = load_paths()
    if not (p["raw_dir"] / "formatted_transactions.csv").exists():
        pytest.skip("formatted_transactions.csv not present")
    return p


def _load(paths, **kw):
    pytest.importorskip("torch")
    from models.tgn import load_data
    return load_data(paths["raw_dir"], paths["processed_dir"], _args(**kw))


def _train_day_range(paths):
    """The split's training days, so the test works on whichever dataset is selected."""
    tr, _, _, tr_inds, _, _, meta = _load(paths)
    days = np.unique(_day(meta["Timestamp"].to_numpy()[tr_inds.numpy()]))
    return int(days.min()), int(days.max())


def test_day0_excluded_from_seeds_but_present_in_graph(paths):
    lo, hi = _train_day_range(paths)
    if hi <= lo:
        pytest.skip(f"training block is a single day ({lo}); nothing to exclude")

    full = _load(paths)
    cut = _load(paths, train_label_days=[lo + 1, hi])
    tr_full, tr_cut = full[0], cut[0]
    inds_full, inds_cut = full[3].numpy(), cut[3].numpy()
    ids = full[6]["EdgeID"].to_numpy()
    ts = full[6]["Timestamp"].to_numpy()

    # 1. the excluded day is gone from the TRAINING SEED EDGES
    seed_days_cut = np.unique(_day(ts[inds_cut]))
    assert lo not in seed_days_cut, f"day {lo} still a training seed"
    assert set(seed_days_cut) == set(range(lo + 1, hi + 1)), seed_days_cut
    assert len(inds_cut) < len(inds_full), "nothing was excluded"

    # 2. the excluded day is STILL IN THE GRAPH the sampler walks
    assert tr_cut.edge_index.shape[1] == tr_full.edge_index.shape[1], \
        "train graph changed size; day-0 history was dropped, not just its supervision"
    assert tr_cut.num_nodes == tr_full.num_nodes
    import torch
    assert torch.equal(tr_cut.edge_index, tr_full.edge_index), "train graph edges differ"
    assert torch.equal(tr_cut.timestamps, tr_full.timestamps), "train graph timestamps differ"
    graph_days = np.unique(_day(tr_cut.timestamps.numpy()))
    assert lo in graph_days, f"day {lo} missing from the sampled graph"

    # 3. the excluded edges keep their labels -- they are unsupervised, not relabelled licit
    assert torch.equal(tr_cut.y, tr_full.y), "labels were altered; exclusion must not zero them"

    # 4. val and test are untouched
    assert np.array_equal(full[4].numpy(), cut[4].numpy()), "val seeds changed"
    assert np.array_equal(full[5].numpy(), cut[5].numpy()), "test seeds changed"
    assert np.array_equal(ids, cut[6]["EdgeID"].to_numpy()), "edge_meta changed"


def test_default_is_unrestricted(paths):
    """Absent flag must reproduce the old behaviour: seeds == every train edge."""
    import torch
    _, _, _, tr_inds, _, _, _ = _load(paths)
    assert torch.equal(tr_inds, torch.arange(tr_inds.shape[0])), \
        "without --train-label-days the train seeds must be arange(n_train)"


def test_rejects_empty_day_range(paths):
    lo, hi = _train_day_range(paths)
    with pytest.raises(AssertionError, match="keeps no training day"):
        _load(paths, train_label_days=[hi + 10, hi + 20])
