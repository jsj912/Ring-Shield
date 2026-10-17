from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import sys

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from settings import load_l6_config, load_platform_config


def test_l6_settings_resolve_paths_after_required_artifact_locations_are_provided():
    config = deepcopy(load_platform_config())
    config["l6"]["retrain"].update({
        "val_gfp": "data/val_gfp.parquet",
        "val_embeddings": "data/val_embeddings.parquet",
        "truth_parquet": "data/amlworld_ring_ground_truth.parquet",
    })
    l6 = load_l6_config(config)

    assert l6["simulator"]["review_fraction"] == 0.05
    assert l6["retrain"]["components"] == ["expansion", "affinity"]
    assert l6["paths"]["val_scored_edges"].name == "scored_edges_gine_causal_1_val.parquet"


def test_default_l6_settings_fail_clearly_for_unavailable_val_gfp():
    with pytest.raises(RuntimeError, match="l6.retrain.val_gfp"):
        load_l6_config(load_platform_config())


def test_l6_config_names_an_unavailable_required_path():
    config = deepcopy(load_platform_config())
    config["l6"]["retrain"]["val_gfp"] = None

    with pytest.raises(RuntimeError, match="l6.retrain.val_gfp"):
        load_l6_config(config)


def test_l6_retraining_cannot_add_typing_without_verdict_labels():
    config = load_platform_config()
    config["l6"]["retrain"]["components"] = ["expansion", "affinity", "typing"]

    with pytest.raises(RuntimeError, match="typing has no verdict label"):
        load_l6_config(config)
