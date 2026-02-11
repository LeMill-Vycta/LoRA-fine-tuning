from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEvent


def log_audit_event(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    details: dict,
    user_id: str | None = None,
    project_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        user_id=user_id,
        project_id=project_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=details,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event

