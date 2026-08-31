"""AI recommendation model.

String storage policy (applies to every model in this package):
  - Bounded identifiers, enums, codes, hashes and ISO-8601 timestamps use String(n);
    the length documents a value that is already structurally bounded.
  - Free text of unpredictable length uses Text. Never cap free text with String(n):
    SQLite silently ignores the limit while PostgreSQL raises "value too long", so a
    guessed cap is a latent production failure that local tests cannot catch.
  - Length limits that exist for product/UX reasons belong at the API boundary
    (Pydantic schemas), not in the storage layer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AIRecommendation(Base):
    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[str] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=False, index=True)
    exception_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("exceptions.id"), nullable=True, index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_correction: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity_classification: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reviewer_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")

    loan: Mapped["Loan"] = relationship(back_populates="ai_recommendations")
    exception: Mapped["ExceptionRecord | None"] = relationship(back_populates="ai_recommendations", foreign_keys="[AIRecommendation.exception_id]")
    review_actions: Mapped[list["ReviewAction"]] = relationship(back_populates="ai_recommendation", foreign_keys="[ReviewAction.ai_recommendation_id]")
