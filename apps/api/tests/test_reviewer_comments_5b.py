from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.seed import hash_password
from app.main import app
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.user import User
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


client = TestClient(app)


VALID_LOAN = {
    "loan_id": "L-5B-001",
    "borrower_id": "B-5B-001",
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
        transaction.rollback()
        SessionLocal.configure(bind=engine)
        connection.close()


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


def _create_exception_for_loan(loan_id: str) -> int:
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)
    with SessionLocal() as db:
        exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range").one()
        return exception.id


def test_reviewer_can_add_a_comment_to_an_existing_exception():
    loan_id = _seed_loan(loan_id="L-5B-EXC-001")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "reviewer comment"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exception_id"] == exception_id
    assert payload["loan_id"] == loan_id
    assert payload["action_type"] == "comment"
    assert payload["comment_text"] == "reviewer comment"
    assert payload["action_id"]


def test_created_review_action_has_expected_fields():
    loan_id = _seed_loan(loan_id="L-5B-EXC-002")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_2")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "  exact comment text  "},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        action = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="comment").order_by(ReviewAction.id.desc()).first()
        assert action is not None
        assert action.loan_id == loan_id
        assert action.exception_id == exception_id
        assert action.reviewer_id is not None
        assert action.action_type == "comment"
        assert action.comment_text == "exact comment text"


def test_audit_event_reviewer_comment_added_is_created():
    loan_id = _seed_loan(loan_id="L-5B-EXC-003")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_3")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "needs review"},
    )
    assert response.status_code == 200
    review_action_id = response.json()["action_id"]

    with SessionLocal() as db:
        audit = db.query(AuditLog).filter(AuditLog.event_type == "reviewer_comment_added").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.loan_id == loan_id
        assert audit.details["exception_id"] == exception_id
        assert audit.details["review_action_id"] == review_action_id


def test_data_operator_cannot_add_comments():
    loan_id = _seed_loan(loan_id="L-5B-EXC-004")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("data_operator_5b", role="data_operator")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "should fail"},
    )
    assert response.status_code == 403


def test_data_consumer_cannot_add_comments():
    loan_id = _seed_loan(loan_id="L-5B-EXC-005")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("data_consumer_5b", role="data_consumer")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "should fail"},
    )
    assert response.status_code == 403


def test_unauthenticated_request_is_rejected():
    loan_id = _seed_loan(loan_id="L-5B-EXC-006")
    exception_id = _create_exception_for_loan(loan_id)

    response = client.post(f"/exceptions/{exception_id}/comment", json={"text": "needs review"})
    assert response.status_code == 401


def test_nonexistent_exception_returns_404():
    token = _authenticate("reviewer_5b_404")

    response = client.post(
        "/exceptions/999999/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "missing exception"},
    )
    assert response.status_code == 404


def test_empty_comment_is_rejected():
    loan_id = _seed_loan(loan_id="L-5B-EXC-007")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_7")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": ""},
    )
    assert response.status_code in {400, 422}


def test_whitespace_only_comment_is_rejected():
    loan_id = _seed_loan(loan_id="L-5B-EXC-008")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_8")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "   \n  "},
    )
    assert response.status_code in {400, 422}


def test_overly_long_comment_is_rejected():
    loan_id = _seed_loan(loan_id="L-5B-EXC-009")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_9")

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "x" * 2001},
    )
    assert response.status_code in {400, 422}


def test_two_identical_comments_create_two_actions_and_two_audit_events():
    loan_id = _seed_loan(loan_id="L-5B-EXC-010")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_10")

    first = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "same text"},
    )
    second = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "same text"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    with SessionLocal() as db:
        actions = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="comment", comment_text="same text").all()
        audit_events = db.query(AuditLog).filter_by(event_type="reviewer_comment_added").all()
        assert len(actions) == 2
        assert len(audit_events) >= 2


def test_get_exception_detail_returns_review_action_history():
    loan_id = _seed_loan(loan_id="L-5B-EXC-011")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_11")

    client.post(f"/exceptions/{exception_id}/comment", headers={"Authorization": f"Bearer {token}"}, json={"text": "first"})
    client.post(f"/exceptions/{exception_id}/comment", headers={"Authorization": f"Bearer {token}"}, json={"text": "second"})

    response = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    review_actions = payload["review_actions"]
    assert len(review_actions) >= 2
    assert [item["comment_text"] for item in review_actions[:2]] == ["first", "second"]


def test_multiple_comments_are_returned_in_deterministic_order():
    loan_id = _seed_loan(loan_id="L-5B-EXC-012")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_12")

    ordered = ["alpha", "beta", "gamma"]
    for text in ordered:
        response = client.post(f"/exceptions/{exception_id}/comment", headers={"Authorization": f"Bearer {token}"}, json={"text": text})
        assert response.status_code == 200

    response = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    history = response.json()["review_actions"]
    assert [item["comment_text"] for item in history[-3:]] == ordered


def test_adding_a_comment_does_not_modify_loan_or_exception_status():
    loan_id = _seed_loan(loan_id="L-5B-EXC-013")
    exception_id = _create_exception_for_loan(loan_id)
    token = _authenticate("reviewer_5b_13")

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        original_balance = loan.current_balance
        original_interest_rate = loan.interest_rate
        exception = db.get(ExceptionRecord, exception_id)
        original_status = exception.status

    response = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "no mutation"},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        exception = db.get(ExceptionRecord, exception_id)
        assert loan.current_balance == original_balance
        assert loan.interest_rate == original_interest_rate
        assert exception.status == original_status

    with SessionLocal() as db:
        validation_count = db.query(__import__("app.models.validation_result", fromlist=["ValidationResult"]).ValidationResult).filter_by(loan_id=loan_id).count()
        assert validation_count >= 1
