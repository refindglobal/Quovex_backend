"""Users router - profile management, proficiency, social unlock status."""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, Body
from sqlalchemy.orm import Session as DBSession

from app.core.security import get_current_user
from app.core.constants import get_filtered_tags, get_education_level, profile_is_complete
from app.db.session import get_db
from app.models import User, UserSubjectProficiency, UserTopicProgress, Topic, AppUsageLog, Session as StudySession
from app.schemas import UserProfileOut, UserPublicOut, UserUpdateIn, SubjectBreakdownOut, MonthlyAccuracyOut, TopicBreakdownOut
from sqlalchemy import func

router = APIRouter(prefix="/users", tags=["users"])

from pydantic import BaseModel

class StreakOut(BaseModel):
    current_streak: int
    longest_streak: int
    freeze_available: int

streak_router = APIRouter(prefix="/streak", tags=["streak"])

@streak_router.get("", response_model=StreakOut)
@streak_router.get("/", response_model=StreakOut)
async def get_streak(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get current streak status."""
    return StreakOut(
        current_streak=current_user.streak_count or 0,
        longest_streak=current_user.streak_count or 0,
        freeze_available=1 if current_user.streak_frozen_until else 0,
    )


def _auto_advance_class_if_april(user: User, db: DBSession) -> bool:
    """Auto-advance class/year if it's April and not already advanced this year."""
    now = datetime.now(timezone.utc)
    if now.month != 4:
        return False
    if not user.class_or_year or not user.institution_type:
        return False
    if user.class_auto_advanced_year == now.year:
        return False
    from app.core.constants import next_class
    new_class, is_passed_out = next_class(
        user.class_or_year,
        user.institution_type.value if user.institution_type else "",
    )
    old_class = user.class_or_year
    user.class_or_year = new_class
    user.class_auto_advanced_year = now.year
    db.commit()
    return True


def _validate_and_clean_exam_tags(user: User, db: DBSession):
    """Nullify exam_tags if they don't match user's country + education level."""
    if not user.exam_tags or not user.country:
        return
    inst_type = getattr(user.institution_type, 'value', user.institution_type) if user.institution_type else None
    level = get_education_level(
        inst_type,
        user.class_or_year,
    )
    valid = get_filtered_tags(country=user.country, education_level=level)
    valid_labels = {t["tag"] for t in valid}
    clean = [t for t in user.exam_tags if t in valid_labels]
    if len(clean) != len(user.exam_tags):
        user.exam_tags = clean if clean else None


@router.get("/me", response_model=UserProfileOut)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the authenticated user's full profile. Runs class auto-advance if applicable."""
    _auto_advance_class_if_april(current_user, db)
    _validate_and_clean_exam_tags(current_user, db)
    current_user.profile_complete = profile_is_complete(current_user)
    db.commit()
    return UserProfileOut.model_validate(current_user)


@router.patch("/me", response_model=UserProfileOut)
async def update_my_profile(
    body: UserUpdateIn,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update the authenticated user's profile fields."""
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(current_user, field):
            if field == "institution_type" and isinstance(value, str) and value:
                try:
                    from app.models import InstitutionType
                    value = InstitutionType(value)
                except ValueError:
                    pass
            setattr(current_user, field, value)
    _validate_and_clean_exam_tags(current_user, db)
    current_user.profile_complete = profile_is_complete(current_user)
    db.commit()
    db.refresh(current_user)
    return UserProfileOut.model_validate(current_user)


@router.post("/me/streak-freeze")
async def streak_freeze(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Freeze streak for 24 hours after watching a rewarded ad."""
    now = datetime.now(timezone.utc)
    if current_user.streak_frozen_until and current_user.streak_frozen_until > now:
        remaining = int((current_user.streak_frozen_until - now).total_seconds())
        raise HTTPException(
            status_code=400,
            detail=f"Streak already frozen. {remaining // 3600}h {remaining % 3600 // 60}m remaining.",
        )
    current_user.streak_frozen_until = now + timedelta(hours=24)
    db.commit()
    return {
        "status": "ok",
        "streak_frozen_until": current_user.streak_frozen_until.isoformat(),
        "message": "Streak frozen for 24 hours.",
    }


@router.post("/me/gifts/welcome")
async def claim_welcome_gift(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Claim onboarding starter boost (+30 wallet minutes, 1 streak freeze, +50 XP). Can only be claimed once."""
    if getattr(current_user, "welcome_gift_claimed", False):
        return {
            "status": "already_claimed",
            "wallet_minutes": current_user.wallet_minutes or 0,
            "points_total": current_user.points_total or 0,
            "message": "Welcome gift has already been claimed."
        }

    current_user.wallet_minutes = (current_user.wallet_minutes or 0) + 30
    current_user.points_total = (current_user.points_total or 0) + 50
    current_user.welcome_gift_claimed = True

    # Safe timezone-aware comparison for streak freeze
    try:
        now = datetime.now(timezone.utc)
        frozen = current_user.streak_frozen_until
        if frozen is not None and frozen.tzinfo is None:
            frozen = frozen.replace(tzinfo=timezone.utc)
        if frozen is None or frozen < now:
            current_user.streak_frozen_until = now + timedelta(hours=24)
    except Exception:
        current_user.streak_frozen_until = datetime.now(timezone.utc) + timedelta(hours=24)

    db.commit()
    db.refresh(current_user)
    return {
        "status": "ok",
        "wallet_minutes": current_user.wallet_minutes,
        "points_total": current_user.points_total,
        "message": "Welcome gift claimed successfully! +30 Time Wallet minutes and +50 XP granted."
    }


@router.get("/me/proficiency")
async def get_my_proficiency(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the authenticated user's subject proficiency scores."""
    records = (
        db.query(UserSubjectProficiency)
        .filter(UserSubjectProficiency.user_id == current_user.id)
        .order_by(UserSubjectProficiency.rolling_accuracy_score.desc())
        .all()
    )
    return [
        {
            "subject": r.subject,
            "exam_tag": r.exam_tag,
            "rolling_accuracy_score": r.rolling_accuracy_score,
            "total_questions_answered": r.total_questions_answered,
            "total_correct": r.total_correct,
        }
        for r in records
    ]


@router.get("/me/subject-breakdown", response_model=list[SubjectBreakdownOut])
async def get_subject_breakdown(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Breakdown per subject: study minutes, quiz accuracy, topics with progress."""
    # Study minutes per subject
    study_rows = (
        db.query(
            StudySession.subject_tag,
            func.coalesce(func.sum(StudySession.verified_minutes), 0).label("total_minutes"),
        )
        .filter(
            StudySession.user_id == current_user.id,
            StudySession.is_active == False,
            StudySession.subject_tag.isnot(None),
        )
        .group_by(StudySession.subject_tag)
        .all()
    )
    study_map = {r.subject_tag: r.total_minutes for r in study_rows}

    # Quiz proficiency per subject
    proficiencies = (
        db.query(UserSubjectProficiency)
        .filter(UserSubjectProficiency.user_id == current_user.id)
        .all()
    )
    prof_map = {p.subject: p for p in proficiencies}

    # Topic progress per subject
    topic_rows = (
        db.query(UserTopicProgress, Topic)
        .join(Topic, UserTopicProgress.topic_id == Topic.id)
        .filter(UserTopicProgress.user_id == current_user.id)
        .all()
    )
    topic_map: dict[str, list[TopicBreakdownOut]] = {}
    for utp, t in topic_rows:
        topic_map.setdefault(t.subject, []).append(TopicBreakdownOut(
            topic_id=utp.topic_id,
            topic_name=t.name,
            questions_answered=utp.questions_answered,
            correct=utp.correct,
            accuracy=utp.accuracy,
            study_minutes=utp.study_minutes,
        ))

    # Collect all unique subjects
    all_subjects = set(study_map.keys()) | {p.subject for p in proficiencies} | set(topic_map.keys())

    result = []
    for subject in sorted(all_subjects):
        prof = prof_map.get(subject)
        topics = topic_map.get(subject, [])
        monthly_hist = []
        if prof and prof.monthly_accuracy_history:
            monthly_hist = [
                MonthlyAccuracyOut(month=m["month"], accuracy=m["accuracy"])
                for m in prof.monthly_accuracy_history
            ]
        result.append(SubjectBreakdownOut(
            subject=subject,
            total_study_minutes=study_map.get(subject, 0),
            total_quiz_questions=prof.total_questions_answered if prof else 0,
            total_quiz_correct=prof.total_correct if prof else 0,
            avg_accuracy=prof.rolling_accuracy_score if prof else 0.0,
            topics_count=len(topics),
            monthly_accuracy=monthly_hist,
            topics=topics,
        ))
    return result


@router.get("/me/social-unlock")
async def get_social_unlock_status(
    current_user: User = Depends(get_current_user),
):
    """Get current social unlock bank status (minutes remaining today)."""
    return {
        "social_unlock_minutes_today": current_user.social_unlock_minutes_today,
        "streak_count": current_user.streak_count,
    }


@router.post("/fcm-token")
async def register_fcm_token(
    token: str = Body(...),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Register a Firebase Cloud Messaging device token for push notifications."""
    current_user.fcm_token = token
    db.commit()
    return {"status": "ok", "message": "FCM token registered"}


@router.post("/me/app-open")
async def log_app_open(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Log an app open event for the current user (tracks daily usage count)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    log = (
        db.query(AppUsageLog)
        .filter(
            AppUsageLog.user_id == current_user.id,
            AppUsageLog.date == today,
        )
        .first()
    )
    if log:
        log.open_count += 1
    else:
        log = AppUsageLog(user_id=current_user.id, date=today, open_count=1)
        db.add(log)
    db.commit()
    return {"status": "ok", "opens_today": log.open_count}


@router.delete("/me")
async def delete_my_account(
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Permanently delete the current user's account and all associated data."""
    db.delete(current_user)
    db.commit()
    return {"status": "ok", "message": "Account deleted"}


@router.get("/{user_id}", response_model=UserPublicOut)
async def get_user_public(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get public profile of any user (for leaderboard taps)."""
    user = db.query(User).filter(
        User.id == user_id, User.is_banned == False
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublicOut.model_validate(user)
