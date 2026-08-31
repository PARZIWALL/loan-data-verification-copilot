import json
import re

import pytest

import tests.test_verification_6a as verification_6a
from app.core.database import create_db_and_tables
from app.models.audit import AuditLog
from app.models.verified_loan import VerifiedLoan
from app.services.verification_service import compute_verified_record_hash
from app.validators.engine import clear_rules
from app.validators.rules import register_default_rules


@pytest.fixture(scope="session", autouse=True)
def ensure_hash_schema():
    create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def reset_hash_state():
    clear_rules()
    verification_6a._clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        verification_6a._clear_database()


def _hash_components() -> tuple[dict, dict, dict]:
    return (
        {"loan_id": "L-6B-001", "current_balance": 240000.0, "flags": [True, None]},
        {"primary_source_file": "loan_tape.csv", "source_row_number": 1},
        {"total_results": 3, "passed": 3, "failed": 0, "rule_statuses": {"required_fields": "pass"}},
    )


def _verify_loan(loan_id: str, username: str = "reviewer_6b"):
    token = verification_6a._authenticate(username)
    return verification_6a.client.post(
        "/verified-loans",
        headers={"Authorization": f"Bearer {token}"},
        json={"loan_id": loan_id},
    )


def test_verified_record_receives_persisted_sha256_hash():
    loan_id = verification_6a._seed_loan(loan_id="L-6B-HASH-001")
    verification_6a.validate_loan(loan_id)

    response = _verify_loan(loan_id)

    assert response.status_code == 200
    record_hash = response.json()["record_hash"]
    assert re.fullmatch(r"[0-9a-f]{64}", record_hash)
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, response.json()["verified_record_id"])
        assert record.record_hash == record_hash


def test_same_logical_snapshot_has_same_hash():
    final_data, source_reference, summary = _hash_components()

    assert compute_verified_record_hash(final_data, source_reference, summary) == compute_verified_record_hash(
        dict(final_data), dict(source_reference), dict(summary)
    )


def test_dictionary_key_order_does_not_change_hash():
    first = compute_verified_record_hash(
        {"b": {"z": 2, "a": 1}, "a": [2, 1]},
        {"row": 1, "file": "loan.csv"},
        {"failed": 0, "passed": 2},
    )
    second = compute_verified_record_hash(
        {"a": [2, 1], "b": {"a": 1, "z": 2}},
        {"file": "loan.csv", "row": 1},
        {"passed": 2, "failed": 0},
    )

    assert first == second


def test_json_whitespace_does_not_change_hash():
    compact = json.loads('{"loan_id":"L-6B-WS","balance":10}')
    spaced = json.loads('{  "loan_id" : "L-6B-WS",  "balance" : 10 }')

    assert compute_verified_record_hash(compact, {}, {}) == compute_verified_record_hash(spaced, {}, {})


def test_changing_final_data_changes_hash():
    final_data, source_reference, summary = _hash_components()
    changed_final_data = {**final_data, "current_balance": 239999.0}

    assert compute_verified_record_hash(final_data, source_reference, summary) != compute_verified_record_hash(
        changed_final_data, source_reference, summary
    )


def test_changing_source_reference_changes_hash():
    final_data, source_reference, summary = _hash_components()
    changed_source_reference = {**source_reference, "source_row_number": 2}

    assert compute_verified_record_hash(final_data, source_reference, summary) != compute_verified_record_hash(
        final_data, changed_source_reference, summary
    )


def test_changing_validation_summary_changes_hash():
    final_data, source_reference, summary = _hash_components()
    changed_summary = {**summary, "failed": 1}

    assert compute_verified_record_hash(final_data, source_reference, summary) != compute_verified_record_hash(
        final_data, source_reference, changed_summary
    )


def test_excluded_verified_record_metadata_does_not_change_hash():
    final_data, source_reference, summary = _hash_components()
    first_record = VerifiedLoan(
        final_data=final_data,
        source_reference=source_reference,
        validation_result_summary=summary,
        verified_by="reviewer_one",
        verification_timestamp="2026-08-30T12:00:00Z",
        exported=False,
    )
    second_record = VerifiedLoan(
        final_data=final_data,
        source_reference=source_reference,
        validation_result_summary=summary,
        verified_by="reviewer_two",
        verification_timestamp="2026-08-31T12:00:00Z",
        exported=True,
    )

    assert compute_verified_record_hash(
        first_record.final_data, first_record.source_reference, first_record.validation_result_summary
    ) == compute_verified_record_hash(
        second_record.final_data, second_record.source_reference, second_record.validation_result_summary
    )


def test_verification_creates_exactly_one_hashed_record_and_preserves_duplicate_behavior():
    loan_id = verification_6a._seed_loan(loan_id="L-6B-DUPLICATE-001")
    verification_6a.validate_loan(loan_id)

    first = _verify_loan(loan_id, "reviewer_6b_duplicate")
    second = _verify_loan(loan_id, "reviewer_6b_duplicate")

    assert first.status_code == 200
    assert second.status_code == 409
    with verification_6a.SessionLocal() as db:
        assert db.query(VerifiedLoan).filter_by(loan_id=loan_id).count() == 1
        assert (
            db.query(AuditLog)
            .filter_by(loan_id=loan_id, event_type="verified_record_created")
            .count()
            == 1
        )


def test_ineligible_verification_creates_no_record_or_audit_event():
    loan_id = verification_6a._seed_loan(loan_id="L-6B-INELIGIBLE-001")
    verification_6a._create_exception_for_loan(loan_id, status="rejected", current_balance=300000.0)

    response = _verify_loan(loan_id, "reviewer_6b_ineligible")

    assert response.status_code == 200
    assert response.json()["status"] == "ineligible"
    with verification_6a.SessionLocal() as db:
        assert db.query(VerifiedLoan).filter_by(loan_id=loan_id).count() == 0
        assert (
            db.query(AuditLog)
            .filter_by(loan_id=loan_id, event_type="verified_record_created")
            .count()
            == 0
        )


def test_hashing_does_not_change_snapshot_immutability():
    loan_id = verification_6a._seed_loan(loan_id="L-6B-IMMUTABLE-001")
    verification_6a.validate_loan(loan_id)

    response = _verify_loan(loan_id, "reviewer_6b_immutable")
    record_id = response.json()["verified_record_id"]
    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        original_balance = record.final_data["current_balance"]
        original_hash = record.record_hash

    verification_6a._set_loan_field(loan_id, current_balance=1.0)

    with verification_6a.SessionLocal() as db:
        record = db.get(VerifiedLoan, record_id)
        assert record.final_data["current_balance"] == original_balance
        assert record.record_hash == original_hash


def test_unsupported_hash_input_fails_clearly():
    with pytest.raises(TypeError, match="Unsupported verified record hash input type"):
        compute_verified_record_hash({"unsupported": {1, 2}}, {}, {})
