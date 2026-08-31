"""Business validation rules for canonical loan checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.loan import Loan
from app.models.loan_source import LoanSource
from app.validators.engine import register_rule

# loan_tape.csv is the primary system of record; servicer_update and
# document_manifest are supporting evidence layered on top of it.
PRIMARY_SOURCE_SYSTEM = "loan_tape"

REQUIRED_LOAN_FIELDS = [
    "loan_id",
    "borrower_id",
    "origination_date",
    "original_principal",
    "current_balance",
    "term_months",
    "payment_status",
]

INTEREST_RATE_MINIMUM = 0.0
INTEREST_RATE_MAXIMUM = 1.0
STALE_RECORD_FRESHNESS_DAYS = 365
MAX_BORROWER_OCCURRENCES = 5
VALID_PAYMENT_STATUSES = {
    "current",
    "performing",
    "on_time",
    "paid",
    "closed",
    "paid_off",
    "paid-off",
    "delinquent",
    "late",
    "default",
    "prepaid",
}
VALID_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
}


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return text
    return value


def _parse_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rule_result(context: dict[str, Any], *, rule_name: str, status: str, severity: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "rule_name": rule_name,
        "status": status,
        "severity": severity,
        "message": message,
        "details": details or {},
        "loan_id": context["loan"].loan_id,
        "run_at": context["run_at"],
    }


def required_fields(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    missing = [field for field in REQUIRED_LOAN_FIELDS if getattr(loan, field, None) in (None, "")]
    if missing:
        return _rule_result(
            context,
            rule_name="required_fields",
            status="fail",
            severity="high",
            message="One or more required loan fields are missing.",
            details={"missing_fields": missing},
        )
    return _rule_result(
        context,
        rule_name="required_fields",
        status="pass",
        severity="low",
        message="All required canonical fields are present.",
        details={"missing_fields": []},
    )


def negative_original_principal(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    value = getattr(loan, "original_principal", None)
    if value is None:
        return _rule_result(context, rule_name="negative_original_principal", status="pass", severity="low", message="No original principal value to validate.", details={"original_principal": None})
    if float(value) < 0:
        return _rule_result(context, rule_name="negative_original_principal", status="fail", severity="high", message="original_principal is negative.", details={"original_principal": value})
    return _rule_result(context, rule_name="negative_original_principal", status="pass", severity="low", message="original_principal is not negative.", details={"original_principal": value})


def negative_current_balance(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    value = getattr(loan, "current_balance", None)
    if value is None:
        return _rule_result(context, rule_name="negative_current_balance", status="pass", severity="low", message="No current balance value to validate.", details={"current_balance": None})
    if float(value) < 0:
        return _rule_result(context, rule_name="negative_current_balance", status="fail", severity="high", message="current_balance is negative.", details={"current_balance": value})
    return _rule_result(context, rule_name="negative_current_balance", status="pass", severity="low", message="current_balance is not negative.", details={"current_balance": value})


def balance_gt_principal(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    original = getattr(loan, "original_principal", None)
    current = getattr(loan, "current_balance", None)
    if original is None or current is None:
        return _rule_result(context, rule_name="balance_gt_principal", status="pass", severity="low", message="Balance/principal comparison not applicable with missing values.", details={"original_principal": original, "current_balance": current})
    difference = float(current) - float(original)
    if float(current) > float(original):
        return _rule_result(context, rule_name="balance_gt_principal", status="fail", severity="high", message="current_balance exceeds original_principal.", details={"original_principal": original, "current_balance": current, "difference": difference})
    return _rule_result(context, rule_name="balance_gt_principal", status="pass", severity="low", message="current_balance is not greater than original_principal.", details={"original_principal": original, "current_balance": current, "difference": difference})


def interest_rate_range(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    value = getattr(loan, "interest_rate", None)
    if value is None:
        return _rule_result(context, rule_name="interest_rate_range", status="pass", severity="low", message="No interest rate value to validate.", details={"value": None, "minimum": INTEREST_RATE_MINIMUM, "maximum": INTEREST_RATE_MAXIMUM})
    numeric = float(value)
    if numeric < INTEREST_RATE_MINIMUM or numeric > INTEREST_RATE_MAXIMUM:
        return _rule_result(context, rule_name="interest_rate_range", status="fail", severity="high", message="interest_rate is outside the allowed range.", details={"value": value, "minimum": INTEREST_RATE_MINIMUM, "maximum": INTEREST_RATE_MAXIMUM})
    return _rule_result(context, rule_name="interest_rate_range", status="pass", severity="low", message="interest_rate is within the configured range.", details={"value": value, "minimum": INTEREST_RATE_MINIMUM, "maximum": INTEREST_RATE_MAXIMUM})


def valid_dates(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    fields = ["origination_date", "maturity_date", "last_payment_date", "last_updated_at"]
    invalid_fields: list[str] = []
    for field in fields:
        value = getattr(loan, field, None)
        if value is None:
            continue
        if _parse_date(value) is None:
            invalid_fields.append(field)
    if invalid_fields:
        return _rule_result(context, rule_name="valid_dates", status="fail", severity="high", message="One or more date fields are malformed.", details={"invalid_fields": invalid_fields})
    return _rule_result(context, rule_name="valid_dates", status="pass", severity="low", message="All populated date fields are valid.", details={"invalid_fields": []})


def maturity_after_origination(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    origination = getattr(loan, "origination_date", None)
    maturity = getattr(loan, "maturity_date", None)
    if origination is None or maturity is None:
        return _rule_result(context, rule_name="maturity_after_origination", status="pass", severity="low", message="Maturity/origination comparison not applicable with missing values.", details={"origination_date": origination, "maturity_date": maturity})
    orig_dt = _parse_date(origination)
    mat_dt = _parse_date(maturity)
    if orig_dt is None or mat_dt is None:
        return _rule_result(context, rule_name="maturity_after_origination", status="pass", severity="low", message="Date comparison skipped because one or both dates are malformed.", details={"origination_date": origination, "maturity_date": maturity})
    if mat_dt <= orig_dt:
        return _rule_result(context, rule_name="maturity_after_origination", status="fail", severity="high", message="maturity_date is not after origination_date.", details={"origination_date": origination, "maturity_date": maturity})
    return _rule_result(context, rule_name="maturity_after_origination", status="pass", severity="low", message="maturity_date is after origination_date.", details={"origination_date": origination, "maturity_date": maturity})


def stale_record(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    value = getattr(loan, "last_updated_at", None)
    if value is None:
        return _rule_result(context, rule_name="stale_record", status="fail", severity="medium", message="last_updated_at is missing.", details={"last_updated_at": None, "threshold": f"{STALE_RECORD_FRESHNESS_DAYS} days"})
    parsed = _parse_date(value)
    if parsed is None:
        return _rule_result(context, rule_name="stale_record", status="fail", severity="medium", message="last_updated_at is malformed.", details={"last_updated_at": value, "threshold": f"{STALE_RECORD_FRESHNESS_DAYS} days"})
    threshold = datetime.now(timezone.utc) - timedelta(days=STALE_RECORD_FRESHNESS_DAYS)
    if parsed < threshold:
        return _rule_result(context, rule_name="stale_record", status="fail", severity="medium", message="last_updated_at exceeds the freshness threshold.", details={"last_updated_at": value, "threshold": f"{STALE_RECORD_FRESHNESS_DAYS} days"})
    return _rule_result(context, rule_name="stale_record", status="pass", severity="low", message="last_updated_at is within the freshness threshold.", details={"last_updated_at": value, "threshold": f"{STALE_RECORD_FRESHNESS_DAYS} days"})


def duplicate_loan_id(context: dict[str, Any]) -> dict[str, Any]:
    """Fail when the primary loan tape lists the same loan_id more than once.

    Scoped to the primary source (loan_tape) on purpose, for two reasons:

    * A loan legitimately appears in loan_tape.csv, servicer_update.csv and
      document_manifest.csv. Combining those is the product's purpose, not a defect.
    * Within a supporting file, repeats are also normal -- a document manifest carries
      one row per document, so several rows per loan is its expected shape.

    A repeated loan_id in the canonical tape is the genuine defect this rule is for.
    """
    loan_id = context["loan"].loan_id
    rows_by_file: dict[str | None, list[Any]] = {}
    for row in context["source_rows"]:
        if row.loan_id == loan_id and row.source_system == PRIMARY_SOURCE_SYSTEM:
            rows_by_file.setdefault(row.source_file, []).append(row)

    duplicated = [rows for rows in rows_by_file.values() if len(rows) > 1]
    if duplicated:
        affected = sorted(row.id for rows in duplicated for row in rows)
        offending_files = sorted(str(file) for file, rows in rows_by_file.items() if len(rows) > 1)
        return _rule_result(
            context,
            rule_name="duplicate_loan_id",
            status="fail",
            severity="critical",
            message="The same loan_id appears more than once within a single source file.",
            details={"loan_id": loan_id, "affected_source_rows": affected, "source_files": offending_files},
        )
    return _rule_result(
        context,
        rule_name="duplicate_loan_id",
        status="pass",
        severity="low",
        message="No duplicate loan_id representations were found.",
        details={"loan_id": loan_id, "affected_source_rows": []},
    )


def duplicate_borrower_amount_date(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    db = context["db"]
    affected = db.query(Loan).filter(
        Loan.borrower_id == loan.borrower_id,
        Loan.original_principal == loan.original_principal,
        Loan.origination_date == loan.origination_date,
    ).all()
    affected_ids = [item.loan_id for item in affected]
    if len(affected_ids) > 1:
        return _rule_result(context, rule_name="duplicate_borrower_amount_date", status="fail", severity="medium", message="Borrower/principal/origination-date combination is duplicated.", details={"borrower_id": loan.borrower_id, "original_principal": loan.original_principal, "origination_date": loan.origination_date, "affected_loan_ids": affected_ids})
    return _rule_result(context, rule_name="duplicate_borrower_amount_date", status="pass", severity="low", message="Borrower/principal/origination-date combination is unique.", details={"borrower_id": loan.borrower_id, "original_principal": loan.original_principal, "origination_date": loan.origination_date, "affected_loan_ids": []})


def suspicious_repeated_borrower(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    db = context["db"]
    borrower_loans = db.query(Loan).filter(Loan.borrower_id == loan.borrower_id).all()
    occurrence_count = len(borrower_loans)
    affected_ids = [item.loan_id for item in borrower_loans]
    if occurrence_count > MAX_BORROWER_OCCURRENCES:
        return _rule_result(context, rule_name="suspicious_repeated_borrower", status="fail", severity="medium", message="Borrower occurrence count exceeds the configured threshold.", details={"borrower_id": loan.borrower_id, "occurrence_count": occurrence_count, "threshold": MAX_BORROWER_OCCURRENCES, "affected_loan_ids": affected_ids})
    return _rule_result(context, rule_name="suspicious_repeated_borrower", status="pass", severity="low", message="Borrower occurrence count is within the threshold.", details={"borrower_id": loan.borrower_id, "occurrence_count": occurrence_count, "threshold": MAX_BORROWER_OCCURRENCES, "affected_loan_ids": affected_ids})


def valid_payment_status(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    value = getattr(loan, "payment_status", None)
    if value is None:
        return _rule_result(context, rule_name="valid_payment_status", status="pass", severity="low", message="No payment status provided.", details={"payment_status": None, "allowed_values": sorted(VALID_PAYMENT_STATUSES)})
    normalized = str(value).strip().lower()
    if normalized not in VALID_PAYMENT_STATUSES:
        return _rule_result(context, rule_name="valid_payment_status", status="fail", severity="medium", message="Unsupported payment_status encountered.", details={"payment_status": value, "allowed_values": sorted(VALID_PAYMENT_STATUSES)})
    return _rule_result(context, rule_name="valid_payment_status", status="pass", severity="low", message="payment_status is supported.", details={"payment_status": value, "allowed_values": sorted(VALID_PAYMENT_STATUSES)})


def payment_status_dpd_consistency(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    status = str(getattr(loan, "payment_status", "") or "").strip().lower()
    dpd = getattr(loan, "days_past_due", None)
    expected_relationship = "current or on-time statuses should not have positive delinquency days; delinquent statuses should align with positive DPD values"

    if status in {"current", "performing", "on_time", "paid", "closed", "paid_off", "paid-off"} and dpd not in (None, 0):
        return _rule_result(context, rule_name="payment_status_dpd_consistency", status="fail", severity="medium", message="A current/on-time status has positive delinquency days.", details={"payment_status": loan.payment_status, "days_past_due": dpd, "expected_relationship": expected_relationship})
    if status in {"delinquent", "late", "default", "prepaid"} and (dpd is None or dpd <= 0):
        return _rule_result(context, rule_name="payment_status_dpd_consistency", status="fail", severity="medium", message="A delinquent status is not consistent with positive days_past_due.", details={"payment_status": loan.payment_status, "days_past_due": dpd, "expected_relationship": expected_relationship})
    return _rule_result(context, rule_name="payment_status_dpd_consistency", status="pass", severity="low", message="payment_status and days_past_due are consistent.", details={"payment_status": loan.payment_status, "days_past_due": dpd, "expected_relationship": expected_relationship})


def closed_positive_balance(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    status = str(getattr(loan, "payment_status", "") or "").strip().lower()
    balance = getattr(loan, "current_balance", None)
    if status in {"closed", "paid", "paid_off", "paid-off"} and balance is not None and float(balance) > 0:
        return _rule_result(context, rule_name="closed_positive_balance", status="fail", severity="medium", message="A closed/paid-off loan still has a positive current_balance.", details={"payment_status": loan.payment_status, "current_balance": balance})
    return _rule_result(context, rule_name="closed_positive_balance", status="pass", severity="low", message="Closed/paid-off loans do not retain positive balances.", details={"payment_status": loan.payment_status, "current_balance": balance})


def missing_document_status(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    if getattr(loan, "document_status", None) in (None, ""):
        return _rule_result(context, rule_name="missing_document_status", status="fail", severity="medium", message="document_status is missing.", details={"document_status": getattr(loan, "document_status", None)})
    return _rule_result(context, rule_name="missing_document_status", status="pass", severity="low", message="document_status is present.", details={"document_status": getattr(loan, "document_status", None)})


def invalid_state_code(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    state = getattr(loan, "borrower_state", None)
    if state is None:
        return _rule_result(context, rule_name="invalid_state_code", status="pass", severity="low", message="No state code to validate.", details={"borrower_state": None, "valid_states": sorted(VALID_STATE_CODES)})
    normalized = str(state).strip().upper()
    if normalized not in VALID_STATE_CODES:
        return _rule_result(context, rule_name="invalid_state_code", status="fail", severity="medium", message="borrower_state is not a supported code.", details={"borrower_state": state, "valid_states": sorted(VALID_STATE_CODES)})
    return _rule_result(context, rule_name="invalid_state_code", status="pass", severity="low", message="borrower_state is supported.", details={"borrower_state": state, "valid_states": sorted(VALID_STATE_CODES)})


def source_conflict(context: dict[str, Any]) -> dict[str, Any]:
    loan = context["loan"]
    db = context["db"]
    secondary_sources = db.query(LoanSource).filter(LoanSource.loan_id == loan.loan_id).filter(
        (LoanSource.source_file.like("%servicer_update%")) | (LoanSource.source_system == "servicer_update")
    ).all()
    if not secondary_sources:
        return _rule_result(context, rule_name="source_conflict", status="pass", severity="low", message="No servicer_update record exists for this loan; no false conflict created.", details={"field": None, "loan_tape_value": None, "servicer_update_value": None, "primary_source": "loan_tape.csv", "secondary_source": "servicer_update.csv"})

    secondary = secondary_sources[-1]
    raw = secondary.raw_data or {}
    candidate_fields = [
        "borrower_id",
        "origination_date",
        "maturity_date",
        "original_principal",
        "current_balance",
        "interest_rate",
        "term_months",
        "payment_status",
        "days_past_due",
        "document_status",
        "borrower_state",
    ]

    for field in candidate_fields:
        loan_value = getattr(loan, field, None)
        servicer_value = raw.get(field)
        if servicer_value is None:
            continue
        if _normalize_scalar(loan_value) != _normalize_scalar(servicer_value):
            return _rule_result(context, rule_name="source_conflict", status="fail", severity="high", message="Canonical loan data conflicts with a servicer update source value.", details={
                "field": field,
                "loan_tape_value": loan_value,
                "servicer_update_value": servicer_value,
                "primary_source": "loan_tape.csv",
                "secondary_source": "servicer_update.csv",
            })

    return _rule_result(context, rule_name="source_conflict", status="pass", severity="low", message="No material source conflicts were detected.", details={"field": None, "loan_tape_value": None, "servicer_update_value": None, "primary_source": "loan_tape.csv", "secondary_source": "servicer_update.csv"})


def register_default_rules() -> None:
    """Register the default 4B rule set in the required execution order."""
    rule_specs = [
        ("required_fields", required_fields, "required", 0),
        ("negative_original_principal", negative_original_principal, "numeric", 1),
        ("negative_current_balance", negative_current_balance, "numeric", 2),
        ("balance_gt_principal", balance_gt_principal, "numeric", 3),
        ("interest_rate_range", interest_rate_range, "numeric", 4),
        ("valid_dates", valid_dates, "date", 5),
        ("maturity_after_origination", maturity_after_origination, "date", 6),
        ("stale_record", stale_record, "date", 7),
        ("duplicate_loan_id", duplicate_loan_id, "identity", 8),
        ("duplicate_borrower_amount_date", duplicate_borrower_amount_date, "identity", 9),
        ("suspicious_repeated_borrower", suspicious_repeated_borrower, "identity", 10),
        ("valid_payment_status", valid_payment_status, "status", 11),
        ("payment_status_dpd_consistency", payment_status_dpd_consistency, "status", 12),
        ("closed_positive_balance", closed_positive_balance, "status", 13),
        ("missing_document_status", missing_document_status, "document", 14),
        ("invalid_state_code", invalid_state_code, "document", 15),
        ("source_conflict", source_conflict, "cross_source", 16),
    ]
    for rule_name, func, phase, order in rule_specs:
        register_rule(rule_name, func, phase=phase, order=order)


register_default_rules()

