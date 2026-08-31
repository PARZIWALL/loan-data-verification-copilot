"""Canonical loan persistence model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Loan(Base):
    __tablename__ = "loans"

    loan_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    borrower_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    loan_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    origination_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    maturity_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_principal: Mapped[float | None] = mapped_column(nullable=True)
    current_balance: Mapped[float | None] = mapped_column(nullable=True)
    interest_rate: Mapped[float | None] = mapped_column(nullable=True)
    term_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    borrower_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    loan_purpose: Mapped[str | None] = mapped_column(String(120), nullable=True)
    credit_grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employment_length: Mapped[str | None] = mapped_column(String(50), nullable=True)
    income_band: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    days_past_due: Mapped[int | None] = mapped_column(Integer, nullable=True)
    servicer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_payment_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    document_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(80), nullable=True)
    primary_source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("loan_sources.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")
    updated_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")

    sources: Mapped[list["LoanSource"]] = relationship(back_populates="loan", foreign_keys="[LoanSource.loan_id]")
    validations: Mapped[list["ValidationResult"]] = relationship(back_populates="loan")
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(back_populates="loan")
    review_actions: Mapped[list["ReviewAction"]] = relationship(back_populates="loan")
    ai_recommendations: Mapped[list["AIRecommendation"]] = relationship(back_populates="loan")
    verified_loans: Mapped[list["VerifiedLoan"]] = relationship(back_populates="loan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="loan")

