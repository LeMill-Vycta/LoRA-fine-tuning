from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.db import get_session_maker, init_db
from app.models import Membership, PlanTier, Project, Role, Tenant, User
from app.services.auth import AuthService, TenantService
from app.services.entitlements import EntitlementService
from app.services.project import ProjectService


@dataclass(frozen=True)
class PlanAccount:
    plan: PlanTier
    email: str
    role: Role


PLAN_ACCOUNTS: tuple[PlanAccount, ...] = (
    PlanAccount(plan=PlanTier.STARTER, email="starter@lorastudio.local", role=Role.OWNER),
    PlanAccount(plan=PlanTier.STANDARD, email="standard@lorastudio.local", role=Role.OWNER),
    PlanAccount(plan=PlanTier.PRO, email="pro@lorastudio.local", role=Role.OWNER),
    PlanAccount(plan=PlanTier.ENTERPRISE, email="enterprise@lorastudio.local", role=Role.OWNER),
)


def ensure_user(db: Session, auth: AuthService, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user:
        return user
    return auth.register_user(email=email, password=password)


def ensure_membership(db: Session, user: User, tenant: Tenant, role: Role) -> Membership:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant.id,
        )
    )
    if membership:
        if membership.role != role:
            membership.role = role
            db.commit()
            db.refresh(membership)
        return membership

    membership = Membership(user_id=user.id, tenant_id=tenant.id, role=role)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def ensure_tenant_for_plan(db: Session, tenant_service: TenantService, user: User, plan_tier: PlanTier) -> Tenant:
    namespace = f"{plan_tier.value}-tenant"
    tenant = db.scalar(select(Tenant).where(Tenant.namespace == namespace))
    if tenant:
        ensure_membership(db, user, tenant, Role.OWNER)
        return tenant
    return tenant_service.create_tenant(
        user_id=user.id,
        name=f"{plan_tier.value.title()} Tenant",
        namespace=namespace,
    )


def ensure_project(db: Session, project_service: ProjectService, tenant: Tenant, project_name: str) -> Project:
    project = db.scalar(select(Project).where(Project.tenant_id == tenant.id, Project.name == project_name))
    if project:
        return project
    return project_service.create_project(
        tenant_id=tenant.id,
        name=project_name,
        description=f"Seeded project for {tenant.namespace}",
        system_prompt=None,
        style_rules=["Use concise answers."],
        refusal_rules=["Refuse unsupported claims and escalate."],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed plan-tier test accounts for LoRA Studio")
    parser.add_argument("--password", default="TestPass123!", help="Shared password for seeded plan accounts")
    parser.add_argument("--project", default="Demo Project")
    parser.add_argument(
        "--skip-plan-accounts",
        action="store_true",
        help="Skip creating starter/standard/pro/enterprise test accounts",
    )
    args = parser.parse_args()

    init_db()
    session_maker = get_session_maker()

    with session_maker() as db:
        auth = AuthService(db)
        tenant_service = TenantService(db)
        entitlement_service = EntitlementService(db)
        project_service = ProjectService(db)

        seeded_rows: list[dict[str, str]] = []

        if not args.skip_plan_accounts:
            for spec in PLAN_ACCOUNTS:
                user = ensure_user(db, auth, spec.email, args.password)
                tenant = ensure_tenant_for_plan(db, tenant_service, user, spec.plan)
                ensure_membership(db, user, tenant, spec.role)
                plan = entitlement_service.set_tenant_plan(tenant.id, spec.plan)
                project = ensure_project(db, project_service, tenant, args.project)
                seeded_rows.append(
                    {
                        "plan": spec.plan.value,
                        "email": spec.email,
                        "role": spec.role.value,
                        "tenant_id": tenant.id,
                        "tenant_namespace": tenant.namespace,
                        "project_id": project.id,
                        "max_docs": str(plan.max_documents),
                        "max_runs_monthly": str(plan.max_training_runs_monthly),
                    }
                )

        print("Seed summary")
        print("------------")
        if seeded_rows:
            print("Plan accounts (all use same password):")
            for row in seeded_rows:
                print(
                    "- "
                    f"plan={row['plan']:10s} "
                    f"email={row['email']:30s} "
                    f"role={row['role']:8s} "
                    f"tenant={row['tenant_namespace']}({row['tenant_id']}) "
                    f"project={row['project_id']} "
                    f"quota_docs={row['max_docs']} "
                    f"quota_runs_monthly={row['max_runs_monthly']}"
                )
            print(f"Password: {args.password}")
        else:
            print("No accounts created (skip mode).")


if __name__ == "__main__":
    main()
