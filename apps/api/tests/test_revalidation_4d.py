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
    "loan_id": "L-4D-001",
    "borrower_id": "B-4D-001",
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


def _set_loan_field(loan_id: str, **kwargs):
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        for key, value in kwargs.items():
            setattr(loan, key, value)
        db.commit()


def test_fail_then_fail_reuses_existing_open_exception():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)

    first = validate_loan(loan_id)
    second = validate_loan(loan_id)

    assert any(result["rule_name"] == "balance_gt_principal" and result["status"] == "fail" for result in first)
    assert any(result["rule_name"] == "balance_gt_principal" and result["status"] == "fail" for result in second)

    with SessionLocal() as db:
        assert db.query(ValidationResult).filter_by(loan_id=loan_id, rule_name="balance_gt_principal").count() == 2
        assert db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal", status="open").count() == 1
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1


def test_fail_then_pass_resolves_open_exception_and_keeps_history():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)

    first = validate_loan(loan_id)
    assert any(result["rule_name"] == "balance_gt_principal" and result["status"] == "fail" for result in first)

    _set_loan_field(loan_id, current_balance=240000.0)
    second = validate_loan(loan_id)
    assert any(result["rule_name"] == "balance_gt_principal" and result["status"] == "pass" for result in second)

    with SessionLocal() as db:
        validation_results = db.query(ValidationResult).filter_by(loan_id=loan_id, rule_name="balance_gt_principal").all()
        assert len(validation_results) == 2
        assert {result.status for result in validation_results} == {"fail", "pass"}

        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(exceptions) == 1
        assert exceptions[0].status == "resolved"
        assert exceptions[0].resolved_at is not None


def test_multiple_independent_exceptions_resolve_only_the_correct_rule():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0, borrower_state="ZZ")
    validate_loan(loan_id)

    _set_loan_field(loan_id, current_balance=240000.0, borrower_state="ZZ")
    validate_loan(loan_id)

    with SessionLocal() as db:
        open_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, status="open").all()
        assert len(open_exceptions) == 1
        assert {exception.type for exception in open_exceptions} == {"invalid_state_code"}

        resolved = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal", status="resolved").one_or_none()
        assert resolved is not None


def test_resolved_exception_then_new_failure_creates_new_open_exception():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal", status="open").one()
        exc.status = "resolved"
        exc.resolved_at = "2024-03-01T00:00:00Z"
        db.commit()

    _set_loan_field(loan_id, current_balance=350000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(exceptions) == 2
        assert sum(1 for exc in exceptions if exc.status == "resolved") == 1
        assert sum(1 for exc in exceptions if exc.status == "open") == 1


def test_repeated_clean_validation_creates_no_exceptions():
    loan_id = _seed_loan()
    validate_loan(loan_id)
    validate_loan(loan_id)

    with SessionLocal() as db:
        assert db.query(ExceptionRecord).filter_by(loan_id=loan_id).count() == 0
        assert db.query(ValidationResult).filter_by(loan_id=loan_id).count() >= 2


def test_historical_validation_results_are_never_deleted():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)
    validate_loan(loan_id)
    _set_loan_field(loan_id, current_balance=240000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        results = db.query(ValidationResult).filter_by(loan_id=loan_id).all()
        assert len(results) >= 2


def test_historical_exceptions_are_never_deleted():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal", status="open").one()
        exc.status = "resolved"
        exc.resolved_at = "2024-03-01T00:00:00Z"
        db.commit()

    _set_loan_field(loan_id, current_balance=350000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(exceptions) == 2


def test_validation_never_mutates_the_canonical_loan():
    loan_id = _seed_loan()
    original = {"current_balance": 240000.0, "interest_rate": 0.05}
    _set_loan_field(loan_id, current_balance=300000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        assert loan.current_balance == 300000.0
        assert loan.interest_rate == 0.05

    _set_loan_field(loan_id, current_balance=240000.0)
    validate_loan(loan_id)

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        assert loan.current_balance == 240000.0
        assert loan.interest_rate == 0.05


def test_audit_history_is_preserved_and_exception_created_only_for_new_exceptions():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, current_balance=300000.0)

    validate_loan(loan_id)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="validation_executed").count() >= 1
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1

    validate_loan(loan_id)
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_created").count() == 1
        assert db.query(AuditLog).filter_by(loan_id=loan_id, event_type="exception_resolved").count() == 0
