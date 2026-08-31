"""Regression tests for the approval/rejection-vs-revalidation contradiction (0C.1).

Once validation runs on every field edit (not just the field that was edited), an
exception the reviewer already approved or rejected must not be silently duplicated
by a fresh ExceptionRecord just because the same rule still fails and an unrelated
edit happened to trigger a full revalidation pass.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.seed import hash_password
from app.main import app
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.user import User
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


client = TestClient(app)

VALID_LOAN = {
    "loan_id": "L-0C1-001",
    "borrower_id": "B-0C1-001",
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


def _seed_loan_with_two_failures(loan_id: str) -> str:
    """Seed a loan that fails both balance_gt_principal and invalid_state_code."""
    data = {**VALID_LOAN, "loan_id": loan_id, "current_balance": 300000.0, "borrower_state": "ZZ"}
    with SessionLocal() as db:
        db.add(Loan(**data))
        db.commit()
    validate_loan(loan_id)
    return loan_id


def _exception_id_for_rule(loan_id: str, rule_name: str) -> int:
    with SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type=rule_name).one()
        return exc.id


def test_approved_exception_is_not_duplicated_by_unrelated_edit_revalidation():
    loan_id = _seed_loan_with_two_failures("L-0C1-APPROVE")
    balance_exc_id = _exception_id_for_rule(loan_id, "balance_gt_principal")
    state_exc_id = _exception_id_for_rule(loan_id, "invalid_state_code")

    reviewer_token = _authenticate("reviewer_0c1_approve")
    headers = {"Authorization": f"Bearer {reviewer_token}"}

    approve_response = client.post(
        f"/exceptions/{balance_exc_id}/approve",
        headers=headers,
        json={"comment": "Accepted as a known business exception."},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["exception_status"] == "resolved"

    # Unrelated edit: fixes invalid_state_code, does not touch current_balance, so
    # balance_gt_principal still fails when the full-loan revalidation runs.
    edit_response = client.post(
        f"/exceptions/{state_exc_id}/edit",
        headers=headers,
        json={"field": "borrower_state", "value": "NY"},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["status"] == "updated"

    with SessionLocal() as db:
        balance_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(balance_exceptions) == 1, "approved exception must be reused, not duplicated"
        assert balance_exceptions[0].id == balance_exc_id
        assert balance_exceptions[0].status == "resolved"

        state_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="invalid_state_code").all()
        assert len(state_exceptions) == 1
        assert state_exceptions[0].status == "resolved"


def test_rejected_exception_is_not_duplicated_by_unrelated_edit_revalidation():
    loan_id = _seed_loan_with_two_failures("L-0C1-REJECT")
    balance_exc_id = _exception_id_for_rule(loan_id, "balance_gt_principal")
    state_exc_id = _exception_id_for_rule(loan_id, "invalid_state_code")

    reviewer_token = _authenticate("reviewer_0c1_reject")
    headers = {"Authorization": f"Bearer {reviewer_token}"}

    reject_response = client.post(
        f"/exceptions/{balance_exc_id}/reject",
        headers=headers,
        json={"comment": "Not acceptable, but tracked separately."},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["exception_status"] == "rejected"

    edit_response = client.post(
        f"/exceptions/{state_exc_id}/edit",
        headers=headers,
        json={"field": "borrower_state", "value": "NY"},
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["status"] == "updated"

    with SessionLocal() as db:
        balance_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(balance_exceptions) == 1, "rejected exception must be reused, not duplicated"
        assert balance_exceptions[0].id == balance_exc_id
        assert balance_exceptions[0].status == "rejected"


def test_auto_resolved_exception_still_gets_a_new_record_on_later_failure():
    """Regression guard: only human decisions (approve/reject) suppress duplication.

    An exception that closed via automatic pass-based resolution (no ReviewAction)
    must still produce a new ExceptionRecord on a later failure, exactly as already
    covered by test_revalidation_4d.py -- this pins the boundary between the two
    behaviors down at the API-driven-edit boundary too, not just direct validate_loan.
    """
    loan_id = "L-0C1-AUTO-RESOLVE"
    data = {**VALID_LOAN, "loan_id": loan_id, "current_balance": 300000.0, "borrower_state": "ZZ"}
    with SessionLocal() as db:
        db.add(Loan(**data))
        db.commit()
    validate_loan(loan_id)
    state_exc_id = _exception_id_for_rule(loan_id, "invalid_state_code")

    # Fix current_balance directly (no reviewer decision recorded) so
    # balance_gt_principal auto-resolves on the next validation pass.
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        loan.current_balance = 240000.0
        db.commit()
    validate_loan(loan_id)

    with SessionLocal() as db:
        balance_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(balance_exceptions) == 1
        assert balance_exceptions[0].status == "resolved"

    # Now make it fail again and edit an unrelated field via the API.
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        loan.current_balance = 310000.0
        db.commit()

    reviewer_token = _authenticate("reviewer_0c1_auto")
    headers = {"Authorization": f"Bearer {reviewer_token}"}
    edit_response = client.post(
        f"/exceptions/{state_exc_id}/edit",
        headers=headers,
        json={"field": "borrower_state", "value": "NY"},
    )
    assert edit_response.status_code == 200

    with SessionLocal() as db:
        balance_exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").all()
        assert len(balance_exceptions) == 2, "auto-resolved exceptions still get a fresh record on a new failure"
        assert sum(1 for exc in balance_exceptions if exc.status == "open") == 1
        assert sum(1 for exc in balance_exceptions if exc.status == "resolved") == 1
