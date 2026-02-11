from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models import DatasetStatus, DeploymentStatus, DocumentStatus, PlanTier, Role, RunState


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    namespace: str = Field(min_length=2, max_length=255)


class TenantResponse(BaseModel):
    id: str
    name: str
    namespace: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MembershipResponse(BaseModel):
    tenant_id: str
    role: Role


class AuthMembershipResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    tenant_namespace: str
    role: Role


class AuthMeResponse(BaseModel):
    user_id: str
    email: str
    is_active: bool
    memberships: list[AuthMembershipResponse]


class TenantPlanResponse(BaseModel):
    tenant_id: str
    plan_tier: PlanTier
    max_documents: int
    max_training_runs_monthly: int
    max_storage_mb: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantPlanUpdateRequest(BaseModel):
    plan_tier: PlanTier


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    style_rules: list[str] = Field(default_factory=list)
    refusal_rules: list[str] = Field(default_factory=list)


class ProjectResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    system_prompt: str
    style_rules: list[str]
    refusal_rules: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    status: DocumentStatus
    quality_score: int
    pii_hits: list[dict[str, Any]]
    near_duplicate_of: str | None


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    filename: str
    file_type: str
    quality_score: int
    status: DocumentStatus
    pii_hits: list[dict[str, Any]]
    metadata_json: dict[str, Any]
    near_duplicate_of: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    document_ids: list[str] | None = None


class DatasetResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    name: str
    status: DatasetStatus
    source_document_ids: list[str]
    stats_json: dict[str, Any]
    quality_score: int
    created_at: datetime

    model_config = {"from_attributes": True}


class VramEstimateResponse(BaseModel):
    estimated_gb: float
    safe_limit_gb: float
    will_fit: bool
    recommendation: str


class TrainingConfig(BaseModel):
    lora_rank: int = Field(default=16, ge=4, le=256)
    lora_alpha: int = Field(default=32, ge=8, le=512)
    lora_dropout: float = Field(default=0.05, ge=0.0, le=0.6)
    sequence_length: int = Field(default=1024, ge=256, le=8192)
    per_device_batch_size: int = Field(default=1, ge=1, le=64)
    gradient_accumulation_steps: int = Field(default=8, ge=1, le=1024)
    precision: str = Field(default="bf16")
    epochs: int = Field(default=3, ge=1, le=30)
    max_steps: int = Field(default=0, ge=0, le=200000)
    save_every_steps: int = Field(default=100, ge=10, le=50000)
    use_4bit: bool = True


class TrainingRunCreateRequest(BaseModel):
    dataset_version_id: str
    base_model_id: str
    config: TrainingConfig
    data_rights_confirmed: bool = True


class TrainingRunResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    dataset_version_id: str
    base_model_id: str
    state: RunState
    progress: float
    state_message: str | None
    vram_estimate_gb: float
    checkpoint_path: str | None
    adapter_path: str | None
    package_path: str | None
    eval_report_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RunEventResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    run_id: str
    from_state: str | None
    to_state: str
    message: str | None
    details_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class EvaluationReportResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    training_run_id: str
    metrics_json: dict[str, Any]
    go_no_go: bool
    failure_modes: list[dict[str, Any]]
    report_path: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DeploymentCreateRequest(BaseModel):
    training_run_id: str
    version: str = Field(min_length=1, max_length=64)
    endpoint_url: str | None = None


class DeploymentResponse(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    training_run_id: str
    version: str
    status: DeploymentStatus
    package_path: str
    endpoint_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=3)
    use_grounding: bool = True


class Citation(BaseModel):
    document_id: str
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    latency_ms: int


class AuditEventResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str | None
    project_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: str
    version: str


class DashboardResponse(BaseModel):
    active_model_version: str | None
    latest_eval_score: float | None
    last_update: datetime | None
    alerts: list[str]

