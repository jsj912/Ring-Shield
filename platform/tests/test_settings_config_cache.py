from __future__ import annotations

from pathlib import Path
import sys

import pytest

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
    assert load_platform_config()["l4"]["rings_schema_version"] == 1


def test_worker_and_l4_environment_overrides_are_process_local(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_WORKER_MODE", "supervisor")
    monkeypatch.setenv("RINGSHIELD_L4_REGENERATE_URL", "http://127.0.0.1:9000/regenerate")

    config = load_platform_config()

    assert config["worker_mode"] == "supervisor"
    assert config["l4"]["regenerate_url"] == "http://127.0.0.1:9000/regenerate"


def test_worker_mode_environment_override_rejects_unknown_value(monkeypatch):
    monkeypatch.setenv("RINGSHIELD_WORKER_MODE", "inline")

    with pytest.raises(RuntimeError, match="worker_mode must be spawn or supervisor"):
        load_platform_config()


@pytest.mark.parametrize("l4_config", [None, {}, {"rings_schema_version": "1"},
                                       {"rings_schema_version": True},
                                       {"rings_schema_version": 3}])
def test_l4_rings_schema_version_is_required_and_validated(tmp_path, l4_config):
    from settings import load_platform_config

    config_path = tmp_path / "config.yaml"
    contents = "active_model_id: demo\nactive_seed: 1\n"
    if l4_config is not None:
        import yaml

        contents += yaml.safe_dump({"l4": l4_config})
    config_path.write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"l4.rings_schema_version"):
        load_platform_config(str(config_path))
