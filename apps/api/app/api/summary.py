"""Dashboard summary routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, get_db
from app.models.user import User
from app.schemas.summary import SummaryResponse
from app.services.summary_service import build_summary

router = APIRouter(tags=["summary"])


@router.get("/summary", response_model=SummaryResponse)
def get_summary_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return portfolio-wide counts powering all three role dashboards.

    Read-only and role-agnostic: every role sees the same underlying numbers and each
    dashboard chooses which of them to surface.
    """
    del current_user
    return build_summary(db)
