import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_validation_framework.db")

import pytest
from sqlalchemy import text
from sqlalchemy.orm import close_all_sessions

from app.core.database import Base, SessionLocal, engine
from app.models.audit import AuditLog
from app.models.loan import Loan
from app.models.validation_result import ValidationResult
from app.validators.engine import clear_rules, register_rule, validate_loan


def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_loan(loan_id: str = "L-VALID-001") -> None:
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        if loan is None:
            db.add(
                Loan(
                    loan_id=loan_id,
                    borrower_id="B-001",
                    origination_date="2024-01-15",
                    original_principal=250000.0,
                    current_balance=240000.0,
                    term_months=360,
                    payment_status="current",
                )
            )
        db.commit()


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
    seed_loan()
    try:
        yield
    finally:
        clear_rules()
        close_all_sessions()
        transaction.rollback()
        SessionLocal.configure(bind=engine)
        connection.close()


def test_validation_rule_can_execute():
    clear_rules()
    register_rule(
        "test_rule_pass",
        lambda context: {
            "rule_name": "test_rule_pass",
            "status": "pass",
            "severity": "low",
            "message": "Rule executed successfully.",
            "details": {"checked": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )

    results = validate_loan("L-VALID-001")
    assert len(results) == 1
    assert results[0]["status"] == "pass"
    assert results[0]["rule_name"] == "test_rule_pass"


def test_pass_result_is_persisted():
    clear_rules()
    register_rule(
        "test_rule_pass_persisted",
        lambda context: {
            "rule_name": "test_rule_pass_persisted",
            "status": "pass",
            "severity": "medium",
            "message": "Persisted pass result.",
            "details": {"passed": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )

    validate_loan("L-VALID-001")

    with SessionLocal() as db:
        persisted = db.execute(
            text("SELECT COUNT(*) FROM validation_results WHERE rule_name = 'test_rule_pass_persisted'")
        ).scalar_one()
        assert persisted == 1


def test_fail_result_is_persisted():
    clear_rules()
    register_rule(
        "test_rule_fail_persisted",
        lambda context: {
            "rule_name": "test_rule_fail_persisted",
            "status": "fail",
            "severity": "high",
            "message": "Persisted fail result.",
            "details": {"failed": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )

    validate_loan("L-VALID-001")

    with SessionLocal() as db:
        persisted = db.execute(
            text("SELECT COUNT(*) FROM validation_results WHERE rule_name = 'test_rule_fail_persisted' AND status = 'fail'")
        ).scalar_one()
        assert persisted == 1


def test_validation_can_be_called_for_a_single_loan():
    clear_rules()
    register_rule(
        "single_loan_validation_rule",
        lambda context: {
            "rule_name": "single_loan_validation_rule",
            "status": "pass",
            "severity": "low",
            "message": "Single loan validation called.",
            "details": {"loan_id": context["loan"].loan_id},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )

    results = validate_loan("L-VALID-001")
    assert len(results) == 1
    assert results[0]["loan_id"] == "L-VALID-001"


def test_engine_continues_after_a_rule_fails():
    clear_rules()
    register_rule(
        "first_rule_fails",
        lambda context: {
            "rule_name": "first_rule_fails",
            "status": "fail",
            "severity": "high",
            "message": "first failure",
            "details": {"failed": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )
    register_rule(
        "second_rule_passes",
        lambda context: {
            "rule_name": "second_rule_passes",
            "status": "pass",
            "severity": "low",
            "message": "still ran",
            "details": {"ran": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="numeric",
    )

    results = validate_loan("L-VALID-001")
    assert len(results) == 2
    assert [result["rule_name"] for result in results] == ["first_rule_fails", "second_rule_passes"]
    assert any(result["status"] == "fail" for result in results)
    assert any(result["status"] == "pass" for result in results)


def test_multiple_results_are_persisted_together():
    clear_rules()
    register_rule(
        "multi_rule_a",
        lambda context: {
            "rule_name": "multi_rule_a",
            "status": "pass",
            "severity": "low",
            "message": "a passed",
            "details": {"a": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )
    register_rule(
        "multi_rule_b",
        lambda context: {
            "rule_name": "multi_rule_b",
            "status": "fail",
            "severity": "medium",
            "message": "b failed",
            "details": {"b": False},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="numeric",
    )

    results = validate_loan("L-VALID-001")
    assert len(results) == 2

    with SessionLocal() as db:
        persisted = db.query(ValidationResult).filter(ValidationResult.loan_id == "L-VALID-001").count()
        assert persisted == 2


def test_loan_not_found_raises_expected_error():
    with pytest.raises(LookupError, match="not found"):
        validate_loan("L-DOES-NOT-EXIST")


def test_validation_executed_audit_event_is_created():
    clear_rules()
    register_rule(
        "audit_rule",
        lambda context: {
            "rule_name": "audit_rule",
            "status": "pass",
            "severity": "low",
            "message": "audit check",
            "details": {"audit": True},
            "loan_id": context["loan"].loan_id,
            "run_at": context["run_at"],
        },
        phase="required",
    )

    validate_loan("L-VALID-001")

    with SessionLocal() as db:
        event = db.query(AuditLog).filter(AuditLog.event_type == "validation_executed").one_or_none()
        assert event is not None
        assert event.loan_id == "L-VALID-001"
        assert event.details["rules_executed"] == 1
        assert event.details["passed"] == 1
        assert event.details["failed"] == 0
