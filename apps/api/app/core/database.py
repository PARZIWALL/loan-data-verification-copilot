from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return settings.DATABASE_URL


def build_engine():
    url = get_database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def create_db_and_tables() -> None:
    from app.models.ai_recommendation import AIRecommendation
    from app.models.audit import AuditLog
    from app.models.exception import ExceptionRecord
    from app.models.loan import Loan
    from app.models.loan_source import LoanSource
    from app.models.review_action import ReviewAction
    from app.models.user import User
    from app.models.validation_result import ValidationResult
    from app.models.verified_loan import VerifiedLoan

    Base.metadata.create_all(bind=engine)


engine = build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
