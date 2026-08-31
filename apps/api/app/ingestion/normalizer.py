"""Canonical loan normalization."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _as_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d")
        except ValueError:
            return text


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value: {value}") from exc


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError as exc:
        raise ValueError(f"Invalid integer value: {value}") from exc


def normalize_loan_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parsed loan_tape row into canonical loan fields."""
    loan_id = (row.get("loan_id") or "").strip()
    if not loan_id:
        raise ValueError("Missing loan_id")

    normalized = {
        "loan_id": loan_id,
        "borrower_id": (row.get("borrower_id") or "").strip() or None,
        "loan_type": (row.get("loan_type") or "").strip() or None,
        "origination_date": _as_date(row.get("origination_date")),
        "maturity_date": _as_date(row.get("maturity_date")),
        "original_principal": _as_float(row.get("original_principal")),
        "current_balance": _as_float(row.get("current_balance")),
        "interest_rate": _as_float(row.get("interest_rate")),
        "term_months": _as_int(row.get("term_months")),
        "borrower_state": (row.get("borrower_state") or "").strip() or None,
        "loan_purpose": (row.get("loan_purpose") or "").strip() or None,
        "credit_grade": (row.get("credit_grade") or "").strip() or None,
        "employment_length": (row.get("employment_length") or "").strip() or None,
        "income_band": (row.get("income_band") or "").strip() or None,
        "payment_status": (row.get("payment_status") or "").strip() or None,
        "days_past_due": _as_int(row.get("days_past_due")),
        "servicer_name": (row.get("servicer_name") or "").strip() or None,
        "last_payment_date": _as_date(row.get("last_payment_date")),
        "last_updated_at": _as_date(row.get("last_updated_at")) or None,
        "document_status": (row.get("document_status") or "").strip() or None,
        "source_system": (row.get("source_system") or "").strip() or None,
    }
    return normalized
