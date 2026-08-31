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
    "loan_id": "L-5C-001",
    "borrower_id": "B-5C-001",
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


def _create_exception_for_loan(loan_id: str, **kwargs) -> int:
    _set_loan_field(loan_id, **kwargs)
    validate_loan(loan_id)
    with SessionLocal() as db:
        exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one_or_none()
        if exception is None:
            exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range").one_or_none()
        return exception.id


def test_reviewer_can_edit_an_allowed_field():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_1")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "updated"
    assert payload["exception_id"] == exception_id
    assert payload["loan_id"] == loan_id
    assert payload["field_name"] == "current_balance"


def test_edit_captures_old_and_new_values_and_uses_edit_action_type():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_2")

    client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )

    with SessionLocal() as db:
        action = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="edit_field").order_by(ReviewAction.id.desc()).first()
        assert action is not None
        assert action.field_name == "current_balance"
        assert action.old_value == 300000.0
        assert action.new_value == 240000.0
        assert action.reviewer_id is not None


def test_field_edited_audit_event_is_created():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-003")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_3")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )
    action_id = response.json()["action_id"]

    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(event_type="field_edited").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.loan_id == loan_id
        assert audit.details["exception_id"] == exception_id
        assert audit.details["review_action_id"] == action_id
        assert audit.details["field_name"] == "current_balance"


def test_non_reviewer_cannot_edit_field():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-004")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)

    for role in ("data_operator", "data_consumer"):
        token = _authenticate(f"{role}_5c", role=role)
        response = client.post(
            f"/exceptions/{exception_id}/edit",
            headers={"Authorization": f"Bearer {token}"},
            json={"field": "current_balance", "value": 240000},
        )
        assert response.status_code == 403


def test_unauthenticated_user_cannot_edit_field():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-005")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)

    response = client.post(f"/exceptions/{exception_id}/edit", json={"field": "current_balance", "value": 240000})
    assert response.status_code == 401


def test_invalid_field_is_rejected():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-006")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_6")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "unknown_field", "value": 50},
    )
    assert response.status_code == 400


def test_forbidden_internal_field_is_rejected():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-007")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_7")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "loan_id", "value": "NEW-LOAN"},
    )
    assert response.status_code == 400


def test_invalid_value_type_is_rejected_and_does_not_mutate_loan():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-008")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_8")

    with SessionLocal() as db:
        before = db.get(Loan, loan_id).current_balance

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": "not-a-number"},
    )
    assert response.status_code == 400

    with SessionLocal() as db:
        after = db.get(Loan, loan_id).current_balance
        assert after == before
        assert db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="edit_field").count() == 0


def test_no_op_edit_returns_no_change_and_no_history():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-009")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_9")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 300000.0},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_change"
    assert payload["action_id"] is None

    with SessionLocal() as db:
        assert db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="edit_field").count() == 0
        assert db.query(AuditLog).filter_by(event_type="field_edited").count() == 0


def test_successful_edit_triggers_existing_validation_engine_and_resolves_exception():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-010")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_10")

    response = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        assert loan.current_balance == 240000.0
        exception = db.get(ExceptionRecord, exception_id)
        assert exception.status == "resolved"
        validation_results = db.query(__import__("app.models.validation_result", fromlist=["ValidationResult"]).ValidationResult).filter_by(loan_id=loan_id, rule_name="balance_gt_principal").all()
        assert any(result.status == "pass" for result in validation_results)


def test_edit_history_is_exposed_in_exception_detail():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-011")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_11")

    client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )

    response = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    actions = payload["review_actions"]
    assert any(action["action_type"] == "edit_field" and action["field_name"] == "current_balance" for action in actions)


def test_two_legitimate_edits_create_two_review_actions():
    loan_id = _seed_loan(loan_id="L-5C-EDIT-012")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5c_12")

    first = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 250000},
    )
    second = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    with SessionLocal() as db:
        actions = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="edit_field").all()
        assert len(actions) == 2


def test_nonexistent_exception_returns_404():
    token = _authenticate("reviewer_5c_13")
    response = client.post(
        "/exceptions/999999/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )
    assert response.status_code == 404
