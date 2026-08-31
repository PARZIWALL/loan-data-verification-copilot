"""Human review action model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ReviewAction(Base):
    __tablename__ = "review_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exception_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("exceptions.id"), nullable=True, index=True)
    loan_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=True, index=True)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False, default="comment")
    field_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    old_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # Free text: the 2000-char product limit is enforced at the API boundary, not here.
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_recommendation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("ai_recommendations.id"), nullable=True, index=True)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")

    loan: Mapped["Loan | None"] = relationship(back_populates="review_actions", foreign_keys="[ReviewAction.loan_id]")
    exception: Mapped["ExceptionRecord | None"] = relationship(back_populates="review_actions", foreign_keys="[ReviewAction.exception_id]")
    ai_recommendation: Mapped["AIRecommendation | None"] = relationship(back_populates="review_actions", foreign_keys="[ReviewAction.ai_recommendation_id]")
