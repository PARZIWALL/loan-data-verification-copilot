"""Canonical loan API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class LoanValidationResultItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_name: str
    status: str
    severity: str
    message: str | None = None
    details: dict[str, Any] | None = None
    run_at: str


class LoanExceptionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    severity: str
    status: str
    created_at: str
    resolved_at: str | None = None


class LoanSourceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_file: str | None = None
    source_system: str | None = None
    source_row_number: int | None = None
    raw_data: dict[str, Any] | None = None
    imported_at: str | None = None
    import_status: str | None = None


class LoanDetailResponse(BaseModel):
    loan_id: str
    borrower_id: str | None = None
    loan_type: str | None = None
    origination_date: str | None = None
    maturity_date: str | None = None
    original_principal: float | None = None
    current_balance: float | None = None
    interest_rate: float | None = None
    term_months: int | None = None
    borrower_state: str | None = None
    loan_purpose: str | None = None
    credit_grade: str | None = None
    employment_length: str | None = None
    income_band: str | None = None
    payment_status: str | None = None
    days_past_due: int | None = None
    servicer_name: str | None = None
    last_payment_date: str | None = None
    last_updated_at: str | None = None
    document_status: str | None = None
    source_system: str | None = None
    primary_source_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None
    validation_results: list[LoanValidationResultItem] = []
    exceptions: list[LoanExceptionSummary] = []
    source_records: list[LoanSourceSummary] = []



class LoanListItem(BaseModel):
    """One row in the loan portfolio list, with its current review state."""

    loan_id: str
    borrower_id: str | None = None
    loan_type: str | None = None
    original_principal: float | None = None
    current_balance: float | None = None
    interest_rate: float | None = None
    borrower_state: str | None = None
    payment_status: str | None = None
    document_status: str | None = None
    last_updated_at: str | None = None
    open_exception_count: int = 0
    verified: bool = False


class LoanListResponse(BaseModel):
    items: list[LoanListItem]
    page: int
    page_size: int
    total: int
    total_pages: int
