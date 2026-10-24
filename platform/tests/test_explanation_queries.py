from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

from sqlalchemy import DateTime, Integer, String, create_engine, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.explanation_queries import (latest_explanation_statement,
                                      next_explanation_revision_statement)


class _Base(DeclarativeBase):
    pass


class _Explanation(_Base):
    __tablename__ = "test_explanations"

    tenant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ring_id: Mapped[str] = mapped_column(String, primary_key=True)
    explainer_version: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    narrative: Mapped[str] = mapped_column(String, nullable=False)


def _utc(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=timezone.utc)


def _latest(session: Session, tenant_id: int, ring_id: str):
    return session.scalar(latest_explanation_statement(
        tenant_id, ring_id, model=_Explanation,
    ))


def test_latest_version_uses_first_storage_time_then_highest_revision():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            _Explanation(tenant_id=21, ring_id="r", explainer_version="0.4.0",
                         revision=1, created_at=_utc(1), narrative="old"),
            _Explanation(tenant_id=21, ring_id="r", explainer_version="0.5.0",
                         revision=1, created_at=_utc(2), narrative="new"),
            _Explanation(tenant_id=21, ring_id="r", explainer_version="0.5.0",
                         revision=2, created_at=_utc(3), narrative="regenerated"),
        ])
        session.commit()

        latest = _latest(session, 21, "r")

    assert (latest.explainer_version, latest.revision) == ("0.5.0", 2)


def test_reloading_old_version_does_not_change_its_first_storage_time():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        old = _Explanation(tenant_id=21, ring_id="r", explainer_version="0.4.0",
                           revision=1, created_at=_utc(1), narrative="old")
        session.add(old)
        session.commit()
        original_created_at = old.created_at
        session.add(_Explanation(tenant_id=21, ring_id="r", explainer_version="0.5.0",
                                 revision=1, created_at=_utc(2), narrative="new"))
        session.commit()

        # This mirrors the loader upsert: payload fields can refresh, created_at cannot.
        session.execute(update(_Explanation).where(
            _Explanation.tenant_id == 21,
            _Explanation.ring_id == "r",
            _Explanation.explainer_version == "0.4.0",
            _Explanation.revision == 1,
        ).values(narrative="reloaded old"))
        session.commit()
        old_after_reload = session.scalar(select(_Explanation).where(
            _Explanation.explainer_version == "0.4.0",
        ))
        latest = _latest(session, 21, "r")

    assert old_after_reload.created_at == original_created_at
    assert (latest.explainer_version, latest.revision) == ("0.5.0", 1)


def test_latest_query_and_next_revision_are_tenant_scoped():
    latest_sql = str(latest_explanation_statement(
        21, "r", model=_Explanation,
    ).compile(dialect=postgresql.dialect())).lower()
    next_sql = str(next_explanation_revision_statement(
        21, "r", "0.5.0", model=_Explanation,
    ).compile(dialect=postgresql.dialect())).lower()
    assert "test_explanations.tenant_id =" in latest_sql
    assert "test_explanations.ring_id =" in latest_sql
    assert "min(" in latest_sql
    assert "test_explanations.tenant_id =" in next_sql
    assert "test_explanations.ring_id =" in next_sql
    assert "test_explanations.explainer_version =" in next_sql

    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            _Explanation(tenant_id=21, ring_id="r", explainer_version="0.5.0",
                         revision=2, created_at=_utc(2), narrative="tenant A"),
            _Explanation(tenant_id=22, ring_id="r", explainer_version="0.5.0",
                         revision=9, created_at=_utc(9), narrative="tenant B"),
        ])
        session.commit()
        tenant_a = _latest(session, 21, "r")
        next_a = session.scalar(next_explanation_revision_statement(
            21, "r", "0.5.0", model=_Explanation,
        ))

    assert tenant_a.tenant_id == 21
    assert tenant_a.revision == 2
    assert next_a == 3
