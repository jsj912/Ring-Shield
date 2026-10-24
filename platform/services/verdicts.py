"""One verdict persistence path for analyst submissions and simulation jobs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from audit import add_audit_event
from db.models import Ring, Verdict


class PartialCorrectionError(ValueError):
    """A partial correction cannot produce a valid tenant-visible ring."""


def map_partial_correction_to_exclusions(
    *,
    member_accounts: Sequence[int],
    member_edges: Sequence[int],
    edge_endpoints: Mapping[int, tuple[int, int]],
    corrected_members: Sequence[int],
    corrected_edges: Sequence[int] | None,
) -> tuple[list[int], list[int]]:
    """Validate kept members/edges and return the server-computed L4 exclusions."""
    members = [int(value) for value in member_accounts]
    edges = [int(value) for value in member_edges]
    kept_members = [int(value) for value in corrected_members]
    if len(members) != len(set(members)) or len(edges) != len(set(edges)):
        raise PartialCorrectionError("Ring membership data is invalid")
    if len(kept_members) != len(set(kept_members)):
        raise PartialCorrectionError("Corrected members must be unique")
    if not set(kept_members) <= set(members):
        raise PartialCorrectionError("Corrected members must belong to this ring")
    if len(kept_members) < 2:
        raise PartialCorrectionError("At least two corrected members must remain")
    if len(kept_members) >= len(members):
        raise PartialCorrectionError("A partial correction must remove at least one member")

    if corrected_edges is None:
        if not set(edges) <= set(edge_endpoints):
            raise PartialCorrectionError("Ring edge data is incomplete")
        kept_edges = {
            edge_id for edge_id in edges
            if set(edge_endpoints[edge_id]) <= set(kept_members)
        }
        excluded_edges: list[int] = []
    else:
        requested_edges = [int(value) for value in corrected_edges]
        if len(requested_edges) != len(set(requested_edges)):
            raise PartialCorrectionError("Corrected edges must be unique")
        if not set(requested_edges) <= set(edges):
            raise PartialCorrectionError("Corrected edges must belong to this ring")
        if any(edge_id not in edge_endpoints for edge_id in requested_edges):
            raise PartialCorrectionError("Ring edge data is incomplete")
        if any(not set(edge_endpoints[edge_id]) <= set(kept_members)
               for edge_id in requested_edges):
            raise PartialCorrectionError("Corrected edges must connect corrected members")
        kept_edges = set(requested_edges)
        excluded_edges = sorted(set(edges) - kept_edges)
    if not kept_edges:
        raise PartialCorrectionError("At least one ring edge must remain")

    return sorted(set(members) - set(kept_members)), excluded_edges


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
