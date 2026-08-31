"""Exception API schemas."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExceptionSeverity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class ExceptionStatus(str, Enum):
    open = "open"
    in_review = "in_review"
    resolved = "resolved"
    rejected = "rejected"


class ExceptionQueueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exception_id: int
    loan_id: str
    borrower_id: str | None = None
    type: str
    severity: str
    status: str
    validation_result_id: int | None = None
    message: str | None = None
    created_at: str
    resolved_at: str | None = None


class ExceptionListResponse(BaseModel):
    items: list[ExceptionQueueItem]
    page: int
    page_size: int
    total: int
    total_pages: int


class ValidationResultSummary(BaseModel):
    rule_name: str
    status: str | None = None
    severity: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None
    run_at: str | None = None


class ExceptionDetailRecord(BaseModel):
    id: int
    loan_id: str
    type: str
    severity: str
    status: str
    created_at: str
    resolved_at: str | None = None


class LoanSourceEvidence(BaseModel):
    id: int
    source_file: str | None = None
    source_system: str | None = None
    source_row_number: int | None = None
    raw_data: dict[str, Any] | None = None
    imported_at: str | None = None
    import_status: str | None = None


class AuditEventSummary(BaseModel):
    id: int
    event_type: str
    actor: str | None = None
    created_at: str
    details: dict[str, Any] | None = None


class CanonicalLoanDetail(BaseModel):
    loan_id: str | None = None
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


class ReviewActionSummary(BaseModel):
    action_id: int
    action_type: str
    reviewer_id: int | None = None
    field_name: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    comment_text: str | None = None
    ai_recommendation_id: int | None = None
    created_at: str


class AIRecommendationSummary(BaseModel):
    """An AI recommendation as shown to a reviewer.

    Excludes the stored evidence snapshot, which stays in the database for audit.
    """

    ai_recommendation_id: int
    exception_id: int | None = None
    loan_id: str
    recommendation_type: str | None = None
    summary: str | None = None
    explanation: str | None = None
    confidence: float | None = None
    affected_fields: list[str] = []
    suggested_corrections: list[dict[str, Any]] = []
    evidence_citations: list[dict[str, Any]] = []
    limitations: list[str] = []
    severity_classification: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    downgraded: bool = False
    downgrade_reasons: list[str] = []
    reviewer_status: str
    created_at: str


class ReviewerCommentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Comment text cannot be empty.")
        return cleaned


class ReviewerFieldEditRequest(BaseModel):
    field: str = Field(..., min_length=1)
    value: Any

    @field_validator("field")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field name is required.")
        return cleaned


class ReviewerDecisionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class ReviewActionResponse(BaseModel):
    action_id: int
    exception_id: int
    loan_id: str
    reviewer_id: int
    action_type: str
    comment_text: str
    created_at: str


class ReviewerDecisionResponse(BaseModel):
    action_id: int
    exception_id: int
    loan_id: str
    reviewer_id: int
    action_type: str
    comment_text: str | None = None
    created_at: str
    exception_status: str


class FieldEditResponse(BaseModel):
    status: str
    message: str
    exception_id: int | None = None
    loan_id: str | None = None
    reviewer_id: int | None = None
    action_id: int | None = None
    field_name: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    created_at: str | None = None


class ExceptionDetailResponse(BaseModel):
    exception: ExceptionDetailRecord
    validation_result: ValidationResultSummary
    canonical_loan: CanonicalLoanDetail
    source_evidence: list[LoanSourceEvidence]
    historical_validation_results: list[ValidationResultSummary]
    audit_events: list[AuditEventSummary]
    review_actions: list[ReviewActionSummary] = []
    ai_recommendations: list[AIRecommendationSummary] = []



class AIRecommendationCorrection(BaseModel):
    """One reviewer-supplied replacement value when editing an AI recommendation."""

    field: str = Field(..., min_length=1)
    value: Any

    @field_validator("field")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field name is required.")
        return cleaned


class AIDispositionRequest(BaseModel):
    """Body for accepting or rejecting an AI recommendation."""

    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class AIEditDispositionRequest(AIDispositionRequest):
    """Body for applying the reviewer's own values instead of the AI's."""

    corrections: list[AIRecommendationCorrection] = Field(..., min_length=1)


class AppliedChange(BaseModel):
    field: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    status: str | None = None
    review_action_id: int | None = None


class AIDispositionResponse(BaseModel):
    ai_recommendation_id: int
    exception_id: int | None = None
    loan_id: str
    disposition: str
    reviewer_status: str
    recommendation_type: str | None = None
    reviewer_id: int
    review_action_id: int
    comment_text: str | None = None
    applied_changes: list[AppliedChange] = []
    created_at: str
