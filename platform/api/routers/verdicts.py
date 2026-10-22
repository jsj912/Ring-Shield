from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select

from audit import add_audit_event
from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.request_context import current_request_id
from api.schemas import (RegenerationResponse, TenantAnalystOption, TenantVerdictCounts, TenantVerdictItem,
                         TenantVerdictPage, VerdictHistoryPage, VerdictRequest,
                         VerdictResponse, VerdictKind)
from db.models import (ExplanationJob, Ring as PlatformRing, Transaction, User,
                       Verdict)
from db.session import db_session
from services.verdicts import (PartialCorrectionError,
                               map_partial_correction_to_exclusions,
                               record_verdict)
from settings import load_platform_config

router = APIRouter(tags=["verdicts"])
logger = logging.getLogger(__name__)


def _encode_tenant_cursor(created_at: datetime, verdict_id: int) -> str:
    raw = json.dumps({"created_at": created_at.isoformat(), "verdict_id": verdict_id},
                     separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_tenant_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        item = json.loads(raw)
        created_at = datetime.fromisoformat(item["created_at"])
        verdict_id = item["verdict_id"]
        if created_at.tzinfo is None or type(verdict_id) is not int or verdict_id < 1:
            raise ValueError("invalid verdict cursor values")
        return created_at, verdict_id
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc


@router.get("/tenants/{tenant_id}/verdicts", response_model=TenantVerdictPage)
def list_tenant_verdicts(
    tenant_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    verdict_filter: list[str] | None = Query(default=None, alias="verdict"),
    analyst_id: int | None = Query(default=None, gt=0),
    simulated: bool | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> TenantVerdictPage:
    """Return filtered tenant verdict history without exposing analyst email."""
    require_tenant_access(tenant_id, principal)
    allowed = {kind.value for kind in VerdictKind}
    if verdict_filter and not set(verdict_filter) <= allowed:
        raise HTTPException(status_code=422, detail="Unsupported verdict filter")
    for bound in (since, until):
        if bound is not None and bound.tzinfo is None:
            raise HTTPException(status_code=422, detail="Date filters must include a timezone")
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=422, detail="Date range start must not follow its end")

    clauses = [Verdict.tenant_id == tenant_id]
    if verdict_filter:
        clauses.append(Verdict.verdict.in_(verdict_filter))
    if analyst_id is not None:
        clauses.append(Verdict.user_id == analyst_id)
    if simulated is not None:
        clauses.append(Verdict.is_simulated.is_(simulated))
    if since is not None:
        clauses.append(Verdict.created_at >= since)
    if until is not None:
        clauses.append(Verdict.created_at <= until)
    where = and_(*clauses)

    # Migration 0007's tenant/ring/created index serves ring-specific history;
    # tenant-wide newest-first listing uses ix_verdicts_tenant_created. PostgreSQL
    # can scan that (tenant_id, created_at) B-tree backward for the requested order.
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        total = int(session.scalar(
            select(func.count()).select_from(Verdict).where(where)
        ) or 0)
        count_rows = session.execute(
            select(Verdict.verdict, func.count())
            .where(where).group_by(Verdict.verdict)
        ).all()
        counts_by_kind = {kind: count for kind, count in count_rows}
        analyst_ids = session.scalars(
            select(Verdict.user_id).where(Verdict.tenant_id == tenant_id)
            .distinct().order_by(Verdict.user_id)
        ).all()
        query = select(Verdict).where(where)
        if cursor:
            before_created_at, before_verdict_id = _decode_tenant_cursor(cursor)
            query = query.where(or_(
                Verdict.created_at < before_created_at,
                and_(Verdict.created_at == before_created_at,
                     Verdict.verdict_id < before_verdict_id),
            ))
        rows = list(session.scalars(
            query.order_by(Verdict.created_at.desc(), Verdict.verdict_id.desc())
            .limit(limit + 1)
        ))

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [TenantVerdictItem(
        verdict_id=row.verdict_id,
        ring_id=row.ring_id,
        verdict=VerdictKind(row.verdict),
        analyst_id=row.user_id,
        analyst_label=f"Analyst {row.user_id}",
        is_simulated=row.is_simulated,
        note_excerpt=(row.note[:160] if row.note else None),
        created_at=row.created_at,
    ) for row in rows]
    next_cursor = (
        _encode_tenant_cursor(rows[-1].created_at, rows[-1].verdict_id)
        if has_more and rows else None
    )
    return TenantVerdictPage(
        items=items,
        next_cursor=next_cursor,
        total=total,
        counts=TenantVerdictCounts(
            confirmed=int(counts_by_kind.get("confirm", 0)),
            rejected=int(counts_by_kind.get("reject", 0)),
            partial=int(counts_by_kind.get("partial", 0)),
        ),
        analysts=[TenantAnalystOption(analyst_id=user_id,
                                      analyst_label=f"Analyst {user_id}")
                  for user_id in analyst_ids],
    )


@router.get("/tenants/{tenant_id}/rings/{ring_id}/verdicts",
            response_model=VerdictHistoryPage)
def list_verdicts(
    tenant_id: int,
    ring_id: str,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> VerdictHistoryPage:
    """Return newest-first verdict history for one tenant-visible ring."""
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")

        query = (
            select(Verdict, User.email)
            .join(User, User.user_id == Verdict.user_id)
            .where(Verdict.tenant_id == tenant_id, Verdict.ring_id == ring_id)
        )
        if before_id is not None:
            query = query.where(Verdict.verdict_id < before_id)
        rows = list(session.execute(
            query.order_by(Verdict.verdict_id.desc()).limit(limit + 1)
        ))

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        VerdictResponse(
            verdict_id=row.verdict_id,
            ring_id=row.ring_id,
            user_id=row.user_id,
            user_name=email,
            verdict=VerdictKind(row.verdict),
            corrected_members=list(row.corrected_members or []),
            corrected_edges=list(row.corrected_edges or []),
            note=row.note,
            is_simulated=row.is_simulated,
            created_at=row.created_at,
        )
        for row, email in rows
    ]
    return VerdictHistoryPage(
        items=items,
        next_before_id=items[-1].verdict_id if has_more and items else None,
    )


@router.post("/tenants/{tenant_id}/rings/{ring_id}/verdicts",
             response_model=VerdictResponse, status_code=status.HTTP_201_CREATED)
def submit_verdict(
    tenant_id: int,
    ring_id: str,
    payload: VerdictRequest,
    principal: Principal = Depends(get_principal),
) -> VerdictResponse:
    require_tenant_access(tenant_id, principal)
    if principal.role == "admin":
        raise HTTPException(status_code=403, detail="Administrators cannot record verdicts")
    exclusions: tuple[list[int], list[int]] | None = None
    regeneration_configured = False
    if payload.verdict == VerdictKind.partial:
        l4_settings = load_platform_config().get("l4", {})
        regeneration_configured = bool(l4_settings.get("regenerate_url"))
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")
        if payload.verdict == VerdictKind.partial:
            edge_ids = sorted(set(map(int, ring.member_edges or [])))
            edge_rows = session.execute(
                select(Transaction.edge_id, Transaction.from_id, Transaction.to_id)
                .where(Transaction.tenant_id == tenant_id,
                       Transaction.edge_id.in_(edge_ids))
            ).all() if edge_ids else []
            edge_endpoints = {
                int(edge_id): (int(from_id), int(to_id))
                for edge_id, from_id, to_id in edge_rows
            }
            corrected_edges = (payload.corrected_edges
                               if "corrected_edges" in payload.model_fields_set else None)
            try:
                exclusions = map_partial_correction_to_exclusions(
                    member_accounts=ring.member_accounts or [],
                    member_edges=ring.member_edges or [],
                    edge_endpoints=edge_endpoints,
                    corrected_members=payload.corrected_members,
                    corrected_edges=corrected_edges,
                )
            except PartialCorrectionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None

        user_email = session.scalar(select(User.email).where(
            User.tenant_id == tenant_id, User.user_id == principal.user_id
        ))
        if user_email is None:
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        verdict = record_verdict(
            session,
            ring=ring,
            tenant_id=tenant_id,
            ring_id=ring_id,
            user_id=principal.user_id,
            verdict=payload.verdict.value,
            corrected_members=payload.corrected_members,
            corrected_edges=payload.corrected_edges,
            note=payload.note,
            is_simulated=False,
            actor=f"user:{principal.user_id}",
            request_id=current_request_id(),
        )
        regeneration = None
        if payload.verdict == VerdictKind.partial:
            if regeneration_configured and exclusions is not None:
                excluded_members, excluded_edges = exclusions
                job_id = f"{tenant_id}.{uuid4().hex}"
                session.add(ExplanationJob(
                    job_id=job_id, tenant_id=tenant_id, ring_id=ring_id,
                    verdict_id=verdict.verdict_id, requested_by=principal.user_id,
                    excluded_members=excluded_members, excluded_edges=excluded_edges,
                    status="queued",
                ))
                session.flush()
                add_audit_event(
                    session, tenant_id=tenant_id, user_id=principal.user_id,
                    actor=f"user:{principal.user_id}",
                    action="explanation.regeneration_requested",
                    entity_type="explanation_job", entity_id=job_id,
                    request_id=current_request_id(), details={"status": "queued"},
                )
                session.flush()
                regeneration = RegenerationResponse(status="queued", job_id=job_id)
            else:
                regeneration = RegenerationResponse(status="unavailable", job_id=None)
        response = VerdictResponse(
            verdict_id=verdict.verdict_id,
            ring_id=ring_id,
            user_id=principal.user_id,
            user_name=user_email,
            verdict=payload.verdict,
            corrected_members=list(verdict.corrected_members or []),
            corrected_edges=list(verdict.corrected_edges or []),
            note=payload.note,
            is_simulated=False,
            created_at=verdict.created_at,
            regeneration=regeneration,
        )
    return response
