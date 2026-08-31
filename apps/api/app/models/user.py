"""User persistence model."""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(str, Enum):
    DATA_OPERATOR = "data_operator"
    REVIEWER = "reviewer"
    DATA_CONSUMER = "data_consumer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default=UserRole.DATA_OPERATOR.value)
    created_at: Mapped[str] = mapped_column(String(50), nullable=False, default="now")

    def to_public_dict(self) -> dict[str, str | int]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
        }

