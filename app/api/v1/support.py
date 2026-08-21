"""Support router — user ticket submission and issue reporting."""
import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas import (
    SupportTicketCreateIn,
    SupportTicketOut,
    SupportTicketListOut
)
from app.services import support_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])

SUPPORT_CATEGORIES = [
    {"id": "app_lock", "name": "App Lock / Permissions", "icon": "lock"},
    {"id": "timer", "name": "Focus Timer & Heartbeat", "icon": "timer"},
    {"id": "wallet", "name": "Study Wallet & Rewards", "icon": "wallet"},
    {"id": "quiz_ai", "name": "Quiz & AI Doubt Solver", "icon": "auto_awesome"},
    {"id": "account_sync", "name": "Account & Cloud Sync", "icon": "sync"},
    {"id": "bug_crash", "name": "Bug / App Crash", "icon": "bug_report"},
    {"id": "suggestion", "name": "Feature Request / Suggestion", "icon": "lightbulb"}
]


@router.get("/categories")
async def get_support_categories():
    """Get list of issue categories for reporting form."""
    return {"categories": SUPPORT_CATEGORIES}


@router.post("/tickets", response_model=SupportTicketOut, status_code=status.HTTP_201_CREATED)
async def submit_support_ticket(
    body: SupportTicketCreateIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Submit an issue report / support ticket directly from the app."""
    try:
        ticket = support_service.create_support_ticket(
            user=current_user,
            data=body,
            db=db
        )
        return ticket
    except Exception as e:
        logger.error(f"Failed to create support ticket: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit support ticket. Please try again."
        )


@router.get("/my-tickets", response_model=List[SupportTicketOut])
async def get_my_tickets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """List issues/tickets submitted by current user."""
    return support_service.get_user_tickets(
        user=current_user,
        db=db,
        limit=limit,
        offset=offset
    )


@router.get("/tickets/{ticket_id}", response_model=SupportTicketOut)
async def get_ticket_details(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db)
):
    """Get specific support ticket status and details."""
    ticket = support_service.get_ticket_by_id(
        ticket_id=ticket_id,
        db=db,
        user=current_user
    )
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found")
    return ticket
