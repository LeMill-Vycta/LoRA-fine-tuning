from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import (
    current_tenant_id,
    current_user,
    get_db,
    require_api_key,
    require_operator_token_if_configured,
    require_role,
)
from app.core.config import get_settings
from app.core.metrics import render_metrics
from app.models import (
    AuditEvent,
    DatasetVersion,
    DeploymentPackage,
    Document,
    DocumentStatus,
    EvaluationReport,
    Membership,
    Project,
    Role,
    RunEvent,
    Tenant,
    TrainingRun,
    User,
)
from app.schemas import (
    AuditEventResponse,
    AuthMeResponse,
    ChatRequest,
    ChatResponse,
    DashboardResponse,
    DatasetCreateRequest,
    DatasetResponse,
    DeploymentCreateRequest,
    DeploymentResponse,
    DocumentResponse,
    DocumentUploadResponse,
    EvaluationReportResponse,
    HealthResponse,
    LoginRequest,
    ProjectCreateRequest,
    ProjectResponse,
    RegisterRequest,
    RunEventResponse,
    TenantCreateRequest,
    TenantPlanResponse,
    TenantPlanUpdateRequest,
    TenantResponse,
    TokenResponse,
    TrainingRunCreateRequest,
    TrainingRunResponse,
    VramEstimateResponse,
)
from app.services.audit import log_audit_event
from app.services.auth import AuthService, TenantService
from app.services.dataset import DatasetBuilderService
from app.services.deployment import DeploymentService
from app.services.entitlements import EntitlementService
from app.services.inference import InferenceService
from app.services.ingest import IngestionService
from app.services.project import ProjectService
from app.services.training import TrainingOrchestrator

router = APIRouter(prefix="/api/v1")


@router.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", version=get_settings().app_version)


@router.get("/metrics", tags=["ops"], dependencies=[Depends(require_api_key)])
def metrics() -> Any:
    return render_metrics()


@router.get("/models", tags=["ops"])
def supported_models() -> dict[str, Any]:
    return {"models": get_settings().supported_models}


@router.post("/auth/register", response_model=TokenResponse, tags=["auth"])
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    try:
        service.register_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    token = service.authenticate(payload.email, payload.password)
    return TokenResponse(access_token=token)


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    service = AuthService(db)
    try:
        token = service.authenticate(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=AuthMeResponse, tags=["auth"])
def auth_me(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> AuthMeResponse:
    rows = db.execute(
        select(Membership, Tenant)
        .join(Tenant, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user.id)
        .order_by(Tenant.created_at.asc())
    ).all()
    memberships = [
        {
            "tenant_id": membership.tenant_id,
            "tenant_name": tenant.name,
            "tenant_namespace": tenant.namespace,
            "role": membership.role,
        }
        for membership, tenant in rows
    ]
    return AuthMeResponse(
        user_id=user.id,
        email=user.email,
        is_active=user.is_active,
        memberships=memberships,
    )


@router.post("/tenants", response_model=TenantResponse, tags=["tenants"])
def create_tenant(
    payload: TenantCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TenantResponse:
    try:
        tenant = TenantService(db).create_tenant(user.id, payload.name, payload.namespace)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_audit_event(
        db,
        tenant_id=tenant.id,
        user_id=user.id,
        action="tenant_created",
        entity_type="tenant",
        entity_id=tenant.id,
        details={"namespace": tenant.namespace},
    )
    return TenantResponse.model_validate(tenant)


@router.get("/tenants/memberships", response_model=list[dict[str, Any]], tags=["tenants"])
def list_memberships(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    memberships = TenantService(db).list_memberships(user.id)
    return [{"tenant_id": item.tenant_id, "role": item.role.value} for item in memberships]


@router.get("/tenants/plan", response_model=TenantPlanResponse, tags=["tenants"])
def get_tenant_plan(
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> TenantPlanResponse:
    plan = EntitlementService(db).get_tenant_plan(tenant_id)
    return TenantPlanResponse.model_validate(plan)


@router.put(
    "/tenants/plan",
    response_model=TenantPlanResponse,
    tags=["tenants"],
    dependencies=[Depends(require_role(Role.OWNER))],
)
def set_tenant_plan(
    payload: TenantPlanUpdateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TenantPlanResponse:
    plan = EntitlementService(db).set_tenant_plan(tenant_id, payload.plan_tier)
    log_audit_event(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        action="tenant_plan_updated",
        entity_type="tenant_plan",
        entity_id=plan.id,
        details={"plan_tier": payload.plan_tier.value},
    )
    return TenantPlanResponse.model_validate(plan)


@router.post(
    "/projects",
    response_model=ProjectResponse,
    tags=["projects"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def create_project(
    payload: ProjectCreateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ProjectResponse:
    project = ProjectService(db).create_project(
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        style_rules=payload.style_rules,
        refusal_rules=payload.refusal_rules,
    )
    log_audit_event(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        project_id=project.id,
        action="project_created",
        entity_type="project",
        entity_id=project.id,
        details={"name": project.name},
    )
    return ProjectResponse.model_validate(project)


@router.get("/projects", response_model=list[ProjectResponse], tags=["projects"])
def list_projects(
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[ProjectResponse]:
    projects = ProjectService(db).list_projects(tenant_id)
    return [ProjectResponse.model_validate(item) for item in projects]


@router.get("/projects/{project_id}/dashboard", response_model=DashboardResponse, tags=["projects"])
def project_dashboard(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    try:
        payload = ProjectService(db).dashboard(tenant_id, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DashboardResponse(**payload)


@router.post(
    "/projects/{project_id}/documents/upload",
    response_model=DocumentUploadResponse,
    tags=["documents"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER, Role.REVIEWER))],
)
def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    metadata: str = Form(default="{}"),
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DocumentUploadResponse:
    project = db.get(Project, project_id)
    if not project or project.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    try:
        EntitlementService(db).assert_document_quota(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metadata must be valid JSON") from exc

    try:
        document = IngestionService(db).ingest_upload(
            tenant_id=tenant_id,
            project_id=project_id,
            file=file,
            metadata=meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        project_id=project_id,
        action="document_uploaded",
        entity_type="document",
        entity_id=document.id,
        details={"filename": document.filename, "status": document.status.value},
    )
    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        quality_score=document.quality_score,
        pii_hits=document.pii_hits,
        near_duplicate_of=document.near_duplicate_of,
    )


@router.get("/projects/{project_id}/documents", response_model=list[DocumentResponse], tags=["documents"])
def list_documents(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[DocumentResponse]:
    docs = list(
        db.scalars(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.project_id == project_id,
            )
        ).all()
    )
    return [DocumentResponse.model_validate(doc) for doc in docs]


@router.post(
    "/documents/{document_id}/status",
    response_model=DocumentResponse,
    tags=["documents"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER, Role.REVIEWER))],
)
def update_document_status(
    document_id: str,
    status_value: DocumentStatus,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DocumentResponse:
    document = db.get(Document, document_id)
    if not document or document.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    document.status = status_value
    db.commit()
    db.refresh(document)
    log_audit_event(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        project_id=document.project_id,
        action="document_status_updated",
        entity_type="document",
        entity_id=document.id,
        details={"status": status_value.value},
    )
    return DocumentResponse.model_validate(document)


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DatasetResponse,
    tags=["datasets"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER, Role.REVIEWER))],
)
def create_dataset(
    project_id: str,
    payload: DatasetCreateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DatasetResponse:
    project = db.get(Project, project_id)
    if not project or project.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    try:
        dataset = DatasetBuilderService(db).build_dataset(
            tenant_id=tenant_id,
            project_id=project_id,
            name=payload.name,
            document_ids=payload.document_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        project_id=project_id,
        action="dataset_created",
        entity_type="dataset",
        entity_id=dataset.id,
        details={"status": dataset.status.value, "quality": dataset.quality_score},
    )
    return DatasetResponse.model_validate(dataset)


@router.get("/projects/{project_id}/datasets", response_model=list[DatasetResponse], tags=["datasets"])
def list_datasets(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[DatasetResponse]:
    datasets = list(
        db.scalars(
            select(DatasetVersion).where(
                DatasetVersion.tenant_id == tenant_id,
                DatasetVersion.project_id == project_id,
            )
        ).all()
    )
    return [DatasetResponse.model_validate(item) for item in datasets]


@router.post(
    "/projects/{project_id}/runs/estimate",
    response_model=VramEstimateResponse,
    tags=["training"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def estimate_run(
    project_id: str,
    payload: TrainingRunCreateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> VramEstimateResponse:
    project = db.get(Project, project_id)
    if not project or project.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    result = TrainingOrchestrator(db).estimate_vram(
        config=payload.config.model_dump(),
        base_model_id=payload.base_model_id,
    )
    return VramEstimateResponse(**result)


@router.post(
    "/projects/{project_id}/runs",
    response_model=TrainingRunResponse,
    tags=["training"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def create_run(
    project_id: str,
    payload: TrainingRunCreateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TrainingRunResponse:
    project = db.get(Project, project_id)
    if not project or project.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    try:
        run = TrainingOrchestrator(db).create_run(
            tenant_id=tenant_id,
            project_id=project_id,
            dataset_version_id=payload.dataset_version_id,
            requested_by_user_id=user.id,
            base_model_id=payload.base_model_id,
            config=payload.config.model_dump(),
            data_rights_confirmed=payload.data_rights_confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return TrainingRunResponse.model_validate(run)


@router.get("/projects/{project_id}/runs", response_model=list[TrainingRunResponse], tags=["training"])
def list_runs(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[TrainingRunResponse]:
    runs = list(
        db.scalars(
            select(TrainingRun).where(
                TrainingRun.tenant_id == tenant_id,
                TrainingRun.project_id == project_id,
            )
        ).all()
    )
    return [TrainingRunResponse.model_validate(item) for item in runs]


@router.get("/runs/{run_id}/events", response_model=list[RunEventResponse], tags=["training"])
def run_events(
    run_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[RunEventResponse]:
    run = db.get(TrainingRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    events = list(
        db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id, RunEvent.tenant_id == tenant_id)
            .order_by(RunEvent.created_at.asc())
        ).all()
    )
    return [RunEventResponse.model_validate(event) for event in events]


@router.post(
    "/runs/process-next",
    response_model=TrainingRunResponse | None,
    tags=["training"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER)), Depends(require_operator_token_if_configured)],
)
def process_next_run(
    db: Session = Depends(get_db),
) -> TrainingRunResponse | None:
    run = TrainingOrchestrator(db).process_next_queued_run()
    return TrainingRunResponse.model_validate(run) if run else None


@router.post(
    "/runs/{run_id}/cancel",
    response_model=TrainingRunResponse,
    tags=["training"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def cancel_run(
    run_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TrainingRunResponse:
    run = db.get(TrainingRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    run = TrainingOrchestrator(db).cancel_run(run, user.id)
    return TrainingRunResponse.model_validate(run)


@router.post(
    "/runs/{run_id}/retry",
    response_model=TrainingRunResponse,
    tags=["training"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def retry_run(
    run_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TrainingRunResponse:
    run = db.get(TrainingRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    try:
        run = TrainingOrchestrator(db).retry_run(run, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TrainingRunResponse.model_validate(run)


@router.get(
    "/projects/{project_id}/evaluations",
    response_model=list[EvaluationReportResponse],
    tags=["evaluation"],
)
def list_evaluations(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[EvaluationReportResponse]:
    reports = list(
        db.scalars(
            select(EvaluationReport).where(
                EvaluationReport.tenant_id == tenant_id,
                EvaluationReport.project_id == project_id,
            )
        ).all()
    )
    return [EvaluationReportResponse.model_validate(item) for item in reports]


@router.post(
    "/projects/{project_id}/deployments",
    response_model=DeploymentResponse,
    tags=["deployments"],
    dependencies=[Depends(require_role(Role.OWNER, Role.MANAGER))],
)
def create_deployment(
    project_id: str,
    payload: DeploymentCreateRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeploymentResponse:
    try:
        deployment = DeploymentService(db).create_deployment(
            tenant_id=tenant_id,
            project_id=project_id,
            training_run_id=payload.training_run_id,
            version=payload.version,
            endpoint_url=payload.endpoint_url,
            user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DeploymentResponse.model_validate(deployment)


@router.get(
    "/projects/{project_id}/deployments",
    response_model=list[DeploymentResponse],
    tags=["deployments"],
)
def list_deployments(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[DeploymentResponse]:
    deployments = list(
        db.scalars(
            select(DeploymentPackage).where(
                DeploymentPackage.tenant_id == tenant_id,
                DeploymentPackage.project_id == project_id,
            )
        ).all()
    )
    return [DeploymentResponse.model_validate(item) for item in deployments]


@router.post("/inference/chat", response_model=ChatResponse, tags=["inference"])
def chat(
    payload: ChatRequest,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> ChatResponse:
    try:
        return InferenceService(db).chat(
            tenant_id=tenant_id,
            project_id=payload.project_id,
            question=payload.question,
            use_grounding=payload.use_grounding,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/audit",
    response_model=list[AuditEventResponse],
    tags=["audit"],
)
def project_audit(
    project_id: str,
    tenant_id: str = Depends(current_tenant_id),
    db: Session = Depends(get_db),
) -> list[AuditEventResponse]:
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.project_id == project_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(500)
        ).all()
    )
    return [AuditEventResponse.model_validate(event) for event in events]
