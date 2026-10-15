"""Week 3 SHAP feature weights (spec 4.4, XR-13 / XR-14)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xgboost as xgb
import yaml

from explainability.contract_io import load_config, repo_path
from explainability.feature_weights import (FeatureExplainer, load_feature_model, load_feature_rows, model_features,
                                            ring_feature_weights, verify_rows)

CFG = load_config()
SEEDS = CFG["inputs"]["seeds"]


def _seed_edge_ids(seed: int) -> list[int]:
    rings = pd.read_parquet(repo_path(CFG["inputs"]["rings"].format(seed=seed)), columns=["seed_edges"])
    return sorted({int(e) for l in rings.seed_edges for e in l})


@pytest.fixture(scope="module")
def seed1():
    booster = load_feature_model(CFG, 1)
    ids = _seed_edge_ids(1)
    rows = load_feature_rows(CFG, booster, ids)
    return booster, ids, rows, FeatureExplainer(booster, rows)


@pytest.mark.parametrize("seed", SEEDS)
def test_feature_order_is_the_model_files_and_the_refit_config(seed):
    """XR-13: the 17 features, in the model file's order, equal the research refit's feature_cols."""
    refit = yaml.safe_load(repo_path("experiments/R2_b0/gfpxgb_scores/config.yaml").read_text(encoding="utf-8"))
    feats = model_features(load_feature_model(CFG, seed))
    assert feats == refit["feature_cols"] and len(feats) == 17


@pytest.mark.parametrize("seed", SEEDS)
def test_rows_reproduce_the_shipped_scores_on_every_seed_edge(seed):
    """Our feature rows ARE the model's training-style input: predictions equal the shipped scores exactly."""
    booster = load_feature_model(CFG, seed)
    rows = load_feature_rows(CFG, booster, _seed_edge_ids(seed))
    assert list(rows.columns) == model_features(booster)
    assert verify_rows(booster, rows, CFG["feature_weights"]["shipped_scores"].format(seed=seed)) < 1e-7


def test_rows_come_from_researchs_loader_and_a_missing_edge_is_refused():
    """Since v2 b35b233 the rows come from baselines/refit_data.py (Joan's loader, importable without optuna);
    its feature list must equal the model file's. Its own asserts refuse a non-trailing GFP file."""
    from baselines import refit_data
    booster = load_feature_model(CFG, 1)
    assert refit_data.REFIT_TABULAR + refit_data.GFP_COLS == model_features(booster)
    with pytest.raises(ValueError, match="no feature row"):
        load_feature_rows(CFG, booster, [-1])


def test_shap_adds_up_to_the_model_output(seed1):
    """base + sum of the 17 contributions = the model's raw output, for every seed edge."""
    _, ids, _, fx = seed1
    sv = fx.shap_values(ids)
    gap = np.abs(sv.sum(axis=1).to_numpy() + fx.expected_value - fx.margin(ids))
    assert gap.max() < float(CFG["feature_weights"]["additivity_tolerance"])


def test_shap_equals_xgboosts_own_contributions(seed1):
    booster, ids, rows, fx = seed1
    own = booster.predict(xgb.DMatrix(rows.to_numpy(), feature_names=fx.features), pred_contribs=True)
    assert np.abs(fx.shap_values(ids).to_numpy() - own[:, :-1]).max() < 1e-6
    assert np.ptp(own[:, -1]) == 0 and fx.expected_value == pytest.approx(float(own[0, -1]))


def test_ring_feature_weights_by_hand():
    """Mean per feature, sorted by |mean|; the top edge is the largest |value|; ties -> feature order / smaller id."""
    sv = pd.DataFrame({"a": [0.2, 0.4], "b": [-1.0, 0.0], "c": [0.3, -0.3], "d": [0.5, -0.5]},
                      index=pd.Index([20, 10], name="edge_id"))
    fw = ring_feature_weights(sv, top_n=3)
    assert [f["feature_name"] for f in fw] == ["b", "a", "c"]          # |-0.5|, 0.3, then c before d (both 0)
    assert fw[0] == {"feature_name": "b", "mean_shap": -0.5, "top_edge_id": 20}
    assert fw[1]["mean_shap"] == pytest.approx(0.3) and fw[1]["top_edge_id"] == 10
    assert fw[2]["top_edge_id"] == 10                                  # |0.3| on both edges -> smaller id
    assert ring_feature_weights(sv.iloc[:0], top_n=3) == []


def test_snapshot_of_one_real_ring(seed1):
    """XR-14 snapshot: ring full-gine_causal-1-15 (16 seed edges), top 10 as computed on 2026-10-15."""
    rings = pd.read_parquet(repo_path(CFG["inputs"]["rings"].format(seed=1)), columns=["ring_id", "seed_edges"])
    seeds = rings.set_index("ring_id").loc["full-gine_causal-1-15", "seed_edges"]
    got = [(f["feature_name"], round(f["mean_shap"], 6), f["top_edge_id"])
           for f in ring_feature_weights(seed1[3].shap_values(seeds), top_n=CFG["feature_weights"]["top_n"])]
    assert got == [("Payment Format", 2.611266, 5077996), ("scatter_gather", 1.440621, 5077996),
                   ("hour_of_day", -1.056723, 5077910), ("fan_out", -0.881275, 5077910),
                   ("Amount Sent", -0.77839, 5078119), ("Amount Received", -0.751811, 5077334),
                   ("deg_out_src", -0.582904, 5078181), ("day_of_week", 0.56608, 5077648),
                   ("deg_out_dst", -0.457488, 5077334), ("Sent Currency", -0.343286, 5077286)]
