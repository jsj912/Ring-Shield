from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import BigInteger, Float, and_, cast, func, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.regeneration import launch_regeneration_process
from api.request_context import current_request_id
from api.label_maps import currency_label, payment_format_label
from api.schemas import (RingDetail, RingEvidenceEdge, RingEvidenceGraph,
                         ExplanationJobResponse, RegenerateExplanationRequest,
                         RingEvidenceNode, RingExplanation, RingPage, RingSummary)
from api.timebasis import from_utc, to_utc
from contract.schema import TOPOLOGY_TYPES
from audit import add_audit_event
from db.models import (Account, EdgeScore, Explanation, ExplanationJob,
                       Ring as PlatformRing, Transaction, Verdict)
from db.session import db_session
from jobs.explanation_queries import latest_explanation_statement
from services.verdicts import (PartialCorrectionError,
                                map_partial_correction_to_exclusions)
from settings import load_platform_config

router = APIRouter(tags=["rings"])
logger = logging.getLogger(__name__)
SortField = Literal["confidence", "total_amount", "start_time", "members"]
SortOrder = Literal["asc", "desc"]
AllowedStatuses = {"open", "confirmed", "rejected", "partial"}
EvidenceRoleKeys = {
    "is_source": "source_accounts",
    "is_sink": "sink_accounts",
    "is_mule": "mule_accounts",
}
_UNSAFE_JOB_ERROR = re.compile(r"(?:https?://|[A-Za-z]:\\|/(?:[^/\s]+/)*[^/\s]+|\b[^\s@]+@[^\s@]+)", re.I)


def _safe_job_error(value: str | None) -> str | None:
    if not value:
        return None
    if _UNSAFE_JOB_ERROR.search(value) or "RINGSHIELD_" in value:
        return "Explanation regeneration could not be completed"
    return value[:240]


def _edge_endpoints(session, tenant_id: int, ring: PlatformRing) -> dict[int, tuple[int, int]]:
    edge_ids = sorted(set(map(int, ring.member_edges or [])))
    if not edge_ids:
        return {}
    rows = session.execute(
        select(Transaction.edge_id, Transaction.from_id, Transaction.to_id)
        .where(Transaction.tenant_id == tenant_id, Transaction.edge_id.in_(edge_ids))
    ).all()
    return {int(edge_id): (int(from_id), int(to_id))
            for edge_id, from_id, to_id in rows}


@router.get("/tenants/{tenant_id}/rings/{ring_id}/explanation",
            response_model=RingExplanation)
def get_ring_explanation(
    tenant_id: int,
    ring_id: str,
    principal: Principal = Depends(get_principal),
) -> RingExplanation:
    """Return the newest persisted L4 explanation for a tenant-visible ring."""
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")
        explanation = session.scalar(latest_explanation_statement(tenant_id, ring_id))
        if explanation is None:
            raise HTTPException(status_code=404, detail="Explanation not found")
        regenerating = session.scalar(select(ExplanationJob.job_id).where(
            ExplanationJob.tenant_id == tenant_id,
            ExplanationJob.ring_id == ring_id,
            ExplanationJob.status.in_(("queued", "running")),
        ).limit(1)) is not None
        raw_provenance = explanation.provenance or {}
        public_provenance = {
            key: raw_provenance[key]
            for key in ("aggregator_id", "model_id", "seed", "explainer_version",
                        "currency_policy", "rings_schema_version", "mixing", "loo",
                        "flow_partial", "features_degraded", "feature_scope",
                        "fx_rates_sha256")
            if key in raw_provenance
        }
        if explanation.fx_rates_sha256:
            public_provenance["fx_rates_sha256"] = explanation.fx_rates_sha256
        return RingExplanation(
            tenant_id=tenant_id,
            ring_id=ring_id,
            explainer_version=explanation.explainer_version,
            revision=explanation.revision,
            regenerated=(raw_provenance.get("regenerated") is True),
            edge_weights=explanation.edge_weights if isinstance(explanation.edge_weights, list) else [],
            account_weights=explanation.account_weights if isinstance(explanation.account_weights, list) else [],
            feature_weights=explanation.feature_weights if isinstance(explanation.feature_weights, list) else [],
            narrative=explanation.narrative,
            evidence_summary=explanation.evidence_summary,
            latency_ms=explanation.latency_ms,
            provenance=public_provenance,
            created_at=explanation.created_at,
            regenerating=regenerating,
        )


@router.post("/tenants/{tenant_id}/rings/{ring_id}/explanation/regenerate",
             response_model=ExplanationJobResponse, status_code=status.HTTP_202_ACCEPTED)
def regenerate_ring_explanation(
    tenant_id: int,
    ring_id: str,
    payload: RegenerateExplanationRequest,
    principal: Principal = Depends(get_principal),
) -> ExplanationJobResponse:
    require_tenant_access(tenant_id, principal)
    if principal.role not in {"analyst", "supervisor"}:
        raise HTTPException(status_code=403, detail="Not permitted")
    config = load_platform_config()
    if not config.get("l4", {}).get("regenerate_url"):
        raise HTTPException(status_code=503, detail="Explanation regeneration is not configured")

    launch_job_id: str | None = None
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")
        verdict = session.scalar(select(Verdict).where(
            Verdict.tenant_id == tenant_id,
            Verdict.ring_id == ring_id,
            Verdict.verdict_id == payload.verdict_id,
        ))
        if verdict is None:
            raise HTTPException(status_code=404, detail="Partial verdict not found")
        if verdict.verdict != "partial" or verdict.is_simulated:
            raise HTTPException(status_code=422, detail="A non-simulated partial verdict is required")

        active_job = session.scalar(select(ExplanationJob).where(
            ExplanationJob.tenant_id == tenant_id,
            ExplanationJob.ring_id == ring_id,
            ExplanationJob.verdict_id == verdict.verdict_id,
            ExplanationJob.status.in_(("queued", "running", "succeeded")),
        ).order_by(ExplanationJob.created_at.desc(), ExplanationJob.job_id.desc()).limit(1))
        if active_job is not None:
            if (active_job.status == "queued" and active_job.created_at is not None
                    and datetime.now(timezone.utc) - active_job.created_at > timedelta(seconds=30)):
                launch_job_id = active_job.job_id
            response = ExplanationJobResponse(
                job_id=active_job.job_id, status=active_job.status,
                result_revision=active_job.result_revision,
                error=_safe_job_error(active_job.error), created_at=active_job.created_at,
                finished_at=active_job.finished_at,
            )
        else:
            latest_job = session.scalar(select(ExplanationJob).where(
                ExplanationJob.tenant_id == tenant_id,
                ExplanationJob.ring_id == ring_id,
                ExplanationJob.verdict_id == verdict.verdict_id,
            ).order_by(ExplanationJob.created_at.desc(), ExplanationJob.job_id.desc()).limit(1))
            if latest_job is not None and latest_job.status != "failed":
                # A concurrent request may have created an active job after our first read.
                raise HTTPException(status_code=409, detail="Regeneration job state changed; retry")
            try:
                excluded_members, excluded_edges = map_partial_correction_to_exclusions(
                    member_accounts=ring.member_accounts or [],
                    member_edges=ring.member_edges or [],
                    edge_endpoints=_edge_endpoints(session, tenant_id, ring),
                    corrected_members=verdict.corrected_members or [],
                    corrected_edges=(verdict.corrected_edges or None),
                )
            except PartialCorrectionError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            job_id = f"{tenant_id}.{uuid4().hex}"
            job = ExplanationJob(
                job_id=job_id, tenant_id=tenant_id, ring_id=ring_id,
                verdict_id=verdict.verdict_id, requested_by=principal.user_id,
                excluded_members=excluded_members, excluded_edges=excluded_edges,
                status="queued",
            )
            session.add(job)
            session.flush()
            add_audit_event(
                session, tenant_id=tenant_id, user_id=principal.user_id,
                actor=f"user:{principal.user_id}", action="explanation.regeneration_requested",
                entity_type="explanation_job", entity_id=job_id,
                request_id=current_request_id(), details={"status": "queued"},
            )
            session.flush()
            launch_job_id = job_id
            response = ExplanationJobResponse(
                job_id=job_id, status="queued", result_revision=None,
                error=None, created_at=job.created_at or datetime.now(timezone.utc),
                finished_at=None,
            )
    if launch_job_id is not None:
        try:
            launch_regeneration_process(launch_job_id)
        except OSError as exc:
            logger.info("regeneration_worker_launch_failed", extra={
                "event": "regeneration_worker_launch_failed",
                "tenant_id": tenant_id, "job_id": launch_job_id,
                "error_type": type(exc).__name__,
            })
    return response


@router.get("/tenants/{tenant_id}/rings/{ring_id}/explanation/jobs/{job_id}",
            response_model=ExplanationJobResponse)
def get_explanation_job(
    tenant_id: int,
    ring_id: str,
    job_id: str,
    principal: Principal = Depends(get_principal),
) -> ExplanationJobResponse:
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        job = session.scalar(select(ExplanationJob).where(
            ExplanationJob.tenant_id == tenant_id,
            ExplanationJob.ring_id == ring_id,
            ExplanationJob.job_id == job_id,
        ))
        if job is None:
            raise HTTPException(status_code=404, detail="Explanation job not found")
        return ExplanationJobResponse(
            job_id=job.job_id, status=job.status, result_revision=job.result_revision,
            error=_safe_job_error(job.error), created_at=job.created_at,
            finished_at=job.finished_at,
        )


@contextmanager
def _tenant_session(tenant_id: int, principal: Principal) -> Iterator[Session]:
    require_tenant_access(tenant_id, principal)
    with db_session(tenant_id=tenant_id, role=principal.role) as session:
        yield session


def _summary(row: PlatformRing) -> RingSummary:
    payload = row.payload or {}
    n_currencies = _optional_int(payload.get("n_currencies"))
    single_currency = n_currencies == 1
    probabilities = row.topology_probs or []
    try:
        topology_probability = float(probabilities[TOPOLOGY_TYPES.index(row.topology_type)])
    except (ValueError, IndexError, TypeError):
        topology_probability = 0.0
    return RingSummary(
        ring_id=row.ring_id,
        tenant_id=row.tenant_id,
        topology_type=row.topology_type,
        topology_prob=topology_probability,
        n_members=len(row.member_accounts),
        n_edges=int(payload.get("n_edges", len(row.member_edges))),
        total_amount=_optional_float(payload.get("total_amount")) if single_currency else None,
        total_currency=currency_label(payload.get("total_currency")) if single_currency else None,
        n_currencies=n_currencies,
        start_time=to_utc(row.start_time),
        end_time=to_utc(row.end_time),
        window_text=_window_text(row.end_time - row.start_time),
        confidence=float(row.confidence),
        cross_bank=bool(payload.get("cross_bank", False)),
        counterparty_banks=list(payload.get("counterparty_banks") or []),
        status=row.status,
    )


def _window_text(duration_seconds: int) -> str:
    """Format the loader-basis window as the ready-to-display FR-D10 text."""
    if duration_seconds >= 86400:
        amount = duration_seconds / 86400
        unit = "d"
    elif duration_seconds >= 3600:
        amount = duration_seconds / 3600
        unit = "h"
    else:
        amount = duration_seconds / 60
        unit = "min"
    number = f"{amount:g}"
    return f"over {number} {unit}"


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def _optional_int(value) -> int | None:
    return None if value is None else int(value)


def _fingerprint(filters: dict) -> str:
    encoded = json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _encode_cursor(fingerprint: str, sort: str, value, ring_id: str) -> str:
    raw = json.dumps({"f": fingerprint, "s": sort, "v": value, "r": ring_id},
                     separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, fingerprint: str, sort: str) -> tuple[float | int, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        item = json.loads(raw)
        if item.get("f") != fingerprint or item.get("s") != sort:
            raise ValueError("cursor does not match these filters")
        if not isinstance(item.get("r"), str):
            raise ValueError("cursor ring id is invalid")
        value = item.get("v")
        if not isinstance(value, (int, float)):
            raise ValueError("cursor sort value is invalid")
        return value, item["r"]
    except (ValueError, TypeError, AttributeError, KeyError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc


@router.get("/tenants/{tenant_id}/rings", response_model=RingPage)
def list_rings(
    tenant_id: int,
    status_filter: list[str] | None = Query(default=None, alias="status"),
    min_conf: float | None = Query(default=None, ge=0, le=1),
    topology_type: list[str] | None = Query(default=None),
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    cross_bank_only: bool = False,
    q: str | None = None,
    sort: SortField = "confidence",
    order: SortOrder = "desc",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> RingPage:
    require_tenant_access(tenant_id, principal)
    statuses = status_filter or ["open"]
    if not set(statuses) <= AllowedStatuses:
        raise HTTPException(status_code=422, detail="Unsupported ring status filter")
    if topology_type and not set(topology_type) <= set(TOPOLOGY_TYPES) | {"UNKNOWN"}:
        raise HTTPException(status_code=422, detail="Unsupported topology type")
    start_min = from_utc(start_after) if start_after is not None else None
    start_max = from_utc(start_before) if start_before is not None else None
    sort_column = {"confidence": PlatformRing.confidence,
                   "start_time": PlatformRing.start_time,
                   "members": func.cardinality(PlatformRing.member_accounts),
                   "total_amount": func.coalesce(
                       cast(PlatformRing.payload["total_amount"].as_string(), Float), 0.0)}[sort]
    search = q.strip() if q and q.strip() else None
    filters = {"status": sorted(statuses), "min_conf": min_conf,
               "topology_type": sorted(topology_type or []), "start_min": start_min,
               "start_max": start_max, "cross_bank_only": cross_bank_only,
               "q": search, "sort": sort, "order": order}
    fingerprint = _fingerprint(filters)

    clauses = [PlatformRing.tenant_id == tenant_id, PlatformRing.scope == "tenant",
               PlatformRing.status.in_(statuses)]
    if min_conf is not None:
        clauses.append(PlatformRing.confidence >= min_conf)
    if topology_type:
        clauses.append(PlatformRing.topology_type.in_(topology_type))
    if start_min is not None:
        clauses.append(PlatformRing.start_time >= start_min)
    if start_max is not None:
        clauses.append(PlatformRing.start_time <= start_max)
    if cross_bank_only:
        clauses.append(PlatformRing.payload["cross_bank"].as_boolean().is_(True))
    if search:
        search_clauses = [PlatformRing.ring_id == search]
        try:
            account_id = int(search)
        except ValueError:
            pass
        else:
            account_array = cast([account_id], postgresql.ARRAY(BigInteger))
            search_clauses.append(PlatformRing.member_accounts.op("@>")(account_array))
        clauses.append(or_(*search_clauses))
    where = and_(*clauses)
    tenant_where = and_(PlatformRing.tenant_id == tenant_id,
                        PlatformRing.scope == "tenant")

    with _tenant_session(tenant_id, principal) as session:
        total = session.scalar(select(func.count()).select_from(PlatformRing).where(where)) or 0
        tenant_total = session.scalar(
            select(func.count()).select_from(PlatformRing).where(tenant_where)
        ) or 0
        query = select(PlatformRing).where(where)
        if cursor:
            cursor_value, cursor_ring_id = _decode_cursor(cursor, fingerprint, sort)
            if order == "desc":
                query = query.where(or_(sort_column < cursor_value,
                                        and_(sort_column == cursor_value,
                                             PlatformRing.ring_id > cursor_ring_id)))
            else:
                query = query.where(or_(sort_column > cursor_value,
                                        and_(sort_column == cursor_value,
                                             PlatformRing.ring_id > cursor_ring_id)))
        ordered = sort_column.desc() if order == "desc" else sort_column.asc()
        rows = list(session.scalars(query.order_by(ordered, PlatformRing.ring_id.asc()).limit(limit + 1)))

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        sort_value = (float(last.confidence) if sort == "confidence" else
                      int(last.start_time) if sort == "start_time" else
                      len(last.member_accounts) if sort == "members" else
                      float((last.payload or {}).get("total_amount") or 0.0))
        next_cursor = _encode_cursor(fingerprint, sort, sort_value, last.ring_id)
    return RingPage(items=[_summary(row) for row in rows], next_cursor=next_cursor,
                    total=int(total), tenant_total=int(tenant_total))


@router.get("/tenants/{tenant_id}/rings/{ring_id}", response_model=RingDetail)
def get_ring(tenant_id: int, ring_id: str,
             principal: Principal = Depends(get_principal)) -> RingDetail:
    with _tenant_session(tenant_id, principal) as session:
        row = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if row is None or row.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")
    summary = _summary(row).model_dump()
    payload = row.payload or {}
    return RingDetail(
        **summary,
        member_accounts=[int(v) for v in row.member_accounts],
        member_edges=[int(v) for v in row.member_edges],
        seed_edges=[int(v) for v in row.seed_edges],
        expanded_edges=[int(v) for v in row.expanded_edges],
        conservation_closure=row.conservation_closure,
        source_accounts=[int(v) for v in payload.get("source_accounts", [])],
        sink_accounts=[int(v) for v in payload.get("sink_accounts", [])],
        mule_accounts=[int(v) for v in payload.get("mule_accounts", [])],
        model_id=row.model_id,
        aggregator_id=row.aggregator_id,
    )


@router.get("/tenants/{tenant_id}/rings/{ring_id}/evidence",
            response_model=RingEvidenceGraph)
def get_ring_evidence(
    tenant_id: int,
    ring_id: str,
    before_edge_id: int | None = Query(default=None),
    limit: int = Query(default=250, ge=1, le=500),
    principal: Principal = Depends(get_principal),
) -> RingEvidenceGraph:
    """Return a tenant-scoped account/transaction subgraph for one ring."""
    with _tenant_session(tenant_id, principal) as session:
        ring = session.get(PlatformRing, {"tenant_id": tenant_id, "ring_id": ring_id})
        if ring is None or ring.scope != "tenant":
            raise HTTPException(status_code=404, detail="Ring not found")

        member_edges = [int(edge_id) for edge_id in ring.member_edges]
        if before_edge_id is not None and before_edge_id not in member_edges:
            raise HTTPException(status_code=400, detail="Evidence cursor is not part of this ring")
        eligible_edge_ids = sorted(
            (edge_id for edge_id in member_edges
             if before_edge_id is None or edge_id < before_edge_id),
            reverse=True,
        )
        page_candidate_ids = eligible_edge_ids[:limit]
        has_more = len(eligible_edge_ids) > limit
        transaction_rows = []
        if page_candidate_ids:
            transaction_rows = list(session.scalars(
                select(Transaction)
                .where(Transaction.tenant_id == tenant_id,
                       Transaction.edge_id.in_(page_candidate_ids))
                .order_by(Transaction.edge_id.desc())
            ))
        score_rows = []
        if page_candidate_ids:
            active = load_platform_config()
            score_rows = list(session.scalars(
                select(EdgeScore)
                .where(EdgeScore.tenant_id == tenant_id,
                       EdgeScore.edge_id.in_(page_candidate_ids),
                       EdgeScore.model_id == active["active_model_id"],
                       EdgeScore.seed == int(active["active_seed"]))
            ))

        page_account_ids = sorted({
            int(account_id)
            for row in transaction_rows
            for account_id in (row.from_id, row.to_id)
        })
        account_rows = []
        if page_account_ids:
            account_rows = list(session.scalars(
                select(Account)
                .where(Account.tenant_id == tenant_id,
                       Account.account_id.in_(page_account_ids))
            ))

        payload = ring.payload or {}
        account_banks = {int(row.account_id): int(row.bank_code) for row in account_rows}
        for row in transaction_rows:
            account_banks.setdefault(int(row.from_id), int(row.from_bank))
            account_banks.setdefault(int(row.to_id), int(row.to_bank))

    returned_edge_ids = {int(row.edge_id) for row in transaction_rows}
    scores_by_edge = {int(row.edge_id): row for row in score_rows}
    roles = {
        role: {int(account_id) for account_id in payload.get(payload_key, [])}
        for role, payload_key in EvidenceRoleKeys.items()
    }
    node_ids = sorted(set(page_account_ids) | set(account_banks))
    nodes = [
        RingEvidenceNode(
            account_id=account_id,
            bank_code=account_banks.get(account_id),
            bank_label=(f"Bank {account_banks[account_id]}" if account_id in account_banks else None),
            is_source=account_id in roles["is_source"],
            is_sink=account_id in roles["is_sink"],
            is_mule=account_id in roles["is_mule"],
        )
        for account_id in node_ids
    ]
    edges = [
        RingEvidenceEdge(
            edge_id=int(row.edge_id),
            source_account=int(row.from_id),
            target_account=int(row.to_id),
            timestamp=to_utc(row.timestamp),
            amount_sent=_optional_float(row.amount_sent),
            amount_received=_optional_float(row.amount_received),
            currency_sent=currency_label(row.currency_sent),
            currency_received=currency_label(row.currency_received),
            payment_format=payment_format_label(row.payment_format),
            calibrated_score=_optional_float(scores_by_edge[row.edge_id].score_calibrated)
            if row.edge_id in scores_by_edge else None,
            is_seed=scores_by_edge[row.edge_id].is_seed if row.edge_id in scores_by_edge else None,
        )
        for row in transaction_rows
    ]
    next_before_edge_id = page_candidate_ids[-1] if has_more and page_candidate_ids else None
    return RingEvidenceGraph(
        tenant_id=tenant_id,
        ring_id=ring_id,
        nodes=nodes,
        edges=edges,
        next_before_edge_id=next_before_edge_id,
        missing_edge_ids=sorted(set(page_candidate_ids) - returned_edge_ids),
    )
