from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeploymentPackage, DeploymentStatus, EvaluationReport, Project, RunState, TrainingRun


class ProjectService:
    def __init__(self, db: Session):
        self.db = db

    def create_project(
        self,
        *,
        tenant_id: str,
        name: str,
        description: str | None,
        system_prompt: str | None,
        style_rules: list[str],
        refusal_rules: list[str],
    ) -> Project:
        project = Project(
            tenant_id=tenant_id,
            name=name,
            description=description,
            system_prompt=system_prompt
            or "You are a specialized business assistant. Answer with grounded evidence and safe refusals.",
            style_rules=style_rules,
            refusal_rules=refusal_rules,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def list_projects(self, tenant_id: str) -> list[Project]:
        return list(self.db.scalars(select(Project).where(Project.tenant_id == tenant_id)).all())

    def dashboard(self, tenant_id: str, project_id: str) -> dict:
        project = self.db.get(Project, project_id)
        if not project or project.tenant_id != tenant_id:
            raise ValueError("Project not found")

        active_deployment = self.db.scalar(
            select(DeploymentPackage)
            .where(
                DeploymentPackage.tenant_id == tenant_id,
                DeploymentPackage.project_id == project_id,
                DeploymentPackage.status == DeploymentStatus.ACTIVE,
            )
            .order_by(DeploymentPackage.created_at.desc())
            .limit(1)
        )

        latest_report = self.db.scalar(
            select(EvaluationReport)
            .where(
                EvaluationReport.tenant_id == tenant_id,
                EvaluationReport.project_id == project_id,
            )
            .order_by(EvaluationReport.created_at.desc())
            .limit(1)
        )

        latest_run = self.db.scalar(
            select(TrainingRun)
            .where(
                TrainingRun.tenant_id == tenant_id,
                TrainingRun.project_id == project_id,
            )
            .order_by(TrainingRun.updated_at.desc())
            .limit(1)
        )

        alerts: list[str] = []
        if latest_run and latest_run.state in {RunState.FAILED, RunState.CANCELLED}:
            alerts.append("Recent training run ended in failure/cancellation")
        if latest_report and not latest_report.go_no_go:
            alerts.append("Latest eval report indicates no-go")
        if not active_deployment:
            alerts.append("No active deployment")

        return {
            "active_model_version": active_deployment.version if active_deployment else None,
            "latest_eval_score": float(latest_report.metrics_json.get("semantic_similarity")) if latest_report else None,
            "last_update": latest_run.updated_at if latest_run else None,
            "alerts": alerts,
        }

