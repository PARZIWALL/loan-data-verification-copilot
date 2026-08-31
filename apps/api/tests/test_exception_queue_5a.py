from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.seed import hash_password, seed_users
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.models.user import User
from app.models.validation_result import ValidationResult
from app.main import app
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


client = TestClient(app)


VALID_LOAN = {
    "loan_id": "L-5A-001",
    "borrower_id": "B-5A-001",
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


def _seed_user(username: str, role: str = "reviewer") -> str:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            user = User(username=username, password_hash=hash_password("reviewer_dev"), role=role)
            db.add(user)
            db.commit()
        return user.username


def _authenticate(username: str = "reviewer") -> str:
    _seed_user(username)
    response = client.post("/auth/login", json={"username": username, "password": "reviewer_dev"})
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


def test_authenticated_user_can_list_exceptions():
    loan_id = _seed_loan()
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 1
    assert payload["items"]


def test_exceptions_list_returns_exception_data():
    loan_id = _seed_loan(loan_id="L-5A-EXC-001")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions", headers={"Authorization": f"Bearer {token}"})
    item = next(item for item in response.json()["items"] if item["loan_id"] == loan_id)
    assert item["exception_id"]
    assert item["type"] == "interest_rate_range"
    assert item["severity"] == "high"
    assert item["status"] == "open"
    assert item["loan_id"] == loan_id
    assert item["message"]


def test_filter_by_severity_works():
    loan_id = _seed_loan(loan_id="L-5A-SEV-001")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions?severity=high", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert all(item["severity"] == "high" for item in response.json()["items"])


def test_filter_by_type_works():
    loan_id = _seed_loan(loan_id="L-5A-TYPE-001")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions?type=interest_rate_range", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert all(item["type"] == "interest_rate_range" for item in response.json()["items"])


def test_filter_by_status_works():
    loan_id = _seed_loan(loan_id="L-5A-STATUS-001")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions?status=open", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert all(item["status"] == "open" for item in response.json()["items"])


def test_search_by_loan_id_works():
    loan_id = _seed_loan(loan_id="L-5A-SEARCH-LOAN")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions?search=L-5A-SEARCH", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert any(item["loan_id"] == loan_id for item in response.json()["items"])


def test_search_by_borrower_id_works():
    loan_id = _seed_loan(loan_id="L-5A-SEARCH-BORROWER", borrower_id="B-SEARCH-USER")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get("/exceptions?search=B-SEARCH", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert any(item["loan_id"] == loan_id for item in response.json()["items"])


def test_combined_filters_work():
    loan_id = _seed_loan(loan_id="L-5A-MIXED-001", borrower_id="B-MIXED-01")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    response = client.get(
        "/exceptions?type=interest_rate_range&severity=high&status=open&search=B-MIXED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    final_items = response.json()["items"]
    assert final_items
    assert all(item["type"] == "interest_rate_range" for item in final_items)
    assert all(item["severity"] == "high" for item in final_items)
    assert all(item["status"] == "open" for item in final_items)
    assert any(item["loan_id"] == loan_id for item in final_items)


def test_pagination_works():
    token = _authenticate()
    for index in range(5):
        loan_id = _seed_loan(loan_id=f"L-5A-PAGE-{index}", borrower_id=f"B-PAGE-{index}")
        _set_loan_field(loan_id, interest_rate=1.5)
        validate_loan(loan_id)

    response = client.get("/exceptions?page=1&page_size=2", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total"] >= 5
    assert payload["total_pages"] >= 1
    assert len(payload["items"]) == 2


def test_results_have_deterministic_ordering():
    token = _authenticate()
    response = client.get("/exceptions?page=1&page_size=10", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    items = response.json()["items"]
    severities = [item["severity"] for item in items]
    assert severities == sorted(severities, key=lambda level: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(level, 99))


def test_empty_search_result_returns_valid_empty_response():
    token = _authenticate()
    response = client.get("/exceptions?search=NO_SUCH_LOAN_ABCDEF", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0
    assert payload["total_pages"] == 0


def test_exception_detail_returns_exception_validation_loan_and_sources():
    loan_id = _seed_loan(loan_id="L-5A-DETAIL-001")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    with SessionLocal() as db:
        exception = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="interest_rate_range").one()
        exception_id = exception.id

    token = _authenticate()
    response = client.get(f"/exceptions/{exception_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["exception"]["loan_id"] == loan_id
    assert payload["validation_result"]["rule_name"] == "interest_rate_range"
    assert payload["canonical_loan"]["loan_id"] == loan_id
    assert payload["source_evidence"]
    assert payload["historical_validation_results"]


def test_exception_detail_404_for_missing_exception():
    token = _authenticate()
    response = client.get("/exceptions/999999", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_get_loan_detail_returns_canonical_and_related_records():
    loan_id = _seed_loan(loan_id="L-5A-LOAN-DETAIL")
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    with SessionLocal() as db:
        db.add(LoanSource(loan_id=loan_id, source_file="review.csv", source_system="reviewer", source_row_number=3, raw_data={"borrower_id": "B-5A-LOAN-DETAIL"}, import_status="success"))
        db.commit()

    token = _authenticate()
    response = client.get(f"/loans/{loan_id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["loan_id"] == loan_id
    assert payload["validation_results"]
    assert payload["source_records"]
    assert payload["exceptions"]


def test_get_loan_detail_404_for_missing_loan():
    token = _authenticate()
    response = client.get("/loans/NO_SUCH_LOAN", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404


def test_unauthenticated_access_is_rejected():
    response = client.get("/exceptions")
    assert response.status_code == 401


def test_endpoints_perform_no_mutations():
    loan_id = _seed_loan(loan_id="L-5A-MUTATION-001")
    original_balance = 240000.0
    _set_loan_field(loan_id, interest_rate=1.5)
    validate_loan(loan_id)

    token = _authenticate()
    before = client.get(f"/loans/{loan_id}", headers={"Authorization": f"Bearer {token}"})
    response = client.get(f"/exceptions/{next(item['exception_id'] for item in client.get('/exceptions', headers={'Authorization': f'Bearer {token}'}).json()['items'] if item['loan_id'] == loan_id)}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    after = client.get(f"/loans/{loan_id}", headers={"Authorization": f"Bearer {token}"})
    assert before.json()["current_balance"] == after.json()["current_balance"] == original_balance
