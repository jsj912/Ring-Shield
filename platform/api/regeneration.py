"""Safe process launcher for the separate regeneration worker."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def launch_regeneration_process(job_id: str) -> None:
    """Launch one job without reading worker credentials in the API process."""
    command = [sys.executable, "-m", "jobs.regenerate_worker", job_id]
    options = {
        "cwd": str(Path(__file__).resolve().parents[1]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)
