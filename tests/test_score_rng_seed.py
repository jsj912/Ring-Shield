"""models/score.py --rng-seed (open item 20): default unseeded, opt-in fixed seed."""
import inspect

import numpy as np
import torch

import models.score as sc


def test_cli_default_is_unseeded():
    a = sc.build_parser().parse_args(["--run-dir", "x", "--seeds", "1", "--splits", "val"])
    assert a.rng_seed is None
    a = sc.build_parser().parse_args(["--run-dir", "x", "--seeds", "1", "--splits", "val", "--rng-seed", "7"])
    assert a.rng_seed == 7


def test_score_signature_defaults_to_none():
    assert inspect.signature(sc.RunScorer.score).parameters["rng_seed"].default is None


def test_fixed_seed_reproduces_draws():
    sc.set_scoring_seed(123); a = (torch.rand(5), np.random.rand(5))
    sc.set_scoring_seed(123); b = (torch.rand(5), np.random.rand(5))
    assert torch.equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_none_leaves_state_untouched():
    torch.manual_seed(5); np.random.seed(5)
    ts, ns = torch.get_rng_state(), np.random.get_state()[1].copy()
    sc.set_scoring_seed(None)
    assert torch.equal(ts, torch.get_rng_state()) and np.array_equal(ns, np.random.get_state()[1])
