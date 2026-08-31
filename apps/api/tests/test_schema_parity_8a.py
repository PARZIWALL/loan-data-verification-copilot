"""8A: schema uniformity guard.

The bug this file exists to prevent: review_actions.comment_text was String(2000) in
the model but String(500) in the migration, while the API accepted 2000 characters.
Nothing caught it, because SQLite ignores VARCHAR length and PostgreSQL is not
available in this environment -- so every test passed while the deployed schema was
wrong. These tests compare the migrated schema against the models directly, and pin
the free-text storage policy.
"""

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import settings
from app.core.database import Base
from app.models.ai_recommendation import AIRecommendation
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.validation_result import ValidationResult

API_ROOT = Path(__file__).resolve().parents[1]

# The complete set of free-text (Class B) columns. Anything here must be Text, never
# String(n): a guessed cap is silently ignored by SQLite and fatal on PostgreSQL.
FREE_TEXT_COLUMNS = [
    (AIRecommendation, "response_text"),
    (AIRecommendation, "explanation"),
    (ReviewAction, "comment_text"),
    (ValidationResult, "message"),
    (LoanSource, "failure_reason"),
]


@pytest.fixture(scope="module")
def migrated_database_url():
    """Build a database from the Alembic migrations alone (never create_all).

    alembic/env.py deliberately overrides sqlalchemy.url with settings.DATABASE_URL,
    so pointing the migration at a temporary database means patching the setting
    itself -- setting the Alembic config option alone is silently ignored.
    """
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp).as_posix()}/parity.db"
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(settings, "DATABASE_URL", url)
            command.upgrade(config, "head")
        yield url


def test_migrated_schema_matches_the_models_exactly(migrated_database_url):
    """Any model change without a matching migration fails here."""
    engine = sa.create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert differences == [], (
        "Model definitions and Alembic migrations have drifted. "
        f"Differences: {differences}"
    )


@pytest.mark.parametrize("model, column_name", FREE_TEXT_COLUMNS)
def test_free_text_columns_are_unbounded_text(model, column_name):
    column_type = model.__table__.columns[column_name].type
    assert isinstance(column_type, sa.Text), f"{model.__tablename__}.{column_name} must be Text"
    assert getattr(column_type, "length", None) is None, (
        f"{model.__tablename__}.{column_name} must not declare a length"
    )


def test_migrated_free_text_columns_are_text_in_the_database(migrated_database_url):
    engine = sa.create_engine(migrated_database_url)
    try:
        inspector = sa.inspect(engine)
        for model, column_name in FREE_TEXT_COLUMNS:
            columns = {c["name"]: c for c in inspector.get_columns(model.__tablename__)}
            assert str(columns[column_name]["type"]).upper() == "TEXT", (
                f"{model.__tablename__}.{column_name} is "
                f"{columns[column_name]['type']} in the migrated database, expected TEXT"
            )
    finally:
        engine.dispose()


def test_prompt_version_column_replaced_prompt_text():
    """The column stores 'loan-review-v1', so its name must not promise prompt text."""
    columns = AIRecommendation.__table__.columns
    assert "prompt_version" in columns
    assert "prompt_text" not in columns


def test_ai_recommendation_text_survives_beyond_the_old_2000_char_cap(migrated_database_url):
    """The originating 7B limitation: long AI output was truncated with a marker.

    response_text and explanation must now round-trip byte-for-byte at a length the
    old String(2000) column could not hold.
    """
    engine = sa.create_engine(migrated_database_url)
    session_factory = sa.orm.sessionmaker(bind=engine)
    long_explanation = "The servicer update contradicts the loan tape. " * 300  # ~14k chars
    long_response = "{\"padding\": \"" + ("z" * 9000) + "\"}"
    assert len(long_explanation) > 2000 and len(long_response) > 2000

    try:
        with session_factory() as session:
            session.add(
                sa.inspect(AIRecommendation).class_(
                    loan_id="L-PARITY-1",
                    exception_id=None,
                    model_name="openai/gpt-oss-120b",
                    prompt_version="loan-review-v1",
                    response_text=long_response,
                    suggested_correction={"recommendation": {}},
                    explanation=long_explanation,
                    severity_classification="high",
                    confidence=0.5,
                    reviewer_status="pending",
                    created_at="2026-08-30T00:00:00Z",
                )
            )
            # No loans row exists, but SQLite does not enforce FKs here and this test is
            # about column capacity, not referential integrity.
            session.commit()

        with session_factory() as session:
            stored = session.query(AIRecommendation).one()
            assert stored.explanation == long_explanation
            assert stored.response_text == long_response
            assert "[truncated]" not in stored.explanation
    finally:
        engine.dispose()
