"""Safe, transaction-local audit event writer for platform state changes."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import insert

from db.models import AuditLog

_ALLOWED_DETAIL_KEYS = {
    "status", "verdict", "is_simulated", "reviewed", "inserted",
    "visible_edge_rows", "edge_score_rows", "unique_source_edges", "account_tenant_rows",
    "rings_loaded", "rings_preserved_after_verdict", "explanations_loaded", "rows_validated",
    "component", "version_tag", "promoted", "gate_reason", "model_version_id",
    "run_id", "role", "acted_on",
    "banks", "accounts", "loaded",
}
_UNSAFE_TEXT = re.compile(r"(?:[A-Za-z]:\\|/[^/\s]+/|\b[^\s@]+@[^\s@]+\b)")


def add_audit_event(
    session,
    *,
    tenant_id: int | None,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    details: dict[str, Any] | None = None,
    user_id: int | None = None,
    request_id: str | None = None,
) -> None:
    """Append one small safe event in the caller's existing transaction.

    Deliberately accepts only an allow-list of short scalar details. This keeps
    audit rows out of the business payload, which may contain secrets or evidence.
    """
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if key not in _ALLOWED_DETAIL_KEYS:
            raise ValueError(f"unsupported audit detail field: {key}")
        if isinstance(value, bool) or value is None:
            safe_details[key] = value
        elif isinstance(value, int):
            safe_details[key] = value
        elif isinstance(value, float):
            if not (float("-inf") < value < float("inf")):
                raise ValueError("audit detail numbers must be finite")
            safe_details[key] = value
        elif isinstance(value, str) and len(value) <= 180 and not _UNSAFE_TEXT.search(value):
            safe_details[key] = value
        else:
            raise ValueError(f"unsafe audit detail value for {key}")
    if not action or "." not in action or len(action) > 80:
        raise ValueError("audit action must be a dotted event name")
    if not actor or len(actor) > 80 or _UNSAFE_TEXT.search(actor):
        raise ValueError("audit actor must be a safe identifier")
    entity_value = None if entity_id is None else str(entity_id)
    if entity_value is not None and (len(entity_value) > 180 or _UNSAFE_TEXT.search(entity_value)):
        raise ValueError("audit entity ID must be a safe identifier")
    values = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "actor": actor,
        "action": action,
        "object_type": entity_type,
        "object_id": entity_value,
        "request_id": request_id,
        "details": safe_details,
    }
    # Keep this as Core DML with no RETURNING or ORM flush. INSERT privilege
    # (and sequence USAGE for log_id) is sufficient for loader/simulator callers.
    session.execute(_audit_insert_statement(values))


def _audit_insert_statement(values: dict[str, Any]):
    """Build the Core INSERT so its privilege requirements can be tested."""
    return insert(AuditLog.__table__).inline().values(**values)
