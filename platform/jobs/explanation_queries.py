"""Tenant-scoped query builders for explanation revisions."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from db.models import Explanation


def latest_explanation_statement(tenant_id: int, ring_id: str, *, model=Explanation):
    """Select the highest revision of the version first stored most recently."""
    version_row = aliased(model)
    first_stored_at = (
        select(func.min(version_row.created_at))
        .where(
            version_row.tenant_id == tenant_id,
            version_row.ring_id == ring_id,
            version_row.explainer_version == model.explainer_version,
        )
        .correlate(model)
        .scalar_subquery()
    )
    return (
        select(model)
        .where(model.tenant_id == tenant_id, model.ring_id == ring_id)
        .order_by(first_stored_at.desc(), model.revision.desc(), model.created_at.desc())
        .limit(1)
    )


def next_explanation_revision_statement(
    tenant_id: int, ring_id: str, explainer_version: str, *, model=Explanation,
):
    """Return the next revision number within one tenant, ring, and version."""
    return select(func.coalesce(func.max(model.revision), 0) + 1).where(
        model.tenant_id == tenant_id,
        model.ring_id == ring_id,
        model.explainer_version == explainer_version,
    )
