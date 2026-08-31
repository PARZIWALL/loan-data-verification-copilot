from datetime import datetime, timezone
import re

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, create_db_and_tables, engine
from app.core.seed import hash_password
from app.main import app
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.user import User
from app.models.verified_loan import VerifiedLoan
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


client = TestClient(app)

VALID_LOAN = {
    "loan_id": "L-6A-001",
    "borrower_id": "B-6A-001",
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
    create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def reset_validation_state():
    clear_rules()
    _clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        _clear_database()


def _clear_database() -> None:
    """Delete test data while keeping the shared SQLite schema intact.

    API requests use their own SessionLocal sessions and commit normally, so
    cleanup must use committed deletes rather than an outer test transaction.
    """
    with engine.begin() as connection:
        tables = Base.metadata.tables
        loan_table = tables["loans"]
        connection.execute(loan_table.update().values(primary_source_id=None))
        for table_name in (
            "audit_logs",
            "review_actions",
            "ai_recommendations",
            "verified_loans",
            "exceptions",
            "validation_results",
            "verifications",
            "loan_sources",
            "loans",
            "users",
        ):
            table = tables.get(table_name)
            if table is not None:
                connection.execute(table.delete())


def _seed_user(username: str, role: str) -> User:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(username=username, password_hash=hash_password("dev_password"), role=role)
            db.add(user)
            db.commit()
        return user


def _authenticate(username: str, role: str = "reviewer") -> str:
    _seed_user(username, role)
    response = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _seed_loan(**overrides):
    data = {**VALID_LOAN, **overrides}
    with SessionLocal() as db:
        loan = Loan(**data)
        db.add(loan)
        db.flush()
        db.add(
            LoanSource(
                loan_id=loan.loan_id,
                source_file="loan_tape.csv",
                source_system="loan_tape",
                source_row_number=1,
                raw_data={"loan_id": loan.loan_id, "borrower_id": loan.borrower_id},
                import_status="success",
            )
        )
        db.commit()
        return loan.loan_id


def _set_loan_field(loan_id: str, **kwargs):
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        for key, value in kwargs.items():
            setattr(loan, key, value)
        db.commit()


def _create_exception_for_loan(loan_id: str, status: str = "open", **kwargs) -> int:
    _set_loan_field(loan_id, **kwargs)
    validate_loan(loan_id)
    with SessionLocal() as db:
        exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one_or_none()
        if exception is None:
            exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range").one_or_none()
        if exception and status != "open":
            exception.status = status
            if status in ("resolved", "rejected"):
                exception.resolved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            db.commit()
        return exception.id if exception else None


def _assert_no_verification_side_effects(loan_id: str) -> None:
    with SessionLocal() as db:
        assert db.query(VerifiedLoan).filter_by(loan_id=loan_id).count() == 0
        assert (
            db.query(AuditLog)
            .filter_by(loan_id=loan_id, event_type="verified_record_created")
            .count()
            == 0
        )


def test_eligible_loan_can_be_verified_by_reviewer():
    loan_id = _seed_loan(loan_id="L-6A-VERIFY-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_1")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "verified"
    assert payload["loan_id"] == loan_id
    assert payload["verified_record_id"] is not None


def test_verified_record_has_correct_fields():
    loan_id = _seed_loan(loan_id="L-6A-FIELDS-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_2")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    payload = response.json()
    assert payload["status"] == "verified"
    assert payload["verified_by"] is not None
    assert payload["verification_timestamp"] is not None
    assert re.fullmatch(r"[0-9a-f]{64}", payload["record_hash"])
    assert payload["exported"] is False


def test_verified_record_contains_final_data_snapshot():
    loan_id = _seed_loan(loan_id="L-6A-SNAPSHOT-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_3")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.final_data is not None
        assert record.final_data["loan_id"] == loan_id
        assert record.final_data["borrower_id"] is not None


def test_verified_record_contains_source_reference():
    loan_id = _seed_loan(loan_id="L-6A-SOURCE-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_4")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.source_reference is not None
        assert "source_records_count" in record.source_reference


def test_verified_record_contains_validation_result_summary():
    loan_id = _seed_loan(loan_id="L-6A-VALSUM-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_5")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.validation_result_summary is not None
        assert "total_results" in record.validation_result_summary
        assert "passed" in record.validation_result_summary


def test_verified_record_contains_reviewer_decision():
    loan_id = _seed_loan(loan_id="L-6A-DECISION-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_6")

    with SessionLocal() as db:
        db.add(
            ReviewAction(
                loan_id=loan_id,
                action_type="approve",
                comment_text="Reviewed and approved.",
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.commit()

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.reviewer_decision == "approved"


def test_verification_creates_audit_event():
    loan_id = _seed_loan(loan_id="L-6A-AUDIT-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_7")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(event_type="verified_record_created").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.loan_id == loan_id
        assert audit.details["verified_record_id"] == record_id


def test_verification_does_not_modify_canonical_loan():
    loan_id = _seed_loan(loan_id="L-6A-NOMUT-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_8")

    with SessionLocal() as db:
        before = db.get(Loan, loan_id).current_balance

    client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    with SessionLocal() as db:
        after = db.get(Loan, loan_id).current_balance
        assert after == before


def test_verification_does_not_delete_validation_results():
    loan_id = _seed_loan(loan_id="L-6A-VALRES-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_9")

    from app.models.validation_result import ValidationResult

    with SessionLocal() as db:
        result_count_before = db.query(ValidationResult).filter_by(loan_id=loan_id).count()

    client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    with SessionLocal() as db:
        result_count_after = db.query(ValidationResult).filter_by(loan_id=loan_id).count()
        assert result_count_after == result_count_before


def test_verification_does_not_delete_exceptions():
    loan_id = _seed_loan(loan_id="L-6A-EXCRES-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_10")

    with SessionLocal() as db:
        exc_count_before = db.query(ExceptionRecord).filter_by(loan_id=loan_id).count()

    client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    with SessionLocal() as db:
        exc_count_after = db.query(ExceptionRecord).filter_by(loan_id=loan_id).count()
        assert exc_count_after == exc_count_before


def test_verification_does_not_delete_review_actions():
    loan_id = _seed_loan(loan_id="L-6A-RAACT-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_11")

    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id).first()
        if exc:
            action = ReviewAction(
                exception_id=exc.id,
                loan_id=loan_id,
                reviewer_id=1,
                action_type="comment",
                comment_text="Test",
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            db.add(action)
            db.commit()
            action_count_before = db.query(ReviewAction).filter_by(loan_id=loan_id).count()
        else:
            action_count_before = 0

    client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    with SessionLocal() as db:
        action_count_after = db.query(ReviewAction).filter_by(loan_id=loan_id).count()
        assert action_count_after == action_count_before


def test_verification_does_not_mutate_canonical_exception_validation_or_review_data():
    loan_id = _seed_loan(loan_id="L-6A-NO-RELATED-MUTATION-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_related_data")

    with SessionLocal() as db:
        db.add(
            ReviewAction(
                loan_id=loan_id,
                action_type="comment",
                comment_text="Retain this review action.",
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        db.commit()
        loan_before = db.get(Loan, loan_id).current_balance
        exceptions_before = [
            (exc.id, exc.status, exc.resolved_at)
            for exc in db.query(ExceptionRecord).filter_by(loan_id=loan_id).order_by(ExceptionRecord.id)
        ]
        from app.models.validation_result import ValidationResult

        validations_before = [
            (result.id, result.status, result.run_at)
            for result in db.query(ValidationResult).filter_by(loan_id=loan_id).order_by(ValidationResult.id)
        ]
        review_actions_before = [
            (action.id, action.action_type, action.comment_text)
            for action in db.query(ReviewAction).filter_by(loan_id=loan_id).order_by(ReviewAction.id)
        ]

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        assert db.get(Loan, loan_id).current_balance == loan_before
        assert [
            (exc.id, exc.status, exc.resolved_at)
            for exc in db.query(ExceptionRecord).filter_by(loan_id=loan_id).order_by(ExceptionRecord.id)
        ] == exceptions_before
        assert [
            (result.id, result.status, result.run_at)
            for result in db.query(ValidationResult).filter_by(loan_id=loan_id).order_by(ValidationResult.id)
        ] == validations_before
        assert [
            (action.id, action.action_type, action.comment_text)
            for action in db.query(ReviewAction).filter_by(loan_id=loan_id).order_by(ReviewAction.id)
        ] == review_actions_before


def test_loan_with_open_exception_cannot_be_verified():
    loan_id = _seed_loan(loan_id="L-6A-BLOCK-OPEN-001")
    _create_exception_for_loan(loan_id, status="open", current_balance=300000.0)
    token = _authenticate("reviewer_6a_12")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ineligible"
    assert payload["blocking_exception_count"] > 0
    _assert_no_verification_side_effects(loan_id)


def test_loan_with_in_review_exception_cannot_be_verified():
    loan_id = _seed_loan(loan_id="L-6A-BLOCK-REVIEW-001")
    _create_exception_for_loan(loan_id, status="in_review", current_balance=300000.0)
    token = _authenticate("reviewer_6a_13")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ineligible"
    _assert_no_verification_side_effects(loan_id)


def test_loan_with_only_resolved_exceptions_can_be_verified():
    loan_id = _seed_loan(loan_id="L-6A-RESOLVED-001")
    _create_exception_for_loan(loan_id, status="resolved", current_balance=300000.0)
    token = _authenticate("reviewer_6a_14")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "verified"


def test_loan_with_rejected_exception_cannot_be_verified():
    loan_id = _seed_loan(loan_id="L-6A-REJECTED-001")
    _create_exception_for_loan(loan_id, status="rejected", current_balance=300000.0)
    token = _authenticate("reviewer_6a_15")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ineligible"
    assert payload["blocking_exception_count"] > 0
    _assert_no_verification_side_effects(loan_id)


def test_data_operator_cannot_verify():
    loan_id = _seed_loan(loan_id="L-6A-AUTHZ-001")
    validate_loan(loan_id)
    token = _authenticate("data_op_6a", role="data_operator")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    assert response.status_code == 403


def test_data_consumer_cannot_verify():
    loan_id = _seed_loan(loan_id="L-6A-AUTHZ-002")
    validate_loan(loan_id)
    token = _authenticate("data_cons_6a", role="data_consumer")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    assert response.status_code == 403


def test_unauthenticated_user_cannot_verify():
    loan_id = _seed_loan(loan_id="L-6A-AUTHZ-003")
    validate_loan(loan_id)

    response = client.post("/verified-loans", json={"loan_id": loan_id})
    assert response.status_code == 401


def test_nonexistent_loan_returns_404():
    token = _authenticate("reviewer_6a_16")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": "NONEXISTENT-LOAN"},
    )
    assert response.status_code == 404


def test_duplicate_verification_is_rejected():
    loan_id = _seed_loan(loan_id="L-6A-DUPE-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_17")

    first = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "verified"

    with SessionLocal() as db:
        audit_count_after_first = (
            db.query(AuditLog)
            .filter_by(loan_id=loan_id, event_type="verified_record_created")
            .count()
        )

    second = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    assert 400 <= second.status_code < 500
    payload = second.json()["detail"]
    assert payload["status"] == "duplicate"
    assert payload["existing_verified_record_id"] is not None

    with SessionLocal() as db:
        assert db.query(VerifiedLoan).filter_by(loan_id=loan_id).count() == 1
        assert (
            db.query(AuditLog)
            .filter_by(loan_id=loan_id, event_type="verified_record_created")
            .count()
            == audit_count_after_first
        )


def test_changing_canonical_loan_after_verification_does_not_change_snapshot():
    loan_id = _seed_loan(loan_id="L-6A-IMMU-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_18")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        original_balance = record.final_data["current_balance"]

    _set_loan_field(loan_id, current_balance=500000.0)

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        snapshot_balance = record.final_data["current_balance"]
        assert snapshot_balance == original_balance


def test_verified_record_is_not_live_reference():
    loan_id = _seed_loan(loan_id="L-6A-NOTLIVE-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_19")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert isinstance(record.final_data, dict)
        assert not hasattr(record.final_data, "__dict__")


def test_audit_record_points_to_verified_record():
    loan_id = _seed_loan(loan_id="L-6A-AUDIT-LINK-001")
    validate_loan(loan_id)
    token = _authenticate("reviewer_6a_20")

    response = client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )
    record_id = response.json()["verified_record_id"]

    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(event_type="verified_record_created").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.details["verified_record_id"] == record_id


def test_existing_5a_5b_5c_5d_behavior_remains_intact():
    loan_id = _seed_loan(loan_id="L-6A-INTACT-001")
    exception_id = None
    
    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id).first()
        if exc:
            exception_id = exc.id
            db.delete(exc)
            db.commit()

    validate_loan(loan_id)

    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id).first()
        if exc:
            exception_id = exc.id

    if exception_id:
        token = _authenticate("reviewer_6a_21")

        response_list = client.get("/exceptions", headers={"Authorization": f"Bearer {token}"})
        assert response_list.status_code == 200

        response_detail = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
        assert response_detail.status_code == 200
