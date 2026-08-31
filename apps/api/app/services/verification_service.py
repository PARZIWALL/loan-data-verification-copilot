"""Human verification operations."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.service import log_audit_event
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.verified_loan import VerifiedLoan


def compute_verified_record_hash(
    final_data: dict[str, Any] | None,
    source_reference: dict[str, Any] | None,
    validation_result_summary: dict[str, Any] | None,
) -> str:
    """Return the deterministic SHA-256 digest for a verified snapshot.

    Only the persisted verification snapshot components are included.  The
    normalizer deliberately rejects unsupported values instead of coercing
    them through ``str`` so an unreliable integrity fingerprint is never
    persisted.
    """

    def normalize(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Verified record hash input cannot contain non-finite floats")
            return value
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise TypeError("Verified record hash input dictionaries must use string keys")
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        raise TypeError(f"Unsupported verified record hash input type: {type(value).__name__}")

    payload = normalize(
        {
            "final_data": final_data,
            "source_reference": source_reference,
            "validation_result_summary": validation_result_summary,
        }
    )
    canonical_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def _build_final_data_snapshot(loan: Loan) -> dict[str, Any]:
    """Create an immutable snapshot of the canonical loan state."""
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
        "created_at": loan.created_at,
        "updated_at": loan.updated_at,
    }


def _build_source_reference(loan: Loan, db: Session) -> dict[str, Any]:
    """Capture source lineage from the canonical loan and its sources."""
    primary_source = None
    if loan.primary_source_id:
        primary_source = db.get(LoanSource, loan.primary_source_id)

    return {
        "primary_source_id": loan.primary_source_id,
        "primary_source_system": primary_source.source_system if primary_source else None,
        "primary_source_file": primary_source.source_file if primary_source else None,
        "primary_source_row_number": primary_source.source_row_number if primary_source else None,
        "source_records_count": db.query(LoanSource).filter(LoanSource.loan_id == loan.loan_id).count(),
    }


def _build_validation_result_summary(loan: Loan, db: Session) -> dict[str, Any]:
    """Capture current validation state at verification time."""
    from app.models.validation_result import ValidationResult

    all_results = db.query(ValidationResult).filter(ValidationResult.loan_id == loan.loan_id).all()
    passed_results = [r for r in all_results if r.status == "pass"]
    failed_results = [r for r in all_results if r.status == "fail"]

    most_recent = db.query(ValidationResult).filter(ValidationResult.loan_id == loan.loan_id).order_by(ValidationResult.run_at.desc()).first()

    return {
        "total_results": len(all_results),
        "passed": len(passed_results),
        "failed": len(failed_results),
        "most_recent_run_at": most_recent.run_at if most_recent else None,
        "rule_statuses": {r.rule_name: r.status for r in all_results},
    }


def _build_reviewer_decision_summary(loan: Loan, db: Session) -> str | None:
    """Capture reviewer decision state if available."""
    from app.models.review_action import ReviewAction

    approves = (
        db.query(ReviewAction)
        .filter(ReviewAction.loan_id == loan.loan_id, ReviewAction.action_type == "approve")
        .order_by(ReviewAction.created_at.desc())
        .first()
    )
    if approves:
        return "approved"

    rejects = (
        db.query(ReviewAction)
        .filter(ReviewAction.loan_id == loan.loan_id, ReviewAction.action_type == "reject")
        .order_by(ReviewAction.created_at.desc())
        .first()
    )
    if rejects:
        return "rejected"

    corrections = (
        db.query(ReviewAction)
        .filter(ReviewAction.loan_id == loan.loan_id, ReviewAction.action_type == "request_correction")
        .order_by(ReviewAction.created_at.desc())
        .first()
    )
    if corrections:
        return "correction_requested"

    return None


def verify_loan(
    db: Session,
    *,
    loan_id: str,
    verified_by_id: int,
    verified_by_username: str,
) -> dict[str, Any]:
    """Verify a loan by creating an immutable verified_loans snapshot if eligible."""
    loan = db.query(Loan).filter(Loan.loan_id == loan_id).one_or_none()
    if loan is None:
        raise LookupError(f"Loan '{loan_id}' not found.")

    from app.models.validation_result import ValidationResult

    has_been_validated = (
        db.query(ValidationResult).filter(ValidationResult.loan_id == loan_id).first() is not None
    )
    if not has_been_validated:
        return {
            "status": "ineligible",
            "loan_id": loan_id,
            "reason": "Loan has not been validated",
            "blocking_exception_count": 0,
            "blocking_exceptions": [],
        }

    blocking_exceptions = (
        db.query(ExceptionRecord)
        .filter(ExceptionRecord.loan_id == loan_id, ExceptionRecord.status.in_(["open", "in_review", "rejected"]))
        .all()
    )

    if blocking_exceptions:
        return {
            "status": "ineligible",
            "loan_id": loan_id,
            "reason": "Loan has unresolved exceptions",
            "blocking_exception_count": len(blocking_exceptions),
            "blocking_exceptions": [
                {
                    "exception_id": exc.id,
                    "type": exc.type,
                    "severity": exc.severity,
                    "status": exc.status,
                }
                for exc in blocking_exceptions
            ],
        }

    existing_verified = (
        db.query(VerifiedLoan).filter(VerifiedLoan.loan_id == loan_id).order_by(VerifiedLoan.id.desc()).first()
    )
    if existing_verified is not None:
        return {
            "status": "duplicate",
            "loan_id": loan_id,
            "reason": "Loan is already verified",
            "existing_verified_record_id": existing_verified.id,
            "existing_verification_timestamp": existing_verified.verification_timestamp,
        }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    final_data = _build_final_data_snapshot(loan)
    source_reference = _build_source_reference(loan, db)
    validation_result_summary = _build_validation_result_summary(loan, db)
    reviewer_decision = _build_reviewer_decision_summary(loan, db)
    record_hash = compute_verified_record_hash(
        final_data,
        source_reference,
        validation_result_summary,
    )

    verified_record = VerifiedLoan(
        loan_id=loan_id,
        final_data=final_data,
        source_reference=source_reference,
        validation_result_summary=validation_result_summary,
        reviewer_decision=reviewer_decision,
        verified_by=verified_by_username,
        verification_timestamp=now,
        record_hash=record_hash,
        exported=False,
    )
    db.add(verified_record)
    db.flush()

    log_audit_event(
        db,
        "verified_record_created",
        loan_id=loan_id,
        actor="reviewer",
        details={
            "loan_id": loan_id,
            "verified_record_id": verified_record.id,
            "verified_by": verified_by_username,
            "verification_timestamp": now,
            "final_data_snapshot_size_bytes": len(str(final_data)),
        },
    )

    return {
        "status": "verified",
        "verified_record_id": verified_record.id,
        "loan_id": loan_id,
        "verified_by": verified_by_username,
        "verification_timestamp": now,
        "record_hash": record_hash,
        "exported": False,
    }


def serialize_verified_loan(record: VerifiedLoan) -> dict[str, Any]:
    """Return only the stored verified snapshot and its public metadata."""
    return {
        "verified_loan_id": record.id,
        "loan_id": record.loan_id,
        "final_data": record.final_data,
        "source_reference": record.source_reference,
        "validation_result_summary": record.validation_result_summary,
        "reviewer_decision": record.reviewer_decision,
        "verified_by": record.verified_by,
        "verification_timestamp": record.verification_timestamp,
        "record_hash": record.record_hash,
        "exported": record.exported,
        "exported_at": record.exported_at,
    }


def list_verified_loans(db: Session, *, page: int, page_size: int) -> dict[str, Any]:
    query = db.query(VerifiedLoan)
    total = query.count()
    records = (
        query.order_by(VerifiedLoan.verification_timestamp.desc(), VerifiedLoan.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [serialize_verified_loan(record) for record in records],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


def get_verified_loan(db: Session, verified_loan_id: int) -> VerifiedLoan | None:
    return db.get(VerifiedLoan, verified_loan_id)


def export_verified_loan(db: Session, *, verified_loan_id: int, actor: str) -> dict[str, Any]:
    """Generate a JSON-safe export from the stored snapshot, then record it."""
    record = get_verified_loan(db, verified_loan_id)
    if record is None:
        raise LookupError(f"Verified loan '{verified_loan_id}' not found.")

    exported_payload = {
        key: value
        for key, value in serialize_verified_loan(record).items()
        if key not in {"exported", "exported_at"}
    }
    # Validate the downloadable payload before changing export state.
    json.dumps(exported_payload, ensure_ascii=False, allow_nan=False)

    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record.exported = True
    record.exported_at = exported_at
    log_audit_event(
        db,
        "verified_record_exported",
        loan_id=record.loan_id,
        actor=actor,
        details={
            "verified_loan_id": record.id,
            "loan_id": record.loan_id,
            "actor": actor,
            "export_timestamp": exported_at,
        },
    )
    return exported_payload
