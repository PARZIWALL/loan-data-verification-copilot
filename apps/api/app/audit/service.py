"""Audit event creation service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def log_audit_event(
    db: Session,
    event_type: str,
    *,
    loan_id: str | None = None,
    actor: str = "system",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Persist a single audit record."""
    event = AuditLog(
        loan_id=loan_id,
        event_type=event_type,
        actor=actor,
        details=details or {},
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(event)
    return event
