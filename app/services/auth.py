from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_password_hash,
    normalize_email,
    password_needs_rehash,
    validate_password,
    verify_password,
)
from app.models import Membership, PlanTier, Role, Tenant, User


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def register_user(self, email: str, password: str) -> User:
        normalized = normalize_email(email)
        existing = self.db.scalar(select(User).where(User.email == normalized))
        if existing:
            raise ValueError("User already exists")

        ok, reason = validate_password(password)
        if not ok:
            raise ValueError(reason or "Invalid password")

        user = User(email=normalized, hashed_password=get_password_hash(password))
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> str:
        normalized = normalize_email(email)
        user = self.db.scalar(select(User).where(User.email == normalized))
        if not user or not verify_password(password, user.hashed_password):
            raise ValueError("Invalid credentials")
        if not user.is_active:
            raise ValueError("User inactive")
        if password_needs_rehash(user.hashed_password):
            user.hashed_password = get_password_hash(password)
            self.db.commit()
        return create_access_token(subject=user.id, expires_delta=timedelta(days=1))

    def get_user_by_id(self, user_id: str) -> User | None:
        return self.db.get(User, user_id)


class TenantService:
    def __init__(self, db: Session):
        self.db = db

    def create_tenant(self, user_id: str, name: str, namespace: str) -> Tenant:
        clean_namespace = namespace.strip().lower().replace(" ", "-")
        if self.db.scalar(select(Tenant).where(Tenant.namespace == clean_namespace)):
            raise ValueError("Tenant namespace already exists")

        tenant = Tenant(name=name.strip(), namespace=clean_namespace)
        self.db.add(tenant)
        self.db.flush()

        membership = Membership(user_id=user_id, tenant_id=tenant.id, role=Role.OWNER)
        self.db.add(membership)
        from app.services.entitlements import EntitlementService

        EntitlementService(self.db).ensure_tenant_plan(tenant.id, default_tier=PlanTier.STARTER)
        self.db.commit()
        self.db.refresh(tenant)
        return tenant

    def list_memberships(self, user_id: str) -> list[Membership]:
        return list(self.db.scalars(select(Membership).where(Membership.user_id == user_id)).all())

    def role_for_user(self, user_id: str, tenant_id: str) -> Role | None:
        membership = self.db.scalar(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
            )
        )
        return membership.role if membership else None

    def require_role(self, user_id: str, tenant_id: str, allowed_roles: set[Role]) -> Role:
        role = self.role_for_user(user_id=user_id, tenant_id=tenant_id)
        if role is None:
            raise PermissionError("User is not a tenant member")
        if role not in allowed_roles:
            raise PermissionError("User lacks role permissions")
        return role
