"""Raw source ingestion model for immutable loan evidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LoanSource(Base):
    __tablename__ = "loan_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("loans.loan_id"), nullable=True, index=True)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")
    import_status: Mapped[str] = mapped_column(String(40), nullable=False, default="success")
    # Free text: holds str(exception) from a failed row import, which is unbounded.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    loan: Mapped["Loan | None"] = relationship(back_populates="sources", foreign_keys="[LoanSource.loan_id]")
