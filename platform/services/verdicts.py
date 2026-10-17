"""One verdict persistence path for analyst submissions and simulation jobs."""

from __future__ import annotations

from collections.abc import Sequence

from db.models import AuditLog, Ring, Verdict


def record_verdict(session, *, ring: Ring, tenant_id: int, ring_id: str, user_id: int,
                   verdict: str, corrected_members: Sequence[int] = (),
                   corrected_edges: Sequence[int] = (), note: str | None = None,
                   is_simulated: bool = False) -> Verdict:
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
    session.add(AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action="ring.verdict_recorded",
        object_type="ring",
        object_id=ring_id,
        details={"verdict_id": row.verdict_id, "verdict": verdict, "is_simulated": is_simulated},
    ))
    session.flush()
    return row
