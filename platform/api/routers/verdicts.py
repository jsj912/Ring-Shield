from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.request_context import current_request_id
from api.schemas import VerdictHistoryPage, VerdictRequest, VerdictResponse, VerdictKind
from db.models import Ring as PlatformRing, User, Verdict
from db.session import db_session
from services.verdicts import record_verdict

router = APIRouter(tags=["verdicts"])


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
    if payload.verdict == VerdictKind.partial:
        # Do not persist a partial status until ring and L4 explanation regeneration
        # can happen atomically in this same workflow.
        raise HTTPException(status_code=503,
                            detail="Partial correction is unavailable until regeneration is configured")

    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")
        user_email = session.scalar(select(User.email).where(User.user_id == principal.user_id))
        if user_email is None:
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        verdict = record_verdict(
            session,
            ring=ring,
            tenant_id=tenant_id,
            ring_id=ring_id,
            user_id=principal.user_id,
            verdict=payload.verdict.value,
            note=payload.note,
            is_simulated=False,
            actor=f"user:{principal.user_id}",
            request_id=current_request_id(),
        )
        return VerdictResponse(
            verdict_id=verdict.verdict_id,
            ring_id=ring_id,
            user_id=principal.user_id,
            user_name=user_email,
            verdict=payload.verdict,
            corrected_members=[],
            corrected_edges=[],
            note=payload.note,
            is_simulated=False,
            created_at=verdict.created_at,
        )
