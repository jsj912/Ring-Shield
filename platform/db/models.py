"""Platform persistence models. Research payloads remain losslessly in JSONB."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bank_code: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_loaded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('analyst', 'supervisor', 'admin')", name="ck_users_role"),
        CheckConstraint(
            "(role = 'admin' AND tenant_id IS NULL) OR "
            "(role IN ('analyst', 'supervisor') AND tenant_id IS NOT NULL)",
            name="ck_users_role_tenant",
        ),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("tenant_id", "user_id", name="uq_users_tenant_user"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.tenant_id"), nullable=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


Index("uq_users_email_lower", func.lower(User.email), unique=True)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        Index("ix_accounts_tenant_bank", "tenant_id", "bank_code"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bank_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_seen: Mapped[int | None] = mapped_column(BigInteger)
    last_seen: Mapped[int | None] = mapped_column(BigInteger)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        Index("ix_transactions_tenant_time", "tenant_id", "timestamp"),
        Index("ix_transactions_tenant_from", "tenant_id", "from_id"),
        Index("ix_transactions_tenant_to", "tenant_id", "to_id"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    edge_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    from_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_bank: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_bank: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_sent: Mapped[float | None] = mapped_column(Float)
    amount_received: Mapped[float | None] = mapped_column(Float)
    currency_sent: Mapped[int | None] = mapped_column(Integer)
    currency_received: Mapped[int | None] = mapped_column(Integer)
    payment_format: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class EdgeScore(Base):
    """Model-specific detector scores; a new model never replaces another model's scores."""
    __tablename__ = "edge_scores"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        Index("ix_edge_scores_active", "tenant_id", "model_id", "seed", "edge_id"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    edge_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    seed: Mapped[int] = mapped_column(Integer, primary_key=True)
    score_raw: Mapped[float | None] = mapped_column(Float)
    score_calibrated: Mapped[float | None] = mapped_column(Float)
    is_seed: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class Ring(Base):
    __tablename__ = "rings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        CheckConstraint("scope IN ('tenant', 'pooled')", name="ck_rings_scope"),
        CheckConstraint("status IN ('open', 'confirmed', 'rejected', 'partial')", name="ck_rings_status"),
        Index("ix_rings_tenant_status_conf", "tenant_id", "status", text("confidence DESC")),
        Index("ix_rings_tenant_start", "tenant_id", "start_time"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ring_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregator_id: Mapped[str] = mapped_column(String(40), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(String(12), nullable=False, server_default="tenant")
    member_accounts: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    member_edges: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    seed_edges: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    expanded_edges: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    conservation_closure: Mapped[float | None] = mapped_column(Float)
    topology_type: Mapped[str] = mapped_column(String(32), nullable=False)
    topology_probs: Mapped[list[float]] = mapped_column(ARRAY(Float, dimensions=1), nullable=False)
    start_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_time: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class Explanation(Base):
    __tablename__ = "explanations"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "ring_id"], ["rings.tenant_id", "rings.ring_id"], ondelete="CASCADE"),
    )

    tenant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ring_id: Mapped[str] = mapped_column(String(180), primary_key=True)
    explainer_version: Mapped[str] = mapped_column(String(80), primary_key=True)
    edge_weights: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    account_weights: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    feature_weights: Mapped[list | dict] = mapped_column(JSONB, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fx_rates_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "ring_id"], ["rings.tenant_id", "rings.ring_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.user_id"]),
        CheckConstraint("verdict IN ('confirm', 'reject', 'partial')", name="ck_verdicts_kind"),
        Index("ix_verdicts_tenant_created", "tenant_id", "created_at"),
        Index("ix_verdicts_tenant_ring_created", "tenant_id", "ring_id", text("created_at DESC")),
    )

    verdict_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ring_id: Mapped[str] = mapped_column(String(180), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)
    corrected_members: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False, default=list)
    corrected_edges: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint("component IN ('expansion', 'affinity', 'typing', 'detector')", name="ck_model_versions_component"),
        UniqueConstraint("tenant_id", "model_version_id", name="uq_model_versions_tenant_version"),
        Index("uq_model_versions_promoted", "tenant_id", "component", unique=True,
              postgresql_where=text("promoted IS TRUE")),
        Index("ix_model_versions_tenant_component", "tenant_id", "component", "trained_at"),
    )

    model_version_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.tenant_id"))
    component: Mapped[str] = mapped_column(String(16), nullable=False)
    version_tag: Mapped[str] = mapped_column(String(80), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_label_count: Mapped[int] = mapped_column(Integer, nullable=False)
    holdout_ring_f1: Mapped[float | None] = mapped_column(Float)
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    gate_reason: Mapped[str | None] = mapped_column(Text)
    artifact_path: Mapped[str | None] = mapped_column(Text)


class RetrainRun(Base):
    __tablename__ = "retrain_runs"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "model_version_id"],
                             ["model_versions.tenant_id", "model_versions.model_version_id"]),
        CheckConstraint("triggered_by IN ('schedule', 'supervisor')", name="ck_retrain_runs_trigger"),
        Index("ix_retrain_runs_tenant_started", "tenant_id", "started_at"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.tenant_id"), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version_id: Mapped[int | None] = mapped_column(BigInteger)
    log_path: Mapped[str | None] = mapped_column(Text)


class DriftEvent(Base):
    __tablename__ = "drift_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        CheckConstraint("monitor IN ('adwin_score_mean', 'adwin_score_p99')", name="ck_drift_events_monitor"),
        UniqueConstraint("tenant_id", "monitor", "window_end",
                         name="uq_drift_events_tenant_monitor_window_end"),
        Index("ix_drift_events_tenant_detected", "tenant_id", "detected_at"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monitor: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    statistic: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    acted_on: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        Index("ix_audit_log_tenant_at", "tenant_id", "at"),
    )

    log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(180))
    request_id: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
