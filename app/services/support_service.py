"""Support Service — handles user support ticket submissions and admin ticket resolution."""
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import desc, func

from app.models import SupportTicket, TicketStatus, TicketPriority, User
from app.schemas import SupportTicketCreateIn, SupportTicketUpdateIn

logger = logging.getLogger(__name__)


def create_support_ticket(
    user: User,
    data: SupportTicketCreateIn,
    db: DBSession
) -> SupportTicket:
    """Create a new support ticket from user app submission."""
    ticket = SupportTicket(
        user_id=user.id,
        category=data.category,
        title=data.title,
        description=data.description,
        contact_email=data.contact_email or user.email,
        device_info=data.device_info or {},
        status=TicketStatus.open,
        priority=TicketPriority.medium
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    
    logger.info(
        f"Support ticket created #{ticket.id} by user {user.id} "
        f"[{ticket.category}]: {ticket.title}"
    )
    return ticket


def get_user_tickets(
    user: User,
    db: DBSession,
    limit: int = 50,
    offset: int = 0
) -> List[SupportTicket]:
    """Retrieve tickets submitted by a specific user."""
    return (
        db.query(SupportTicket)
        .filter(SupportTicket.user_id == user.id)
        .order_by(desc(SupportTicket.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_ticket_by_id(
    ticket_id: UUID,
    db: DBSession,
    user: Optional[User] = None
) -> Optional[SupportTicket]:
    """Retrieve a single support ticket."""
    query = db.query(SupportTicket).filter(SupportTicket.id == ticket_id)
    if user and not user.admin_role:
        query = query.filter(SupportTicket.user_id == user.id)
    return query.first()


def list_admin_tickets(
    db: DBSession,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Admin query for all support tickets with filtering and pagination."""
    query = db.query(SupportTicket)
    
    if status:
        query = query.filter(SupportTicket.status == status)
    if category:
        query = query.filter(SupportTicket.category == category)
    if priority:
        query = query.filter(SupportTicket.priority == priority)
        
    total = query.count()
    tickets = query.order_by(desc(SupportTicket.created_at)).offset(offset).limit(limit).all()
    
    return {
        "total": total,
        "tickets": tickets
    }


def update_ticket_status(
    ticket_id: UUID,
    admin_user: User,
    data: SupportTicketUpdateIn,
    db: DBSession
) -> Optional[SupportTicket]:
    """Admin update ticket status, priority, or response notes."""
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        return None
        
    if data.status:
        try:
            ticket.status = TicketStatus(data.status.lower())
            if ticket.status in [TicketStatus.resolved, TicketStatus.closed]:
                ticket.resolved_at = datetime.now(timezone.utc)
                ticket.resolved_by = admin_user.id
        except ValueError:
            pass
            
    if data.priority:
        try:
            ticket.priority = TicketPriority(data.priority.lower())
        except ValueError:
            pass
            
    if data.admin_notes is not None:
        ticket.admin_notes = data.admin_notes
        
    db.commit()
    db.refresh(ticket)
    logger.info(f"Support ticket #{ticket.id} updated by admin {admin_user.id} -> {ticket.status}")
    return ticket
