"""Loan routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.database import SessionLocal
from app.ingestion.pipeline import import_upload
from app.models.user import User
from app.schemas.loan import LoanDetailResponse, LoanListResponse
from app.services.loan_service import get_loan_detail, list_loans
from app.validators.engine import validate_loan_in_session

router = APIRouter(tags=["loans"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/loans", response_model=LoanListResponse)
def list_loans_route(
    search: str | None = Query(default=None, description="Match loan_id or borrower_id"),
    payment_status: str | None = Query(default=None),
    has_open_exceptions: bool | None = Query(default=None),
    verified: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return a paginated loan portfolio with per-loan review state."""
    del current_user
    return list_loans(
        db,
        search=search,
        payment_status=payment_status,
        has_open_exceptions=has_open_exceptions,
        verified=verified,
        page=page,
        page_size=page_size,
    )


@router.get("/loans/{loan_id}", response_model=LoanDetailResponse)
def get_loan_detail_route(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return the canonical loan and all related validation and source records."""
    del current_user
    detail = get_loan_detail(db, loan_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan not found")
    return detail


@router.post("/upload")
def upload_csv(
    file: UploadFile = File(...),
    source_type: Literal["loan_tape", "servicer_update", "document_manifest"] = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upload a CSV file and persist the raw rows plus canonical loan data where applicable."""
    if current_user.role != "data_operator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only data operators can upload files")
    try:
        result = import_upload(db, file, source_type)
    except ValueError as exc:
        return {"source_type": source_type, "total_rows": 0, "imported_rows": 0, "failed_rows": 1, "failed_details": [{"row_number": 0, "reason": str(exc)}]}
    return result


@router.post("/loans/{loan_id}/revalidate")
def revalidate_loan_route(
    loan_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Manually re-run validation for a loan without editing a field."""
    del current_user
    try:
        results = validate_loan_in_session(db, loan_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    db.commit()
    return {
        "loan_id": loan_id,
        "rules_executed": len(results),
        "passed": sum(1 for r in results if r["status"] == "pass"),
        "failed": sum(1 for r in results if r["status"] == "fail"),
    }
