"""R11's seed config is dumped to YAML: the Path that load_platform_config adds must not reach it."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest
import yaml

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from experiments import r11_seed_config  # noqa: E402
from settings import load_platform_config  # noqa: E402


def test_a_loaded_platform_config_dumps_as_a_seed_config():
    if not (r11_seed_config.REPO_ROOT / "contract/out/scored_edges_gine_causal_1.parquet.log.json").is_file():
        pytest.skip("seed-1 score log is not present")
    config = r11_seed_config.seed_config(1, load_platform_config(r11_seed_config.BASE_CONFIG))
    assert "_path" not in config
    assert yaml.safe_load(yaml.safe_dump(config, sort_keys=False))["active_seed"] == 1
