from __future__ import annotations

import base64
import binascii
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from api.dependencies import get_principal, require_tenant_access
from api.identity import Principal
from api.label_maps import currency_label, payment_format_label
from api.schemas import (RingDetail, RingEvidenceEdge, RingEvidenceGraph,
                         RingEvidenceNode, RingExplanation, RingPage, RingSummary)
from api.timebasis import from_utc, to_utc
from contract.schema import TOPOLOGY_TYPES
from db.models import Account, EdgeScore, Explanation, Ring as PlatformRing, Transaction
from db.session import db_session
from settings import load_platform_config

router = APIRouter(tags=["rings"])
SortField = Literal["confidence", "total_amount", "start_time", "members"]
SortOrder = Literal["asc", "desc"]
AllowedStatuses = {"open", "confirmed", "rejected", "partial"}
EvidenceRoleKeys = {
    "is_source": "source_accounts",
    "is_sink": "sink_accounts",
    "is_mule": "mule_accounts",
}


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
        explanation = session.scalar(
            select(Explanation)
            .where(Explanation.tenant_id == tenant_id, Explanation.ring_id == ring_id)
            .order_by(Explanation.created_at.desc(), Explanation.explainer_version.desc())
            .limit(1)
        )
        if explanation is None:
            raise HTTPException(status_code=404, detail="Explanation not found")
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
            edge_weights=explanation.edge_weights if isinstance(explanation.edge_weights, list) else [],
            account_weights=explanation.account_weights if isinstance(explanation.account_weights, list) else [],
            feature_weights=explanation.feature_weights if isinstance(explanation.feature_weights, list) else [],
            narrative=explanation.narrative,
            evidence_summary=explanation.evidence_summary,
            latency_ms=explanation.latency_ms,
            provenance=public_provenance,
            created_at=explanation.created_at,
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
    sort: SortField = "confidence",
    order: SortOrder = "desc",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
) -> RingPage:
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
    filters = {"status": sorted(statuses), "min_conf": min_conf,
               "topology_type": sorted(topology_type or []), "start_min": start_min,
               "start_max": start_max, "cross_bank_only": cross_bank_only,
               "sort": sort, "order": order}
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
