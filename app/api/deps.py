from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import get_db_session
from app.core.security import decode_access_token
from app.models import Role, User
from app.services.auth import AuthService, TenantService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_db() -> Session:
    yield from get_db_session()


def current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = AuthService(db).get_user_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not active")
    return user


def current_tenant_id(
    tenant_id: str = Header(alias="X-Tenant-Id"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> str:
    role = TenantService(db).role_for_user(user_id=user.id, tenant_id=tenant_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing tenant membership")
    return tenant_id


def require_role(*roles: Role):
    allowed = set(roles)

    def _checker(
        tenant_id: str = Depends(current_tenant_id),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> str:
        role = TenantService(db).role_for_user(user.id, tenant_id)
        if role is None or role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role not permitted")
        return tenant_id

    return _checker


def require_api_key(
    api_key: str | None = Depends(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.api_key and api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def require_operator_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.operator_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator mode disabled",
        )
    token = request.headers.get(settings.operator_header_name)
    if token != settings.operator_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


def require_operator_token_if_configured(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.operator_token:
        return
    token = request.headers.get(settings.operator_header_name)
    if token != settings.operator_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")
