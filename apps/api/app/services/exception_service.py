"""Exception workflow operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from app.audit.service import log_audit_event
from app.models.ai_recommendation import AIRecommendation
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.validation_result import ValidationResult

ALLOWED_EDITABLE_FIELDS = {
    "borrower_id",
    "loan_type",
    "origination_date",
    "maturity_date",
    "original_principal",
    "current_balance",
    "interest_rate",
    "term_months",
    "borrower_state",
    "loan_purpose",
    "credit_grade",
    "employment_length",
    "income_band",
    "payment_status",
    "days_past_due",
    "servicer_name",
    "last_payment_date",
    "last_updated_at",
    "document_status",
}
INT_FIELDS = {"term_months", "days_past_due"}
FLOAT_FIELDS = {"original_principal", "current_balance", "interest_rate"}
DATE_FIELDS = {"origination_date", "maturity_date", "last_payment_date", "last_updated_at"}


def _normalize_edit_value(field_name: str, raw_value: Any) -> Any:
    if raw_value is None:
        return None

    if field_name in INT_FIELDS:
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Field '{field_name}' requires an integer value.") from exc

    if field_name in FLOAT_FIELDS:
        try:
            return float(str(raw_value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Field '{field_name}' requires a numeric value.") from exc

    if field_name in DATE_FIELDS:
        text = str(raw_value).strip()
        if not text:
            raise ValueError(f"Field '{field_name}' requires a valid date value.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d")
                return parsed.date().isoformat()
            except ValueError as exc:
                raise ValueError(f"Field '{field_name}' requires a valid date in YYYY-MM-DD format.") from exc

    if isinstance(raw_value, str):
        trimmed = raw_value.strip()
        if not trimmed:
            return ""
        return trimmed
    return raw_value


def edit_exception_field(
    db: Session,
    *,
    exception_id: int,
    loan_id: str,
    reviewer_id: int,
    field_name: str,
    raw_value: Any,
    ai_recommendation_id: int | None = None,
) -> dict[str, Any]:
    """Edit an allowlisted canonical loan field and trigger revalidation.

    ai_recommendation_id attributes the edit to the AI recommendation that prompted it
    (7C). It defaults to None, which is the ordinary reviewer-initiated edit.
    """
    cleaned_field = field_name.strip()
    if cleaned_field not in ALLOWED_EDITABLE_FIELDS:
        raise ValueError(f"Field '{cleaned_field}' is not allowed to be edited.")

    loan = db.query(Loan).filter(Loan.loan_id == loan_id).one_or_none()
    if loan is None:
        raise LookupError(f"Loan '{loan_id}' not found.")

    current_value = getattr(loan, cleaned_field)
    normalized_value = _normalize_edit_value(cleaned_field, raw_value)

    if current_value == normalized_value:
        return {
            "status": "no_change",
            "message": f"No change was made for field '{cleaned_field}'.",
            "exception_id": exception_id,
            "loan_id": loan_id,
            "reviewer_id": reviewer_id,
            "field_name": cleaned_field,
            "old_value": current_value,
            "new_value": normalized_value,
            "created_at": None,
            "action_id": None,
        }

    old_value = current_value
    setattr(loan, cleaned_field, normalized_value)
    loan.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    action = ReviewAction(
        exception_id=exception_id,
        loan_id=loan_id,
        reviewer_id=reviewer_id,
        action_type="edit_field",
        field_name=cleaned_field,
        old_value=old_value,
        new_value=normalized_value,
        ai_recommendation_id=ai_recommendation_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(action)
    db.flush()

    log_audit_event(
        db,
        "field_edited",
        loan_id=loan_id,
        actor="reviewer",
        details={
            "loan_id": loan_id,
            "exception_id": exception_id,
            "reviewer_id": reviewer_id,
            "review_action_id": action.id,
            "field_name": cleaned_field,
            "old_value": old_value,
            "new_value": normalized_value,
            "ai_recommendation_id": ai_recommendation_id,
            "timestamp": action.created_at,
        },
    )

    from app.validators.engine import validate_loan_in_session

    validate_loan_in_session(db, loan_id)

    return {
        "status": "updated",
        "message": f"Field '{cleaned_field}' was updated.",
        "exception_id": exception_id,
        "loan_id": loan_id,
        "reviewer_id": reviewer_id,
        "field_name": cleaned_field,
        "old_value": old_value,
        "new_value": normalized_value,
        "created_at": action.created_at,
        "action_id": action.id,
    }

SEVERITY_PRIORITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def create_or_reuse_exception_for_validation_result(db: Session, result: dict[str, Any]) -> ExceptionRecord | None:
    """Create a single open exception for a failed result, or reuse an existing one.

    An exception is reused (never duplicated) when it is still `open`/`in_review`, or
    when it was already closed by an explicit human decision (`approve`/`reject`) --
    otherwise a still-failing rule would silently spawn a fresh duplicate exception
    every time an unrelated field edit or upload triggers a full revalidation,
    contradicting the reviewer's already-recorded decision. An exception that closed
    via automatic pass-based resolution is NOT reused: a later failure of that same
    rule is treated as a new occurrence, matching the existing revalidation behavior.
    """
    if result.get("status") != "fail":
        return None

    loan_id = result.get("loan_id")
    rule_name = result.get("rule_name")
    if not loan_id or not rule_name:
        return None

    existing = (
        db.query(ExceptionRecord)
        .filter(
            ExceptionRecord.loan_id == loan_id,
            ExceptionRecord.type == rule_name,
            ExceptionRecord.status.in_(("open", "in_review")),
        )
        .order_by(ExceptionRecord.id.desc())
        .first()
    )
    if existing is not None:
        return existing

    most_recent = (
        db.query(ExceptionRecord)
        .filter(
            ExceptionRecord.loan_id == loan_id,
            ExceptionRecord.type == rule_name,
        )
        .order_by(ExceptionRecord.id.desc())
        .first()
    )
    if most_recent is not None and most_recent.status in ("resolved", "rejected"):
        has_human_decision = (
            db.query(ReviewAction)
            .filter(
                ReviewAction.exception_id == most_recent.id,
                ReviewAction.action_type.in_(("approve", "reject")),
            )
            .first()
            is not None
        )
        if has_human_decision:
            return most_recent

    validation_result_id = result.get("validation_result_id")
    if validation_result_id is None:
        raise ValueError(f"Validation result for {rule_name} is missing a persisted id.")

    exception = ExceptionRecord(
        loan_id=loan_id,
        validation_result_id=validation_result_id,
        type=rule_name,
        severity=result.get("severity") or "medium",
        status="open",
        created_at=result.get("run_at") or "now",
    )
    db.add(exception)
    db.flush()

    log_audit_event(
        db,
        "exception_created",
        loan_id=loan_id,
        details={
            "loan_id": loan_id,
            "exception_id": exception.id,
            "validation_result_id": validation_result_id,
            "rule": rule_name,
            "severity": exception.severity,
        },
    )
    return exception


def resolve_open_exceptions_for_pass_result(db: Session, loan_id: str, rule_name: str, run_at: str) -> ExceptionRecord | None:
    """Resolve any open exception for a rule when the current validation result passes."""
    existing = (
        db.query(ExceptionRecord)
        .filter(
            ExceptionRecord.loan_id == loan_id,
            ExceptionRecord.type == rule_name,
            ExceptionRecord.status == "open",
        )
        .first()
    )
    if existing is None:
        return None

    existing.status = "resolved"
    existing.resolved_at = run_at
    db.flush()

    log_audit_event(
        db,
        "exception_resolved",
        loan_id=loan_id,
        details={
            "loan_id": loan_id,
            "exception_id": existing.id,
            "rule": rule_name,
            "severity": existing.severity,
            "resolved_at": run_at,
        },
    )
    return existing


def list_exceptions(
    db: Session,
    *,
    type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return reviewer queue items with basic exception data."""
    query = db.query(ExceptionRecord).outerjoin(Loan, Loan.loan_id == ExceptionRecord.loan_id)

    if type:
        query = query.filter(ExceptionRecord.type == type)
    if severity:
        query = query.filter(ExceptionRecord.severity == severity)
    if status:
        query = query.filter(ExceptionRecord.status == status)
    if search:
        needle = f"%{search.strip()}%"
        query = query.filter(or_(ExceptionRecord.loan_id.ilike(needle), Loan.borrower_id.ilike(needle)))

    total = query.distinct().count()
    query = query.order_by(
        case((ExceptionRecord.severity == "critical", 0), (ExceptionRecord.severity == "high", 1), (ExceptionRecord.severity == "medium", 2), (ExceptionRecord.severity == "low", 3), else_=4),
        ExceptionRecord.created_at.desc(),
        ExceptionRecord.id.desc(),
    )

    items = query.offset((page - 1) * page_size).limit(page_size).all()
    payload = []
    for exc in items:
        validation_result = exc.validation_result
        payload.append(
            {
                "exception_id": exc.id,
                "loan_id": exc.loan_id,
                "borrower_id": exc.loan.borrower_id if exc.loan else None,
                "type": exc.type,
                "severity": exc.severity,
                "status": exc.status,
                "validation_result_id": exc.validation_result_id,
                "message": validation_result.message if validation_result else None,
                "created_at": exc.created_at,
                "resolved_at": exc.resolved_at,
            }
        )
    total_pages = (total + page_size - 1) // page_size if total else 0
    return payload, total, total_pages


def create_exception_comment(db: Session, *, exception_id: int, loan_id: str, reviewer_id: int, comment_text: str) -> dict[str, Any]:
    """Persist a single reviewer comment action and matching audit event."""
    comment = comment_text.strip()
    if not comment:
        raise ValueError("Comment text cannot be empty.")
    if len(comment) > 2000:
        raise ValueError("Comment text exceeds the maximum supported length.")

    action = ReviewAction(
        exception_id=exception_id,
        loan_id=loan_id,
        reviewer_id=reviewer_id,
        action_type="comment",
        comment_text=comment,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(action)
    db.flush()

    log_audit_event(
        db,
        "reviewer_comment_added",
        loan_id=loan_id,
        actor="reviewer",
        details={
            "loan_id": loan_id,
            "exception_id": exception_id,
            "reviewer_id": reviewer_id,
            "review_action_id": action.id,
        },
    )
    db.flush()
    return {
        "action_id": action.id,
        "exception_id": action.exception_id,
        "loan_id": action.loan_id,
        "reviewer_id": action.reviewer_id,
        "action_type": action.action_type,
        "comment_text": action.comment_text,
        "created_at": action.created_at,
    }


def serialize_ai_recommendation(record: AIRecommendation) -> dict[str, Any]:
    """Present one AI recommendation to a reviewer.

    Deliberately omits the evidence_snapshot held alongside the recommendation in the
    suggested_correction JSON column: it is the entire 7A.1 evidence packet, kept for
    audit and reproducibility, and would dominate every exception-detail response.
    """
    stored = record.suggested_correction or {}
    recommendation = stored.get("recommendation") or {}
    return {
        "ai_recommendation_id": record.id,
        "exception_id": record.exception_id,
        "loan_id": record.loan_id,
        "recommendation_type": recommendation.get("recommendation_type"),
        "summary": recommendation.get("summary"),
        "explanation": record.explanation,
        "confidence": record.confidence,
        "affected_fields": recommendation.get("affected_fields", []),
        "suggested_corrections": recommendation.get("suggested_corrections", []),
        "evidence_citations": recommendation.get("evidence_citations", []),
        "limitations": recommendation.get("limitations", []),
        "severity_classification": record.severity_classification,
        "model_name": record.model_name,
        "prompt_version": record.prompt_version,
        "downgraded": stored.get("downgraded", False),
        "downgrade_reasons": stored.get("downgrade_reasons", []),
        "reviewer_status": record.reviewer_status,
        "created_at": record.created_at,
    }


def get_exception_detail(db: Session, exception_id: int) -> dict[str, Any] | None:
    """Return full reviewer detail for one exception."""
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).one_or_none()
    if exc is None:
        return None

    loan = db.query(Loan).filter(Loan.loan_id == exc.loan_id).one_or_none()
    validation_result = exc.validation_result
    source_records = (
        db.query(LoanSource)
        .filter(LoanSource.loan_id == exc.loan_id)
        .order_by(LoanSource.id.desc())
        .all()
    )
    historical_results = (
        db.query(ValidationResult)
        .filter(ValidationResult.loan_id == exc.loan_id, ValidationResult.rule_name == exc.type)
        .order_by(ValidationResult.run_at.desc(), ValidationResult.id.desc())
        .all()
    )
    audit_events = (
        db.query(AuditLog)
        .filter(AuditLog.loan_id == exc.loan_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .all()
    )
    review_actions = (
        db.query(ReviewAction)
        .filter(ReviewAction.exception_id == exc.id)
        .order_by(ReviewAction.created_at.asc(), ReviewAction.id.asc())
        .all()
    )
    ai_recommendations = (
        db.query(AIRecommendation)
        .filter(AIRecommendation.exception_id == exc.id)
        .order_by(AIRecommendation.id.asc())
        .all()
    )

    return {
        "exception": {
            "id": exc.id,
            "loan_id": exc.loan_id,
            "type": exc.type,
            "severity": exc.severity,
            "status": exc.status,
            "created_at": exc.created_at,
            "resolved_at": exc.resolved_at,
        },
        "validation_result": {
            "rule_name": validation_result.rule_name if validation_result else exc.type,
            "status": validation_result.status if validation_result else None,
            "severity": validation_result.severity if validation_result else exc.severity,
            "message": validation_result.message if validation_result else None,
            "details": validation_result.details if validation_result else None,
            "run_at": validation_result.run_at if validation_result else None,
        },
        "canonical_loan": {
            "loan_id": loan.loan_id if loan else None,
            "borrower_id": loan.borrower_id if loan else None,
            "loan_type": loan.loan_type if loan else None,
            "origination_date": loan.origination_date if loan else None,
            "maturity_date": loan.maturity_date if loan else None,
            "original_principal": loan.original_principal if loan else None,
            "current_balance": loan.current_balance if loan else None,
            "interest_rate": loan.interest_rate if loan else None,
            "term_months": loan.term_months if loan else None,
            "borrower_state": loan.borrower_state if loan else None,
            "loan_purpose": loan.loan_purpose if loan else None,
            "credit_grade": loan.credit_grade if loan else None,
            "employment_length": loan.employment_length if loan else None,
            "income_band": loan.income_band if loan else None,
            "payment_status": loan.payment_status if loan else None,
            "days_past_due": loan.days_past_due if loan else None,
            "servicer_name": loan.servicer_name if loan else None,
            "last_payment_date": loan.last_payment_date if loan else None,
            "last_updated_at": loan.last_updated_at if loan else None,
            "document_status": loan.document_status if loan else None,
            "source_system": loan.source_system if loan else None,
            "primary_source_id": loan.primary_source_id if loan else None,
            "created_at": loan.created_at if loan else None,
            "updated_at": loan.updated_at if loan else None,
        },
        "source_evidence": [
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
        "historical_validation_results": [
            {
                "id": row.id,
                "rule_name": row.rule_name,
                "status": row.status,
                "severity": row.severity,
                "message": row.message,
                "details": row.details,
                "run_at": row.run_at,
            }
            for row in historical_results
        ],
        "audit_events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "created_at": event.created_at,
                "details": event.details,
            }
            for event in audit_events
        ],
        "review_actions": [
            {
                "action_id": action.id,
                "action_type": action.action_type,
                "reviewer_id": action.reviewer_id,
                "field_name": action.field_name,
                "old_value": action.old_value,
                "new_value": action.new_value,
                "comment_text": action.comment_text,
                "ai_recommendation_id": action.ai_recommendation_id,
                "created_at": action.created_at,
            }
            for action in review_actions
        ],
        "ai_recommendations": [serialize_ai_recommendation(record) for record in ai_recommendations],
    }


def approve_exception(
    db: Session,
    *,
    exception_id: int,
    reviewer_id: int,
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Approve an exception as acceptable/resolved by the reviewer."""
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).one_or_none()
    if exc is None:
        raise LookupError(f"Exception {exception_id} not found.")

    if exc.status in ("resolved", "rejected"):
        raise ValueError(f"Cannot approve exception in terminal state '{exc.status}'.")

    cleaned_comment = None
    if comment_text:
        cleaned_comment = comment_text.strip() if isinstance(comment_text, str) else str(comment_text).strip()
        if not cleaned_comment:
            cleaned_comment = None
        elif len(cleaned_comment) > 2000:
            raise ValueError("Comment text exceeds the maximum supported length.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = ReviewAction(
        exception_id=exception_id,
        loan_id=exc.loan_id,
        reviewer_id=reviewer_id,
        action_type="approve",
        comment_text=cleaned_comment,
        created_at=now,
    )
    db.add(action)
    db.flush()

    exc.status = "resolved"
    exc.resolved_at = now

    log_audit_event(
        db,
        "loan_approved",
        loan_id=exc.loan_id,
        actor="reviewer",
        details={
            "loan_id": exc.loan_id,
            "exception_id": exception_id,
            "reviewer_id": reviewer_id,
            "review_action_id": action.id,
            "status": exc.status,
            "resolved_at": now,
        },
    )

    return {
        "action_id": action.id,
        "exception_id": exception_id,
        "loan_id": exc.loan_id,
        "reviewer_id": reviewer_id,
        "action_type": "approve",
        "comment_text": cleaned_comment,
        "created_at": now,
        "exception_status": exc.status,
    }


def reject_exception(
    db: Session,
    *,
    exception_id: int,
    reviewer_id: int,
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Reject an exception as not acceptable by the reviewer."""
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).one_or_none()
    if exc is None:
        raise LookupError(f"Exception {exception_id} not found.")

    if exc.status in ("resolved", "rejected"):
        raise ValueError(f"Cannot reject exception in terminal state '{exc.status}'.")

    cleaned_comment = None
    if comment_text:
        cleaned_comment = comment_text.strip() if isinstance(comment_text, str) else str(comment_text).strip()
        if not cleaned_comment:
            cleaned_comment = None
        elif len(cleaned_comment) > 2000:
            raise ValueError("Comment text exceeds the maximum supported length.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = ReviewAction(
        exception_id=exception_id,
        loan_id=exc.loan_id,
        reviewer_id=reviewer_id,
        action_type="reject",
        comment_text=cleaned_comment,
        created_at=now,
    )
    db.add(action)
    db.flush()

    exc.status = "rejected"
    exc.resolved_at = now

    log_audit_event(
        db,
        "loan_rejected",
        loan_id=exc.loan_id,
        actor="reviewer",
        details={
            "loan_id": exc.loan_id,
            "exception_id": exception_id,
            "reviewer_id": reviewer_id,
            "review_action_id": action.id,
            "status": exc.status,
            "resolved_at": now,
        },
    )

    return {
        "action_id": action.id,
        "exception_id": exception_id,
        "loan_id": exc.loan_id,
        "reviewer_id": reviewer_id,
        "action_type": "reject",
        "comment_text": cleaned_comment,
        "created_at": now,
        "exception_status": exc.status,
    }


def request_correction_exception(
    db: Session,
    *,
    exception_id: int,
    reviewer_id: int,
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Request correction on an exception's data."""
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.id == exception_id).one_or_none()
    if exc is None:
        raise LookupError(f"Exception {exception_id} not found.")

    if exc.status in ("resolved", "rejected"):
        raise ValueError(f"Cannot request correction on exception in terminal state '{exc.status}'.")

    cleaned_comment = None
    if comment_text:
        cleaned_comment = comment_text.strip() if isinstance(comment_text, str) else str(comment_text).strip()
        if not cleaned_comment:
            cleaned_comment = None
        elif len(cleaned_comment) > 2000:
            raise ValueError("Comment text exceeds the maximum supported length.")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action = ReviewAction(
        exception_id=exception_id,
        loan_id=exc.loan_id,
        reviewer_id=reviewer_id,
        action_type="request_correction",
        comment_text=cleaned_comment,
        created_at=now,
    )
    db.add(action)
    db.flush()

    previous_status = exc.status
    exc.status = "in_review"

    log_audit_event(
        db,
        "correction_requested",
        loan_id=exc.loan_id,
        actor="reviewer",
        details={
            "loan_id": exc.loan_id,
            "exception_id": exception_id,
            "reviewer_id": reviewer_id,
            "review_action_id": action.id,
            "previous_status": previous_status,
            "status": exc.status,
            "reason": cleaned_comment,
        },
    )

    return {
        "action_id": action.id,
        "exception_id": exception_id,
        "loan_id": exc.loan_id,
        "reviewer_id": reviewer_id,
        "action_type": "request_correction",
        "comment_text": cleaned_comment,
        "created_at": now,
        "exception_status": exc.status,
    }

