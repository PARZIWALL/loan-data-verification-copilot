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
    "loan_id": "L-5D-001",
    "borrower_id": "B-5D-001",
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


def test_reviewer_can_approve_an_open_exception():
    loan_id = _seed_loan(loan_id="L-5D-APPROVE-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_1")

    response = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action_type"] == "approve"
    assert payload["exception_status"] == "resolved"
    assert payload["exception_id"] == exception_id


def test_approve_creates_review_action_and_audit_event():
    loan_id = _seed_loan(loan_id="L-5D-APPROVE-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_2")

    response = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Looks good."},
    )
    action_id = response.json()["action_id"]

    with SessionLocal() as db:
        action = db.get(ReviewAction, action_id)
        assert action is not None
        assert action.action_type == "approve"
        assert action.comment_text == "Looks good."

        audit = db.query(AuditLog).filter_by(event_type="loan_approved").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.details["exception_id"] == exception_id
        assert audit.details["review_action_id"] == action_id


def test_reviewer_can_reject_an_open_exception():
    loan_id = _seed_loan(loan_id="L-5D-REJECT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_3")

    response = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action_type"] == "reject"
    assert payload["exception_status"] == "rejected"


def test_reject_creates_review_action_and_audit_event():
    loan_id = _seed_loan(loan_id="L-5D-REJECT-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_4")

    response = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Not acceptable."},
    )
    action_id = response.json()["action_id"]

    with SessionLocal() as db:
        action = db.get(ReviewAction, action_id)
        assert action is not None
        assert action.action_type == "reject"

        audit = db.query(AuditLog).filter_by(event_type="loan_rejected").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.details["exception_id"] == exception_id


def test_reviewer_can_request_correction():
    loan_id = _seed_loan(loan_id="L-5D-CORRECT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_5")

    response = client.post(
        f"/exceptions/{exception_id}/request-correction",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Please verify balance."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action_type"] == "request_correction"
    assert payload["exception_status"] == "in_review"


def test_request_correction_creates_review_action_and_audit_event():
    loan_id = _seed_loan(loan_id="L-5D-CORRECT-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_6")

    response = client.post(
        f"/exceptions/{exception_id}/request-correction",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Verify balance."},
    )
    action_id = response.json()["action_id"]

    with SessionLocal() as db:
        action = db.get(ReviewAction, action_id)
        assert action is not None
        assert action.action_type == "request_correction"
        assert action.comment_text == "Verify balance."

        audit = db.query(AuditLog).filter_by(event_type="correction_requested").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.details["exception_id"] == exception_id
        assert audit.details["review_action_id"] == action_id


def test_data_operator_cannot_approve():
    loan_id = _seed_loan(loan_id="L-5D-AUTHZ-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("data_op_5d", role="data_operator")

    response = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert response.status_code == 403


def test_data_consumer_cannot_reject():
    loan_id = _seed_loan(loan_id="L-5D-AUTHZ-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("data_cons_5d", role="data_consumer")

    response = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert response.status_code == 403


def test_unauthenticated_user_cannot_decide():
    loan_id = _seed_loan(loan_id="L-5D-AUTHZ-003")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)

    for endpoint in ("approve", "reject", "request-correction"):
        response = client.post(f"/exceptions/{exception_id}/{endpoint}", json={"comment": None})
        assert response.status_code == 401


def test_nonexistent_exception_returns_404():
    token = _authenticate("reviewer_5d_7")

    for endpoint in ("approve", "reject", "request-correction"):
        response = client.post(
            f"/exceptions/999999/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            json={"comment": None},
        )
        assert response.status_code == 404


def test_already_resolved_exception_rejects_new_decision():
    loan_id = _seed_loan(loan_id="L-5D-TERM-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_8")

    first = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert first.status_code == 200

    second = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert second.status_code == 400


def test_already_rejected_exception_rejects_new_decision():
    loan_id = _seed_loan(loan_id="L-5D-TERM-002")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_9")

    first = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert first.status_code == 200

    second = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert second.status_code == 400


def test_duplicate_decision_attempt_does_not_create_another_action():
    loan_id = _seed_loan(loan_id="L-5D-DUPE-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_10")

    first = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert first.status_code == 200

    with SessionLocal() as db:
        action_count_after_first = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="approve").count()
        assert action_count_after_first == 1

        second = client.post(
            f"/exceptions/{exception_id}/approve",
            headers={"Authorization": f"Bearer {token}"},
            json={"comment": None},
        )
        assert second.status_code == 400

        action_count_after_second = db.query(ReviewAction).filter_by(exception_id=exception_id, action_type="approve").count()
        assert action_count_after_second == 1


def test_one_exception_decision_does_not_change_another_exception_for_same_loan():
    loan_id = _seed_loan(loan_id="L-5D-MULTI-001")
    _set_loan_field(loan_id, current_balance=300000.0, interest_rate=0.20)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id).all()
        if len(exceptions) < 2:
            exc = db.get(ExceptionRecord, exceptions[0].id)
            new_exc = ExceptionRecord(
                loan_id=loan_id,
                validation_result_id=None,
                type="invalid_state_code" if exc.type != "invalid_state_code" else "stale_record",
                severity="high",
                status="open",
                created_at=exceptions[0].created_at,
            )
            db.add(new_exc)
            db.commit()
            exceptions = db.query(ExceptionRecord).filter_by(loan_id=loan_id).all()

        exc1_id = exceptions[0].id
        exc2_id = exceptions[1].id

    token = _authenticate("reviewer_5d_11")

    response = client.post(
        f"/exceptions/{exc1_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )
    assert response.status_code == 200

    with SessionLocal() as db:
        exc1 = db.get(ExceptionRecord, exc1_id)
        exc2 = db.get(ExceptionRecord, exc2_id)
        assert exc1.status == "resolved"
        assert exc2.status == "open"


def test_decision_does_not_mutate_canonical_loan_data():
    loan_id = _seed_loan(loan_id="L-5D-NOMUT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_12")

    with SessionLocal() as db:
        before = db.get(Loan, loan_id).current_balance

    client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    with SessionLocal() as db:
        after = db.get(Loan, loan_id).current_balance
        assert after == before


def test_decision_does_not_delete_validation_results():
    loan_id = _seed_loan(loan_id="L-5D-VALRES-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_13")

    with SessionLocal() as db:
        exc = db.get(ExceptionRecord, exception_id)
        rule_name = exc.type
        from app.models.validation_result import ValidationResult

        result_count_before = db.query(ValidationResult).filter_by(loan_id=loan_id, rule_name=rule_name).count()

    client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    with SessionLocal() as db:
        from app.models.validation_result import ValidationResult

        result_count_after = db.query(ValidationResult).filter_by(loan_id=loan_id, rule_name=rule_name).count()
        assert result_count_after == result_count_before


def test_decision_does_not_create_verified_loan():
    loan_id = _seed_loan(loan_id="L-5D-NOVERIF-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_14")

    client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    with SessionLocal() as db:
        from app.models.verified_loan import VerifiedLoan

        verified_count = db.query(VerifiedLoan).filter_by(loan_id=loan_id).count()
        assert verified_count == 0


def test_action_history_contains_decision_action():
    loan_id = _seed_loan(loan_id="L-5D-HIST-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_15")

    client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    response = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    actions = payload["review_actions"]
    assert any(action["action_type"] == "approve" for action in actions)


def test_audit_record_links_to_review_action():
    loan_id = _seed_loan(loan_id="L-5D-AUDIT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_16")

    response = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Approved."},
    )
    action_id = response.json()["action_id"]

    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(event_type="loan_approved").order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert audit.details["review_action_id"] == action_id


def test_existing_5a_5b_5c_behavior_remains_intact():
    loan_id = _seed_loan(loan_id="L-5D-INTACT-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_17")

    response_list = client.get("/exceptions", headers={"Authorization": f"Bearer {token}"})
    assert response_list.status_code == 200
    assert "items" in response_list.json()

    response_detail = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    assert response_detail.status_code == 200
    assert "exception" in response_detail.json()

    response_comment = client.post(
        f"/exceptions/{exception_id}/comment",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Test comment."},
    )
    assert response_comment.status_code == 200

    response_edit = client.post(
        f"/exceptions/{exception_id}/edit",
        headers={"Authorization": f"Bearer {token}"},
        json={"field": "current_balance", "value": 240000},
    )
    assert response_edit.status_code == 200


def test_request_correction_from_open_state():
    loan_id = _seed_loan(loan_id="L-5D-RC-OPEN-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_18")

    response = client.post(
        f"/exceptions/{exception_id}/request-correction",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": "Needs correction"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exception_status"] == "in_review"


def test_approve_from_in_review_state():
    loan_id = _seed_loan(loan_id="L-5D-APR-REVIEW-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_19")

    client.post(
        f"/exceptions/{exception_id}/request-correction",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    response = client.post(
        f"/exceptions/{exception_id}/approve",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exception_status"] == "resolved"


def test_reject_from_in_review_state():
    loan_id = _seed_loan(loan_id="L-5D-REJ-REVIEW-001")
    exception_id = _create_exception_for_loan(loan_id, current_balance=300000.0)
    token = _authenticate("reviewer_5d_20")

    client.post(
        f"/exceptions/{exception_id}/request-correction",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    response = client.post(
        f"/exceptions/{exception_id}/reject",
        headers={"Authorization": f"Bearer {token}"},
        json={"comment": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["exception_status"] == "rejected"
