from __future__ import annotations

from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from settings import load_platform_config


def test_environment_config_switch_uses_each_resolved_path(monkeypatch):
    demo_config = PLATFORM_ROOT / "tests" / "isolation" / "config.test.yaml"
    repo_config = PLATFORM_ROOT / "config.yaml"

    monkeypatch.setenv("RINGSHIELD_PLATFORM_CONFIG", str(demo_config))
    assert load_platform_config()["active_model_id"] == "demo-model"

    monkeypatch.setenv("RINGSHIELD_PLATFORM_CONFIG", str(repo_config))
    assert load_platform_config()["active_model_id"] == "gine_causal"
