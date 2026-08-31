"""Validation result model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[str] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pass")
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    # Free text: rule-authored prose, so no rule needs to know about a storage cap.
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    run_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")

    loan: Mapped["Loan"] = relationship(back_populates="validations")
    exceptions: Mapped[list["ExceptionRecord"]] = relationship(back_populates="validation_result")
