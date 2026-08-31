"""7A / 7A.1 tests: the read-only AI evidence packet contract.

Reuses the fixtures and seeding helpers from test_verification_6a.py (schema setup,
per-test cleanup, _seed_loan, validate_loan usage) rather than duplicating them.
"""

import inspect

import pytest
import tests.test_verification_6a as base
from app.models.ai_recommendation import AIRecommendation
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.validation_result import ValidationResult
from app.models.verified_loan import VerifiedLoan
from app.services import ai_evidence_service
from app.services.ai_evidence_service import build_evidence_packet
from app.services.exception_service import ALLOWED_EDITABLE_FIELDS
from app.validators.engine import _get_rules_in_order, clear_rules, validate_loan
from app.validators.rules import register_default_rules


@pytest.fixture(scope="session", autouse=True)
def schema():
    base.create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def clean():
    clear_rules()
    base._clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        base._clear_database()


def _db_snapshot(loan_id: str) -> tuple:
    with base.SessionLocal() as db:
        loan = db.get(base.Loan, loan_id)
        return (
            loan.current_balance if loan else None,
            db.query(ValidationResult).filter_by(loan_id=loan_id).count(),
            db.query(ExceptionRecord).filter_by(loan_id=loan_id).count(),
            db.query(ReviewAction).filter_by(loan_id=loan_id).count(),
            db.query(AuditLog).count(),
            db.query(VerifiedLoan).count(),
            db.query(AIRecommendation).count(),
        )


def _add_source(loan_id: str, *, source_file: str, source_system: str, row_number: int, raw_data: dict, ingested_at: str = "2024-01-01T00:00:00Z") -> int:
    with base.SessionLocal() as db:
        row = LoanSource(
            loan_id=loan_id,
            source_file=source_file,
            source_system=source_system,
            source_row_number=row_number,
            raw_data=raw_data,
            ingested_at=ingested_at,
            import_status="success",
        )
        db.add(row)
        db.commit()
        return row.id


def _set_primary_source(loan_id: str, source_id: int) -> None:
    with base.SessionLocal() as db:
        loan = db.get(base.Loan, loan_id)
        loan.primary_source_id = source_id
        db.commit()


# ---------------------------------------------------------------------------
# 1. Field metadata contract covers every registered rule
# ---------------------------------------------------------------------------


def test_every_registered_rule_has_usable_field_metadata():
    registered_rule_names = {rule["name"] for rule in _get_rules_in_order()}
    assert registered_rule_names, "expected the default rule set to be registered"

    for rule_name in registered_rule_names:
        metadata = ai_evidence_service.RULE_METADATA.get(rule_name)
        assert metadata is not None, f"{rule_name} has no explicit RULE_METADATA entry"
        assert metadata["purpose"]
        assert metadata["failure_condition"]
        assert metadata["severity"] in {"critical", "high", "medium", "low"}
        assert metadata["relevant_fields"], f"{rule_name} must name at least one relevant field"
        for field in metadata["relevant_fields"]:
            assert field in base.Loan.__table__.columns, f"{rule_name} names non-existent field {field}"


def test_unregistered_rule_type_falls_back_to_generic_metadata_not_a_crash():
    loan_id = base._seed_loan(loan_id="L-7A-UNKNOWN-RULE")
    with base.SessionLocal() as db:
        exc = ExceptionRecord(loan_id=loan_id, type="not_a_real_rule", severity="low", status="open", created_at="now")
        db.add(exc)
        db.commit()
        exception_id = exc.id

    with base.SessionLocal() as db:
        packet = build_evidence_packet(db, exception_id)
    assert packet["rule_definition"]["rule_name"] == "not_a_real_rule"
    assert packet["loan"]["relevant_fields"] == []


# ---------------------------------------------------------------------------
# 2-4. Original vs latest validation semantics
# ---------------------------------------------------------------------------


def test_original_exception_linked_validation_result_is_preserved():
    loan_id = base._seed_loan(loan_id="L-7A-ORIGINAL", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        original_validation_result_id = exc.validation_result_id

    with base.SessionLocal() as db:
        packet = build_evidence_packet(db, exc.id)
    assert packet["validation"]["original"]["id"] == original_validation_result_id


def test_latest_validation_result_is_selected_when_it_differs_from_original():
    loan_id = base._seed_loan(loan_id="L-7A-LATEST", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        exception_id, original_id = exc.id, exc.validation_result_id

    base._set_loan_field(loan_id, current_balance=240000.0)
    validate_loan(loan_id)  # passes -> exception auto-resolves, but FK still points at first fail
    base._set_loan_field(loan_id, current_balance=350000.0)
    validate_loan(loan_id)  # fails again -> a NEW exception is created (existing 4D behavior)

    with base.SessionLocal() as db:
        latest_result = (
            db.query(ValidationResult)
            .filter_by(loan_id=loan_id, rule_name="balance_gt_principal")
            .order_by(ValidationResult.run_at.desc(), ValidationResult.id.desc())
            .first()
        )
        packet = build_evidence_packet(db, exception_id)

    assert packet["validation"]["original"]["id"] == original_id
    assert packet["validation"]["latest"]["id"] == latest_result.id
    assert packet["validation"]["original"]["id"] != packet["validation"]["latest"]["id"]
    assert len(packet["validation"]["history"]) == 3


def test_historical_validation_results_are_deterministically_ordered():
    loan_id = base._seed_loan(loan_id="L-7A-HISTORY", current_balance=300000.0)
    validate_loan(loan_id)
    base._set_loan_field(loan_id, current_balance=240000.0)
    validate_loan(loan_id)
    base._set_loan_field(loan_id, current_balance=310000.0)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").order_by(ExceptionRecord.id.desc()).first()
        packet_a = build_evidence_packet(db, exc.id)
        packet_b = build_evidence_packet(db, exc.id)

    run_ats = [entry["id"] for entry in packet_a["validation"]["history"]]
    assert run_ats == sorted(run_ats), "history must be ordered oldest-to-newest deterministically"
    assert packet_a["validation"]["history"] == packet_b["validation"]["history"]


# ---------------------------------------------------------------------------
# 5-8. Exception-specific evidence
# ---------------------------------------------------------------------------


def test_balance_exception_has_correct_canonical_and_source_field_evidence():
    loan_id = base._seed_loan(loan_id="L-7A-BALANCE", current_balance=300000.0, original_principal=250000.0)
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=1, raw_data={"current_balance": "300000", "original_principal": "250000"})
    _set_primary_source(loan_id, source_id)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    assert set(packet["loan"]["relevant_fields"]) == {"current_balance", "original_principal"}
    assert packet["field_evidence"]["current_balance"]["canonical_value"] == 300000.0
    assert packet["field_evidence"]["current_balance"]["primary_source"]["loan_source_id"] == source_id
    assert packet["field_evidence"]["current_balance"]["primary_source"]["value"] == "300000"
    assert packet["field_evidence"]["original_principal"]["canonical_value"] == 250000.0


def test_source_conflict_pinpoints_the_exact_conflicting_field_and_both_source_values():
    loan_id = base._seed_loan(loan_id="L-7A-CONFLICT", current_balance=90000.0)
    primary_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=1, raw_data={"current_balance": "90000"})
    _set_primary_source(loan_id, primary_id)
    secondary_id = _add_source(loan_id, source_file="servicer_update.csv", source_system="servicer_update", row_number=9, raw_data={"current_balance": "77777"}, ingested_at="2024-02-01T00:00:00Z")
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="source_conflict").one()
        packet = build_evidence_packet(db, exc.id)

    assert packet["loan"]["relevant_fields"] == ["current_balance"], "must narrow to the exact conflicting field"
    evidence = packet["field_evidence"]["current_balance"]
    assert evidence["canonical_value"] == 90000.0
    assert evidence["primary_source"]["loan_source_id"] == primary_id
    assert evidence["primary_source"]["value"] == "90000"
    assert evidence["primary_source"]["source_file"] == "loan_tape.csv"
    assert len(evidence["secondary_sources"]) == 1
    assert evidence["secondary_sources"][0]["loan_source_id"] == secondary_id
    assert evidence["secondary_sources"][0]["value"] == "77777"
    assert evidence["secondary_sources"][0]["source_file"] == "servicer_update.csv"
    # rule-level list still documents everything the rule *could* touch, separate from this instance
    assert "payment_status" in packet["rule_definition"]["relevant_fields"]


def test_missing_document_status_includes_relevant_document_evidence():
    loan_id = base._seed_loan(loan_id="L-7A-DOC", document_status=None)
    _add_source(loan_id, source_file="document_manifest.csv", source_system="document_manifest", row_number=1, raw_data={"loan_id": loan_id, "doc_status": "pending", "document_type": "credit_file"})
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="missing_document_status").one()
        packet = build_evidence_packet(db, exc.id)

    assert packet["loan"]["relevant_fields"] == ["document_status"]
    assert packet["field_evidence"]["document_status"]["canonical_value"] is None
    assert "doc_status" in packet["rule_definition"]["relevant_source_fields"]
    manifest_rows = [row for row in packet["source_evidence"] if row["source_system"] == "document_manifest"]
    assert manifest_rows
    assert manifest_rows[0]["raw_data"]["fields"].get("doc_status") == "pending"


def test_duplicate_borrower_amount_date_includes_affected_loan_records():
    loan_id_a = base._seed_loan(loan_id="L-7A-DUP-A", borrower_id="B-7A-DUP", original_principal=50000.0, current_balance=40000.0, origination_date="2024-01-01")
    loan_id_b = base._seed_loan(loan_id="L-7A-DUP-B", borrower_id="B-7A-DUP", original_principal=50000.0, current_balance=40000.0, origination_date="2024-01-01")
    validate_loan(loan_id_a)
    validate_loan(loan_id_b)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id_a, type="duplicate_borrower_amount_date").one()
        packet = build_evidence_packet(db, exc.id)

    related_ids = {item["loan_id"] for item in packet["related_entities"]}
    assert related_ids == {loan_id_a, loan_id_b}


# ---------------------------------------------------------------------------
# 9-11. Provenance, schema, and relationship context
# ---------------------------------------------------------------------------


def test_provenance_identifies_the_real_source_record_not_a_vague_label():
    loan_id = base._seed_loan(loan_id="L-7A-PROVENANCE", current_balance=300000.0)
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=4, raw_data={"current_balance": "300000"})
    _set_primary_source(loan_id, source_id)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    primary_source = packet["field_evidence"]["current_balance"]["primary_source"]
    assert primary_source["loan_source_id"] == source_id
    assert primary_source["source_file"] == "loan_tape.csv"
    assert primary_source["source_row_number"] == 4
    assert primary_source != "loan"


def test_provenance_is_none_not_fabricated_when_primary_source_lacks_the_field():
    loan_id = base._seed_loan(loan_id="L-7A-NOPROV", current_balance=300000.0)
    # Primary source row exists but does not actually carry current_balance.
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=1, raw_data={"borrower_id": "B-1"})
    _set_primary_source(loan_id, source_id)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    assert packet["field_evidence"]["current_balance"]["primary_source"] is None


def test_schema_metadata_matches_actual_canonical_field_definitions():
    loan_id = base._seed_loan(loan_id="L-7A-SCHEMA", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    by_field = {entry["field"]: entry for entry in packet["schema_context"]["fields"]}
    assert by_field["current_balance"]["type"] == str(base.Loan.__table__.columns["current_balance"].type)
    assert by_field["current_balance"]["nullable"] == base.Loan.__table__.columns["current_balance"].nullable
    assert by_field["current_balance"]["editable"] is True
    assert by_field["original_principal"]["required"] is True


def test_relevant_relationships_are_represented_correctly():
    loan_id = base._seed_loan(loan_id="L-7A-RELS", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    relationships = {entry["relationship"]: entry for entry in packet["schema_context"]["relationships"]}
    assert relationships["Loan.sources"]["foreign_key_field"] == "loan_sources.loan_id"
    assert relationships["Loan.validations"]["foreign_key_field"] == "validation_results.loan_id"
    assert relationships["Loan.exceptions"]["foreign_key_field"] == "exceptions.loan_id"
    assert relationships["Loan.review_actions"]["foreign_key_field"] == "review_actions.loan_id"


# ---------------------------------------------------------------------------
# 12-13. Bounded raw source evidence
# ---------------------------------------------------------------------------


def _source_entry(packet: dict, source_id: int) -> dict:
    matches = [entry for entry in packet["source_evidence"] if entry["source_id"] == source_id]
    assert matches, f"expected source_id {source_id} in source_evidence"
    return matches[0]


def test_raw_source_evidence_is_bounded_and_does_not_exceed_the_limit():
    loan_id = base._seed_loan(loan_id="L-7A-BOUNDED", current_balance=300000.0)
    oversized_raw_data = {f"noise_field_{i}": f"value_{i}" for i in range(ai_evidence_service.MAX_RAW_SOURCE_FIELDS + 10)}
    oversized_raw_data["current_balance"] = "300000"
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=2, raw_data=oversized_raw_data)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    raw = _source_entry(packet, source_id)["raw_data"]
    assert raw["included_field_count"] <= ai_evidence_service.MAX_RAW_SOURCE_FIELDS
    assert len(raw["fields"]) <= ai_evidence_service.MAX_RAW_SOURCE_FIELDS
    # the relevant field must survive truncation even though it wasn't inserted first
    assert raw["fields"].get("current_balance") == "300000"


def test_truncation_is_explicit_and_source_identifiers_are_never_dropped():
    loan_id = base._seed_loan(loan_id="L-7A-TRUNC", current_balance=300000.0)
    oversized_raw_data = {f"noise_field_{i}": f"value_{i}" for i in range(ai_evidence_service.MAX_RAW_SOURCE_FIELDS + 10)}
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=3, raw_data=oversized_raw_data)
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    entry = _source_entry(packet, source_id)
    assert entry["source_id"] == source_id
    assert entry["source_file"] == "loan_tape.csv"
    assert entry["source_row_number"] == 3
    raw = entry["raw_data"]
    assert raw["truncated"] is True
    assert raw["omitted_field_count"] == raw["total_field_count"] - raw["included_field_count"]
    assert raw["omitted_field_count"] > 0


def test_long_raw_string_values_are_truncated_with_an_explicit_marker():
    loan_id = base._seed_loan(loan_id="L-7A-LONGVAL", current_balance=300000.0)
    long_value = "x" * (ai_evidence_service.MAX_RAW_VALUE_LENGTH + 100)
    source_id = _add_source(loan_id, source_file="loan_tape.csv", source_system="loan_tape", row_number=2, raw_data={"notes": long_value, "current_balance": "300000"})
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    stored_value = _source_entry(packet, source_id)["raw_data"]["fields"]["notes"]
    assert len(stored_value) < len(long_value)
    assert stored_value.endswith("...[value truncated]")


# ---------------------------------------------------------------------------
# 14-15. Review history and editable fields
# ---------------------------------------------------------------------------


def test_review_history_is_relevant_and_deterministic():
    loan_id = base._seed_loan(loan_id="L-7A-REVIEW", current_balance=300000.0, borrower_state="ZZ")
    validate_loan(loan_id)

    with base.SessionLocal() as db:
        balance_exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        state_exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="invalid_state_code").one()
        db.add(ReviewAction(exception_id=balance_exc.id, loan_id=loan_id, reviewer_id=1, action_type="comment", comment_text="first", created_at="2024-01-01T00:00:00Z"))
        db.add(ReviewAction(exception_id=balance_exc.id, loan_id=loan_id, reviewer_id=1, action_type="comment", comment_text="second", created_at="2024-01-02T00:00:00Z"))
        db.add(ReviewAction(exception_id=state_exc.id, loan_id=loan_id, reviewer_id=1, action_type="comment", comment_text="unrelated to balance exception", created_at="2024-01-03T00:00:00Z"))
        db.commit()
        balance_exc_id = balance_exc.id

    with base.SessionLocal() as db:
        packet = build_evidence_packet(db, balance_exc_id)

    comments = [action["comment_text"] for action in packet["review_history"]]
    assert comments == ["first", "second"], "must be scoped to this exception and ordered oldest-first"


def test_editable_fields_come_from_the_existing_reviewer_allowlist():
    loan_id = base._seed_loan(loan_id="L-7A-EDITABLE", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet = build_evidence_packet(db, exc.id)

    assert set(packet["allowed_actions"]["editable_fields"]).issubset(ALLOWED_EDITABLE_FIELDS)
    assert "current_balance" in packet["allowed_actions"]["editable_fields"]
    assert packet["allowed_actions"]["full_reviewer_editable_allowlist"] == sorted(ALLOWED_EDITABLE_FIELDS)


# ---------------------------------------------------------------------------
# 16-18. Determinism, no mutation, no AI/LLM interaction
# ---------------------------------------------------------------------------


def test_packet_is_deterministic_for_identical_database_state():
    loan_id = base._seed_loan(loan_id="L-7A-DETERMINISM", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        packet_a = build_evidence_packet(db, exc.id)
        packet_b = build_evidence_packet(db, exc.id)
    assert packet_a == packet_b


def test_evidence_builder_does_not_mutate_the_database():
    loan_id = base._seed_loan(loan_id="L-7A-NOMUTATE", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        exception_id, status_before = exc.id, exc.status

    before = _db_snapshot(loan_id)
    with base.SessionLocal() as db:
        build_evidence_packet(db, exception_id)
        build_evidence_packet(db, exception_id)
    after = _db_snapshot(loan_id)

    assert before == after
    with base.SessionLocal() as db:
        assert db.get(ExceptionRecord, exception_id).status == status_before


def test_evidence_builder_never_calls_an_llm_or_creates_ai_records():
    source = inspect.getsource(ai_evidence_service)
    assert "openai" not in source.lower()
    assert "groq" not in source.lower()

    loan_id = base._seed_loan(loan_id="L-7A-NOLLM", current_balance=300000.0)
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="balance_gt_principal").one()
        exception_id = exc.id
        assert db.query(AIRecommendation).count() == 0
        build_evidence_packet(db, exception_id)
        assert db.query(AIRecommendation).count() == 0


def test_missing_exception_is_not_found():
    with base.SessionLocal() as db:
        with pytest.raises(LookupError):
            build_evidence_packet(db, 999999)
