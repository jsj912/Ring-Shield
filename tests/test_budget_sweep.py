"""Unit tests for evaluation/budget_sweep.py (the pipeline itself is checked by reproduction runs)."""
import json

import numpy as np
import pandas as pd
import pytest

bs = pytest.importorskip("evaluation.budget_sweep")
from ringshield.aggregators.cc import seed_mask_for_pct  # noqa: E402


def test_kdir():
    assert bs.kdir(0.1) == "k0.10" and bs.kdir(0.05) == "k0.05" and bs.kdir(0.3) == "k0.30"


def test_seed_mask_monotone_in_k():
    rng = np.random.default_rng(0)
    s = rng.random(100_000)
    prev = None
    for k in bs.K_GRID:
        m = seed_mask_for_pct(s, k)
        if prev is not None:
            assert m.sum() >= prev.sum() and not (prev & ~m).any()
        prev = m


def _cell(root, det, rule, k, S, seeds, rings):
    d = root / det / rule / bs.kdir(k) / f"seed{S}"
    d.mkdir(parents=True)
    (d / "seeds.json").write_text(json.dumps({"seed_edges_in_window": seeds, "touched_rings": rings}))


def test_pair_stats(tmp_path):
    _cell(tmp_path, "a", "global", 0.1, 1, [1, 2, 3], [10, 11])
    _cell(tmp_path, "b", "global", 0.1, 1, [2, 3, 4, 5], [11, 12, 13])
    (r,) = bs.pair_stats(tmp_path, "a", "b", [1], [0.1], ["global"])
    assert r["seed_jaccard"] == pytest.approx(2 / 5)
    assert (r["touched_union"], r["touched_intersection"], r["touched_a"], r["touched_b"]) == (4, 1, 2, 3)


def test_summarise_bars_and_veto():
    rows = []
    for S, (g, m) in enumerate([(0.50, 0.52), (0.52, 0.50), (0.54, 0.55)], start=1):
        for det, f in (("gine_causal", g), ("mega", m)):
            rows.append({"detector": det, "rule": "global", "k_pct": 0.2, "seed": S, "b0_ring_f1": f,
                         "added_member_precision": 0.80 if (det == "mega" and S == 1) else 0.9})
    out = bs.summarise(pd.DataFrame(rows), pd.DataFrame())
    (bar,) = out["tp8_bar"]
    assert bar["mega_minus_gine_b0_f1"] == pytest.approx(np.mean([0.52, 0.50, 0.55]) - np.mean([0.50, 0.52, 0.54]))
    assert bar["holds"] and not bar["fails"]
    assert len(out["veto_rows"]) == 1 and out["veto_rows"][0]["detector"] == "mega"
