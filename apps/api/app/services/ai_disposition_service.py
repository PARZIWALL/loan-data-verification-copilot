"""Reviewer disposition of AI recommendations (7C).

Closes the copilot loop: an AI recommendation is only ever a suggestion until a human
accepts, edits, or rejects it here. This service holds no AI logic and calls no model.

Two invariants define it:

  * Every data change goes through exception_service.edit_exception_field(), never
    through direct Loan mutation. The reviewer edit allowlist, value normalization, the
    field_edited audit event and same-transaction revalidation therefore apply to an
    AI-driven correction exactly as they do to a hand-typed one -- the AI cannot reach a
    field a reviewer could not have edited themselves.
  * A disposition decides the *recommendation*, never the *exception*. Approving,
    rejecting or resolving an exception stays with the existing reviewer endpoints. The
    only exception-status movement a disposition can cause is indirect and already
    correct: an applied correction triggers revalidation, and a now-passing rule
    auto-resolves its exception through the existing path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.service import log_audit_event
from app.models.ai_recommendation import AIRecommendation
from app.models.review_action import ReviewAction
from app.services.exception_service import edit_exception_field

PENDING = "pending"

_DISPOSITION_ACTION_TYPES = {
    "accepted": "ai_accept",
    "edited": "ai_edit",
    "rejected": "ai_reject",
}


class RecommendationAlreadyDispositionedError(RuntimeError):
    """Raised when a recommendation that already has a human decision is dispositioned again."""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_pending_recommendation(db: Session, ai_recommendation_id: int) -> AIRecommendation:
    record = db.get(AIRecommendation, ai_recommendation_id)
    if record is None:
        raise LookupError(f"AI recommendation {ai_recommendation_id} not found.")
    if record.reviewer_status != PENDING:
        raise RecommendationAlreadyDispositionedError(
            f"AI recommendation {ai_recommendation_id} was already dispositioned as "
            f"'{record.reviewer_status}'."
        )
    return record


def _recommendation_payload(record: AIRecommendation) -> dict[str, Any]:
    stored = record.suggested_correction or {}
    return stored.get("recommendation") or {}


def _clean_comment(comment_text: str | None) -> str | None:
    if not comment_text:
        return None
    cleaned = comment_text.strip() if isinstance(comment_text, str) else str(comment_text).strip()
    if not cleaned:
        return None
    if len(cleaned) > 2000:
        raise ValueError("Comment text exceeds the maximum supported length.")
    return cleaned


def _apply_corrections(
    db: Session,
    *,
    record: AIRecommendation,
    corrections: list[dict[str, Any]],
    reviewer_id: int,
) -> list[dict[str, Any]]:
    """Apply each correction through the ordinary reviewer edit path."""
    applied = []
    for correction in corrections:
        field_name = correction.get("field")
        if not field_name:
            continue
        result = edit_exception_field(
            db,
            exception_id=record.exception_id,
            loan_id=record.loan_id,
            reviewer_id=reviewer_id,
            field_name=field_name,
            raw_value=correction.get("suggested_value"),
            ai_recommendation_id=record.id,
        )
        applied.append(
            {
                "field": result["field_name"],
                "old_value": result["old_value"],
                "new_value": result["new_value"],
                "status": result["status"],
                "review_action_id": result["action_id"],
            }
        )
    return applied


def _disposition(
    db: Session,
    *,
    ai_recommendation_id: int,
    reviewer_id: int,
    disposition: str,
    comment_text: str | None,
    corrections: list[dict[str, Any]],
) -> dict[str, Any]:
    record = _load_pending_recommendation(db, ai_recommendation_id)
    cleaned_comment = _clean_comment(comment_text)
    payload = _recommendation_payload(record)
    recommendation_type = payload.get("recommendation_type")

    applied = _apply_corrections(
        db,
        record=record,
        corrections=corrections,
        reviewer_id=reviewer_id,
    )

    record.reviewer_status = disposition

    now = _utc_timestamp()
    action = ReviewAction(
        exception_id=record.exception_id,
        loan_id=record.loan_id,
        reviewer_id=reviewer_id,
        action_type=_DISPOSITION_ACTION_TYPES[disposition],
        comment_text=cleaned_comment,
        ai_recommendation_id=record.id,
        created_at=now,
    )
    db.add(action)
    db.flush()

    log_audit_event(
        db,
        "ai_recommendation_dispositioned",
        loan_id=record.loan_id,
        actor="reviewer",
        details={
            "loan_id": record.loan_id,
            "exception_id": record.exception_id,
            "ai_recommendation_id": record.id,
            "reviewer_id": reviewer_id,
            "disposition": disposition,
            # recorded so "accepted" is never ambiguous when the trail is read back
            "recommendation_type": recommendation_type,
            "ai_suggested_corrections": payload.get("suggested_corrections", []),
            "applied_changes": applied,
            "review_action_id": action.id,
            "comment": cleaned_comment,
            "timestamp": now,
        },
    )

    return {
        "ai_recommendation_id": record.id,
        "exception_id": record.exception_id,
        "loan_id": record.loan_id,
        "disposition": disposition,
        "reviewer_status": record.reviewer_status,
        "recommendation_type": recommendation_type,
        "reviewer_id": reviewer_id,
        "review_action_id": action.id,
        "comment_text": cleaned_comment,
        "applied_changes": applied,
        "created_at": now,
    }


def accept_recommendation(
    db: Session,
    *,
    ai_recommendation_id: int,
    reviewer_id: int,
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Concur with the AI's assessment.

    For suggest_field_correction this applies the AI's suggested value(s). For
    suggest_no_change and request_human_review there is nothing to apply and the
    disposition records concurrence only -- those recommendation types carry no
    suggested_corrections, so accepting one cannot alter data. Accepting never resolves
    the exception; the reviewer still decides that separately.
    """
    record = _load_pending_recommendation(db, ai_recommendation_id)
    corrections = _recommendation_payload(record).get("suggested_corrections") or []
    return _disposition(
        db,
        ai_recommendation_id=ai_recommendation_id,
        reviewer_id=reviewer_id,
        disposition="accepted",
        comment_text=comment_text,
        corrections=corrections,
    )


def edit_recommendation(
    db: Session,
    *,
    ai_recommendation_id: int,
    reviewer_id: int,
    corrections: list[dict[str, Any]],
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Apply the reviewer's own values instead of the AI's.

    Each correction is {"field": ..., "value": ...} and is applied through the same
    allowlisted edit path, so the reviewer cannot reach a field they could not edit by
    hand. The AI's original proposal is preserved in the audit event alongside what was
    actually applied, so any divergence stays visible.
    """
    if not corrections:
        raise ValueError("At least one correction is required to edit a recommendation.")
    normalized = [
        {"field": correction.get("field"), "suggested_value": correction.get("value")}
        for correction in corrections
    ]
    return _disposition(
        db,
        ai_recommendation_id=ai_recommendation_id,
        reviewer_id=reviewer_id,
        disposition="edited",
        comment_text=comment_text,
        corrections=normalized,
    )


def reject_recommendation(
    db: Session,
    *,
    ai_recommendation_id: int,
    reviewer_id: int,
    comment_text: str | None = None,
) -> dict[str, Any]:
    """Dismiss the AI's suggestion. Never changes loan data or the exception's status."""
    return _disposition(
        db,
        ai_recommendation_id=ai_recommendation_id,
        reviewer_id=reviewer_id,
        disposition="rejected",
        comment_text=comment_text,
        corrections=[],
    )
