from __future__ import annotations

import ast
from pathlib import Path


APP_FILE = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


def test_dashboard_imports_sibling_regeneration_flow_without_package_prefix():
    tree = ast.parse(APP_FILE.read_text(encoding="utf-8"))
    local_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "regeneration_flow" in local_imports
    assert "dashboard.regeneration_flow" not in local_imports
