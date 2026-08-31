"""Loan domain operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.validation_result import ValidationResult
from app.models.verified_loan import VerifiedLoan

OPEN_EXCEPTION_STATUSES = ("open", "in_review")


def list_loans(
    db: Session,
    *,
    search: str | None = None,
    payment_status: str | None = None,
    has_open_exceptions: bool | None = None,
    verified: bool | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Return a paginated loan portfolio view with review state per loan.

    open_exception_count and verified are computed with correlated subqueries rather
    than per-row lookups so the list stays a single query regardless of page size.
    """
    open_exception_count = (
        db.query(func.count(ExceptionRecord.id))
        .filter(
            ExceptionRecord.loan_id == Loan.loan_id,
            ExceptionRecord.status.in_(OPEN_EXCEPTION_STATUSES),
        )
        .correlate(Loan)
        .scalar_subquery()
    )
    verified_count = (
        db.query(func.count(VerifiedLoan.id))
        .filter(VerifiedLoan.loan_id == Loan.loan_id)
        .correlate(Loan)
        .scalar_subquery()
    )

    query = db.query(Loan, open_exception_count.label("open_exception_count"), verified_count.label("verified_count"))

    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(or_(Loan.loan_id.ilike(needle), Loan.borrower_id.ilike(needle)))
    if payment_status:
        query = query.filter(Loan.payment_status == payment_status)
    if has_open_exceptions is True:
        query = query.filter(open_exception_count > 0)
    elif has_open_exceptions is False:
        query = query.filter(open_exception_count == 0)
    if verified is True:
        query = query.filter(verified_count > 0)
    elif verified is False:
        query = query.filter(verified_count == 0)

    total = query.count()
    rows = query.order_by(Loan.loan_id.asc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "loan_id": loan.loan_id,
                "borrower_id": loan.borrower_id,
                "loan_type": loan.loan_type,
                "original_principal": loan.original_principal,
                "current_balance": loan.current_balance,
                "interest_rate": loan.interest_rate,
                "borrower_state": loan.borrower_state,
                "payment_status": loan.payment_status,
                "document_status": loan.document_status,
                "last_updated_at": loan.last_updated_at,
                "open_exception_count": int(open_count or 0),
                "verified": bool(verified_total),
            }
            for loan, open_count, verified_total in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


def get_loan_detail(db: Session, loan_id: str) -> dict[str, Any] | None:
    """Return the canonical loan together with validation, exception, and source context."""
    loan = db.query(Loan).filter(Loan.loan_id == loan_id).one_or_none()
    if loan is None:
        return None

    validation_results = (
        db.query(ValidationResult)
        .filter(ValidationResult.loan_id == loan_id)
        .order_by(desc(ValidationResult.run_at), desc(ValidationResult.id))
        .all()
    )
    exceptions = (
        db.query(ExceptionRecord)
        .filter(ExceptionRecord.loan_id == loan_id)
        .order_by(desc(ExceptionRecord.created_at), desc(ExceptionRecord.id))
        .all()
    )
    source_records = (
        db.query(LoanSource)
        .filter(LoanSource.loan_id == loan_id)
        .order_by(desc(LoanSource.ingested_at), desc(LoanSource.id))
        .all()
    )

    return {
        "loan_id": loan.loan_id,
        "borrower_id": loan.borrower_id,
        "loan_type": loan.loan_type,
        "origination_date": loan.origination_date,
        "maturity_date": loan.maturity_date,
        "original_principal": loan.original_principal,
        "current_balance": loan.current_balance,
        "interest_rate": loan.interest_rate,
        "term_months": loan.term_months,
        "borrower_state": loan.borrower_state,
        "loan_purpose": loan.loan_purpose,
        "credit_grade": loan.credit_grade,
        "employment_length": loan.employment_length,
        "income_band": loan.income_band,
        "payment_status": loan.payment_status,
        "days_past_due": loan.days_past_due,
        "servicer_name": loan.servicer_name,
        "last_payment_date": loan.last_payment_date,
        "last_updated_at": loan.last_updated_at,
        "document_status": loan.document_status,
        "source_system": loan.source_system,
        "primary_source_id": loan.primary_source_id,
        "created_at": loan.created_at,
        "updated_at": loan.updated_at,
        "validation_results": [
            {
                "id": row.id,
                "rule_name": row.rule_name,
                "status": row.status,
                "severity": row.severity,
                "message": row.message,
                "details": row.details,
                "run_at": row.run_at,
            }
            for row in validation_results
        ],
        "exceptions": [
            {
                "id": row.id,
                "type": row.type,
                "severity": row.severity,
                "status": row.status,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in exceptions
        ],
        "source_records": [
            {
                "id": row.id,
                "source_file": row.source_file,
                "source_system": row.source_system,
                "source_row_number": row.source_row_number,
                "raw_data": row.raw_data,
                "imported_at": row.ingested_at,
                "import_status": row.import_status,
            }
            for row in source_records
        ],
    }

