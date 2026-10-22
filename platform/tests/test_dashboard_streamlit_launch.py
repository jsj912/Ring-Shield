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
    script = "\n".join((
        "import importlib, site, sys, sysconfig",
        "from pathlib import Path",
        f"dashboard = Path({str(DASHBOARD_ROOT)!r})",
        f"repo = Path({str(REPO_ROOT)!r})",
        "sys.path[:] = [str(dashboard), str(repo), *site.getsitepackages(),",
        "                sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib'),",
        "                str(Path(sys.base_prefix) / 'DLLs')]",
        f"modules = {local_modules!r}",
        "for name in modules:",
        "    module = importlib.import_module(name)",
        "    assert Path(module.__file__).resolve().parent == dashboard.resolve(), name",
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
