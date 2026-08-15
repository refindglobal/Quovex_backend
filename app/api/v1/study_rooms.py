"""Study Rooms router — live silent accountability rooms for Quovex."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix="/study-rooms", tags=["study-rooms"])


# ─── Schemas ───────────────────────────────────────────────────────────────────

class StudyRoomMemberOut(BaseModel):
    user_id: str
    display_name: str
    avatar_url: Optional[str] = None
    focus_seconds: int = 0
    is_online: bool = True


class StudyRoomOut(BaseModel):
    room_id: str
    name: str
    subject: str
    privacy: str  # "public", "friends", "private"
    member_count: int
    members: List[StudyRoomMemberOut] = []
    room_focus_seconds: int = 0
    created_at: str
    is_live: bool = True


class StudyRoomCreateIn(BaseModel):
    name: str
    subject: str
    privacy: str = "public"
    duration_minutes: int = 120
    mode: str = "silent_focus"


class StudyRoomCreateOut(BaseModel):
    room_id: str
    name: str
    subject: str
    privacy: str
    join_code: Optional[str] = None
    message: str


class JoinRoomOut(BaseModel):
    room_id: str
    name: str
    subject: str
    member_count: int
    members: List[StudyRoomMemberOut] = []
    room_focus_seconds: int = 0
    message: str


class LeaveRoomOut(BaseModel):
    message: str


# ─── In-memory room store (production: use Redis or DB table) ──────────────────
# For production this should be a proper DB table. This is a lightweight MVP.
_LIVE_ROOMS: dict = {}


def _get_or_create_default_rooms():
    """Seed a few demo rooms if empty."""
    if not _LIVE_ROOMS:
        _LIVE_ROOMS["room-physics-1"] = {
            "room_id": "room-physics-1",
            "name": "Physics Mechanics",
            "subject": "Physics",
            "privacy": "public",
            "members": [],
            "room_focus_seconds": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_live": True,
        }
        _LIVE_ROOMS["room-chemistry-1"] = {
            "room_id": "room-chemistry-1",
            "name": "Organic Chemistry",
            "subject": "Chemistry",
            "privacy": "public",
            "members": [],
            "room_focus_seconds": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_live": True,
        }
        _LIVE_ROOMS["room-math-1"] = {
            "room_id": "room-math-1",
            "name": "Maths Problem Solving",
            "subject": "Mathematics",
            "privacy": "public",
            "members": [],
            "room_focus_seconds": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_live": True,
        }
    return _LIVE_ROOMS


@router.get("/", response_model=List[StudyRoomOut])
async def list_rooms(
    subject: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List all live public study rooms, optionally filtered by subject."""
    rooms = _get_or_create_default_rooms()
    result = []
    for room in rooms.values():
        if room["privacy"] != "public":
            continue
        if subject and room["subject"].lower() != subject.lower():
            continue
        result.append(StudyRoomOut(
            room_id=room["room_id"],
            name=room["name"],
            subject=room["subject"],
            privacy=room["privacy"],
            member_count=len(room["members"]),
            members=[StudyRoomMemberOut(**m) for m in room["members"]],
            room_focus_seconds=room["room_focus_seconds"],
            created_at=room["created_at"],
            is_live=room["is_live"],
        ))
    return result


@router.post("/create", response_model=StudyRoomCreateOut)
async def create_room(
    body: StudyRoomCreateIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a new study room."""
    room_id = f"room-{uuid.uuid4().hex[:8]}"
    join_code = uuid.uuid4().hex[:6].upper() if body.privacy == "private" else None

    _get_or_create_default_rooms()
    _LIVE_ROOMS[room_id] = {
        "room_id": room_id,
        "name": body.name,
        "subject": body.subject,
        "privacy": body.privacy,
        "members": [],
        "room_focus_seconds": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_live": True,
        "join_code": join_code,
    }

    return StudyRoomCreateOut(
        room_id=room_id,
        name=body.name,
        subject=body.subject,
        privacy=body.privacy,
        join_code=join_code,
        message="Room created successfully. Share the join code with friends!",
    )


@router.post("/{room_id}/join", response_model=JoinRoomOut)
async def join_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Join an existing study room."""
    rooms = _get_or_create_default_rooms()
    room = rooms.get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Remove if already present (re-join)
    room["members"] = [m for m in room["members"] if m["user_id"] != str(current_user.id)]

    # Add member
    room["members"].append({
        "user_id": str(current_user.id),
        "display_name": current_user.display_name or "Student",
        "avatar_url": current_user.avatar_url,
        "focus_seconds": 0,
        "is_online": True,
    })

    return JoinRoomOut(
        room_id=room_id,
        name=room["name"],
        subject=room["subject"],
        member_count=len(room["members"]),
        members=[StudyRoomMemberOut(**m) for m in room["members"]],
        room_focus_seconds=room["room_focus_seconds"],
        message=f"Joined {room['name']}. Stay focused! 💪",
    )


@router.post("/{room_id}/leave", response_model=LeaveRoomOut)
async def leave_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Leave a study room."""
    rooms = _get_or_create_default_rooms()
    room = rooms.get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room["members"] = [m for m in room["members"] if m["user_id"] != str(current_user.id)]

    return LeaveRoomOut(message="You left the room. Great work today!")


@router.get("/{room_id}/members", response_model=List[StudyRoomMemberOut])
async def get_room_members(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get current members in a study room."""
    rooms = _get_or_create_default_rooms()
    room = rooms.get(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return [StudyRoomMemberOut(**m) for m in room["members"]]
