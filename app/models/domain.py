from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Role(str, enum.Enum):
    OWNER = "owner"
    MANAGER = "manager"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class PlanTier(str, enum.Enum):
    STARTER = "starter"
    STANDARD = "standard"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class DocumentStatus(str, enum.Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    REDACTION_REQUIRED = "redaction_required"
    REJECTED = "rejected"


class DatasetStatus(str, enum.Enum):
    BUILDING = "building"
    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class RunState(str, enum.Enum):
    QUEUED = "queued"
    PREFLIGHT = "preflight"
    STAGING = "staging"
    TRAINING = "training"
    EVALUATING = "evaluating"
    PACKAGING = "packaging"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentStatus(str, enum.Enum):
    CREATED = "created"
    ACTIVE = "active"
    ARCHIVED = "archived"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_membership_user_tenant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


class TenantPlan(Base):
    __tablename__ = "tenant_plans"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_plan_tenant"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    plan_tier: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.STARTER, nullable=False)
    max_documents: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    max_training_runs_monthly: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_storage_mb: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(
        Text,
        default="You are a domain assistant. Use grounded knowledge and refuse unsupported claims.",
        nullable=False,
    )
    style_rules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    refusal_rules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_text_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    near_duplicate_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pii_hits: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), default=DocumentStatus.READY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[DatasetStatus] = mapped_column(Enum(DatasetStatus), default=DatasetStatus.BUILDING, nullable=False)
    source_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    train_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    val_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    test_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    gold_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    review_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    stats_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    quality_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TrainingRun(Base):
    __tablename__ = "training_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    dataset_version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id"), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    base_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[RunState] = mapped_column(Enum(RunState), default=RunState.QUEUED, nullable=False, index=True)
    state_message: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    vram_estimate_gb: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    checkpoint_path: Mapped[str | None] = mapped_column(String(1024))
    adapter_path: Mapped[str | None] = mapped_column(String(1024))
    package_path: Mapped[str | None] = mapped_column(String(1024))
    eval_report_id: Mapped[str | None] = mapped_column(ForeignKey("evaluation_reports.id"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EvaluationReport(Base):
    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    training_run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), nullable=False, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    go_no_go: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failure_modes: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    report_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DeploymentPackage(Base):
    __tablename__ = "deployment_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    training_run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DeploymentStatus] = mapped_column(Enum(DeploymentStatus), default=DeploymentStatus.CREATED, nullable=False)
    package_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36))
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), nullable=False, index=True)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

