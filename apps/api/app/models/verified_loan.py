"""Verified snapshot model for a reviewed loan."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VerifiedLoan(Base):
    __tablename__ = "verified_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[str] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=False, index=True)
    final_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reviewer_decision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ai_recommendation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_recommendations.id"), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    verification_timestamp: Mapped[str | None] = mapped_column(String(50), nullable=True)
    record_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exported_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    loan: Mapped["Loan"] = relationship(back_populates="verified_loans")
