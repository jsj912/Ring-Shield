from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
DASHBOARD_ROOT = PLATFORM_ROOT / "dashboard"


def test_streamlit_style_path_imports_every_dashboard_module():
    local_modules = sorted(path.stem for path in DASHBOARD_ROOT.glob("*.py"))
    parent_sys_path = list(sys.path)
    script = "\n".join((
        "import importlib, os, sys",
        f"dashboard = {str(DASHBOARD_ROOT)!r}",
        f"repo = {str(REPO_ROOT)!r}",
        f"platform = {str(PLATFORM_ROOT)!r}",
        f"working_directory = {str(REPO_ROOT)!r}",
        f"parent_paths = {parent_sys_path!r}",
        "prefix = os.path.normcase(os.path.realpath(sys.prefix))",
        "repo_path = os.path.normcase(os.path.realpath(repo))",
        "platform_path = os.path.normcase(os.path.realpath(platform))",
        "working_path = os.path.normcase(os.path.realpath(working_directory))",
        "def inside(path, parent):",
        "    try:",
        "        return os.path.commonpath((path, parent)) == parent",
        "    except ValueError:",
        "        return False",
        "retained = []",
        "for entry in parent_paths:",
        "    if not entry:",
        "        continue",
        "    resolved = os.path.normcase(os.path.realpath(entry))",
        "    if resolved in {platform_path, working_path}:",
        "        continue",
        "    if inside(resolved, repo_path) and not inside(resolved, prefix):",
        "        continue",
        "    retained.append(entry)",
        "sys.path[:] = [dashboard, repo, *retained]",
        "import csv",
        "assert callable(csv.reader)",
        "try:",
        "    importlib.import_module('dashboard.regeneration_flow')",
        "except ModuleNotFoundError as exc:",
        "    assert exc.name in {'dashboard', 'dashboard.regeneration_flow'}, exc.name",
        "else:",
        "    raise AssertionError('dashboard package import unexpectedly succeeded')",
        f"modules = {local_modules!r}",
        "from pathlib import Path",
        "for name in modules:",
        "    module = importlib.import_module(name)",
        "    assert Path(module.__file__).resolve().parent == Path(dashboard).resolve(), name",
    ))
    child_env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                    "HOMEDRIVE", "HOMEPATH")
        if key in os.environ
    }
    child_env["PYTHONNOUSERSITE"] = "1"
    child_env["PYTHONPATH"] = ""
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, env=child_env,
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
