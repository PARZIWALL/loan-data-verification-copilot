"""Audit trail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_db
from app.models.loan import Loan
from app.models.user import User
from app.schemas.audit import LoanAuditTrailResponse
from app.services.summary_service import get_loan_audit_trail

router = APIRouter(tags=["audit"])


@router.get("/audit/{loan_id}", response_model=LoanAuditTrailResponse)
def get_loan_audit_trail_route(
    loan_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the full audit trail for one loan, oldest event first.

    Read-only: the audit log is append-only and has no mutation surface.
    """
    del current_user
    if db.get(Loan, loan_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")
    return get_loan_audit_trail(db, loan_id, page=page, page_size=page_size)
