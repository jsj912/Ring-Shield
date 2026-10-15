"""`roles_for_edges(currency=)` and detector-aware `features_degraded`.

Two independent claims are under test:

1. `roles_for_edges` and `account_roles` agree on the same edge set, in every currency mode,
   because they run the same code. The `raw` default must also stay byte-identical, since every
   typing-head feature and truth-ring row published so far was computed with it.
2. `features_degraded` reflects the affinity's OWN feature list. An affinity trained without
   embeddings is not degraded by their absence; one trained with them is.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths                      # noqa: E402
from baselines.refit_data import GFP_COLS                            # noqa: E402
from ringshield.partition.affinity import Affinity                      # noqa: E402
from ringshield.partition.pairs import FEATURE_GROUPS, PAIR_FEATURES    # noqa: E402
from ringshield.roles import (                                          # noqa: E402
    CURRENCY_MODES,
    RingRerunner,
    account_roles,
    load_roles_config,
    missing_affinity_features,
    rerun_ring,
)
from ringshield.typing.truth_rings import roles_for_edges               # noqa: E402

FX = REPO_ROOT / "contract" / "fx_rates.json"
SE_COLS = ["edge_id", "from_id", "to_id", "timestamp", "amount_sent", "amount_received",
           "currency_sent", "currency_received", "score_calibrated", "score_raw", "is_seed"]


def same_record(x: dict, y: dict) -> bool:
    """Role records compare equal including NaN: hold_time_s is NaN whenever a side has no edges,
    and `nan != nan`, so a plain dict comparison reports a difference that is not one."""
    if set(x) != set(y):
        return False
    for k in x:
        a, b = x[k], y[k]
        if isinstance(a, float) and isinstance(b, float):
            if math.isnan(a) and math.isnan(b):
                continue
        if a != b:
            return False
    return True


def emb_store(df: pd.DataFrame, dim: int = 4):
    """A real EmbeddingStore. `ctx.emb.get()` is called with an ARRAY of edge ids, so a plain
    {edge_id: vector} dict raises `unhashable type: numpy.ndarray` deep inside the pair builder."""
    from ringshield.expand.features import EmbeddingStore
    ids = df["edge_id"].to_numpy(np.int64)
    # distinct rows, so cos_emb is not degenerate and the affinity sees real variation
    mat = np.eye(len(ids), dim, dtype=np.float32) + 0.01
    return EmbeddingStore(ids, mat)


def gfp_frame(df: pd.DataFrame) -> pd.DataFrame:
    """A GFP slice shaped the way the pair builder expects: an EdgeID column plus every GFP_COL."""
    g = pd.DataFrame({"EdgeID": df["edge_id"].to_numpy()})
    for c in GFP_COLS:
        g[c] = 0.0
    return g


def edges(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "timestamp", "amount_sent",
                                     "amount_received", "currency_sent", "currency_received"])
    df["score_calibrated"] = 0.9
    df["score_raw"] = 0.9
    df["is_seed"] = True
    return df[SE_COLS]


class FakeRing:
    """Covers exactly the whole edge set, so account_roles and roles_for_edges see the same rows."""
    def __init__(self, df):
        self.member_edges = [int(x) for x in df["edge_id"]]
        self.seed_edges = list(self.member_edges)
        self.expanded_edges = []
        self.start_time = int(df["timestamp"].min())
        self.end_time = int(df["timestamp"].max())
        self.members = sorted(set(df["from_id"]) | set(df["to_id"]))


FIXTURES = {
    "single currency": [(1, 10, 11, 0, 900.0, 900.0, 0, 0),
                        (2, 11, 12, 3600, 880.0, 880.0, 0, 0),
                        (3, 12, 13, 7200, 870.0, 870.0, 0, 0)],
    "cross currency": [(1, 9, 10, 0, 1000.0, 1000.0, 0, 0),
                       (2, 10, 11, 3600, 1000.0, 853.4, 0, 2),
                       (3, 11, 12, 7200, 853.4, 853.4, 2, 2)],
    "self-loop conversion": [(1, 9, 10, 0, 500.0, 500.0, 0, 0),
                             (2, 10, 10, 1800, 500.0, 426.7, 0, 2),
                             (3, 10, 11, 3600, 426.7, 426.7, 2, 2)],
}


# --------------------------------------------------------------------------- item 1
@pytest.mark.parametrize("mode", CURRENCY_MODES)
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_roles_for_edges_agrees_with_account_roles(mode, name):
    if mode == "converted" and not FX.exists():
        pytest.skip("contract/fx_rates.json not on disk")
    df = edges(FIXTURES[name])
    cfg = load_roles_config()
    a = account_roles(FakeRing(df), df, edges="member", config=cfg, currency=mode)
    b = roles_for_edges(df, cfg, currency=mode)
    assert set(a) == set(b), f"{name}/{mode}: different account sets"
    for acc in a:
        assert same_record(a[acc], b[acc]), f"{name}/{mode}: account {acc}: {a[acc]} vs {b[acc]}"


def test_roles_for_edges_defaults_to_raw():
    """The default must not change: the typing head's training set was built with it."""
    df = edges(FIXTURES["cross currency"])
    cfg = load_roles_config()
    x, y = roles_for_edges(df, cfg), roles_for_edges(df, cfg, currency="raw")
    assert set(x) == set(y) and all(same_record(x[a], y[a]) for a in x)


def test_an_unknown_currency_mode_is_refused():
    df = edges(FIXTURES["single currency"])
    with pytest.raises(AssertionError, match="currency must be one of"):
        roles_for_edges(df, currency="nonsense")


@pytest.mark.skipif(not FX.exists(), reason="contract/fx_rates.json not on disk")
def test_converted_differs_from_raw_on_a_conversion():
    """Guards against the agreement above being vacuous."""
    df = edges(FIXTURES["self-loop conversion"])
    cfg = load_roles_config()
    raw = roles_for_edges(df, cfg, currency="raw")
    con = roles_for_edges(df, cfg, currency="converted")
    assert any(raw[a]["outflow"] != con[a]["outflow"] for a in raw), (
        "converted booked the same flows as raw on a self-loop conversion")


# --------------------------------------------------------------------------- item 3
def affinity_with(features: list[str]) -> Affinity:
    return Affinity(features)


def test_an_affinity_without_cos_emb_is_not_degraded_without_embeddings():
    """The gfpxgb case: its affinity was trained without embeddings, so their absence is not a gap."""
    aff = affinity_with([f for f in PAIR_FEATURES if f != "cos_emb"])
    assert missing_affinity_features(aff, gfp=pd.DataFrame({"x": [1]}), emb=None) == []


def test_an_affinity_with_cos_emb_is_degraded_without_embeddings():
    """The gine case: same call, opposite verdict."""
    aff = affinity_with(list(PAIR_FEATURES))
    assert missing_affinity_features(aff, gfp=pd.DataFrame({"x": [1]}), emb=None) == ["cos_emb"]


def test_missing_gfp_is_reported_for_both():
    for feats in (PAIR_FEATURES, [f for f in PAIR_FEATURES if f != "cos_emb"]):
        got = missing_affinity_features(affinity_with(list(feats)), gfp=None, emb=object())
        assert got == ["cos_gfp"]


def test_the_mapping_comes_from_the_pair_feature_groups():
    """So a new feature group cannot be added without this following it."""
    assert FEATURE_GROUPS["embedding"] == ["cos_emb"]
    assert FEATURE_GROUPS["gfp"] == ["cos_gfp"]
    for group in ("embedding", "gfp"):
        for f in FEATURE_GROUPS[group]:
            assert f in PAIR_FEATURES


def test_no_affinity_means_nothing_missing():
    assert missing_affinity_features(None, gfp=None, emb=None) == []


@pytest.mark.parametrize("detector,drop_emb,expect_degraded", [
    ("gfpxgb", True, False),
    ("gine_causal", True, True),
    ("gfpxgb", False, False),
    ("gine_causal", False, False),
])
def test_rerun_ring_reports_degradation_per_detector(detector, drop_emb, expect_degraded):
    exp = load_paths()["experiments_dir"]
    d = {"gfpxgb": exp / "R6_gfpxgb_partition" / "affinity_gfpxgb",
         "gine_causal": exp / "R4_partition" / "affinity"}[detector]
    if not (d / "affinity.txt").exists():
        pytest.skip(f"{d} not on disk")
    # Affinity.load, not Affinity(features): a features-only instance has booster=None, and the
    # grouping calls .predict(). The feature LIST is what decides degradation, but the rerun still
    # has to run.
    aff = Affinity.load(d)
    df = edges(FIXTURES["single currency"])
    gfp = gfp_frame(df)
    emb = None if drop_emb else emb_store(df)
    rr = RingRerunner(df, "full", affinity=aff, gfp=gfp, emb=emb)
    assert rr.features_degraded is expect_degraded, (
        f"{detector}, emb={'absent' if drop_emb else 'present'}: "
        f"degraded={rr.features_degraded}, missing={rr.missing_features}")
    out = rr.run()
    assert out["features_degraded"] is expect_degraded
    assert ("cos_emb" in out["missing_features"]) is (expect_degraded and drop_emb)


def test_cc_is_never_degraded():
    df = edges(FIXTURES["single currency"])
    out = rerun_ring(df, "cc")
    assert out["features_degraded"] is False and out["missing_features"] == []


# --------------------------------------------------------------------------- the latency budget
def test_leave_one_out_p95_stays_under_50ms():
    """Kept from the Step 8 budget: p95, not the mean."""
    exp = load_paths()["experiments_dir"]
    d = exp / "R4_partition" / "affinity"
    if not (d / "affinity.txt").exists():
        pytest.skip(f"{d} not on disk")
    aff = Affinity.load(d)
    n = 30
    rows = [(i + 1, 100 + (i % 10), 100 + ((i + 1) % 10), i * 600, 1000.0 - i, 1000.0 - i, 0, 0)
            for i in range(n)]
    df = edges(rows)
    gfp = gfp_frame(df)
    rr = RingRerunner(df, "full", affinity=aff, gfp=gfp, emb=emb_store(df))
    rr.run()                                                   # warm the caches
    times = []
    for e in df["edge_id"]:
        t0 = time.perf_counter()
        rr.without(int(e))
        times.append((time.perf_counter() - t0) * 1000.0)
    p95 = float(np.percentile(times, 95))
    assert p95 <= 50.0, f"p95 {p95:.1f} ms over {n} leave-one-out calls (budget 50 ms)"
