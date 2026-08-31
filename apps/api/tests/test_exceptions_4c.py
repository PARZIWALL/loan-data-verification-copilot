from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import close_all_sessions

from app.core.database import Base, SessionLocal, engine
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.validation_result import ValidationResult
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


VALID_LOAN = {
    "loan_id": "L-4C-001",
    "borrower_id": "B-4C-001",
    "origination_date": "2024-01-15",
    "maturity_date": "2034-01-15",
    "original_principal": 250000.0,
    "current_balance": 240000.0,
    "interest_rate": 0.05,
    "term_months": 360,
    "borrower_state": "CA",
    "payment_status": "current",
    "days_past_due": 0,
    "last_payment_date": "2024-02-01",
    "last_updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "document_status": "complete",
}


@pytest.fixture(scope="session", autouse=True)
def ensure_validation_schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def reset_validation_state():
    clear_rules()
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal.configure(bind=connection)
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        close_all_sessions()
        transaction.rollback()
        SessionLocal.configure(bind=engine)
        connection.close()


def _seed_loan(**overrides):
    loan_data = {**VALID_LOAN, **overrides}
    with SessionLocal() as db:
        loan = Loan(**loan_data)
        db.add(loan)
        db.commit()
        return loan.loan_id


def _seed_loan_with_fresh_timestamp(**overrides):
    return _seed_loan(last_updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **overrides)


def _set_loan_field(loan_id: str, **kwargs):
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        for key, value in kwargs.items():
            setattr(loan, key, value)
        db.commit()


def test_failed_validation_creates_exactly_one_open_exception():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5)

    results = validate_loan(loan_id)
    failed = [result for result in results if result["status"] == "fail"]

    assert any(result["rule_name"] == "interest_rate_range" for result in failed)
    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id).all()
        assert len(exceptions) == 1
        exception = exceptions[0]
        assert exception.validation_result_id is not None
        assert exception.type == "interest_rate_range"
        assert exception.severity == "high"
        assert exception.status == "open"
        assert exception.loan_id == loan_id


def test_pass_validation_creates_no_exception():
    loan_id = _seed_loan_with_fresh_timestamp()

    results = validate_loan(loan_id)
    assert all(result["status"] == "pass" for result in results)

    with SessionLocal() as db:
        assert db.query(ExceptionRecord).filter_by(loan_id=loan_id).count() == 0


def test_multiple_failed_rules_create_one_exception_each():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5, borrower_state="ZZ", document_status=None)

    results = validate_loan(loan_id)
    failed = [result for result in results if result["status"] == "fail"]

    assert len(failed) >= 3
    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id).all()
        assert len(exceptions) == len(failed)
        assert {exception.type for exception in exceptions} >= {"interest_rate_range", "invalid_state_code", "missing_document_status"}


def test_reusing_existing_open_exception_does_not_create_duplicate_exception_or_audit_event():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5)

    first_results = validate_loan(loan_id)
    with SessionLocal() as db:
        first_exception_count = db.query(ExceptionRecord).filter_by(loan_id=loan_id, status="open").count()
        initial_audit_count = db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count()

    assert first_exception_count == 1
    assert initial_audit_count == 1

    second_results = validate_loan(loan_id)
    assert len(second_results) == len(first_results)

    with SessionLocal() as db:
        open_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, status="open").all()
        assert len(open_exceptions) == 1
        assert db.query(ValidationResult).filter_by(loan_id=loan_id).count() > 1
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1


def test_historical_resolved_exception_followed_by_new_failure_creates_new_open_exception():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    with SessionLocal() as db:
        existing = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range", status="open").one()
        existing.status = "resolved"
        existing.resolved_at = "2024-03-01T00:00:00Z"
        db.commit()

    _set_loan_field(loan_id, interest_rate=1.75)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range").all()
        assert len(exceptions) == 2
        assert any(exception.status == "resolved" for exception in exceptions)
        assert any(exception.status == "open" for exception in exceptions)


def test_historical_validation_results_are_not_deleted():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5)
    before_count = 0
    with SessionLocal() as db:
        before_count = db.query(ValidationResult).filter_by(loan_id=loan_id).count()

    validate_loan(loan_id)
    with SessionLocal() as db:
        after_count = db.query(ValidationResult).filter_by(loan_id=loan_id).count()
        assert after_count > before_count


def test_canonical_loan_data_is_not_modified():
    loan_id = _seed_loan_with_fresh_timestamp()
    original = {"original_principal": 250000.0, "current_balance": 240000.0, "interest_rate": 0.05}
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        assert loan.interest_rate == 1.5
        assert loan.original_principal == original["original_principal"]
        assert loan.current_balance == original["current_balance"]


def test_exception_created_audit_logged_only_when_new_exception_is_created():
    loan_id = _seed_loan_with_fresh_timestamp()
    _set_loan_field(loan_id, interest_rate=1.5)

    validate_loan(loan_id)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1

    validate_loan(loan_id)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1
