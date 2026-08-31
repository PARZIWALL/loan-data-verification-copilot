"""Exception workflow routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_db
from app.models.exception import ExceptionRecord
from app.models.user import User
from app.schemas.exception import (
    AIDispositionRequest,
    AIDispositionResponse,
    AIEditDispositionRequest,
    ExceptionDetailResponse,
    ExceptionListResponse,
    ExceptionSeverity,
    ExceptionStatus,
    FieldEditResponse,
    ReviewActionResponse,
    ReviewerCommentRequest,
    ReviewerDecisionRequest,
    ReviewerDecisionResponse,
    ReviewerFieldEditRequest,
)
from app.services.exception_service import (
    approve_exception,
    create_exception_comment,
    edit_exception_field,
    get_exception_detail,
    list_exceptions,
    reject_exception,
    request_correction_exception,
)
from app.services.ai_disposition_service import (
    RecommendationAlreadyDispositionedError,
    accept_recommendation,
    edit_recommendation,
    reject_recommendation,
)
from app.services.ai_recommendation_service import AIRecommendationError, generate_ai_recommendation

router = APIRouter(tags=["exceptions"])


@router.post("/exceptions/{exception_id}/ai-recommendation")
def ai_recommendation_route(
    exception_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Generate a grounded AI recommendation for one exception.

    Takes no client-supplied evidence, model, or prompt: everything the model sees is
    derived server-side from the exception's own EvidencePacket.
    """
    if current_user.role != "reviewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only reviewers can generate AI recommendations",
        )

    try:
        result = generate_ai_recommendation(db, exception_id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AIRecommendationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    db.commit()
    return result


@router.get("/exceptions", response_model=ExceptionListResponse)
def list_exceptions_route(
    exception_type: str | None = Query(default=None, alias="type"),
    severity: ExceptionSeverity | None = Query(default=None),
    status: ExceptionStatus | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return a paginated exception queue for the reviewer workflow."""
    del current_user
    items, total, total_pages = list_exceptions(
        db,
        type=exception_type,
        severity=severity.value if severity else None,
        status=status.value if status else None,
        search=search,
        page=page,
        page_size=page_size,
    )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@router.post("/exceptions/{exception_id}/comment", response_model=ReviewActionResponse)
def create_exception_comment_route(
    exception_id: int,
    payload: ReviewerCommentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add an authenticated reviewer comment and persist an audit event."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can add comments")

    exc = db.query(__import__("app.models.exception", fromlist=["ExceptionRecord"]).ExceptionRecord).filter_by(id=exception_id).one_or_none()
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")

    action = create_exception_comment(
        db,
        exception_id=exception_id,
        loan_id=exc.loan_id,
        reviewer_id=current_user.id,
        comment_text=payload.text,
    )
    db.commit()
    return action


@router.post("/exceptions/{exception_id}/edit", response_model=FieldEditResponse)
def edit_exception_field_route(
    exception_id: int,
    payload: ReviewerFieldEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Edit an allowlisted canonical field for an exception's loan and revalidate it."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can edit fields")

    exc = db.query(ExceptionRecord).filter_by(id=exception_id).one_or_none()
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")

    try:
        result = edit_exception_field(
            db,
            exception_id=exception_id,
            loan_id=exc.loan_id,
            reviewer_id=current_user.id,
            field_name=payload.field,
            raw_value=payload.value,
        )
    except ValueError as exc_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc_value)) from exc_value
    except LookupError as exc_lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup

    db.commit()
    return result


@router.post("/exceptions/{exception_id}/approve", response_model=ReviewerDecisionResponse)
def approve_exception_route(
    exception_id: int,
    payload: ReviewerDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Approve an exception as acceptable/resolved."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can approve exceptions")

    exc = db.query(ExceptionRecord).filter_by(id=exception_id).one_or_none()
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")

    try:
        result = approve_exception(
            db,
            exception_id=exception_id,
            reviewer_id=current_user.id,
            comment_text=payload.comment,
        )
    except ValueError as exc_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc_value)) from exc_value
    except LookupError as exc_lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup

    db.commit()
    return result


@router.post("/exceptions/{exception_id}/reject", response_model=ReviewerDecisionResponse)
def reject_exception_route(
    exception_id: int,
    payload: ReviewerDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reject an exception as not acceptable."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can reject exceptions")

    exc = db.query(ExceptionRecord).filter_by(id=exception_id).one_or_none()
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")

    try:
        result = reject_exception(
            db,
            exception_id=exception_id,
            reviewer_id=current_user.id,
            comment_text=payload.comment,
        )
    except ValueError as exc_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc_value)) from exc_value
    except LookupError as exc_lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup

    db.commit()
    return result


@router.post("/exceptions/{exception_id}/request-correction", response_model=ReviewerDecisionResponse)
def request_correction_exception_route(
    exception_id: int,
    payload: ReviewerDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Request correction on an exception's data."""
    if current_user.role != "reviewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only reviewers can request corrections")

    exc = db.query(ExceptionRecord).filter_by(id=exception_id).one_or_none()
    if exc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")

    try:
        result = request_correction_exception(
            db,
            exception_id=exception_id,
            reviewer_id=current_user.id,
            comment_text=payload.comment,
        )
    except ValueError as exc_value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc_value)) from exc_value
    except LookupError as exc_lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup

    db.commit()
    return result


@router.get("/exceptions/{exception_id}", response_model=ExceptionDetailResponse)
def get_exception_detail_route(
    exception_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return full exception detail, linked validation result, canonical loan, and source evidence."""
    del current_user
    detail = get_exception_detail(db, exception_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exception not found")
    return detail


def _require_reviewer(current_user: User) -> None:
    if current_user.role != "reviewer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only reviewers can disposition AI recommendations",
        )


def _run_disposition(db: Session, operation) -> dict:
    """Run one disposition as a single unit of work.

    The catch-all rollback matters: a disposition can apply a field edit and trigger
    revalidation, and if any of that fails the whole operation -- disposition record,
    reviewer_status, edits and audit events -- must leave no trace. Relying on the
    request session merely being closed without a commit would be an implicit guarantee;
    this makes it explicit.
    """
    try:
        result = operation()
    except LookupError as exc_lookup:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc_lookup)) from exc_lookup
    except RecommendationAlreadyDispositionedError as exc_conflict:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc_conflict)) from exc_conflict
    except ValueError as exc_value:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc_value)) from exc_value
    except Exception:
        db.rollback()
        raise
    db.commit()
    return result


@router.post("/ai-recommendations/{ai_recommendation_id}/accept", response_model=AIDispositionResponse)
def accept_ai_recommendation_route(
    ai_recommendation_id: int,
    payload: AIDispositionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Concur with the AI's assessment, applying its corrections if it proposed any."""
    _require_reviewer(current_user)
    return _run_disposition(
        db,
        lambda: accept_recommendation(
            db,
            ai_recommendation_id=ai_recommendation_id,
            reviewer_id=current_user.id,
            comment_text=payload.comment,
        ),
    )


@router.post("/ai-recommendations/{ai_recommendation_id}/edit", response_model=AIDispositionResponse)
def edit_ai_recommendation_route(
    ai_recommendation_id: int,
    payload: AIEditDispositionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Apply the reviewer's own values in place of the AI's suggestion."""
    _require_reviewer(current_user)
    corrections = [{"field": item.field, "value": item.value} for item in payload.corrections]
    return _run_disposition(
        db,
        lambda: edit_recommendation(
            db,
            ai_recommendation_id=ai_recommendation_id,
            reviewer_id=current_user.id,
            corrections=corrections,
            comment_text=payload.comment,
        ),
    )


@router.post("/ai-recommendations/{ai_recommendation_id}/reject", response_model=AIDispositionResponse)
def reject_ai_recommendation_route(
    ai_recommendation_id: int,
    payload: AIDispositionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Dismiss the AI's suggestion without changing loan data."""
    _require_reviewer(current_user)
    return _run_disposition(
        db,
        lambda: reject_recommendation(
            db,
            ai_recommendation_id=ai_recommendation_id,
            reviewer_id=current_user.id,
            comment_text=payload.comment,
        ),
    )
