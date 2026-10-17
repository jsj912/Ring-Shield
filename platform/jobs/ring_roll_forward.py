"""Stable ring identity matching shared by tenant refresh jobs."""

from __future__ import annotations

from typing import Any, Iterable


def assign_roll_forward_ring_ids(
    records: list[dict[str, Any]],
    existing_rows: Iterable[Any],
    *,
    model_id: str,
    seed: int,
    version: str,
    protected_ring_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Keep identities for similar open rings and allocate collision-free IDs otherwise.

    Existing ring identities are never renamed. Rows with verdicts are excluded from
    matching even if their status is unexpectedly still ``open``.
    """
    existing_rows = list(existing_rows)
    protected_ring_ids = protected_ring_ids or set()
    available = {
        str(row.ring_id): set(map(int, row.member_accounts or []))
        for row in existing_rows
        if row.status == "open" and str(row.ring_id) not in protected_ring_ids
    }
    all_ids = {str(row.ring_id) for row in existing_rows}
    assigned: set[str] = set()
    ordered = sorted(records, key=lambda item: (-float(item["confidence"]), str(item["ring_id"])))
    for idx, record in enumerate(ordered):
        members = set(map(int, record.get("members") or []))
        candidates: list[tuple[float, str]] = []
        for old_id, old_members in available.items():
            if old_id in assigned:
                continue
            union = members | old_members
            score = len(members & old_members) / len(union) if union else 1.0
            if score >= 0.5:
                candidates.append((score, old_id))
        if candidates:
            _, identity = max(candidates, key=lambda item: (item[0], item[1]))
            assigned.add(identity)
        else:
            counter = idx
            identity = f"full-{model_id}-{seed}-v{version}-{counter}"
            while identity in all_ids:
                counter += 1
                identity = f"full-{model_id}-{seed}-v{version}-{counter}"
            all_ids.add(identity)
        record["ring_id"] = identity
    return records
