"""Audit API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AuditEventItem(BaseModel):
    id: int
    event_type: str
    actor: str | None = None
    created_at: str
    details: dict[str, Any] | None = None


class LoanAuditTrailResponse(BaseModel):
    loan_id: str
    items: list[AuditEventItem]
    page: int
    page_size: int
    total: int
    total_pages: int
