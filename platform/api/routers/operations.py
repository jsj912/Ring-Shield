"""Tenant-scoped read APIs for model registry and drift history."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.schemas import (DriftEventPage, DriftEventSummary, ModelVersionPage,
                         ModelVersionSummary)
from db.models import DriftEvent, ModelVersion
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
