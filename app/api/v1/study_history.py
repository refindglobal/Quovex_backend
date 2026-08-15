"""Study History router — list past sessions with analytics."""
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import func

from app.core.security import get_current_user
from app.db.session import get_db
from app.models import User, Session as StudySession

router = APIRouter(prefix="/study-history", tags=["study-history"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class SessionHistoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    mode: str
    subject_tag: Optional[str] = None
    verified_minutes: int
    points_awarded: int
    focus_score: Optional[int] = None
    started_at: str
    ended_at: Optional[str] = None
    streak_count: int = 0


class StudyHistoryOut(BaseModel):
    period: str  # "today", "week", "month"
    total_minutes: int
    total_sessions: int
    focus_score_avg: int
    sessions: List[SessionHistoryItemOut]


class WeeklyAnalyticsOut(BaseModel):
    week_labels: List[str]   # ["Mon", "Tue", ..., "Sun"]
    study_minutes: List[int]  # minutes per day
    focus_scores: List[int]   # average focus score per day
    total_this_week: int
    total_last_week: int
    best_day: str
    best_subject: Optional[str]
    current_streak: int


@router.get("/", response_model=StudyHistoryOut)
async def get_study_history(
    period: str = Query(default="week", regex="^(today|week|month)$"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get study session history for today, this week, or this month."""
    now = datetime.now(timezone.utc)

    if period == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        since = now - timedelta(days=7)
    else:  # month
        since = now - timedelta(days=30)

    sessions = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == False,
            StudySession.start_time >= since,
        )
        .order_by(StudySession.start_time.desc())
        .limit(50)
        .all()
    )

    total_minutes = sum(s.verified_minutes for s in sessions)
    total_sessions = len(sessions)
    focus_score_avg = 92 if sessions else 0  # Placeholder until focus score is tracked

    items = []
    for s in sessions:
        items.append(SessionHistoryItemOut(
            session_id=s.id,
            mode=str(s.mode),
            subject_tag=s.subject_tag,
            verified_minutes=s.verified_minutes,
            points_awarded=s.points_awarded,
            focus_score=92,  # Placeholder
            started_at=s.start_time.isoformat(),
            ended_at=s.end_time.isoformat() if s.end_time else None,
            streak_count=current_user.streak_count,
        ))

    return StudyHistoryOut(
        period=period,
        total_minutes=total_minutes,
        total_sessions=total_sessions,
        focus_score_avg=focus_score_avg,
        sessions=items,
    )


@router.get("/analytics", response_model=WeeklyAnalyticsOut)
async def get_weekly_analytics(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get 7-day analytics for the progress screen charts."""
    now = datetime.now(timezone.utc)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    study_minutes_per_day = []
    focus_scores_per_day = []
    total_this_week = 0

    for i in range(7):
        day_start = (now - timedelta(days=6 - i)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)

        day_sessions = (
            db.query(StudySession)
            .filter(
                StudySession.user_id == current_user.id,
                StudySession.is_active == False,
                StudySession.start_time >= day_start,
                StudySession.start_time < day_end,
            )
            .all()
        )
        mins = sum(s.verified_minutes for s in day_sessions)
        study_minutes_per_day.append(mins)
        focus_scores_per_day.append(92 if day_sessions else 0)
        total_this_week += mins

    # Last week total
    last_week_sessions = (
        db.query(StudySession)
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == False,
            StudySession.start_time >= now - timedelta(days=14),
            StudySession.start_time < now - timedelta(days=7),
        )
        .all()
    )
    total_last_week = sum(s.verified_minutes for s in last_week_sessions)

    best_day_idx = study_minutes_per_day.index(max(study_minutes_per_day)) if any(study_minutes_per_day) else 0
    best_day = days[best_day_idx]

    # Find best subject from sessions this week
    subject_count = {}
    all_week_sessions = db.query(StudySession).filter(
        StudySession.user_id == current_user.id,
        StudySession.is_active == False,
        StudySession.start_time >= now - timedelta(days=7),
    ).all()
    for s in all_week_sessions:
        if s.subject_tag:
            subject_count[s.subject_tag] = subject_count.get(s.subject_tag, 0) + s.verified_minutes
    best_subject = max(subject_count, key=subject_count.get) if subject_count else None

    return WeeklyAnalyticsOut(
        week_labels=days,
        study_minutes=study_minutes_per_day,
        focus_scores=focus_scores_per_day,
        total_this_week=total_this_week,
        total_last_week=total_last_week,
        best_day=best_day,
        best_subject=best_subject,
        current_streak=current_user.streak_count,
    )


@router.get("/verification-quiz", response_model=dict)
async def get_verification_quiz(
    subject: str = Query(default="Physics"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get a quick post-session verification quiz question for the given subject."""
    quiz_bank = {
        "Physics": {
            "question": "Which law explains F = ma?",
            "options": ["First Law", "Second Law", "Third Law", "None of these"],
            "correct_index": 1,
        },
        "Mathematics": {
            "question": "What is the derivative of sin(x)?",
            "options": ["cos(x)", "-cos(x)", "tan(x)", "-sin(x)"],
            "correct_index": 0,
        },
        "Chemistry": {
            "question": "What is the valency of Carbon?",
            "options": ["2", "3", "4", "6"],
            "correct_index": 2,
        },
        "Biology": {
            "question": "What is the powerhouse of the cell?",
            "options": ["Nucleus", "Ribosome", "Mitochondria", "Golgi body"],
            "correct_index": 2,
        },
    }

    quiz = quiz_bank.get(subject, quiz_bank["Physics"])
    return {
        "subject": subject,
        "question": quiz["question"],
        "options": quiz["options"],
        "correct_index": quiz["correct_index"],
        "reward_xp_bonus": 30,
    }
