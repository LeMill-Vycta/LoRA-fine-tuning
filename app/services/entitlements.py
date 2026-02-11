from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, PlanTier, TenantPlan, TrainingRun


@dataclass(frozen=True)
class PlanLimits:
    max_documents: int
    max_training_runs_monthly: int
    max_storage_mb: int


PLAN_LIMITS: dict[PlanTier, PlanLimits] = {
    PlanTier.STARTER: PlanLimits(max_documents=200, max_training_runs_monthly=10, max_storage_mb=2048),
    PlanTier.STANDARD: PlanLimits(max_documents=1000, max_training_runs_monthly=50, max_storage_mb=10240),
    PlanTier.PRO: PlanLimits(max_documents=5000, max_training_runs_monthly=200, max_storage_mb=51200),
    PlanTier.ENTERPRISE: PlanLimits(max_documents=50000, max_training_runs_monthly=5000, max_storage_mb=512000),
}


class EntitlementService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_tenant_plan(self, tenant_id: str, default_tier: PlanTier = PlanTier.STARTER) -> TenantPlan:
        plan = self.db.scalar(select(TenantPlan).where(TenantPlan.tenant_id == tenant_id))
        if plan:
            return plan

        limits = PLAN_LIMITS[default_tier]
        plan = TenantPlan(
            tenant_id=tenant_id,
            plan_tier=default_tier,
            max_documents=limits.max_documents,
            max_training_runs_monthly=limits.max_training_runs_monthly,
            max_storage_mb=limits.max_storage_mb,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def get_tenant_plan(self, tenant_id: str) -> TenantPlan:
        return self.ensure_tenant_plan(tenant_id)

    def set_tenant_plan(self, tenant_id: str, tier: PlanTier) -> TenantPlan:
        plan = self.ensure_tenant_plan(tenant_id)
        limits = PLAN_LIMITS[tier]
        plan.plan_tier = tier
        plan.max_documents = limits.max_documents
        plan.max_training_runs_monthly = limits.max_training_runs_monthly
        plan.max_storage_mb = limits.max_storage_mb
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def assert_document_quota(self, tenant_id: str) -> None:
        plan = self.ensure_tenant_plan(tenant_id)
        doc_count = self.db.scalar(
            select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
        ) or 0
        if doc_count >= plan.max_documents:
            raise ValueError(
                f"Document quota exceeded ({doc_count}/{plan.max_documents}) for plan {plan.plan_tier.value}"
            )

        storage_used_mb = self._tenant_storage_mb(tenant_id)
        if storage_used_mb >= plan.max_storage_mb:
            raise ValueError(
                f"Storage quota exceeded ({storage_used_mb}MB/{plan.max_storage_mb}MB) for plan {plan.plan_tier.value}"
            )

    def assert_training_quota(self, tenant_id: str) -> None:
        plan = self.ensure_tenant_plan(tenant_id)
        now = datetime.now(tz=UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
        runs_this_month = self.db.scalar(
            select(func.count(TrainingRun.id)).where(
                TrainingRun.tenant_id == tenant_id,
                TrainingRun.created_at >= month_start,
            )
        ) or 0
        if runs_this_month >= plan.max_training_runs_monthly:
            raise ValueError(
                (
                    "Monthly training run quota exceeded "
                    f"({runs_this_month}/{plan.max_training_runs_monthly}) for plan {plan.plan_tier.value}"
                )
            )

    def _tenant_storage_mb(self, tenant_id: str) -> int:
        docs = list(
            self.db.scalars(
                select(Document.storage_path).where(Document.tenant_id == tenant_id)
            ).all()
        )
        total_bytes = 0
        for raw_path in docs:
            path = Path(raw_path)
            if path.exists() and path.is_file():
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    continue
        return int(total_bytes / (1024 * 1024))
