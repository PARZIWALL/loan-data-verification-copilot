"""Initial schema for loan verification foundation.

Revision ID: 20260829_000001
Revises: 
Create Date: 2026-08-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260829_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=False)

    op.create_table(
        "loans",
        sa.Column("loan_id", sa.String(length=120), nullable=False),
        sa.Column("borrower_id", sa.String(length=120), nullable=True),
        sa.Column("loan_type", sa.String(length=80), nullable=True),
        sa.Column("origination_date", sa.String(length=50), nullable=True),
        sa.Column("maturity_date", sa.String(length=50), nullable=True),
        sa.Column("original_principal", sa.Float(), nullable=True),
        sa.Column("current_balance", sa.Float(), nullable=True),
        sa.Column("interest_rate", sa.Float(), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column("borrower_state", sa.String(length=50), nullable=True),
        sa.Column("loan_purpose", sa.String(length=120), nullable=True),
        sa.Column("credit_grade", sa.String(length=50), nullable=True),
        sa.Column("employment_length", sa.String(length=50), nullable=True),
        sa.Column("income_band", sa.String(length=60), nullable=True),
        sa.Column("payment_status", sa.String(length=80), nullable=True),
        sa.Column("days_past_due", sa.Integer(), nullable=True),
        sa.Column("servicer_name", sa.String(length=120), nullable=True),
        sa.Column("last_payment_date", sa.String(length=50), nullable=True),
        sa.Column("last_updated_at", sa.String(length=50), nullable=True),
        sa.Column("document_status", sa.String(length=80), nullable=True),
        sa.Column("source_system", sa.String(length=80), nullable=True),
        sa.Column("primary_source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.Column("updated_at", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("loan_id"),
    )

    op.create_table(
        "loan_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("source_system", sa.String(length=80), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("ingested_at", sa.String(length=50), nullable=False),
        sa.Column("import_status", sa.String(length=40), nullable=False),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_loan_sources_id"), "loan_sources", ["id"], unique=False)
    op.create_index(op.f("ix_loan_sources_loan_id"), "loan_sources", ["loan_id"], unique=False)

    # loans.primary_source_id -> loan_sources.id is added as a separate constraint here,
    # once both tables exist, because loans and loan_sources have a circular FK
    # relationship (loan_sources.loan_id -> loans.loan_id, loans.primary_source_id ->
    # loan_sources.id). SQLAlchemy's Base.metadata.create_all() resolves such cycles
    # automatically (create tables, then ALTER for the cyclic FK), which is why this
    # worked silently under SQLite-backed tests; a literal, hand-written Alembic script
    # does not get that resolution for free and needs it done explicitly like this.
    # batch_alter_table (not a plain op.create_foreign_key) is required here: SQLite has
    # no ALTER TABLE ADD CONSTRAINT support at all, so this must run in Alembic's batch
    # mode, which transparently does a create-copy-rename on SQLite and a plain ALTER on
    # Postgres -- this keeps the migration usable against the local SQLite dev database
    # as well as Postgres.
    with op.batch_alter_table("loans") as batch_op:
        batch_op.create_foreign_key(
            "fk_loans_primary_source_id",
            "loan_sources",
            ["primary_source_id"],
            ["id"],
        )

    op.create_table(
        "validation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=False),
        sa.Column("rule_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("run_at", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_validation_results_id"), "validation_results", ["id"], unique=False)
    op.create_index(op.f("ix_validation_results_loan_id"), "validation_results", ["loan_id"], unique=False)
    op.create_index(op.f("ix_validation_results_rule_name"), "validation_results", ["rule_name"], unique=False)

    op.create_table(
        "exceptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=False),
        sa.Column("validation_result_id", sa.Integer(), nullable=True),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.Column("resolved_at", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.ForeignKeyConstraint(["validation_result_id"], ["validation_results.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exceptions_id"), "exceptions", ["id"], unique=False)
    op.create_index(op.f("ix_exceptions_loan_id"), "exceptions", ["loan_id"], unique=False)

    op.create_table(
        "ai_recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=False),
        sa.Column("exception_id", sa.Integer(), nullable=True),
        sa.Column("prompt_text", sa.String(length=1000), nullable=True),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("response_text", sa.String(length=2000), nullable=True),
        sa.Column("suggested_correction", sa.JSON(), nullable=True),
        sa.Column("explanation", sa.String(length=2000), nullable=True),
        sa.Column("severity_classification", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reviewer_status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["exception_id"], ["exceptions.id"]),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_recommendations_id"), "ai_recommendations", ["id"], unique=False)
    op.create_index(op.f("ix_ai_recommendations_loan_id"), "ai_recommendations", ["loan_id"], unique=False)
    op.create_index(op.f("ix_ai_recommendations_exception_id"), "ai_recommendations", ["exception_id"], unique=False)

    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exception_id", sa.Integer(), nullable=True),
        sa.Column("loan_id", sa.String(length=120), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=True),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("comment_text", sa.String(length=500), nullable=True),
        sa.Column("ai_recommendation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["ai_recommendation_id"], ["ai_recommendations.id"]),
        sa.ForeignKeyConstraint(["exception_id"], ["exceptions.id"]),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_actions_id"), "review_actions", ["id"], unique=False)
    op.create_index(op.f("ix_review_actions_exception_id"), "review_actions", ["exception_id"], unique=False)
    op.create_index(op.f("ix_review_actions_loan_id"), "review_actions", ["loan_id"], unique=False)
    op.create_index(op.f("ix_review_actions_reviewer_id"), "review_actions", ["reviewer_id"], unique=False)
    op.create_index(op.f("ix_review_actions_ai_recommendation_id"), "review_actions", ["ai_recommendation_id"], unique=False)

    op.create_table(
        "verified_loans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=False),
        sa.Column("final_data", sa.JSON(), nullable=True),
        sa.Column("source_reference", sa.JSON(), nullable=True),
        sa.Column("validation_result_summary", sa.JSON(), nullable=True),
        sa.Column("reviewer_decision", sa.String(length=80), nullable=True),
        sa.Column("ai_recommendation_id", sa.Integer(), nullable=True),
        sa.Column("verified_by", sa.String(length=120), nullable=True),
        sa.Column("verification_timestamp", sa.String(length=50), nullable=True),
        sa.Column("record_hash", sa.String(length=255), nullable=True),
        sa.Column("exported", sa.Boolean(), nullable=False),
        sa.Column("exported_at", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["ai_recommendation_id"], ["ai_recommendations.id"]),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verified_loans_id"), "verified_loans", ["id"], unique=False)
    op.create_index(op.f("ix_verified_loans_loan_id"), "verified_loans", ["loan_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.loan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_audit_logs_loan_id"), "audit_logs", ["loan_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_loan_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_verified_loans_loan_id"), table_name="verified_loans")
    op.drop_index(op.f("ix_verified_loans_id"), table_name="verified_loans")
    op.drop_table("verified_loans")

    op.drop_index(op.f("ix_review_actions_ai_recommendation_id"), table_name="review_actions")
    op.drop_index(op.f("ix_review_actions_reviewer_id"), table_name="review_actions")
    op.drop_index(op.f("ix_review_actions_loan_id"), table_name="review_actions")
    op.drop_index(op.f("ix_review_actions_exception_id"), table_name="review_actions")
    op.drop_index(op.f("ix_review_actions_id"), table_name="review_actions")
    op.drop_table("review_actions")

    op.drop_index(op.f("ix_ai_recommendations_exception_id"), table_name="ai_recommendations")
    op.drop_index(op.f("ix_ai_recommendations_loan_id"), table_name="ai_recommendations")
    op.drop_index(op.f("ix_ai_recommendations_id"), table_name="ai_recommendations")
    op.drop_table("ai_recommendations")

    op.drop_index(op.f("ix_exceptions_loan_id"), table_name="exceptions")
    op.drop_index(op.f("ix_exceptions_id"), table_name="exceptions")
    op.drop_table("exceptions")

    op.drop_index(op.f("ix_validation_results_rule_name"), table_name="validation_results")
    op.drop_index(op.f("ix_validation_results_loan_id"), table_name="validation_results")
    op.drop_index(op.f("ix_validation_results_id"), table_name="validation_results")
    op.drop_table("validation_results")

    with op.batch_alter_table("loans") as batch_op:
        batch_op.drop_constraint("fk_loans_primary_source_id", type_="foreignkey")
    op.drop_index(op.f("ix_loan_sources_loan_id"), table_name="loan_sources")
    op.drop_index(op.f("ix_loan_sources_id"), table_name="loan_sources")
    op.drop_table("loan_sources")
    op.drop_table("loans")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_table("users")
