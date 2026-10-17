"""Tenant-scoped read APIs for model registry and drift history."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import re
from pathlib import Path, PureWindowsPath
import subprocess
import sys
from typing import Iterator, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
import numpy as np
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.schemas import (DriftEventPage, DriftEventSummary, ModelVersionPage,
                         ModelVersionSummary, RetrainRunCreated, RetrainRunStatusResponse,
                         DriftActedOnUpdate, DriftSeriesResponse, DailyDriftStatistic)
from db.models import DriftEvent, EdgeScore, ModelVersion, RetrainRun, Transaction
from db.session import db_session
from settings import load_platform_config

router = APIRouter(tags=["operations"])
ModelComponent = Literal["expansion", "affinity", "typing", "detector"]


@contextmanager
def _tenant_session(tenant_id: int, principal: Principal) -> Iterator[Session]:
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        yield session


@router.get("/tenants/{tenant_id}/models", response_model=ModelVersionPage)
def list_model_versions(
    tenant_id: int,
    component: ModelComponent | None = None,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> ModelVersionPage:
    """List tenant and shared model versions without exposing artifact paths."""
    with _tenant_session(tenant_id, principal) as session:
        query = select(
            ModelVersion.model_version_id,
            ModelVersion.tenant_id,
            ModelVersion.component,
            ModelVersion.version_tag,
            ModelVersion.trained_at,
            ModelVersion.train_label_count,
            ModelVersion.holdout_ring_f1,
            ModelVersion.promoted,
        ).where(
            or_(ModelVersion.tenant_id == tenant_id, ModelVersion.tenant_id.is_(None))
        )
        if component is not None:
            query = query.where(ModelVersion.component == component)
        if before_id is not None:
            query = query.where(ModelVersion.model_version_id < before_id)
        rows = list(session.execute(
            query.order_by(ModelVersion.model_version_id.desc()).limit(limit + 1)
        ))

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        ModelVersionSummary(
            model_version_id=row.model_version_id,
            component=row.component,
            version_tag=row.version_tag,
            trained_at=row.trained_at,
            train_label_count=row.train_label_count,
            holdout_ring_f1=row.holdout_ring_f1,
            promoted=row.promoted,
            shared=row.tenant_id is None,
        )
        for row in rows
    ]
    return ModelVersionPage(
        items=items,
        next_before_id=items[-1].model_version_id if has_more and items else None,
        active_model_id=load_platform_config()["active_model_id"],
        active_seed=int(load_platform_config()["active_seed"]),
    )


@router.get("/tenants/{tenant_id}/drift", response_model=DriftEventPage)
def list_drift_events(
    tenant_id: int,
    monitor: Literal["adwin_score_mean", "adwin_score_p99"] | None = None,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> DriftEventPage:
    """Return newest tenant drift events; this endpoint never triggers retraining."""
    _require_supervisor_tenant(tenant_id, principal)
    with _tenant_session(tenant_id, principal) as session:
        query = select(DriftEvent).where(DriftEvent.tenant_id == tenant_id)
        if monitor is not None:
            query = query.where(DriftEvent.monitor == monitor)
        if before_id is not None:
            query = query.where(DriftEvent.event_id < before_id)
        rows = list(session.scalars(
            query.order_by(DriftEvent.event_id.desc()).limit(limit + 1)
        ))

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [DriftEventSummary.model_validate(row) for row in rows]
    return DriftEventPage(
        items=items,
        next_before_id=items[-1].event_id if has_more and items else None,
    )


@router.get("/tenants/{tenant_id}/drift/series", response_model=DriftSeriesResponse)
def get_drift_series(tenant_id: int, principal: Principal = Depends(get_principal)) -> DriftSeriesResponse:
    """Return tenant daily score statistics for supervisor drift review."""
    _require_supervisor_tenant(tenant_id, principal)
    config = load_platform_config()
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        rows = session.execute(
            select(Transaction.timestamp, EdgeScore.score_calibrated)
            .join(EdgeScore, (EdgeScore.tenant_id == Transaction.tenant_id)
                  & (EdgeScore.edge_id == Transaction.edge_id))
            .where(Transaction.tenant_id == tenant_id, EdgeScore.tenant_id == tenant_id,
                   EdgeScore.model_id == config["active_model_id"],
                   EdgeScore.seed == int(config["active_seed"]),
                   EdgeScore.score_calibrated.is_not(None))
            .order_by(Transaction.timestamp, Transaction.edge_id)
        ).all()
    by_day: dict[int, list[float]] = defaultdict(list)
    for timestamp, score in rows:
        value = float(score)
        if np.isfinite(value):
            by_day[(int(timestamp) - 10) // 86_400].append(value)
    points = [(day, float(np.mean(values)), float(np.percentile(values, 99)))
              for day, values in sorted(by_day.items())]
    return DriftSeriesResponse(
        tenant_id=tenant_id, active_model_id=config["active_model_id"],
        active_seed=int(config["active_seed"]),
        items=[DailyDriftStatistic(
            day=datetime.fromtimestamp(day * 86_400 + 10, tz=timezone.utc), mean=mean, p99=p99,
        ) for day, mean, p99 in points],
    )


@router.patch("/tenants/{tenant_id}/drift/{event_id}", response_model=DriftEventSummary)
def set_drift_acted_on(
    tenant_id: int,
    event_id: int,
    payload: DriftActedOnUpdate,
    principal: Principal = Depends(get_principal),
) -> DriftEventSummary:
    _require_supervisor_tenant(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        event = session.scalar(select(DriftEvent).where(
            DriftEvent.tenant_id == tenant_id,
            DriftEvent.event_id == event_id,
        ))
        if event is None:
            raise HTTPException(status_code=404, detail="Drift event not found")
        session.execute(update(DriftEvent).where(
            DriftEvent.tenant_id == tenant_id,
            DriftEvent.event_id == event_id,
        ).values(acted_on=payload.acted_on))
        event.acted_on = payload.acted_on
        return DriftEventSummary.model_validate(event)


def _require_supervisor_tenant(tenant_id: int, principal: Principal) -> None:
    if principal.role != "supervisor":
        raise HTTPException(status_code=403, detail="Only a tenant supervisor can access retraining")
    require_tenant_access(tenant_id, principal)


def retrain_log_lines(log_path: str | None, *, limit: int = 50) -> list[str]:
    if not log_path:
        return []
    root = Path(__file__).resolve().parents[3]
    path = Path(log_path)
    if path.is_absolute():
        return []
    resolved = (root / path).resolve()
    allowed = (root / "platform" / "out" / "retrain").resolve()
    try:
        resolved.relative_to(allowed)
        lines = resolved.read_text(encoding="utf-8").splitlines()[-limit:]
    except (OSError, ValueError):
        return []
    windows_path = re.compile(r"(?i)\b[A-Z]:\\(?:[^\\\s]+\\)*[^\\\s]*")
    unix_path = re.compile(r"(?<![\w])/(?:[^/\s]+/)*[^/\s]+")
    return [unix_path.sub(lambda match: Path(match.group()).name,
                          windows_path.sub(lambda match: PureWindowsPath(match.group()).name, line))
            for line in lines]


def launch_retrain_process(tenant_id: int, run_id: str) -> None:
    """Start retraining in a child process; API code does not inspect job credentials."""
    command = [sys.executable, "-m", "jobs.retrain_worker", str(int(tenant_id)), run_id]
    options = {
        "cwd": str(Path(__file__).resolve().parents[2]),
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


@router.post("/tenants/{tenant_id}/retrain", response_model=RetrainRunCreated,
             status_code=status.HTTP_202_ACCEPTED)
def start_retrain(
    tenant_id: int,
    principal: Principal = Depends(get_principal),
) -> RetrainRunCreated:
    """Queue tenant retraining; candidates are gated against the fixed holdout."""
    _require_supervisor_tenant(tenant_id, principal)
    run_id = uuid4().hex
    relative_log = f"platform/out/retrain/{run_id}.log"
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        session.add(RetrainRun(
            run_id=run_id,
            tenant_id=tenant_id,
            triggered_by="supervisor",
            started_at=datetime.now(timezone.utc),
            status="running",
            log_path=relative_log,
        ))
        session.flush()
    try:
        launch_retrain_process(tenant_id, run_id)
    except Exception as exc:
        with db_session(tenant_id=tenant_id, role="supervisor") as session:
            session.execute(update(RetrainRun).where(
                RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
            ).values(status="failed", finished_at=datetime.now(timezone.utc)))
        raise HTTPException(status_code=503, detail="Retrain worker could not be started") from exc
    return RetrainRunCreated(run_id=run_id)


@router.get("/tenants/{tenant_id}/retrain/{run_id}", response_model=RetrainRunStatusResponse)
def get_retrain_status(
    tenant_id: int,
    run_id: str,
    principal: Principal = Depends(get_principal),
) -> RetrainRunStatusResponse:
    _require_supervisor_tenant(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        run = session.scalar(select(RetrainRun).where(
            RetrainRun.tenant_id == tenant_id, RetrainRun.run_id == run_id,
        ))
        if run is None:
            raise HTTPException(status_code=404, detail="Retrain run not found")
        response = RetrainRunStatusResponse(
            run_id=run.run_id,
            status=run.status,
            model_version_id=run.model_version_id,
            log_lines=retrain_log_lines(run.log_path),
        )
    return response
