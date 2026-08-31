"""Validation exception persistence model."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ExceptionRecord(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[str] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=False, index=True)
    validation_result_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("validation_results.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")
    resolved_at: Mapped[str | None] = mapped_column(String(50), nullable=True)

    loan: Mapped["Loan"] = relationship(back_populates="exceptions")
    validation_result: Mapped["ValidationResult | None"] = relationship(back_populates="exceptions")
    review_actions: Mapped[list["ReviewAction"]] = relationship(back_populates="exception", foreign_keys="[ReviewAction.exception_id]")
    ai_recommendations: Mapped[list["AIRecommendation"]] = relationship(back_populates="exception", foreign_keys="[AIRecommendation.exception_id]")

