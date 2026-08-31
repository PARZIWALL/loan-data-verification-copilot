import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_validation_rules_4b.db")

import pytest
from sqlalchemy.orm import close_all_sessions

from app.core.database import Base, SessionLocal, engine
from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules


VALID_RAW_LOAN = {
    "loan_id": "L-4B-001",
    "borrower_id": "B-4B-001",
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
    "last_updated_at": (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "document_status": "complete",
}


@pytest.fixture(scope="session", autouse=True)
def ensure_validation_schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def reset_rule_test_state():
    clear_rules()
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal.configure(bind=connection)
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        close_all_sessions()
        transaction.rollback()
        SessionLocal.configure(bind=engine)
        connection.close()


def _seed_loan(**overrides):
    loan_data = {**VALID_RAW_LOAN, **overrides}
    with SessionLocal() as db:
        loan = Loan(**loan_data)
        db.add(loan)
        db.commit()
        return loan.loan_id


def _rule_status(loan_id: str, rule_name: str) -> str:
    results = validate_loan(loan_id)
    status_map = {result["rule_name"]: result["status"] for result in results}
    return status_map.get(rule_name, "missing")


def test_default_rules_register_in_expected_order():
    loan_id = _seed_loan()
    results = validate_loan(loan_id)
    rule_names = [result["rule_name"] for result in results]
    expected_order = [
        "required_fields",
        "negative_original_principal",
        "negative_current_balance",
        "balance_gt_principal",
        "interest_rate_range",
        "valid_dates",
        "maturity_after_origination",
        "stale_record",
        "duplicate_loan_id",
        "duplicate_borrower_amount_date",
        "suspicious_repeated_borrower",
        "valid_payment_status",
        "payment_status_dpd_consistency",
        "closed_positive_balance",
        "missing_document_status",
        "invalid_state_code",
        "source_conflict",
    ]
    assert rule_names == expected_order
    assert all(result["status"] == "pass" for result in results)


@pytest.mark.parametrize(
    ("rule_name", "modifier", "expected_status"),
    [
        ("required_fields", lambda loan: setattr(loan, "borrower_id", None), "fail"),
        ("negative_original_principal", lambda loan: setattr(loan, "original_principal", -10.0), "fail"),
        ("negative_current_balance", lambda loan: setattr(loan, "current_balance", -5.0), "fail"),
        ("balance_gt_principal", lambda loan: setattr(loan, "current_balance", 260000.0), "fail"),
        ("interest_rate_range", lambda loan: setattr(loan, "interest_rate", 1.5), "fail"),
        ("valid_dates", lambda loan: setattr(loan, "origination_date", "bad-date"), "fail"),
        ("maturity_after_origination", lambda loan: setattr(loan, "maturity_date", "2024-01-10"), "fail"),
        ("stale_record", lambda loan: setattr(loan, "last_updated_at", "2020-01-01"), "fail"),
        ("valid_payment_status", lambda loan: setattr(loan, "payment_status", "weird_status"), "fail"),
        ("payment_status_dpd_consistency", lambda loan: setattr(loan, "days_past_due", 14), "fail"),
        ("closed_positive_balance", lambda loan: setattr(loan, "payment_status", "paid_off"), "fail"),
        ("missing_document_status", lambda loan: setattr(loan, "document_status", None), "fail"),
        ("invalid_state_code", lambda loan: setattr(loan, "borrower_state", "ZZ"), "fail"),
    ],
)
def test_business_rule_failure_cases(rule_name, modifier, expected_status):
    loan_id = _seed_loan()
    with SessionLocal() as db:
        loan = db.get(Loan, loan_id)
        modifier(loan)
        db.commit()

    assert _rule_status(loan_id, rule_name) == expected_status


def test_duplicate_loan_id_rule_fails_for_repeated_source_rows():
    loan_id = _seed_loan()
    with SessionLocal() as db:
        db.add_all(
            [
                LoanSource(loan_id=loan_id, source_file="loan_tape.csv", source_system="loan_tape", raw_data={}),
                LoanSource(loan_id=loan_id, source_file="loan_tape.csv", source_system="loan_tape", raw_data={}),
            ]
        )
        db.commit()

    assert _rule_status(loan_id, "duplicate_loan_id") == "fail"


def test_duplicate_loan_id_rule_passes_for_legitimate_multi_source_lineage():
    """The same loan across loan_tape, servicer_update and document_manifest is normal.

    Combining complementary sources for one loan is the product's purpose. Counting
    source rows across files made every such loan a critical duplicate, which buried
    the real exceptions under false positives.
    """
    loan_id = _seed_loan()
    with SessionLocal() as db:
        db.add_all(
            [
                LoanSource(loan_id=loan_id, source_file="loan_tape.csv", source_system="loan_tape", raw_data={}),
                LoanSource(loan_id=loan_id, source_file="servicer_update.csv", source_system="servicer_update", raw_data={}),
                LoanSource(loan_id=loan_id, source_file="document_manifest.csv", source_system="document_manifest", raw_data={}),
            ]
        )
        db.commit()

    assert _rule_status(loan_id, "duplicate_loan_id") == "pass"


def test_duplicate_loan_id_rule_passes_for_repeated_rows_in_a_supporting_file():
    """A document manifest carries one row per document, so repeats are its normal shape."""
    loan_id = _seed_loan()
    with SessionLocal() as db:
        db.add_all(
            [
                LoanSource(loan_id=loan_id, source_file="document_manifest.csv", source_system="document_manifest", raw_data={"document_type": "credit_file"}),
                LoanSource(loan_id=loan_id, source_file="document_manifest.csv", source_system="document_manifest", raw_data={"document_type": "appraisal"}),
            ]
        )
        db.commit()

    assert _rule_status(loan_id, "duplicate_loan_id") == "pass"


def test_duplicate_borrower_amount_date_rule_fails_for_duplicate_loan():
    loan_id = _seed_loan()
    with SessionLocal() as db:
        db.add(
            Loan(
                loan_id="L-4B-duplicate",
                borrower_id=VALID_RAW_LOAN["borrower_id"],
                origination_date=VALID_RAW_LOAN["origination_date"],
                original_principal=VALID_RAW_LOAN["original_principal"],
                current_balance=VALID_RAW_LOAN["current_balance"],
                interest_rate=VALID_RAW_LOAN["interest_rate"],
                term_months=VALID_RAW_LOAN["term_months"],
                payment_status=VALID_RAW_LOAN["payment_status"],
                borrower_state=VALID_RAW_LOAN["borrower_state"],
                document_status=VALID_RAW_LOAN["document_status"],
                last_updated_at=VALID_RAW_LOAN["last_updated_at"],
            )
        )
        db.commit()

    assert _rule_status(loan_id, "duplicate_borrower_amount_date") == "fail"


def test_suspicious_repeated_borrower_rule_fails_beyond_threshold():
    borrower_id = "B-REPEAT-FAST"
    primary_loan_id = _seed_loan(borrower_id=borrower_id, loan_id="L-4B-001")
    with SessionLocal() as db:
        for index in range(6):
            db.add(
                Loan(
                    loan_id=f"L-4B-repeat-{index}",
                    borrower_id=borrower_id,
                    origination_date=VALID_RAW_LOAN["origination_date"],
                    original_principal=VALID_RAW_LOAN["original_principal"],
                    current_balance=VALID_RAW_LOAN["current_balance"],
                    interest_rate=VALID_RAW_LOAN["interest_rate"],
                    term_months=VALID_RAW_LOAN["term_months"],
                    payment_status=VALID_RAW_LOAN["payment_status"],
                    borrower_state=VALID_RAW_LOAN["borrower_state"],
                    document_status=VALID_RAW_LOAN["document_status"],
                    last_updated_at=VALID_RAW_LOAN["last_updated_at"],
                )
            )
        db.commit()

    assert _rule_status(primary_loan_id, "suspicious_repeated_borrower") == "fail"


def test_source_conflict_rule_fails_when_servicer_update_disagrees():
    loan_id = _seed_loan()
    with SessionLocal() as db:
        db.add(
            LoanSource(
                loan_id=loan_id,
                source_file="servicer_update.csv",
                source_system="servicer_update",
                raw_data={"borrower_id": "B-OTHER", "current_balance": 230000.0},
            )
        )
        db.commit()

    assert _rule_status(loan_id, "source_conflict") == "fail"


def test_all_business_rules_pass_for_clean_loan():
    loan_id = _seed_loan()
    results = validate_loan(loan_id)
    status_by_rule = {result["rule_name"]: result["status"] for result in results}
    assert all(status == "pass" for status in status_by_rule.values())
