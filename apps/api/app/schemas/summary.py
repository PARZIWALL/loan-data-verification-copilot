"""Dashboard summary API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class LoanTotals(BaseModel):
    total: int
    verified: int
    with_open_exceptions: int
    clean: int


class ExceptionTypeCount(BaseModel):
    type: str
    count: int


class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class ExceptionTotals(BaseModel):
    total: int
    open: int = 0
    in_review: int = 0
    resolved: int = 0
    rejected: int = 0
    by_severity: SeverityCounts
    by_type: list[ExceptionTypeCount] = []


class ValidationTotals(BaseModel):
    total_results: int
    passed: int
    failed: int
    latest_run_at: str | None = None


class IngestionTotals(BaseModel):
    files: int
    source_rows: int
    rows_imported: int
    rows_failed: int


class AITotals(BaseModel):
    recommendations: int
    pending: int = 0
    accepted: int = 0
    edited: int = 0
    rejected: int = 0


class VerificationTotals(BaseModel):
    verified_records: int
    exported: int


class AuditTotals(BaseModel):
    events: int


class SummaryResponse(BaseModel):
    loans: LoanTotals
    exceptions: ExceptionTotals
    validation: ValidationTotals
    ingestion: IngestionTotals
    ai: AITotals
    verification: VerificationTotals
    audit: AuditTotals
    data_quality_score: float
