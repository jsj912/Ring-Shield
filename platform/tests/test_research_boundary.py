from __future__ import annotations

import ast
from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN_ROOTS = {"ring" + "shield", "torch", "xgboost", "lightgbm", "sklearn"}
TRUTH_TOKEN = "ring_" + "ground_truth"


def scan_platform_sources(root: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.parts
        if parts[0] == "adapters" or parts[0] in {"scripts", "experiments"}:
            continue
        if relative.as_posix() == "jobs/simulate_verdicts.py":
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, SyntaxError) as exc:
            failures.append(f"{relative}: cannot inspect source: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".", 1)[0]]
            else:
                roots = []
            for module in roots:
                if module in FORBIDDEN_ROOTS:
                    failures.append(f"{relative}:{node.lineno}: forbidden research import {module}")
        truth_literals = [
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        if any(TRUTH_TOKEN in value for value in truth_literals):
            failures.append(f"{relative}: ground-truth file access is restricted to adapters and experiment scripts")
    return failures


def test_platform_research_import_and_ground_truth_boundary():
    assert scan_platform_sources(PLATFORM_ROOT) == []


def test_boundary_scanner_detects_forbidden_import_and_truth_path(tmp_path):
    module = tmp_path / "rogue.py"
    truth_path = "amlworld" + "_" + "ring" + "_" + "ground_truth.parquet"
    module.write_text(f"import torch\npath = {truth_path!r}\n", encoding="utf-8")

    failures = scan_platform_sources(tmp_path)

    assert any("forbidden research import torch" in failure for failure in failures)
    assert any("ground-truth file access" in failure for failure in failures)


def test_worker_has_no_api_imports_and_api_does_not_reach_worker_or_xai():
    import ast

    worker = (PLATFORM_ROOT / "jobs" / "regenerate_worker.py").read_text(encoding="utf-8")
    assert "api." not in worker
    api_root = PLATFORM_ROOT / "api"
    forbidden_api_secrets = {
        "RINGSHIELD_XAI_TOKEN", "RINGSHIELD_LOADER_DATABASE_URL",
    }
    for path in api_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for secret in forbidden_api_secrets:
            assert secret not in source
        tree = ast.parse(source, filename=str(path))
        imported_modules = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        imported_modules.update(
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name == "jobs.regenerate_worker" or name.startswith("jobs.regenerate_worker.")
                       for name in imported_modules)
        assert not any(name == "adapters.xai" or name.startswith("adapters.xai.")
                       for name in imported_modules)
