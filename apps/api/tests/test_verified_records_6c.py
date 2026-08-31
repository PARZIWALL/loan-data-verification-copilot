import pytest

import tests.test_verification_6a as verification_6a
from app.core.database import create_db_and_tables
from app.models.audit import AuditLog
from app.models.verified_loan import VerifiedLoan
from app.validators.engine import clear_rules
from app.validators.rules import register_default_rules


@pytest.fixture(scope="session", autouse=True)
def schema():
    create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def clean_state():
    clear_rules(); verification_6a._clear_database(); register_default_rules()
    try:
        yield
    finally:
        clear_rules(); verification_6a._clear_database()


def _token(username: str, role: str = "reviewer") -> str:
    return verification_6a._authenticate(username, role)


def _create_verified(loan_id: str, username: str = "reviewer_6c") -> int:
    verification_6a._seed_loan(loan_id=loan_id, borrower_id=f"B-{loan_id}")
    verification_6a.validate_loan(loan_id)
    response = verification_6a.client.post("/verified-loans", headers={"Authorization": f"Bearer {_token(username)}"}, json={"loan_id": loan_id})
    assert response.status_code == 200
    assert response.json()["status"] == "verified", response.json()
    return response.json()["verified_record_id"]


def test_list_pagination_and_deterministic_order():
    first = _create_verified("L-6C-LIST-001", "reviewer_6c_1")
    second = _create_verified("L-6C-LIST-002", "reviewer_6c_2")
    response = verification_6a.client.get("/verified-loans?page=1&page_size=1", headers={"Authorization": f"Bearer {_token('consumer_6c', 'data_consumer')}"})
    assert response.status_code == 200
    body = response.json()
    assert (body["page"], body["page_size"], body["total"], body["total_pages"]) == (1, 1, 2, 2)
    assert body["items"][0]["verified_loan_id"] == second
    assert first != second


def test_detail_returns_stored_snapshot_and_not_current_loan():
    record_id = _create_verified("L-6C-SNAPSHOT-001")
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        expected = {key: getattr(record, key) for key in ("final_data", "source_reference", "validation_result_summary", "record_hash")}
    verification_6a._set_loan_field("L-6C-SNAPSHOT-001", current_balance=1.0)
    response = verification_6a.client.get(f"/verified-loans/{record_id}", headers={"Authorization": f"Bearer {_token('reader_6c')}"})
    assert response.status_code == 200
    assert {key: response.json()[key] for key in expected} == expected


def test_read_auth_and_not_found():
    assert verification_6a.client.get("/verified-loans").status_code == 401
    response = verification_6a.client.get("/verified-loans/99999", headers={"Authorization": f"Bearer {_token('reader_6c_404')}"})
    assert response.status_code == 404
    assert verification_6a.client.get("/verified-loans?page=0", headers={"Authorization": f"Bearer {_token('reader_6c_page')}"}).status_code == 422


def test_export_returns_downloadable_stored_snapshot_and_records_audit():
    record_id = _create_verified("L-6C-EXPORT-001")
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        before = {key: getattr(record, key) for key in ("final_data", "source_reference", "validation_result_summary", "reviewer_decision", "verified_by", "verification_timestamp", "record_hash")}
    verification_6a._set_loan_field("L-6C-EXPORT-001", current_balance=1.0)
    response = verification_6a.client.post(f"/verified-loans/{record_id}/export", headers={"Authorization": f"Bearer {_token('consumer_export_6c', 'data_consumer')}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert {key: response.json()[key] for key in before if key != "reviewer_decision"} == {key: before[key] for key in before if key != "reviewer_decision"}
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.exported is True and record.exported_at
        assert {key: getattr(record, key) for key in before} == before
        assert db.query(AuditLog).filter_by(event_type="verified_record_exported", loan_id=record.loan_id).count() == 1


def test_reexport_preserves_snapshot_and_creates_an_audit_per_export():
    record_id = _create_verified("L-6C-REEXPORT-001")
    headers = {"Authorization": f"Bearer {_token('consumer_reexport_6c', 'data_consumer')}"}
    first = verification_6a.client.post(f"/verified-loans/{record_id}/export", headers=headers)
    second = verification_6a.client.post(f"/verified-loans/{record_id}/export", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert db.query(VerifiedLoan).filter_by(loan_id=record.loan_id).count() == 1
        assert db.query(AuditLog).filter_by(event_type="verified_record_exported", loan_id=record.loan_id).count() == 2


def test_export_authorization_and_missing_record():
    record_id = _create_verified("L-6C-AUTH-001")
    assert verification_6a.client.post(f"/verified-loans/{record_id}/export").status_code == 401
    operator = {"Authorization": f"Bearer {_token('operator_6c', 'data_operator')}"}
    assert verification_6a.client.post(f"/verified-loans/{record_id}/export", headers=operator).status_code == 403
    reviewer = {"Authorization": f"Bearer {_token('reviewer_missing_6c')}"}
    assert verification_6a.client.post("/verified-loans/99999/export", headers=reviewer).status_code == 404
