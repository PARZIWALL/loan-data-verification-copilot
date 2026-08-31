"""End-to-end regression test for the real product lifecycle (0H).

Walks upload -> validate -> exception -> review -> revalidate -> verify -> hash ->
export entirely through the real HTTP API (TestClient against app.main), with no
test code ever calling validate_loan()/validate_loan_in_session() directly. This is
the thing the audit found was never actually proven: that the pieces are wired
together, not just individually correct in isolation.

Uses the 6A-style isolation pattern (see test_verification_6a.py), not the 5D
outer-transaction-rollback style: multiple independent TestClient requests each open
and commit their own SessionLocal() via get_db(), so cleanup must use real committed
deletes on a separate connection rather than wrapping the whole test in one outer
transaction that gets rolled back.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, create_db_and_tables, engine
from app.core.seed import hash_password
from app.main import app
from app.models.loan import Loan
from app.models.user import User
from app.validators.engine import clear_rules
from app.validators.rules import register_default_rules

client = TestClient(app)

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(scope="session", autouse=True)
def ensure_schema():
    create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def reset_state():
    clear_rules()
    _clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        _clear_database()


def _clear_database() -> None:
    """Delete test data with real committed deletes, keeping the shared schema intact.

    API requests use their own SessionLocal sessions and commit normally, so cleanup
    must use committed deletes on a separate connection rather than an outer test
    transaction (see test_verification_6a.py's _clear_database docstring).
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


def _authenticate(username: str, role: str) -> dict[str, str]:
    _seed_user(username, role)
    response = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _loan_tape_csv(**overrides) -> str:
    row = {
        "loan_id": "L-0H-001",
        "borrower_id": "B-0H-001",
        "loan_type": "personal",
        "origination_date": "2024-01-15",
        "maturity_date": "2034-01-15",
        "original_principal": "100000",
        "current_balance": "90000",
        "interest_rate": "0.05",
        "term_months": "120",
        "borrower_state": "CA",
        "loan_purpose": "debt_consolidation",
        "credit_grade": "B",
        "employment_length": "5",
        "income_band": "medium",
        "payment_status": "current",
        "days_past_due": "0",
        "servicer_name": "Acme Servicing",
        "last_payment_date": "2024-02-01",
        "last_updated_at": TODAY,
        "document_status": "complete",
        "source_system": "loan_tape",
    }
    row.update(overrides)
    header = ",".join(row.keys())
    values = ",".join(str(v) for v in row.values())
    return f"{header}\n{values}\n"


def _upload(headers: dict[str, str], csv_text: str, source_type: str = "loan_tape", filename: str = "loan_tape.csv"):
    return client.post(
        "/upload",
        data={"source_type": source_type},
        files={"file": (filename, csv_text, "text/csv")},
        headers=headers,
    )


def _open_exception_id(loan_id: str, rule_name: str, headers: dict[str, str]) -> int:
    response = client.get("/exceptions", params={"page_size": 100}, headers=headers)
    assert response.status_code == 200
    matches = [
        item
        for item in response.json()["items"]
        if item["loan_id"] == loan_id and item["type"] == rule_name
    ]
    assert matches, f"expected an exception of type {rule_name} for {loan_id}, got {response.json()['items']}"
    return matches[0]["exception_id"]


def test_upload_without_token_is_rejected():
    response = _upload({}, _loan_tape_csv(loan_id="L-0H-NOAUTH"))
    assert response.status_code == 401


def test_full_lifecycle_edit_path_upload_to_verified_export():
    operator_headers = _authenticate("op-0h-edit", "data_operator")
    reviewer_headers = _authenticate("reviewer-0h-edit", "reviewer")
    loan_id = "L-0H-EDIT-FIX"

    # 1. Upload a loan that fails balance_gt_principal only (current_balance > original_principal).
    upload_response = _upload(operator_headers, _loan_tape_csv(loan_id=loan_id, current_balance="150000"))
    assert upload_response.status_code == 200, upload_response.text
    assert upload_response.json()["imported_rows"] == 1

    # 2. No test code called validate_loan/validate_loan_in_session -- the open exception
    #    must exist purely because the upload itself triggered validation.
    exception_id = _open_exception_id(loan_id, "balance_gt_principal", reviewer_headers)

    # 3. Verification is blocked while the exception is open.
    verify_blocked = client.post("/verified-loans", json={"loan_id": loan_id}, headers=reviewer_headers)
    assert verify_blocked.status_code == 200
    assert verify_blocked.json()["status"] == "ineligible"
    assert verify_blocked.json()["blocking_exception_count"] >= 1

    # 4. Reviewer fixes the field in one call; the same request's revalidation must
    #    resolve the exception atomically (proves the shared-session fix, not just that
    #    validation eventually runs).
    edit_response = client.post(
        f"/exceptions/{exception_id}/edit",
        json={"field": "current_balance", "value": 90000},
        headers=reviewer_headers,
    )
    assert edit_response.status_code == 200
    assert edit_response.json()["status"] == "updated"

    detail_response = client.get(f"/exceptions/{exception_id}", headers=reviewer_headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["exception"]["status"] == "resolved"

    # 6. Loan is now verifiable.
    verify_response = client.post("/verified-loans", json={"loan_id": loan_id}, headers=reviewer_headers)
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()
    assert verify_payload["status"] == "verified"
    assert verify_payload["record_hash"]

    # 8. Export uses the stored snapshot and never recomputes the hash.
    verified_record_id = verify_payload["verified_record_id"]
    export_response = client.post(f"/verified-loans/{verified_record_id}/export", headers=reviewer_headers)
    assert export_response.status_code == 200
    exported_payload = export_response.json()
    assert exported_payload["record_hash"] == verify_payload["record_hash"]

    detail_after_export = client.get(f"/verified-loans/{verified_record_id}", headers=reviewer_headers)
    assert detail_after_export.json()["exported"] is True
    assert detail_after_export.json()["record_hash"] == verify_payload["record_hash"]


def test_full_lifecycle_approve_path_missing_document_status():
    operator_headers = _authenticate("op-0h-approve", "data_operator")
    reviewer_headers = _authenticate("reviewer-0h-approve", "reviewer")
    loan_id = "L-0H-APPROVE"

    # 1. Upload a loan that fails missing_document_status only (empty document_status).
    upload_response = _upload(operator_headers, _loan_tape_csv(loan_id=loan_id, document_status=""))
    assert upload_response.status_code == 200, upload_response.text

    exception_id = _open_exception_id(loan_id, "missing_document_status", reviewer_headers)

    verify_blocked = client.post("/verified-loans", json={"loan_id": loan_id}, headers=reviewer_headers)
    assert verify_blocked.json()["status"] == "ineligible"

    # 5. This is a case that needs a human decision, not a data fix: reviewer approves it.
    approve_response = client.post(
        f"/exceptions/{exception_id}/approve",
        json={"comment": "Document on file with servicer, tracked outside this system."},
        headers=reviewer_headers,
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["exception_status"] == "resolved"

    verify_response = client.post("/verified-loans", json={"loan_id": loan_id}, headers=reviewer_headers)
    assert verify_response.json()["status"] == "verified"
    assert verify_response.json()["record_hash"]


def test_never_validated_loan_cannot_be_verified():
    reviewer_headers = _authenticate("reviewer-0h-unvalidated", "reviewer")
    loan_id = "L-0H-NEVER-VALIDATED"

    # 7. Bypass /upload entirely -- simulate a legacy row that was never validated.
    with SessionLocal() as db:
        db.add(
            Loan(
                loan_id=loan_id,
                borrower_id="B-0H-999",
                origination_date="2024-01-01",
                maturity_date="2030-01-01",
                original_principal=100000.0,
                current_balance=90000.0,
                term_months=60,
                payment_status="current",
                created_at="2024-01-01T00:00:00Z",
                updated_at="2024-01-01T00:00:00Z",
            )
        )
        db.commit()

    verify_response = client.post("/verified-loans", json={"loan_id": loan_id}, headers=reviewer_headers)
    assert verify_response.status_code == 200
    payload = verify_response.json()
    assert payload["status"] == "ineligible"
    assert payload["reason"] == "Loan has not been validated"
