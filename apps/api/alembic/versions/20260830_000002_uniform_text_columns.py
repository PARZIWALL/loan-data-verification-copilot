"""Uniform text storage: free-text columns become Text; normalize username index.

Applies the string storage policy documented in app/models/ai_recommendation.py:
bounded identifiers/enums/timestamps keep String(n); free text of unpredictable
length uses Text.

This also repairs two model/migration drifts that SQLite could not surface, because
SQLite ignores VARCHAR length while PostgreSQL enforces it:

  * review_actions.comment_text was String(2000) in the model but String(500) here,
    while the API accepts up to 2000 characters -- a guaranteed PostgreSQL failure.
  * ix_users_username was created non-unique here while the model declares a unique
    index (uniqueness was still enforced by a separate UniqueConstraint, so this is
    cosmetic, but it kept the schemas from matching).

ai_recommendations.prompt_text is renamed to prompt_version: it only ever stored the
prompt version identifier ("loan-review-v1"), never prompt text.

batch_alter_table is required because SQLite cannot ALTER a column type.

Revision ID: 20260830_000002
Revises: 20260829_000001
Create Date: 2026-08-30 00:00:02.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260830_000002"
down_revision = "20260829_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_recommendations") as batch_op:
        batch_op.alter_column(
            "prompt_text",
            new_column_name="prompt_version",
            existing_type=sa.String(length=1000),
            type_=sa.String(length=80),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "response_text",
            existing_type=sa.String(length=2000),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "explanation",
            existing_type=sa.String(length=2000),
            type_=sa.Text(),
            existing_nullable=True,
        )

    with op.batch_alter_table("review_actions") as batch_op:
        batch_op.alter_column(
            "comment_text",
            existing_type=sa.String(length=500),
            type_=sa.Text(),
            existing_nullable=True,
        )

    with op.batch_alter_table("validation_results") as batch_op:
        batch_op.alter_column(
            "message",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )

    with op.batch_alter_table("loan_sources") as batch_op:
        batch_op.alter_column(
            "failure_reason",
            existing_type=sa.String(length=255),
            type_=sa.Text(),
            existing_nullable=True,
        )

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    with op.batch_alter_table("loan_sources") as batch_op:
        batch_op.alter_column(
            "failure_reason",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )

    with op.batch_alter_table("validation_results") as batch_op:
        batch_op.alter_column(
            "message",
            existing_type=sa.Text(),
            type_=sa.String(length=255),
            existing_nullable=True,
        )

    with op.batch_alter_table("review_actions") as batch_op:
        batch_op.alter_column(
            "comment_text",
            existing_type=sa.Text(),
            type_=sa.String(length=500),
            existing_nullable=True,
        )

    with op.batch_alter_table("ai_recommendations") as batch_op:
        batch_op.alter_column(
            "explanation",
            existing_type=sa.Text(),
            type_=sa.String(length=2000),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "response_text",
            existing_type=sa.Text(),
            type_=sa.String(length=2000),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "prompt_version",
            new_column_name="prompt_text",
            existing_type=sa.String(length=80),
            type_=sa.String(length=1000),
            existing_nullable=True,
        )
