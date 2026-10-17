"""Optional API-process scheduler for separate tenant job workers."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select, update

from db.models import RetrainRun, Tenant
from db.session import db_session

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


def loaded_tenants() -> list[int]:
    # The reserved pooled tenant supplies transaction-local context while this
    # admin metadata query explicitly excludes it and returns only loaded banks.
    with db_session(tenant_id=-1, role="admin") as session:
        return list(session.scalars(
            select(Tenant.tenant_id).where(
                Tenant.tenant_id > 0, Tenant.is_loaded.is_(True),
            ).order_by(Tenant.tenant_id)
        ))


def _launch_worker(module: str, *args: str) -> None:
    command = [sys.executable, "-m", module, *args]
    options = {
        "cwd": str(PLATFORM_ROOT), "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def scheduled_retrain(tenant_id: int) -> str:
    run_id = uuid4().hex
    log_path = f"platform/out/retrain/{run_id}.log"
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        session.add(RetrainRun(
            run_id=run_id, tenant_id=tenant_id, triggered_by="schedule",
            started_at=datetime.now(timezone.utc), status="running", log_path=log_path,
        ))
    try:
        _launch_worker("jobs.retrain_worker", str(int(tenant_id)), run_id)
    except Exception:
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            session.execute(update(RetrainRun).where(
                RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
            ).values(status="failed", finished_at=datetime.now(timezone.utc)))
        raise
    return run_id


def run_nightly_retrain() -> None:
    for tenant_id in loaded_tenants():
        scheduled_retrain(tenant_id)


def run_daily_drift() -> None:
    for tenant_id in loaded_tenants():
        _launch_worker("jobs.drift_monitor_worker", str(int(tenant_id)))


def start_scheduler(config: dict, *, date_trigger: bool = False,
                    retrain_job=run_nightly_retrain, drift_job=run_daily_drift):
    """Start the optional scheduler; date_trigger exists for deterministic smoke tests."""
    scheduler_config = config.get("scheduler") or {}
    if scheduler_config.get("enabled", False) is not True:
        return None
    scheduler = BackgroundScheduler(timezone="UTC")
    if date_trigger:
        run_date = datetime.now(timezone.utc)
        scheduler.add_job(retrain_job, DateTrigger(run_date=run_date), id="nightly-retrain")
        scheduler.add_job(drift_job, DateTrigger(run_date=run_date), id="daily-drift")
    else:
        scheduler.add_job(retrain_job, CronTrigger(hour=2, minute=0, timezone="UTC"),
                          id="nightly-retrain", replace_existing=True)
        scheduler.add_job(drift_job, CronTrigger(hour=3, minute=0, timezone="UTC"),
                          id="daily-drift", replace_existing=True)
    scheduler.start()
    return scheduler
