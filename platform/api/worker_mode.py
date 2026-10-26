"""Safe logging and configuration helpers for API worker launchers."""

from __future__ import annotations

import json
import logging

from settings import load_platform_config


def supervisor_mode_enabled() -> bool:
    return load_platform_config().get("worker_mode", "spawn") == "supervisor"


def log_worker_event(*, worker: str, outcome: str, tenant_id: int | None = None,
                     job_id: str | None = None) -> None:
    logging.getLogger("platform.worker").info(json.dumps({
        "event": "worker_launch", "worker": worker, "outcome": outcome,
        "tenant_id": tenant_id, "job_id": job_id,
    }, separators=(",", ":")))
