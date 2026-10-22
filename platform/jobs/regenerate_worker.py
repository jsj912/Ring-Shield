"""Claim and execute one tenant explanation-regeneration job."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import literal, select, update
from sqlalchemy.dialects.postgresql import insert

from adapters import xai
from audit import add_audit_event
from db.models import Explanation, ExplanationJob
from db.session import loader_db_session
from jobs.explanation_validation import normalize_regenerated_row
from jobs.explanation_queries import next_explanation_revision_statement
from settings import load_platform_config

_SAFE_CODES = {
    "not_configured", "timeout", "connection_failed", "ring_not_found",
    "invalid_edit", "unexpected_status", "invalid_response", "validation_failed",
    "storage_failed", "job_not_found",
}
_UNSAFE_MESSAGE = re.compile(r"(?:https?://|[A-Za-z]:\\|/[^/\s]+/|\b[^\s@]+@[^\s@]+\b)", re.I)


def tenant_from_job_id(job_id: str) -> int:
    """Extract the tenant prefix required to enter the loader's forced-RLS scope."""
    match = re.fullmatch(r"([1-9]\d*)\.[0-9a-f]{32}", job_id)
    if not match:
        raise ValueError("job_id must use <tenant_id>.<uuidhex>")
    return int(match.group(1))


def _safe_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, xai.XaiError):
        code = exc.code if exc.code in _SAFE_CODES else "xai_error"
        message = getattr(exc, "safe_message", "L4 explanation service request failed")
        if _UNSAFE_MESSAGE.search(message) or "RINGSHIELD_XAI_TOKEN" in message:
            message = "L4 explanation service rejected the request"
        return message[:240], code
    if isinstance(exc, ValueError):
        return "L4 explanation result failed tenant validation", "validation_failed"
    return "Explanation regeneration could not be completed", "storage_failed"


def _claim(tenant_id: int, job_id: str) -> dict[str, Any] | None:
    with loader_db_session(tenant_id=tenant_id) as session:
        job = session.scalar(
            select(ExplanationJob)
            .where(ExplanationJob.tenant_id == tenant_id, ExplanationJob.job_id == job_id,
                   ExplanationJob.status == "queued")
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        session.flush()
        return {
            "tenant_id": job.tenant_id, "ring_id": job.ring_id,
            "excluded_members": list(job.excluded_members or []),
            "excluded_edges": list(job.excluded_edges or []),
        }


def _insert_revision(session, row: dict[str, Any], *, tenant_id: int) -> int | None:
    next_revision = next_explanation_revision_statement(
        tenant_id, row["ring_id"], row["explainer_version"],
    )
    columns = (
        "tenant_id", "ring_id", "explainer_version", "revision", "edge_weights",
        "account_weights", "feature_weights", "narrative", "evidence_summary",
        "latency_ms", "provenance", "fx_rates_sha256",
    )
    source = select(
        literal(tenant_id),
        literal(row["ring_id"], type_=Explanation.ring_id.type),
        literal(row["explainer_version"], type_=Explanation.explainer_version.type),
        next_revision.scalar_subquery(),
        literal(row["edge_weights"], type_=Explanation.edge_weights.type),
        literal(row["account_weights"], type_=Explanation.account_weights.type),
        literal(row["feature_weights"], type_=Explanation.feature_weights.type),
        literal(row["narrative"], type_=Explanation.narrative.type),
        literal(row["evidence_summary"], type_=Explanation.evidence_summary.type),
        literal(row["latency_ms"], type_=Explanation.latency_ms.type),
        literal(row["provenance"], type_=Explanation.provenance.type),
        literal(row["fx_rates_sha256"], type_=Explanation.fx_rates_sha256.type),
    )
    statement = insert(Explanation).from_select(columns, source).on_conflict_do_nothing(
        index_elements=[Explanation.tenant_id, Explanation.ring_id,
                        Explanation.explainer_version, Explanation.revision]
    ).returning(Explanation.revision)
    result = session.execute(statement)
    return result.scalar_one_or_none()


def _finish_failure(tenant_id: int, job_id: str, message: str, code: str) -> None:
    with loader_db_session(tenant_id=tenant_id) as session:
        session.execute(update(ExplanationJob).where(
            ExplanationJob.tenant_id == tenant_id, ExplanationJob.job_id == job_id,
            ExplanationJob.status == "running",
        ).values(status="failed", error=message, finished_at=datetime.now(timezone.utc)))
        add_audit_event(
            session, tenant_id=tenant_id, actor="regenerate_worker",
            action="explanation.regeneration_failed", entity_type="explanation_job",
            entity_id=job_id, details={"error_code": code},
        )


def run_job(job_id: str, *, client=None, config: dict[str, Any] | None = None) -> bool:
    tenant_id = tenant_from_job_id(job_id)
    job = _claim(tenant_id, job_id)
    if job is None:
        return False
    root_config = config if config is not None else load_platform_config()
    try:
        result = xai.regenerate(
            tenant_id, job["ring_id"], job["excluded_members"], job["excluded_edges"],
            config=root_config, client=client,
        )
        row = normalize_regenerated_row(
            result, tenant_id=tenant_id, ring_id=job["ring_id"],
            excluded_members=job["excluded_members"], excluded_edges=job["excluded_edges"],
            config=root_config,
        )
        revision = None
        for _attempt in range(2):
            with loader_db_session(tenant_id=tenant_id) as session:
                revision = _insert_revision(session, row, tenant_id=tenant_id)
                if revision is not None:
                    session.execute(update(ExplanationJob).where(
                        ExplanationJob.tenant_id == tenant_id,
                        ExplanationJob.job_id == job_id,
                        ExplanationJob.status == "running",
                    ).values(status="succeeded", result_revision=revision, error=None,
                             finished_at=datetime.now(timezone.utc)))
                    add_audit_event(
                        session, tenant_id=tenant_id, actor="regenerate_worker",
                        action="explanation.regeneration_succeeded",
                        entity_type="explanation_job", entity_id=job_id,
                        details={"revision": revision},
                    )
                    break
        if revision is None:
            raise RuntimeError("storage collision")
        return True
    except Exception as exc:
        message, code = _safe_error(exc)
        _finish_failure(tenant_id, job_id, message, code)
        return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m jobs.regenerate_worker TENANT_ID.UUIDHEX")
    try:
        claimed = run_job(args[0])
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    return 0 if claimed else 1


if __name__ == "__main__":
    raise SystemExit(main())
