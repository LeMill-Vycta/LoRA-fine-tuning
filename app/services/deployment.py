from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeploymentPackage, DeploymentStatus, RunState, TrainingRun
from app.services.audit import log_audit_event


class DeploymentService:
    def __init__(self, db: Session):
        self.db = db

    def create_deployment(
        self,
        *,
        tenant_id: str,
        project_id: str,
        training_run_id: str,
        version: str,
        endpoint_url: str | None,
        user_id: str,
    ) -> DeploymentPackage:
        run = self.db.get(TrainingRun, training_run_id)
        if not run or run.tenant_id != tenant_id or run.project_id != project_id:
            raise ValueError("Training run not found")
        if run.state != RunState.READY or not run.package_path:
            raise ValueError("Training run is not deployable")

        existing_active = list(
            self.db.scalars(
                select(DeploymentPackage).where(
                    DeploymentPackage.tenant_id == tenant_id,
                    DeploymentPackage.project_id == project_id,
                    DeploymentPackage.status == DeploymentStatus.ACTIVE,
                )
            ).all()
        )
        for deployment in existing_active:
            deployment.status = DeploymentStatus.ARCHIVED

        deployment = DeploymentPackage(
            tenant_id=tenant_id,
            project_id=project_id,
            training_run_id=training_run_id,
            version=version,
            status=DeploymentStatus.ACTIVE,
            package_path=run.package_path,
            endpoint_url=endpoint_url,
        )
        self.db.add(deployment)
        self.db.commit()
        self.db.refresh(deployment)

        log_audit_event(
            self.db,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=project_id,
            action="deployment_activated",
            entity_type="deployment",
            entity_id=deployment.id,
            details={"run_id": training_run_id, "version": version},
        )
        return deployment

    def active_deployment(self, tenant_id: str, project_id: str) -> DeploymentPackage | None:
        return self.db.scalar(
            select(DeploymentPackage)
            .where(
                DeploymentPackage.tenant_id == tenant_id,
                DeploymentPackage.project_id == project_id,
                DeploymentPackage.status == DeploymentStatus.ACTIVE,
            )
            .order_by(DeploymentPackage.created_at.desc())
            .limit(1)
        )

