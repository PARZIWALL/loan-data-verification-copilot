"""Dashboard aggregates.

One read-only query set powering all three role dashboards. Every number here is
derived from persisted state -- nothing is estimated or cached -- so the dashboard can
never disagree with the exception queue or the verified-records list.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.ai_recommendation import AIRecommendation
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.validation_result import ValidationResult
from app.models.verified_loan import VerifiedLoan

OPEN_EXCEPTION_STATUSES = ("open", "in_review")
SEVERITIES = ("critical", "high", "medium", "low")
EXCEPTION_STATUSES = ("open", "in_review", "resolved", "rejected")
AI_REVIEWER_STATUSES = ("pending", "accepted", "edited", "rejected")


def _counts_by(db: Session, column, model, keys: tuple[str, ...]) -> dict[str, int]:
    """Group-count a column, guaranteeing every expected key is present as 0."""
    rows = db.query(column, func.count()).group_by(column).all()
    counts = {key: 0 for key in keys}
    for value, count in rows:
        counts[value] = counts.get(value, 0) + count
    return counts


def build_summary(db: Session) -> dict[str, Any]:
    """Return the dashboard summary for the whole portfolio."""
    total_loans = db.query(func.count(Loan.loan_id)).scalar() or 0

    loans_with_open_exceptions = (
        db.query(func.count(func.distinct(ExceptionRecord.loan_id)))
        .filter(ExceptionRecord.status.in_(OPEN_EXCEPTION_STATUSES))
        .scalar()
        or 0
    )
    verified_loan_ids = db.query(func.count(func.distinct(VerifiedLoan.loan_id))).scalar() or 0

    exception_status_counts = _counts_by(db, ExceptionRecord.status, ExceptionRecord, EXCEPTION_STATUSES)
    exception_severity_counts = _counts_by(db, ExceptionRecord.severity, ExceptionRecord, SEVERITIES)
    total_exceptions = sum(exception_status_counts.values())

    by_type = [
        {"type": rule_type, "count": count}
        for rule_type, count in db.query(ExceptionRecord.type, func.count())
        .group_by(ExceptionRecord.type)
        .order_by(func.count().desc(), ExceptionRecord.type.asc())
        .all()
    ]

    validation_status_counts = _counts_by(db, ValidationResult.status, ValidationResult, ("pass", "fail"))
    total_validations = sum(validation_status_counts.values())
    latest_run_at = db.query(func.max(ValidationResult.run_at)).scalar()

    ingestion_total = db.query(func.count(LoanSource.id)).scalar() or 0
    ingestion_failed = (
        db.query(func.count(LoanSource.id)).filter(LoanSource.import_status == "failed").scalar() or 0
    )
    distinct_files = db.query(func.count(func.distinct(LoanSource.source_file))).scalar() or 0

    ai_status_counts = _counts_by(db, AIRecommendation.reviewer_status, AIRecommendation, AI_REVIEWER_STATUSES)
    total_recommendations = sum(ai_status_counts.values())

    exported_records = db.query(func.count(VerifiedLoan.id)).filter(VerifiedLoan.exported.is_(True)).scalar() or 0
    total_verified_records = db.query(func.count(VerifiedLoan.id)).scalar() or 0

    return {
        "loans": {
            "total": total_loans,
            "verified": verified_loan_ids,
            "with_open_exceptions": loans_with_open_exceptions,
            "clean": max(total_loans - loans_with_open_exceptions, 0),
        },
        "exceptions": {
            "total": total_exceptions,
            **exception_status_counts,
            "by_severity": exception_severity_counts,
            "by_type": by_type,
        },
        "validation": {
            "total_results": total_validations,
            "passed": validation_status_counts["pass"],
            "failed": validation_status_counts["fail"],
            "latest_run_at": latest_run_at,
        },
        "ingestion": {
            "files": distinct_files,
            "source_rows": ingestion_total,
            "rows_imported": max(ingestion_total - ingestion_failed, 0),
            "rows_failed": ingestion_failed,
        },
        "ai": {
            "recommendations": total_recommendations,
            **ai_status_counts,
        },
        "verification": {
            "verified_records": total_verified_records,
            "exported": exported_records,
        },
        "audit": {"events": db.query(func.count(AuditLog.id)).scalar() or 0},
        "data_quality_score": _data_quality_score(total_loans, loans_with_open_exceptions),
    }


def _data_quality_score(total_loans: int, loans_with_open_exceptions: int) -> float:
    """Share of loans currently carrying no unresolved exception.

    Deliberately loan-level rather than rule-level: a portfolio where one loan fails
    five rules is in better shape than one where five loans each fail once, and the
    loan is the unit a data consumer actually cares about trusting.
    """
    if total_loans == 0:
        return 0.0
    clean = max(total_loans - loans_with_open_exceptions, 0)
    return round(clean / total_loans, 4)


def get_loan_audit_trail(db: Session, loan_id: str, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """Return the paginated audit trail for one loan, oldest first."""
    query = db.query(AuditLog).filter(AuditLog.loan_id == loan_id)
    total = query.count()
    events = (
        query.order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "loan_id": loan_id,
        "items": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "created_at": event.created_at,
                "details": event.details,
            }
            for event in events
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }
