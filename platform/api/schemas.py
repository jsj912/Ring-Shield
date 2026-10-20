"""Transport schemas for the platform API.

The research contract remains the source of truth for scored edges and rings;
these models describe the tenant-facing envelope and workflow records.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VerdictKind(str, Enum):
    confirm = "confirm"
    reject = "reject"
    partial = "partial"


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class SessionResponse(BaseModel):
    user_id: int
    tenant_id: int | None
    tenant_name: str
    role: str
    token: str
    expires_at: datetime


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    bank_code: int
    name: str
    is_loaded: bool
    created_at: datetime


class UserCreateRequest(BaseModel):
    tenant_id: int | None
    email: str
    password: str = Field(min_length=12, max_length=128)
    role: Literal["analyst", "supervisor", "admin"]

    @field_validator("password")
    @classmethod
    def bcrypt_byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value

    @model_validator(mode="after")
    def role_tenant_pair(self) -> "UserCreateRequest":
        if (self.role == "admin") != (self.tenant_id is None):
            raise ValueError("Admin users must be global; analyst and supervisor users need a tenant")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    tenant_id: int | None
    email: str
    role: str
    disabled: bool
    created_at: datetime


class RingSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ring_id: str
    tenant_id: int
    topology_type: str
    topology_prob: float = Field(ge=0, le=1)
    n_members: int = Field(ge=0)
    n_edges: int = Field(ge=0)
    total_amount: float | None
    total_currency: str | None
    n_currencies: int | None = Field(default=None, ge=1)
    start_time: datetime
    end_time: datetime
    confidence: float = Field(ge=0, le=1)
    cross_bank: bool
    counterparty_banks: list[str]
    status: str


class RingDetail(RingSummary):
    member_accounts: list[int]
    member_edges: list[int]
    seed_edges: list[int]
    expanded_edges: list[int]
    conservation_closure: float | None
    source_accounts: list[int]
    sink_accounts: list[int]
    mule_accounts: list[int]
    model_id: str
    aggregator_id: str


class RingPage(BaseModel):
    items: list[RingSummary]
    next_cursor: str | None = None
    total: int


class RingEvidenceNode(BaseModel):
    account_id: int
    bank_code: int | None
    bank_label: str | None
    is_source: bool
    is_sink: bool
    is_mule: bool


class RingEvidenceEdge(BaseModel):
    edge_id: int
    source_account: int
    target_account: int
    timestamp: datetime
    amount_sent: float | None
    amount_received: float | None
    currency_sent: str | None
    currency_received: str | None
    payment_format: str | None
    calibrated_score: float | None
    is_seed: bool | None


class RingEvidenceGraph(BaseModel):
    tenant_id: int
    ring_id: str
    nodes: list[RingEvidenceNode]
    edges: list[RingEvidenceEdge]
    next_before_edge_id: int | None = None
    missing_edge_ids: list[int] = Field(default_factory=list)


class RingExplanation(BaseModel):
    tenant_id: int
    ring_id: str
    explainer_version: str
    edge_weights: list[dict[str, Any]]
    account_weights: list[dict[str, Any]]
    feature_weights: list[dict[str, Any]]
    narrative: str
    evidence_summary: dict[str, Any]
    latency_ms: int
    provenance: dict[str, Any]
    created_at: datetime


class VerdictRequest(BaseModel):
    verdict: VerdictKind
    corrected_members: list[int] = Field(default_factory=list)
    corrected_edges: list[int] = Field(default_factory=list)
    note: str | None = None

    @model_validator(mode="after")
    def check_partial_correction(self) -> "VerdictRequest":
        if self.verdict == VerdictKind.partial:
            if not self.note or not self.note.strip():
                raise ValueError("A note is required for a partial verdict")
            if not self.corrected_members:
                raise ValueError("At least one corrected member must remain")
        return self


class VerdictResponse(BaseModel):
    verdict_id: int
    ring_id: str
    user_id: int
    user_name: str
    verdict: VerdictKind
    corrected_members: list[int]
    corrected_edges: list[int]
    note: str | None
    is_simulated: bool
    created_at: datetime


class VerdictHistoryPage(BaseModel):
    items: list[VerdictResponse]
    next_before_id: int | None = None


class ModelVersionSummary(BaseModel):
    model_version_id: int
    component: Literal["expansion", "affinity", "typing", "detector"]
    version_tag: str
    trained_at: datetime
    train_label_count: int = Field(ge=0)
    holdout_ring_f1: float | None = Field(default=None, ge=0, le=1)
    promoted: bool
    shared: bool


class ModelVersionPage(BaseModel):
    items: list[ModelVersionSummary]
    next_before_id: int | None = None
    active_model_id: str
    active_seed: int
    active_model_id: str
    active_seed: int


class DriftEventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    monitor: Literal["adwin_score_mean", "adwin_score_p99"]
    detected_at: datetime
    window_start: datetime
    window_end: datetime
    statistic: float
    threshold: float
    acted_on: bool


class DriftEventPage(BaseModel):
    items: list[DriftEventSummary]
    next_before_id: int | None = None


class DailyDriftStatistic(BaseModel):
    day: datetime
    mean: float
    p99: float


class DriftSeriesResponse(BaseModel):
    tenant_id: int
    active_model_id: str
    active_seed: int
    items: list[DailyDriftStatistic]


class DriftActedOnUpdate(BaseModel):
    acted_on: bool


class DriftCheckStarted(BaseModel):
    status: str


class ExperimentJobResponse(BaseModel):
    job_id: str
    status: str
    message: str | None = None
    results: dict | None = None


class RetrainRunCreated(BaseModel):
    run_id: str


class RetrainRunSummary(BaseModel):
    run_id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    model_version_id: int | None


class RetrainRunPage(BaseModel):
    items: list[RetrainRunSummary]


class RetrainRunStatusResponse(BaseModel):
    run_id: str
    status: str
    model_version_id: int | None
    log_lines: list[str]

