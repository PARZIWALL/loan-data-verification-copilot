"""7C tests: reviewer disposition of AI recommendations.

No real Groq calls -- recommendations are created through the 7B service with a stubbed
client, then dispositioned through the real 7C API.

Reuses the 6A shared-schema fixtures (test_verification_6a.py) and the 7B stub client.
"""

import json
from unittest.mock import patch

import pytest
import tests.test_verification_6a as base
from fastapi.testclient import TestClient

from app.core.seed import hash_password
from app.main import app
from app.models.ai_recommendation import AIRecommendation
from app.models.audit import AuditLog
from app.models.exception import ExceptionRecord
from app.models.loan_source import LoanSource
from app.models.review_action import ReviewAction
from app.models.user import User
from app.models.validation_result import ValidationResult
from app.models.verified_loan import VerifiedLoan
from app.services import ai_recommendation_service
from app.services.ai_recommendation_service import generate_ai_recommendation
from app.validators.engine import clear_rules, validate_loan
from app.validators.rules import register_default_rules
from tests.test_ai_recommendation_7b import DUMMY_API_KEY, StubClient

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def schema():
    base.create_db_and_tables()
    yield


@pytest.fixture(autouse=True)
def clean():
    clear_rules()
    base._clear_database()
    register_default_rules()
    try:
        yield
    finally:
        clear_rules()
        base._clear_database()


@pytest.fixture(autouse=True)
def dummy_api_key():
    with patch.object(ai_recommendation_service.settings, "GROQ_API_KEY", DUMMY_API_KEY):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _authenticate(username: str, role: str) -> dict[str, str]:
    with base.SessionLocal() as db:
        if db.query(User).filter(User.username == username).one_or_none() is None:
            db.add(User(username=username, password_hash=hash_password("dev_password"), role=role))
            db.commit()
    response = client.post("/auth/login", json={"username": username, "password": "dev_password"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _recommendation_json(**overrides) -> str:
    payload = {
        "recommendation_type": "suggest_no_change",
        "summary": "Canonical value is supported by the evidence.",
        "affected_fields": [],
        "suggested_corrections": [],
        "explanation": "The canonical value agrees with the primary source record.",
        "confidence": 0.9,
        "evidence_citations": [],
        "limitations": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _seed_conflict_loan(loan_id: str = "L-7C-CONFLICT") -> tuple[int, str, int]:
    """loan_tape says current_balance=95000; servicer_update row 52 says 82000."""
    base._seed_loan(loan_id=loan_id, current_balance=95000.0, original_principal=250000.0)
    with base.SessionLocal() as db:
        primary = LoanSource(
            loan_id=loan_id, source_file="loan_tape.csv", source_system="loan_tape",
            source_row_number=3, raw_data={"loan_id": loan_id, "current_balance": "95000"},
            ingested_at="2024-01-01T00:00:00Z", import_status="success",
        )
        db.add(primary)
        db.flush()
        primary_id = primary.id
        db.add(LoanSource(
            loan_id=loan_id, source_file="servicer_update.csv", source_system="servicer_update",
            source_row_number=52, raw_data={"loan_id": loan_id, "current_balance": "82000"},
            ingested_at="2024-02-01T00:00:00Z", import_status="success",
        ))
        db.get(base.Loan, loan_id).primary_source_id = primary_id
        db.commit()
    validate_loan(loan_id)
    with base.SessionLocal() as db:
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id, type="source_conflict").one()
        return exc.id, loan_id, primary_id


def _create_recommendation(exception_id: int, content: str) -> int:
    """Create a real AIRecommendation row via the 7B service with a stubbed model."""
    with base.SessionLocal() as db:
        result = generate_ai_recommendation(db, exception_id, client=StubClient(content=content))
        db.commit()
        return result["ai_recommendation_id"]


def _correction_recommendation(loan_id: str) -> str:
    return _recommendation_json(
        recommendation_type="suggest_field_correction",
        summary="Align canonical balance with the later servicer update.",
        affected_fields=["current_balance"],
        suggested_corrections=[
            {"field": "current_balance", "current_value": 95000.0, "suggested_value": 82000.0}
        ],
        explanation="servicer_update.csv row 52 reports 82000 while the loan tape reports 95000.",
        confidence=0.88,
        evidence_citations=[
            {"source_id": None, "source_file": "servicer_update.csv", "source_row_number": 52, "field": "current_balance"}
        ],
    )


def _workflow_snapshot(loan_id: str) -> tuple:
    with base.SessionLocal() as db:
        loan = db.get(base.Loan, loan_id)
        exc = db.query(ExceptionRecord).filter_by(loan_id=loan_id).order_by(ExceptionRecord.id).first()
        return (
            loan.current_balance,
            exc.status if exc else None,
            db.query(ValidationResult).filter_by(loan_id=loan_id).count(),
            db.query(ReviewAction).filter_by(loan_id=loan_id).count(),
            db.query(VerifiedLoan).count(),
        )


# ---------------------------------------------------------------------------
# Visibility -- the reviewer must be able to see the recommendation
# ---------------------------------------------------------------------------


def test_exception_detail_shows_the_ai_recommendation():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-see", "reviewer")

    response = client.get(f"/exceptions/{exception_id}", headers=headers)
    assert response.status_code == 200
    recommendations = response.json()["ai_recommendations"]
    assert len(recommendations) == 1
    shown = recommendations[0]
    assert shown["ai_recommendation_id"] == recommendation_id
    assert shown["recommendation_type"] == "suggest_field_correction"
    assert shown["reviewer_status"] == "pending"
    assert shown["suggested_corrections"][0]["suggested_value"] == 82000.0
    assert shown["model_name"] and shown["prompt_version"]


def test_exception_detail_does_not_leak_the_evidence_snapshot():
    exception_id, loan_id, _ = _seed_conflict_loan()
    _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-nosnap", "reviewer")

    shown = client.get(f"/exceptions/{exception_id}", headers=headers).json()["ai_recommendations"][0]
    assert "evidence_snapshot" not in shown
    # ...but it is still retained in the database for audit/reproducibility.
    with base.SessionLocal() as db:
        stored = db.query(AIRecommendation).one()
        assert "evidence_snapshot" in stored.suggested_correction


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


def test_accepting_a_correction_applies_it_and_revalidates():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-accept", "reviewer")

    response = client.post(
        f"/ai-recommendations/{recommendation_id}/accept",
        json={"comment": "Servicer update is the later source."},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["disposition"] == "accepted"
    assert body["reviewer_status"] == "accepted"
    assert body["applied_changes"][0]["field"] == "current_balance"
    assert body["applied_changes"][0]["new_value"] == 82000.0

    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == 82000.0
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "accepted"
        # revalidation ran inside the same request
        assert db.query(ValidationResult).filter_by(loan_id=loan_id, rule_name="source_conflict").count() >= 2
        exc = db.get(ExceptionRecord, exception_id)
        assert exc.status == "resolved", "conflict is gone, so the existing revalidation path resolves it"


def test_accepting_suggest_no_change_records_concurrence_without_touching_data():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _recommendation_json())
    headers = _authenticate("reviewer-7c-nochange", "reviewer")
    before = _workflow_snapshot(loan_id)

    response = client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["applied_changes"] == []

    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == before[0]
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "accepted"
        assert db.get(ExceptionRecord, exception_id).status == before[1]


def test_accepting_request_human_review_never_changes_data_or_the_exception():
    """Pins the semantics: accepting 'I cannot help' closes the AI suggestion only.

    It must not resolve the exception, must not change any field, and must not create an
    edit action -- the reviewer still owns the exception decision.
    """
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(
        exception_id,
        _recommendation_json(
            recommendation_type="request_human_review",
            summary="Sources disagree and no source is authoritative.",
            explanation="Cannot determine which balance is correct from the packet alone.",
            confidence=0.3,
        ),
    )
    headers = _authenticate("reviewer-7c-rhr", "reviewer")
    balance_before, status_before, _, _, _ = _workflow_snapshot(loan_id)

    response = client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)
    assert response.status_code == 200
    assert response.json()["applied_changes"] == []
    assert response.json()["recommendation_type"] == "request_human_review"

    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == balance_before
        exc = db.get(ExceptionRecord, exception_id)
        assert exc.status == status_before == "open", "accepting must not resolve the exception"
        assert db.query(ReviewAction).filter_by(action_type="edit_field").count() == 0
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "accepted"


# ---------------------------------------------------------------------------
# Edit and reject
# ---------------------------------------------------------------------------


def test_editing_applies_the_reviewers_value_not_the_ai_value():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-edit", "reviewer")

    response = client.post(
        f"/ai-recommendations/{recommendation_id}/edit",
        json={"corrections": [{"field": "current_balance", "value": 80000}], "comment": "Reconciled to 80000."},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["disposition"] == "edited"

    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == 80000.0, "reviewer value wins"
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "edited"
        audit = (
            db.query(AuditLog)
            .filter_by(event_type="ai_recommendation_dispositioned")
            .one()
        )
        # divergence between what the AI proposed and what the human applied is visible
        assert audit.details["ai_suggested_corrections"][0]["suggested_value"] == 82000.0
        assert audit.details["applied_changes"][0]["new_value"] == 80000.0


def test_rejecting_changes_nothing_but_records_the_decision():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-reject", "reviewer")
    before = _workflow_snapshot(loan_id)

    response = client.post(
        f"/ai-recommendations/{recommendation_id}/reject",
        json={"comment": "Servicer file is stale."},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["applied_changes"] == []

    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == before[0]
        assert db.get(ExceptionRecord, exception_id).status == before[1]
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "rejected"
        action = db.query(ReviewAction).filter_by(action_type="ai_reject").one()
        assert action.ai_recommendation_id == recommendation_id
        assert action.comment_text == "Servicer file is stale."


# ---------------------------------------------------------------------------
# Auditability of the disposition -- the centrepiece of 7C
# ---------------------------------------------------------------------------


def test_full_audit_chain_links_ai_suggestion_to_the_actual_change():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-audit", "reviewer")
    client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)

    with base.SessionLocal() as db:
        events = {
            event.event_type: event
            for event in db.query(AuditLog).filter_by(loan_id=loan_id).all()
        }
        # AI recommended X ...
        assert events["ai_recommendation_created"].details["ai_recommendation_id"] == recommendation_id
        # ... the reviewer accepted it ...
        disposition = events["ai_recommendation_dispositioned"].details
        assert disposition["ai_recommendation_id"] == recommendation_id
        assert disposition["disposition"] == "accepted"
        assert disposition["recommendation_type"] == "suggest_field_correction"
        # ... and this is what actually changed.
        edited = events["field_edited"].details
        assert edited["ai_recommendation_id"] == recommendation_id
        assert edited["field_name"] == "current_balance"
        assert edited["old_value"] == 95000.0
        assert edited["new_value"] == 82000.0

        # every review action produced is attributable to the recommendation
        actions = db.query(ReviewAction).filter_by(loan_id=loan_id).all()
        assert {a.action_type for a in actions} == {"ai_accept", "edit_field"}
        assert all(a.ai_recommendation_id == recommendation_id for a in actions)


def test_review_actions_are_visible_with_their_recommendation_link():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-link", "reviewer")
    client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)

    detail = client.get(f"/exceptions/{exception_id}", headers=headers).json()
    assert detail["ai_recommendations"][0]["reviewer_status"] == "accepted"
    assert all(a["ai_recommendation_id"] == recommendation_id for a in detail["review_actions"])


# ---------------------------------------------------------------------------
# Terminal state, authorization, and safety
# ---------------------------------------------------------------------------


def test_a_recommendation_cannot_be_dispositioned_twice():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-twice", "reviewer")
    assert client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers).status_code == 200

    after_first = _workflow_snapshot(loan_id)
    second = client.post(f"/ai-recommendations/{recommendation_id}/reject", json={}, headers=headers)
    assert second.status_code == 409
    assert _workflow_snapshot(loan_id) == after_first
    with base.SessionLocal() as db:
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "accepted"


def test_unknown_recommendation_returns_404():
    headers = _authenticate("reviewer-7c-404", "reviewer")
    assert client.post("/ai-recommendations/999999/accept", json={}, headers=headers).status_code == 404


def test_unauthenticated_disposition_is_rejected():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    assert client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}).status_code == 401


@pytest.mark.parametrize("role", ["data_operator", "data_consumer"])
def test_non_reviewer_cannot_disposition(role):
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate(f"user-7c-{role}", role)
    response = client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)
    assert response.status_code == 403


def test_disposition_never_creates_a_verified_record():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-noverify", "reviewer")
    client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)
    with base.SessionLocal() as db:
        assert db.query(VerifiedLoan).count() == 0


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


def test_edit_to_a_non_allowlisted_field_leaves_no_partial_disposition():
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-badfield", "reviewer")
    before = _workflow_snapshot(loan_id)

    response = client.post(
        f"/ai-recommendations/{recommendation_id}/edit",
        json={"corrections": [{"field": "loan_id", "value": "L-HACKED"}]},
        headers=headers,
    )
    assert response.status_code == 400

    assert _workflow_snapshot(loan_id) == before
    with base.SessionLocal() as db:
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "pending"
        assert db.query(ReviewAction).count() == 0
        assert db.query(AuditLog).filter_by(event_type="ai_recommendation_dispositioned").count() == 0


def test_revalidation_failure_rolls_back_the_entire_disposition():
    """The whole 7C operation is one unit of work.

    Revalidation is made to fail *after* the field mutation and the disposition writes
    have already happened in the transaction. Nothing may survive: not the edit, not the
    disposition, not reviewer_status, not the audit events.
    """
    exception_id, loan_id, _ = _seed_conflict_loan()
    recommendation_id = _create_recommendation(exception_id, _correction_recommendation(loan_id))
    headers = _authenticate("reviewer-7c-rollback", "reviewer")
    before = _workflow_snapshot(loan_id)

    def _explode(db, loan):
        raise RuntimeError("revalidation blew up")

    # edit_exception_field imports this symbol lazily, so patching the module attribute
    # takes effect at call time.
    with patch("app.validators.engine.validate_loan_in_session", _explode):
        with pytest.raises(RuntimeError):
            client.post(f"/ai-recommendations/{recommendation_id}/accept", json={}, headers=headers)

    assert _workflow_snapshot(loan_id) == before, "loan/exception/validation/action state must be untouched"
    with base.SessionLocal() as db:
        assert db.get(base.Loan, loan_id).current_balance == 95000.0
        assert db.get(AIRecommendation, recommendation_id).reviewer_status == "pending"
        assert db.query(ReviewAction).count() == 0
        assert db.query(AuditLog).filter_by(event_type="ai_recommendation_dispositioned").count() == 0
        assert db.query(AuditLog).filter_by(event_type="field_edited").count() == 0
