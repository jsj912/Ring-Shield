"""One verdict persistence path for analyst submissions and simulation jobs."""

from __future__ import annotations

from collections.abc import Sequence

from audit import add_audit_event
from db.models import Ring, Verdict


def record_verdict(session, *, ring: Ring, tenant_id: int, ring_id: str, user_id: int,
                   verdict: str, corrected_members: Sequence[int] = (),
                   corrected_edges: Sequence[int] = (), note: str | None = None,
                   is_simulated: bool = False, actor: str | None = None,
                   request_id: str | None = None) -> Verdict:
    if int(ring.tenant_id) != int(tenant_id) or ring.ring_id != ring_id:
        raise ValueError("verdict ring identity does not match tenant-scoped row")
    if verdict not in {"confirm", "reject", "partial"}:
        raise ValueError("unsupported verdict")
    row = Verdict(
        tenant_id=tenant_id,
        ring_id=ring_id,
        user_id=user_id,
        verdict=verdict,
        corrected_members=sorted(set(map(int, corrected_members))),
        corrected_edges=sorted(set(map(int, corrected_edges))),
        note=note,
        is_simulated=is_simulated,
    )
    ring.status = verdict
    session.add(row)
    session.flush()
    add_audit_event(session,
        tenant_id=tenant_id,
        user_id=user_id,
        actor=actor or f"user:{user_id}",
        action="verdict.recorded",
        entity_type="verdict",
        entity_id=row.verdict_id,
        request_id=request_id,
        details={"verdict": verdict, "is_simulated": is_simulated, "status": ring.status},
    )
    session.flush()
    return row
