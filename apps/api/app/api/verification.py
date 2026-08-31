"""Human verification routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_db
from app.models.user import User
from app.schemas.verification import (
    DuplicateVerificationResponse,
    IneligibleVerificationResponse,
    VerificationRequest,
    VerifiedRecordResponse,
)
from app.services.verification_service import (
    export_verified_loan,
    get_verified_loan,
    list_verified_loans,
    serialize_verified_loan,
    verify_loan,
)

router = APIRouter(tags=["verification"])


@router.post("/verified-loans", response_model=VerifiedRecordResponse | IneligibleVerificationResponse | DuplicateVerificationResponse)
def verify_loan_route(
    payload: VerificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Verify a loan by creating an immutable snapshot if eligible."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can verify loans")

    try:
        result = verify_loan(
            db,
            loan_id=payload.loan_id,
            verified_by_id=current_user.id,
            verified_by_username=current_user.username,
        )
    except LookupError as exc_lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup

    if result["status"] == "duplicate":
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result)

    if result["status"] == "ineligible":
        db.rollback()
        return result

    db.commit()
    return result


@router.get("/verified-loans")
def list_verified_loans_route(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, gt=0, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return list_verified_loans(db, page=page, page_size=page_size)


@router.get("/verified-loans/{verified_loan_id}")
def get_verified_loan_route(
    verified_loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    record = get_verified_loan(db, verified_loan_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verified loan not found")
    return serialize_verified_loan(record)


@router.post("/verified-loans/{verified_loan_id}/export")
def export_verified_loan_route(
    verified_loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    if current_user.role not in {"data_consumer", "reviewer"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to export verified loans")
    try:
        payload = export_verified_loan(db, verified_loan_id=verified_loan_id, actor=current_user.username)
        db.commit()
    except LookupError as exc_lookup:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup
    except (TypeError, ValueError) as exc_export:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Verified record export failed") from exc_export
    return JSONResponse(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="verified-loan-{verified_loan_id}.json"'},
    )
