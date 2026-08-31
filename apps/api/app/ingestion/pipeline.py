"""Ingestion pipeline orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.service import log_audit_event
from app.ingestion.csv_reader import parse_csv_rows
from app.ingestion.normalizer import normalize_loan_row
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.validators.engine import validate_loan_in_session

SUPPORTED_SOURCE_TYPES = {"loan_tape", "servicer_update", "document_manifest"}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def import_upload(db: Session, file_obj: Any, source_type: str) -> dict[str, Any]:
    """Process an uploaded CSV file into raw source rows and canonical loans where applicable."""
    source_type = source_type.strip()
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type: {source_type}")

    rows = parse_csv_rows(file_obj)
    total_rows = len(rows)
    imported_rows = 0
    failed_details: list[dict[str, Any]] = []
    loan_ids_to_validate: set[str] = set()

    for row in rows:
        row_number = row["row_number"]
        row_data = row["data"]
        raw_source = LoanSource(
            loan_id=(row_data.get("loan_id") or "").strip() or None,
            source_file=file_obj.filename,
            source_system=source_type,
            source_row_number=row_number,
            raw_data=row_data,
            ingested_at=_utc_timestamp(),
            import_status="success",
            failure_reason=None,
        )
        db.add(raw_source)
        db.flush()

        try:
            if source_type == "loan_tape":
                normalized = normalize_loan_row(row_data)
                existing_loan = db.query(Loan).filter(Loan.loan_id == normalized["loan_id"]).one_or_none()
                if existing_loan is None:
                    loan = Loan(**normalized, primary_source_id=raw_source.id)
                    db.add(loan)
                    db.flush()
                    loan_id = loan.loan_id
                else:
                    for key, value in normalized.items():
                        setattr(existing_loan, key, value)
                    existing_loan.primary_source_id = raw_source.id
                    db.flush()
                    loan_id = existing_loan.loan_id

                imported_rows += 1
                loan_ids_to_validate.add(loan_id)
                log_audit_event(db, "loan_imported", loan_id=loan_id, details={
                    "source_type": source_type,
                    "source_file": file_obj.filename,
                    "row_number": row_number,
                })
            else:
                imported_rows += 1
                if raw_source.loan_id and db.query(Loan).filter(Loan.loan_id == raw_source.loan_id).one_or_none() is not None:
                    # Secondary evidence (servicer_update/document_manifest) for a loan that
                    # already exists as a canonical record: revalidate so rules that depend on
                    # this evidence (source_conflict, missing_document_status) fire immediately
                    # instead of waiting for an unrelated future edit or manual revalidate call.
                    loan_ids_to_validate.add(raw_source.loan_id)
        except Exception as exc:  # row-level import failure
            raw_source.import_status = "failed"
            raw_source.failure_reason = str(exc)
            failed_details.append({"row_number": row_number, "reason": str(exc)})
            db.flush()

    log_audit_event(db, "file_uploaded", details={
        "source_type": source_type,
        "source_file": file_obj.filename,
        "total_rows": total_rows,
        "imported_rows": imported_rows,
        "failed_rows": len(failed_details),
    })

    # SessionLocal is configured with autoflush=False, so flush explicitly before
    # validation queries run -- every LoanSource/Loan row touched above must be visible
    # to the rules, not just the ones already flushed inline per-row by coincidence.
    db.flush()
    for loan_id in sorted(loan_ids_to_validate):
        validate_loan_in_session(db, loan_id)

    db.commit()
    return {
        "source_type": source_type,
        "total_rows": total_rows,
        "imported_rows": imported_rows,
        "failed_rows": len(failed_details),
        "failed_details": failed_details,
    }
