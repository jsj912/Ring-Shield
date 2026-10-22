"""Poll tenant work tables and launch restricted worker child processes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Callable

from sqlalchemy import select

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db.models import ExplanationJob, RetrainRun, Tenant  # noqa: E402
from db.session import loader_db_session  # noqa: E402


@dataclass(frozen=True)
class WorkItem:
    kind: str
    tenant_id: int
    job_id: str
    argv: tuple[str, ...]

    @property
    def key(self) -> tuple[str, int, str]:
        return self.kind, self.tenant_id, self.job_id


def _item(kind: str, tenant_id: int, job_id: str) -> WorkItem:
    if kind == "explanation":
        argv = (sys.executable, "-m", "jobs.regenerate_worker", job_id)
    elif kind == "retrain":
        argv = (sys.executable, "-m", "jobs.retrain_worker", str(tenant_id), job_id)
    else:
        raise ValueError("unsupported worker kind")
    return WorkItem(kind=kind, tenant_id=tenant_id, job_id=job_id, argv=argv)


def discover_tenants() -> list[int]:
    """List loaded tenant IDs using the loader's existing tenants SELECT grant."""
    with loader_db_session() as session:
        return [int(value) for value in session.scalars(
            select(Tenant.tenant_id).where(Tenant.is_loaded.is_(True))
            .order_by(Tenant.tenant_id)
        ).all()]


def collect_pending_work(*, tenants: list[int] | None = None) -> list[WorkItem]:
    """Read pending work in tenant-scoped loader transactions."""
    tenant_ids = discover_tenants() if tenants is None else tenants
    pending: list[WorkItem] = []
    for tenant_id in tenant_ids:
        with loader_db_session(tenant_id=tenant_id) as session:
            explanation_ids = session.scalars(
                select(ExplanationJob.job_id).where(
                    ExplanationJob.tenant_id == tenant_id,
                    ExplanationJob.status == "queued",
                ).order_by(ExplanationJob.created_at, ExplanationJob.job_id)
            ).all()
            pending.extend(_item("explanation", tenant_id, str(job_id))
                           for job_id in explanation_ids)
            # RetrainRun is created as running by the existing API. The supervisor
            # dispatches unfinished rows; the worker finalizes their status.
            retrain_ids = session.scalars(
                select(RetrainRun.run_id).where(
                    RetrainRun.tenant_id == tenant_id,
                    RetrainRun.status == "running",
                    RetrainRun.finished_at.is_(None),
                ).order_by(RetrainRun.started_at, RetrainRun.run_id)
            ).all()
            pending.extend(_item("retrain", tenant_id, str(run_id))
                           for run_id in retrain_ids)
    return pending


def _log(*, kind: str, tenant_id: int | None, job_id: str | None, outcome: str) -> None:
    print(json.dumps({
        "event": "worker_supervisor", "kind": kind, "tenant_id": tenant_id,
        "job_id": job_id, "outcome": outcome,
    }, separators=(",", ":")), flush=True)


def run_supervisor(
    *,
    once: bool = False,
    poll_seconds: float = 2.0,
    max_concurrent: int = 2,
    stop_file: str | None = None,
    pending_work: Callable[[], list[WorkItem]] = collect_pending_work,
    popen: Callable = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    stop_requested: Callable[[], bool] = lambda: False,
) -> None:
    """Poll work and track children so a job is launched once per process."""
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_concurrent < 1:
        raise ValueError("max_concurrent must be positive")

    environment = os.environ.copy()
    options = {
        "cwd": str(PLATFORM_ROOT),
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True

    started: set[tuple[str, int, str]] = set()
    active: dict[tuple[str, int, str], tuple[WorkItem, object]] = {}
    stopping = False

    def reap() -> None:
        for key, (work, process) in list(active.items()):
            return_code = process.poll()
            if return_code is not None:
                _log(kind=work.kind, tenant_id=work.tenant_id, job_id=work.job_id,
                     outcome="succeeded" if return_code == 0 else "failed")
                del active[key]

    def launch_available(items: list[WorkItem]) -> None:
        for work in items:
            if len(active) >= max_concurrent:
                return
            if work.key in started:
                continue
            started.add(work.key)
            try:
                process = popen(list(work.argv), **options)
            except OSError:
                _log(kind=work.kind, tenant_id=work.tenant_id, job_id=work.job_id,
                     outcome="launch_failed")
                continue
            active[work.key] = (work, process)
            _log(kind=work.kind, tenant_id=work.tenant_id, job_id=work.job_id,
                 outcome="started")

    while True:
        if stop_requested() or (stop_file and Path(stop_file).exists()):
            stopping = True
        reap()
        if stopping:
            if not active:
                return
            sleep(0.1)
            continue

        try:
            launch_available(pending_work())
        except Exception as exc:
            # Do not serialize exception text: driver errors may contain connection
            # details. Keep the supervisor alive and record only the error class.
            _log(kind="supervisor", tenant_id=None, job_id=None,
                 outcome=f"scan_failed:{type(exc).__name__}")
        if once:
            while active:
                reap()
                if active:
                    sleep(0.05)
            return
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-concurrent", type=int, default=2)
    parser.add_argument("--stop-file")
    args = parser.parse_args(argv)
    if not os.environ.get("RINGSHIELD_LOADER_DATABASE_URL"):
        parser.error("RINGSHIELD_LOADER_DATABASE_URL is required")

    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    previous_handlers = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)
    try:
        run_supervisor(once=args.once, poll_seconds=args.poll_seconds,
                       max_concurrent=args.max_concurrent, stop_file=args.stop_file,
                       stop_requested=lambda: stopping)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
